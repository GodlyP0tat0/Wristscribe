"""Core flow: audio or text in, clean text out at the cursor. No HTTP here."""

from __future__ import annotations

import threading
import time
from typing import Protocol

from .output import Output


class Transcriber(Protocol):
    def transcribe(self, audio: bytes, fmt_hint: str | None = None) -> str: ...


class DictationService:
    def __init__(self, transcriber: Transcriber, output: Output, append_space: bool = True) -> None:
        self.transcriber = transcriber
        self.output = output
        self.append_space = append_space
        # Two dictations arriving together must not interleave their keystrokes.
        self._insert_lock = threading.Lock()

    def from_text(self, text: str) -> str:
        """Text already transcribed on the watch. Returns what was inserted."""
        return self._insert(text)

    def from_audio(self, audio: bytes, fmt_hint: str | None = None) -> tuple[str, int]:
        """Transcribe audio, insert the text. Returns (inserted text, transcription time in ms)."""
        start = time.perf_counter()
        text = self.transcriber.transcribe(audio, fmt_hint)
        elapsed_ms = round((time.perf_counter() - start) * 1000)
        return self._insert(text), elapsed_ms

    def _insert(self, text: str) -> str:
        clean = text.strip()
        if not clean:
            return ""
        with self._insert_lock:
            self.output.insert(clean + " " if self.append_space else clean)
        return clean
