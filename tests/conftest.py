from __future__ import annotations

import threading

import pytest

from wristscribe.dictation import DictationService
from wristscribe.server import WristScribeServer
from wristscribe.transcriber import TranscriptionError

TOKEN = "test-token-123456"


class RecordingOutput:
    name = "recording"

    def __init__(self) -> None:
        self.inserted: list[str] = []

    def insert(self, text: str) -> None:
        self.inserted.append(text)


class FakeTranscriber:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str | None]] = []
        self.reply = "hello from the watch"
        self.error: str | None = None

    def transcribe(self, audio: bytes, fmt_hint: str | None = None) -> str:
        self.calls.append((audio, fmt_hint))
        if self.error:
            raise TranscriptionError(self.error)
        return self.reply


class Harness:
    def __init__(self, server: WristScribeServer, output: RecordingOutput, transcriber: FakeTranscriber):
        self.server = server
        self.output = output
        self.transcriber = transcriber
        host, port = server.server_address[:2]
        self.base = f"http://{host}:{port}"
        self.auth = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def harness():
    output, transcriber = RecordingOutput(), FakeTranscriber()
    service = DictationService(transcriber, output, append_space=True)
    server = WristScribeServer(("127.0.0.1", 0), TOKEN, service, max_body=1024 * 1024)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield Harness(server, output, transcriber)
    server.shutdown()
    server.server_close()
