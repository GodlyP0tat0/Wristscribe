"""Output tests with fake keyboard/clipboard modules, so they run headless and on any OS."""

from __future__ import annotations

import io
import sys
import types

import pytest

from wristscribe.output import PasteOutput, PrintOutput, TypeOutput, make_output


class FakeClipboard(types.ModuleType):
    def __init__(self, initial: str = "") -> None:
        super().__init__("pyperclip")
        self.value = initial
        self.history: list[str] = []

    def copy(self, text: str) -> None:
        self.value = text
        self.history.append(text)

    def paste(self) -> str:
        return self.value


class FakeKeyboard:
    events: list[tuple] = []

    def type(self, text):
        self.events.append(("type", text))

    def press(self, key):
        self.events.append(("press", key))

    def release(self, key):
        self.events.append(("release", key))

    def pressed(self, key):
        events = self.events

        class _Ctx:
            def __enter__(self):
                events.append(("hold", key))

            def __exit__(self, *exc):
                events.append(("let-go", key))

        return _Ctx()


@pytest.fixture
def fakes(monkeypatch):
    FakeKeyboard.events = []
    keyboard = types.ModuleType("pynput.keyboard")
    keyboard.Controller = FakeKeyboard
    keyboard.Key = types.SimpleNamespace(ctrl="CTRL", cmd="CMD")
    pynput = types.ModuleType("pynput")
    pynput.keyboard = keyboard
    clipboard = FakeClipboard("my old clipboard")
    monkeypatch.setitem(sys.modules, "pynput", pynput)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", keyboard)
    monkeypatch.setitem(sys.modules, "pyperclip", clipboard)
    monkeypatch.setattr(sys, "platform", "win32")
    return clipboard


def test_paste_presses_ctrl_v_and_restores_clipboard(fakes):
    PasteOutput(settle_seconds=0).insert("dictated text")
    assert FakeKeyboard.events == [("hold", "CTRL"), ("press", "v"), ("release", "v"), ("let-go", "CTRL")]
    assert fakes.history == ["dictated text", "my old clipboard"]
    assert fakes.value == "my old clipboard"


def test_paste_uses_cmd_on_macos(fakes, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    PasteOutput(settle_seconds=0).insert("x")
    assert FakeKeyboard.events[0] == ("hold", "CMD")


def test_paste_leaves_transcript_when_clipboard_was_empty(fakes):
    fakes.value = ""
    PasteOutput(settle_seconds=0).insert("dictated text")
    assert fakes.value == "dictated text"


def test_paste_without_restore(fakes):
    PasteOutput(restore_clipboard=False, settle_seconds=0).insert("dictated text")
    assert fakes.history == ["dictated text"]


def test_type_output_types_text(fakes):
    TypeOutput().insert("città")
    assert FakeKeyboard.events == [("type", "città")]


def test_make_output_modes(fakes):
    assert make_output("paste").name == "paste"
    assert make_output("type").name == "type"
    assert make_output("print").name == "print"
    with pytest.raises(ValueError):
        make_output("shout")


def test_missing_dependencies_give_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "pynput", None)  # makes `import pynput` raise ImportError
    with pytest.raises(RuntimeError, match="pip install"):
        make_output("paste")


def test_print_output():
    stream = io.StringIO()
    PrintOutput(stream).insert("hello")
    assert stream.getvalue() == "[dictation] hello\n"
