from __future__ import annotations

import http.client

import requests

from conftest import TOKEN

M4A_HEADER = b"\x00\x00\x00\x20ftypM4A \x00\x00\x02\x00"
FAKE_M4A = M4A_HEADER + bytes(range(256)) * 4 + b"\r\n--not-a-boundary\r\n"


# ---- auth ---------------------------------------------------------------

def test_ping_with_bearer_token(harness):
    r = requests.get(f"{harness.base}/ping", headers=harness.auth)
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_ping_with_query_token(harness):
    r = requests.get(f"{harness.base}/ping", params={"token": TOKEN})
    assert r.status_code == 200


def test_ping_with_custom_header(harness):
    r = requests.get(f"{harness.base}/ping", headers={"X-WristScribe-Token": TOKEN})
    assert r.status_code == 200


def test_missing_token_is_rejected(harness):
    r = requests.post(f"{harness.base}/text", json={"text": "hi"})
    assert r.status_code == 401
    assert harness.output.inserted == []


def test_wrong_token_is_rejected(harness):
    r = requests.post(f"{harness.base}/text", json={"text": "hi"}, headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    assert harness.output.inserted == []


def test_unknown_endpoint(harness):
    r = requests.post(f"{harness.base}/nope", headers=harness.auth, data=b"x")
    assert r.status_code == 404


# ---- /text --------------------------------------------------------------

def test_text_json(harness):
    r = requests.post(f"{harness.base}/text", json={"text": "  Ciao, world  "}, headers=harness.auth)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "text": "Ciao, world"}
    assert harness.output.inserted == ["Ciao, world "]


def test_text_plain(harness):
    r = requests.post(
        f"{harness.base}/text",
        data="perché no".encode(),
        headers={**harness.auth, "Content-Type": "text/plain; charset=utf-8"},
    )
    assert r.status_code == 200
    assert harness.output.inserted == ["perché no "]


def test_text_urlencoded_form(harness):
    r = requests.post(f"{harness.base}/text", data={"text": "a & b"}, headers=harness.auth)
    assert r.status_code == 200
    assert harness.output.inserted == ["a & b "]


def test_text_multipart_form(harness):
    r = requests.post(f"{harness.base}/text", files={"text": (None, "from a form")}, headers=harness.auth)
    assert r.status_code == 200
    assert harness.output.inserted == ["from a form "]


def test_text_keeps_dictated_newlines(harness):
    requests.post(f"{harness.base}/text", json={"text": "line one\nline two"}, headers=harness.auth)
    assert harness.output.inserted == ["line one\nline two "]


def test_empty_text_is_rejected(harness):
    r = requests.post(f"{harness.base}/text", json={"text": "   "}, headers=harness.auth)
    assert r.status_code == 400
    assert harness.output.inserted == []


def test_bad_json_is_rejected(harness):
    r = requests.post(
        f"{harness.base}/text", data=b"{oops", headers={**harness.auth, "Content-Type": "application/json"}
    )
    assert r.status_code == 400


def test_concurrent_requests_do_not_interleave(harness):
    from concurrent.futures import ThreadPoolExecutor

    texts = [f"message {i}" for i in range(20)]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda t: requests.post(f"{harness.base}/text", json={"text": t}, headers=harness.auth), texts))
    assert sorted(harness.output.inserted) == sorted(t + " " for t in texts)


# ---- /audio -------------------------------------------------------------

def test_audio_raw_body(harness):
    r = requests.post(
        f"{harness.base}/audio",
        data=FAKE_M4A,
        headers={**harness.auth, "Content-Type": "audio/x-m4a"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "hello from the watch"
    assert "transcribe_ms" in body
    assert harness.transcriber.calls == [(FAKE_M4A, "m4a")]
    assert harness.output.inserted == ["hello from the watch "]


def test_audio_multipart_is_binary_safe(harness):
    r = requests.post(
        f"{harness.base}/audio",
        files={"file": ("Recording.m4a", FAKE_M4A, "application/octet-stream")},
        headers=harness.auth,
    )
    assert r.status_code == 200
    audio, hint = harness.transcriber.calls[0]
    assert audio == FAKE_M4A
    assert hint == "m4a"


def test_audio_chunked_upload(harness):
    def chunks():
        yield FAKE_M4A[:100]
        yield FAKE_M4A[100:]

    r = requests.post(f"{harness.base}/audio", data=chunks(), headers=harness.auth)
    assert r.status_code == 200
    assert harness.transcriber.calls[0][0] == FAKE_M4A


def test_audio_format_query_overrides_content_type(harness):
    requests.post(
        f"{harness.base}/audio?format=wav",
        data=b"RIFF....WAVE",
        headers={**harness.auth, "Content-Type": "application/octet-stream"},
    )
    assert harness.transcriber.calls[0][1] == "wav"


def test_empty_audio_is_rejected(harness):
    r = requests.post(f"{harness.base}/audio", data=b"", headers=harness.auth)
    assert r.status_code == 400
    assert harness.transcriber.calls == []


def test_silence_inserts_nothing(harness):
    harness.transcriber.reply = "   "
    r = requests.post(f"{harness.base}/audio", data=FAKE_M4A, headers=harness.auth)
    assert r.status_code == 200
    assert r.json()["text"] == ""
    assert harness.output.inserted == []


def test_transcription_error_returns_502(harness):
    harness.transcriber.error = "Speech API rejected the API key"
    r = requests.post(f"{harness.base}/audio", data=FAKE_M4A, headers=harness.auth)
    assert r.status_code == 502
    assert "API key" in r.json()["error"]
    assert harness.output.inserted == []


def test_upload_too_large(harness):
    host, port = harness.server.server_address[:2]
    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.putrequest("POST", "/audio")
    conn.putheader("Authorization", f"Bearer {TOKEN}")
    conn.putheader("Content-Length", str(harness.server.max_body + 1))
    conn.endheaders()  # don't send the body: the server must refuse from the header alone
    resp = conn.getresponse()
    assert resp.status == 413
    conn.close()
