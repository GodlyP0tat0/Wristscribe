"""Put dictated text wherever the keyboard cursor is.

The keyboard/clipboard libraries are imported lazily so the rest of the app
(and the test suite) works on machines without a desktop session.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Protocol, TextIO

log = logging.getLogger(__name__)


class Output(Protocol):
    name: str

    def insert(self, text: str) -> None: ...


class PrintOutput:
    """Print to the console instead of typing. Used by --dry-run."""

    name = "print"

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stdout

    def insert(self, text: str) -> None:
        print(f"[dictation] {text}", file=self._stream, flush=True)


class TypeOutput:
    """Simulate key presses. Leaves the clipboard alone; slower for long text."""

    name = "type"

    def __init__(self) -> None:
        from pynput.keyboard import Controller

        self._kb = Controller()

    def insert(self, text: str) -> None:
        self._kb.type(text)


class PasteOutput:
    """Copy to the clipboard, press Ctrl+V (Cmd+V on macOS), then restore the old clipboard."""

    name = "paste"

    def __init__(self, restore_clipboard: bool = True, settle_seconds: float = 0.3) -> None:
        import pyperclip
        from pynput.keyboard import Controller, Key

        self._clipboard = pyperclip
        self._kb = Controller()
        self._modifier = Key.cmd if sys.platform == "darwin" else Key.ctrl
        self._restore = restore_clipboard
        self._settle = settle_seconds

    def insert(self, text: str) -> None:
        previous = self._read_clipboard() if self._restore else None
        self._clipboard.copy(text)
        time.sleep(0.05)  # let the OS publish the new clipboard before pasting
        with self._kb.pressed(self._modifier):
            self._kb.press("v")
            self._kb.release("v")
        # Only restore real text. If the clipboard held an image or was empty,
        # pyperclip reads "", and writing that back would wipe it anyway.
        if previous:
            time.sleep(self._settle)  # give the target app time to read the clipboard
            self._clipboard.copy(previous)

    def _read_clipboard(self) -> str | None:
        try:
            return self._clipboard.paste()
        except Exception:  # pyperclip raises its own exception types per platform
            log.debug("Could not read clipboard", exc_info=True)
            return None


def make_output(mode: str, restore_clipboard: bool = True) -> Output:
    try:
        if mode == "paste":
            return PasteOutput(restore_clipboard=restore_clipboard)
        if mode == "type":
            return TypeOutput()
    except ImportError as exc:
        raise RuntimeError(
            f"Output mode '{mode}' needs pynput and pyperclip. Install them with: pip install -e ."
        ) from exc
    if mode == "print":
        return PrintOutput()
    raise ValueError(f"Unknown output mode: {mode}")
