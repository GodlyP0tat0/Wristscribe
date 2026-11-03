"""Core flow: audio or text in, clean text out at the cursor. No HTTP here."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from .cleanup import CleanupError
from .output import Output

log = logging.getLogger(__name__)


class Transcriber(Protocol):
    def transcribe(self, audio: bytes, fmt_hint: str | None = None) -> str: ...


class Cleaner(Protocol):
    def clean(self, text: str) -> str: ...


@dataclass
class Result:
    text: str  # what was inserted (without the trailing space)
    raw: str  # before cleanup
    transcribe_ms: int | None = None
    cleanup_ms: int | None = None

    @property
    def cleaned(self) -> bool:
        return self.cleanup_ms is not None and self.text != self.raw


class DictationService:
    def __init__(
        self,
        transcriber: Transcriber,
        output: Output,
        append_space: bool = True,
        cleaner: Cleaner | None = None,
    ) -> None:
        self.transcriber = transcriber
        self.output = output
        self.append_space = append_space
        self.cleaner = cleaner
        # Two dictations arriving together must not interleave their keystrokes.
        self._insert_lock = threading.Lock()

    def from_text(self, text: str) -> Result:
        """Text already transcribed on the watch."""
        return self._process(text)

    def from_audio(self, audio: bytes, fmt_hint: str | None = None) -> Result:
        start = time.perf_counter()
        text = self.transcriber.transcribe(audio, fmt_hint)
        return self._process(text, transcribe_ms=_ms_since(start))

    def _process(self, text: str, transcribe_ms: int | None = None) -> Result:
        raw = text.strip()
        result = Result(text=raw, raw=raw, transcribe_ms=transcribe_ms)
        if not raw:
            return result
        if self.cleaner:
            start = time.perf_counter()
            try:
                result.text = self.cleaner.clean(raw)
                result.cleanup_ms = _ms_since(start)
            except CleanupError as exc:
                log.warning("Cleanup skipped, typing raw text: %s", exc)
        with self._insert_lock:
            self.output.insert(result.text + " " if self.append_space else result.text)
        return result


def _ms_since(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)
