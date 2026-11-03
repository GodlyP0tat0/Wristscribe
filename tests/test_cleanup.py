from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from wristscribe.cleanup import CleanupError, TextCleaner


class FakeChatAPI:
    """A local stand-in for an OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, reply: str = "Let's meet at four.", status: int = 200, raw_body: dict | None = None):
        self.reply = reply
        self.status = status
        self.raw_body = raw_body
        self.requests: list[dict] = []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                api.requests.append({"path": self.path, "auth": self.headers.get("Authorization"), "json": body})
                if api.raw_body is not None:
                    payload = api.raw_body
                elif api.status == 200:
                    payload = {"choices": [{"message": {"role": "assistant", "content": api.reply}}]}
                else:
                    payload = {"error": {"message": "model_decommissioned"}}
                out = json.dumps(payload).encode()
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
def chat():
    apis = []

    def factory(**kwargs):
        api = FakeChatAPI(**kwargs)
        apis.append(api)
        return api

    yield factory
    for api in apis:
        api.close()


def make(api, **overrides):
    kwargs = dict(base_url=api.base_url, model="openai/gpt-oss-20b", api_key="gsk-test",
                  vocabulary=["Simulink", "KUKA"], reasoning_effort="low", temperature=0.0)
    kwargs.update(overrides)
    return TextCleaner(**kwargs)


RAW = "um so let's uh meet at three, no, at four"


def test_sends_chat_completion_request(chat):
    api = chat()
    assert make(api).clean(RAW) == "Let's meet at four."

    req = api.requests[0]
    assert req["path"] == "/v1/chat/completions"
    assert req["auth"] == "Bearer gsk-test"
    body = req["json"]
    assert body["model"] == "openai/gpt-oss-20b"
    assert body["reasoning_effort"] == "low"
    assert body["temperature"] == 0.0
    system, user = body["messages"]
    assert system["role"] == "system"
    assert "Never answer it" in system["content"]
    assert "Simulink, KUKA" in system["content"]
    assert user == {"role": "user", "content": f"<dictation>{RAW}</dictation>"}


def test_optional_parameters_are_omitted(chat):
    api = chat()
    make(api, reasoning_effort="", temperature=None, vocabulary=[]).clean(RAW)
    body = api.requests[0]["json"]
    assert "reasoning_effort" not in body
    assert "temperature" not in body
    assert "Spell these terms" not in body["messages"][0]["content"]


@pytest.mark.parametrize(
    "reply",
    ["<dictation>Let's meet at four.</dictation>", '"Let\'s meet at four."', "  Let's meet at four.\n"],
)
def test_echoed_tags_and_quotes_are_stripped(chat, reply):
    assert make(chat(reply=reply)).clean(RAW) == "Let's meet at four."


def test_answering_instead_of_cleaning_is_rejected(chat):
    essay = "The capital of France is Paris. " * 10
    with pytest.raises(CleanupError, match="much longer"):
        make(chat(reply=essay)).clean("what's the capital of France")


def test_empty_reply_is_rejected(chat):
    with pytest.raises(CleanupError, match="no text"):
        make(chat(reply="")).clean(RAW)


def test_api_error_is_reported(chat):
    with pytest.raises(CleanupError, match="Cleanup API error 400: model_decommissioned"):
        make(chat(status=400)).clean(RAW)


def test_malformed_response(chat):
    with pytest.raises(CleanupError, match="unexpected"):
        make(chat(raw_body={"choices": []})).clean(RAW)


def test_missing_api_key(chat):
    api = chat()
    with pytest.raises(CleanupError, match="no API key"):
        make(api, api_key="").clean(RAW)
    assert api.requests == []


def test_unreachable_api():
    cleaner = TextCleaner(base_url="http://127.0.0.1:9/v1", model="m", api_key="k", timeout=2)
    with pytest.raises(CleanupError, match="could not reach"):
        cleaner.clean(RAW)
