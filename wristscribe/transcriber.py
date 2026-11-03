"""Cloud speech-to-text through any OpenAI-compatible /audio/transcriptions endpoint.

Groq and OpenAI both expose the same API shape, so one small client covers both.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

import requests

from .api import describe_error

if TYPE_CHECKING:
    from .config import TranscriptionConfig

log = logging.getLogger(__name__)

# Formats the Whisper-style APIs accept, with the MIME type sent for each.
SUPPORTED_FORMATS = {
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "mp3": "audio/mpeg",
    "mpeg": "audio/mpeg",
    "mpga": "audio/mpeg",
    "wav": "audio/wav",
    "webm": "audio/webm",
    "ogg": "audio/ogg",
    "flac": "audio/flac",
}

_CONTENT_TYPE_FORMATS = {
    "audio/mp4": "m4a",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "video/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/x-wav": "wav",
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
    "audio/x-caf": "caf",
}


class TranscriptionError(Exception):
    """Speech-to-text failed. The message is safe to show to the user."""


def sniff_audio_format(data: bytes) -> str | None:
    """Identify the container format from the file's first bytes."""
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "m4a"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if data[:4] == b"fLaC":
        return "flac"
    if data[:4] == b"caff":
        return "caf"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    return None


def format_from_content_type(content_type: str) -> str | None:
    return _CONTENT_TYPE_FORMATS.get(content_type.split(";")[0].strip().lower())


class CloudTranscriber:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        language: str | None = None,
        vocabulary: Sequence[str] = (),
        timeout: float = 60.0,
        session: requests.Session | None = None,
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/audio/transcriptions"
        self.model = model
        self.api_key = api_key
        self.language = language or None
        self.vocabulary = [w for w in vocabulary if w.strip()]
        self.timeout = timeout
        self._http = session or requests.Session()

    @classmethod
    def from_config(cls, cfg: TranscriptionConfig) -> CloudTranscriber:
        return cls(
            base_url=cfg.endpoint,
            model=cfg.model_name,
            api_key=cfg.resolved_api_key,
            language=cfg.language,
            vocabulary=cfg.vocabulary,
            timeout=cfg.timeout_seconds,
        )

    def transcribe(self, audio: bytes, fmt_hint: str | None = None) -> str:
        if not self.api_key:
            raise TranscriptionError(
                "No API key configured. Set api_key in config.toml or the WRISTSCRIBE_API_KEY environment variable."
            )
        hint = (fmt_hint or "").lower().lstrip(".") or None
        fmt = sniff_audio_format(audio) or hint or "m4a"
        if fmt == "caf":
            raise TranscriptionError("CAF audio is not supported by the speech API. Record as M4A instead.")
        if fmt not in SUPPORTED_FORMATS:
            raise TranscriptionError(f"Unsupported audio format: {fmt}")

        form = {"model": self.model, "response_format": "json"}
        if self.language:
            form["language"] = self.language
        if self.vocabulary:
            # Whisper copies the spelling of words it sees in the prompt.
            form["prompt"] = "Glossary: " + ", ".join(self.vocabulary) + "."

        try:
            resp = self._http.post(
                self.url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=form,
                files={"file": (f"dictation.{fmt}", audio, SUPPORTED_FORMATS[fmt])},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise TranscriptionError(f"Could not reach the speech API: {exc}") from exc

        if resp.status_code != 200:
            raise TranscriptionError(describe_error(resp, "Speech API"))
        try:
            return str(resp.json().get("text", "")).strip()
        except ValueError as exc:
            raise TranscriptionError("Speech API returned a response that is not JSON") from exc
