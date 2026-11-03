from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from wristscribe.server import parse_multipart
from wristscribe.transcriber import CloudTranscriber, TranscriptionError, sniff_audio_format

M4A = b"\x00\x00\x00\x20ftypM4A \x00\x00\x02\x00" + b"\x00\xff\r\n" * 50


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (M4A, "m4a"),
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", "wav"),
        (b"OggS\x00\x02", "ogg"),
        (b"\x1a\x45\xdf\xa3\x9f", "webm"),
        (b"fLaC\x00", "flac"),
        (b"caff\x00\x01", "caf"),
        (b"ID3\x04\x00", "mp3"),
        (b"\xff\xfb\x90\x00", "mp3"),
        (b"hello", None),
        (b"", None),
    ],
)
def test_sniff_audio_format(data, expected):
    assert sniff_audio_format(data) == expected


class FakeSpeechAPI:
    """A local stand-in for the Groq/OpenAI /audio/transcriptions endpoint."""

    def __init__(self, status: int = 200, payload: dict | None = None):
        self.status = status
        self.payload = payload if payload is not None else {"text": " Hello Simulink. "}
        self.requests: list[dict] = []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                api.requests.append({
                    "path": self.path,
                    "auth": self.headers.get("Authorization"),
                    "parts": parse_multipart(body, self.headers["Content-Type"]),
                })
                out = json.dumps(api.payload).encode()
                self.send_response(api.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def api():
    fake = FakeSpeechAPI()
    yield fake
    fake.close()


def make(api, **overrides):
    kwargs = dict(base_url=api.base_url, model="whisper-large-v3-turbo", api_key="sk-test",
                  language="en", vocabulary=["Simulink", "KUKA"])
    kwargs.update(overrides)
    return CloudTranscriber(**kwargs)


def test_sends_openai_compatible_request(api):
    text = make(api).transcribe(M4A)
    assert text == "Hello Simulink."

    req = api.requests[0]
    assert req["path"] == "/v1/audio/transcriptions"
    assert req["auth"] == "Bearer sk-test"
    fields = {p.name: p for p in req["parts"]}
    assert fields["model"].data == b"whisper-large-v3-turbo"
    assert fields["language"].data == b"en"
    assert fields["prompt"].data == b"Glossary: Simulink, KUKA."
    assert fields["file"].filename == "dictation.m4a"
    assert fields["file"].content_type == "audio/mp4"
    assert fields["file"].data == M4A


def test_optional_fields_are_omitted(api):
    make(api, language="", vocabulary=[]).transcribe(M4A)
    names = {p.name for p in api.requests[0]["parts"]}
    assert "language" not in names
    assert "prompt" not in names


def test_hint_used_when_bytes_are_unrecognised(api):
    make(api).transcribe(b"unknown-bytes", ".mp3")
    file_part = next(p for p in api.requests[0]["parts"] if p.name == "file")
    assert file_part.filename == "dictation.mp3"


def test_missing_api_key(api):
    with pytest.raises(TranscriptionError, match="No API key"):
        make(api, api_key="").transcribe(M4A)
    assert api.requests == []


def test_caf_is_refused_before_upload(api):
    with pytest.raises(TranscriptionError, match="CAF"):
        make(api).transcribe(b"caff\x00\x01rest")
    assert api.requests == []


def test_api_error_message_is_surfaced():
    fake = FakeSpeechAPI(status=401, payload={"error": {"message": "Invalid API Key"}})
    try:
        with pytest.raises(TranscriptionError, match="rejected the API key: Invalid API Key"):
            make(fake).transcribe(M4A)
    finally:
        fake.close()


def test_unreachable_api():
    t = CloudTranscriber(base_url="http://127.0.0.1:9/v1", model="m", api_key="k", timeout=2)
    with pytest.raises(TranscriptionError, match="Could not reach"):
        t.transcribe(M4A)
