"""HTTP endpoint the Apple Watch shortcut talks to.

Endpoints (all need the token):
    GET  /ping   -> health check
    POST /text   -> body is text already dictated on the watch (JSON, form, or plain)
    POST /audio  -> body is a recording (raw file or multipart form); transcribed in the cloud
"""

from __future__ import annotations

import hmac
import json
import logging
import time
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import PurePath
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .dictation import DictationService
from .transcriber import SUPPORTED_FORMATS, TranscriptionError, format_from_content_type

log = logging.getLogger(__name__)

MAX_BODY_BYTES = 25 * 1024 * 1024  # the speech APIs' own upload limit


class RequestError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class FormPart:
    name: str | None
    filename: str | None
    content_type: str
    data: bytes


def parse_multipart(body: bytes, content_type: str) -> list[FormPart]:
    """Split a multipart/form-data body into parts. Binary-safe."""
    header_parser = BytesParser(policy=policy.HTTP)
    boundary = header_parser.parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode("latin-1"), headersonly=True
    ).get_param("boundary")
    if not boundary:
        raise RequestError(HTTPStatus.BAD_REQUEST, "Multipart body has no boundary")

    parts = []
    for chunk in body.split(b"--" + boundary.encode("latin-1"))[1:]:
        if chunk.startswith(b"--"):  # closing delimiter
            break
        head, sep, data = chunk.removeprefix(b"\r\n").partition(b"\r\n\r\n")
        if not sep:
            continue
        headers = header_parser.parsebytes(head + b"\r\n\r\n", headersonly=True)
        parts.append(
            FormPart(
                name=headers.get_param("name", header="content-disposition"),
                filename=headers.get_filename(),
                content_type=headers.get_content_type(),
                data=data.removesuffix(b"\r\n"),
            )
        )
    return parts


def extract_text(body: bytes, content_type: str) -> str:
    ctype = content_type.split(";")[0].strip().lower()
    if ctype == "application/json":
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequestError(HTTPStatus.BAD_REQUEST, "Body is not valid JSON") from exc
        if isinstance(data, str):
            return data
        if isinstance(data, dict) and isinstance(data.get("text"), str):
            return data["text"]
        raise RequestError(HTTPStatus.BAD_REQUEST, 'JSON body needs a "text" field')
    if ctype == "application/x-www-form-urlencoded":
        return parse_qs(body.decode("utf-8", errors="replace")).get("text", [""])[0]
    if ctype == "multipart/form-data":
        for part in parse_multipart(body, content_type):
            if part.name == "text":
                return part.data.decode("utf-8", errors="replace")
        raise RequestError(HTTPStatus.BAD_REQUEST, 'Form needs a "text" field')
    return body.decode("utf-8", errors="replace")


class WristScribeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        token: str,
        service: DictationService,
        max_body: int = MAX_BODY_BYTES,
    ) -> None:
        super().__init__(address, Handler)
        self.token = token
        self.service = service
        self.max_body = max_body


class Handler(BaseHTTPRequestHandler):
    server: WristScribeServer
    server_version = f"WristScribe/{__version__}"

    def do_GET(self) -> None:
        self._dispatch({"/ping": self._ping, "/": self._ping}, read_body=False)

    def do_POST(self) -> None:
        self._dispatch({"/text": self._text, "/audio": self._audio}, read_body=True)

    # ---- plumbing -------------------------------------------------------

    def _dispatch(self, routes: dict, read_body: bool) -> None:
        start = time.perf_counter()
        url = urlsplit(self.path)
        self.query = parse_qs(url.query)
        self.body = b""
        route = routes.get(url.path.rstrip("/") or "/")
        try:
            # Read the body before answering so the client never sees a reset connection.
            if read_body:
                self.body = self._read_body()
            if route is None:
                raise RequestError(HTTPStatus.NOT_FOUND, f"Unknown endpoint {url.path}")
            if not self._authorized():
                raise RequestError(HTTPStatus.UNAUTHORIZED, "Missing or wrong token")
            status, payload = HTTPStatus.OK, route()
        except RequestError as exc:
            status, payload = exc.status, {"ok": False, "error": str(exc)}
        except TranscriptionError as exc:
            status, payload = HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)}
        except Exception:
            log.exception("Unexpected error handling %s %s", self.command, url.path)
            status = HTTPStatus.INTERNAL_SERVER_ERROR
            payload = {"ok": False, "error": "Unexpected error, see the laptop console"}

        self._send_json(status, payload)
        elapsed = round((time.perf_counter() - start) * 1000)
        level = logging.INFO if status == HTTPStatus.OK else logging.WARNING
        detail = "" if status == HTTPStatus.OK else f" ({payload.get('error')})"
        log.log(level, "%s %s from %s -> %d in %d ms%s",
                self.command, url.path, self.client_address[0], status, elapsed, detail)

    def _read_body(self) -> bytes:
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            return self._read_chunked()
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise RequestError(HTTPStatus.BAD_REQUEST, "Bad Content-Length") from exc
        if length > self.server.max_body:
            raise RequestError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Upload is larger than 25 MB")
        return self.rfile.read(length)

    def _read_chunked(self) -> bytes:
        chunks, total = [], 0
        while True:
            try:
                size = int(self.rfile.readline(1024).split(b";")[0].strip(), 16)
            except ValueError as exc:
                raise RequestError(HTTPStatus.BAD_REQUEST, "Malformed chunked body") from exc
            if size == 0:
                while self.rfile.readline(1024).strip():  # skip trailer headers
                    pass
                return b"".join(chunks)
            total += size
            if total > self.server.max_body:
                raise RequestError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Upload is larger than 25 MB")
            chunks.append(self.rfile.read(size))
            self.rfile.readline()  # CRLF after each chunk

    def _authorized(self) -> bool:
        auth = self.headers.get("Authorization", "")
        supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        supplied = (
            supplied
            or self.headers.get("X-WristScribe-Token", "").strip()
            or self.query.get("token", [""])[0]
        )
        return bool(supplied) and hmac.compare_digest(supplied.encode(), self.server.token.encode())

    def _send_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        log.debug("%s %s", self.client_address[0], format % args)

    # ---- routes ---------------------------------------------------------

    def _ping(self) -> dict:
        return {"ok": True, "app": "WristScribe", "version": __version__}

    def _text(self) -> dict:
        text = extract_text(self.body, self.headers.get("Content-Type", ""))
        if not text.strip():
            raise RequestError(HTTPStatus.BAD_REQUEST, "No text received")
        inserted = self.server.service.from_text(text)
        log.info("Inserted %d characters (dictated on watch)", len(inserted))
        return {"ok": True, "text": inserted}

    def _audio(self) -> dict:
        audio = self.body
        content_type = self.headers.get("Content-Type", "")
        filename_hint = None
        if content_type.lower().startswith("multipart/form-data"):
            files = [p for p in parse_multipart(self.body, content_type) if p.filename or p.name in ("file", "audio")]
            if not files:
                raise RequestError(HTTPStatus.BAD_REQUEST, "Form has no audio file")
            audio, content_type = files[0].data, files[0].content_type
            suffix = PurePath(files[0].filename or "").suffix.lstrip(".").lower()
            filename_hint = suffix if suffix in SUPPORTED_FORMATS else None
        if not audio:
            raise RequestError(HTTPStatus.BAD_REQUEST, "No audio received")

        hint = self.query.get("format", [None])[0] or filename_hint or format_from_content_type(content_type)
        inserted, transcribe_ms = self.server.service.from_audio(audio, hint)
        log.info("Inserted %d characters (%.0f KB audio, transcribed in %d ms)",
                 len(inserted), len(audio) / 1024, transcribe_ms)
        return {"ok": True, "text": inserted, "transcribe_ms": transcribe_ms}
