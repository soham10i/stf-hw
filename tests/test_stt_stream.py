"""The streamed question (voice/stt_stream.py): the browser's audio reaches the transcriber as
Scribe Realtime's chunks, partial words come back as they are recognised, the end commits, the
final text is in the factory's names, and a transcriber that fails or never opens ends the
stream with an error, so the browser uploads its recording instead. No call leaves the test."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.testclient import TestClient

from services.api.voice import stt_stream as SS


class FakeScribe:
    """Scribe Realtime as the relay sees it: records what was sent, answers from a script.
    `script` maps what arrives to what it says: a partial per audio chunk, the commit's text."""

    def __init__(self, partials=("store", "store in a"), final="store in a two", fail=None):
        self.sent: list[dict] = []
        self.partials = list(partials)
        self.final, self.fail = final, fail
        self.q: asyncio.Queue = asyncio.Queue()
        self.closed = False

    async def send(self, raw: str) -> None:
        m = json.loads(raw)
        self.sent.append(m)
        if self.fail:
            await self.q.put(json.dumps({"message_type": self.fail, "error": "nope"}))
        elif m["commit"]:
            await self.q.put(
                json.dumps({"message_type": "committed_transcript", "text": self.final})
            )
        elif self.partials:
            await self.q.put(
                json.dumps({"message_type": "partial_transcript", "text": self.partials.pop(0)})
            )

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed:
            raise StopAsyncIteration
        return await self.q.get()

    async def close(self):
        self.closed = True


def app_with(relay: SS.SttStream) -> TestClient:
    app = FastAPI()

    @app.websocket("/s")
    async def s(ws: WebSocket):
        await relay.serve(ws)

    return TestClient(app)


def relay_to(fake, **env) -> SS.SttStream:
    async def connect(url, key):
        assert (
            key == "k" and "model_id=scribe_v2_realtime" in url and "audio_format=pcm_16000" in url
        )
        assert "commit_strategy=manual" in url
        if isinstance(fake, Exception):
            raise fake
        return fake

    return SS.SttStream({"ELEVENLABS_API_KEY": "k", **env}, connect=connect)


def test_audio_goes_up_words_come_down_and_the_end_commits():
    fake = FakeScribe()
    with app_with(relay_to(fake)).websocket_connect("/s") as ws:
        ws.send_bytes(b"\x01\x00" * 1600)
        assert ws.receive_json() == {"type": "partial", "text": "store"}
        ws.send_bytes(b"\x02\x00" * 1600)
        assert ws.receive_json() == {"type": "partial", "text": "store in a"}
        ws.send_text(json.dumps({"type": "end"}))
        final = ws.receive_json()
    assert final == {
        "type": "final",
        "text": "store in A2",
        "heard": "store in a two",
        "model": "elevenlabs scribe_v2_realtime",
    }
    audio, commit = fake.sent[:2], fake.sent[-1]
    assert all(
        m["message_type"] == "input_audio_chunk" and m["sample_rate"] == 16000 for m in fake.sent
    )
    assert (
        base64.b64decode(audio[0]["audio_base_64"]) == b"\x01\x00" * 1600 and not audio[0]["commit"]
    )
    assert commit["commit"] is True and commit["audio_base_64"] == ""


def test_a_failing_transcriber_ends_the_stream_with_an_error():
    fake = FakeScribe(fail="quota_exceeded")
    with app_with(relay_to(fake)).websocket_connect("/s") as ws:
        ws.send_bytes(b"\x00\x00" * 1600)
        err = ws.receive_json()
        assert err["type"] == "error" and err["message"] == "transcriber: quota_exceeded"
        assert err["reason"] == "transcriber_failed" and err["status"] == 502
        # nothing more: no final text the browser could mistake for the question
        ws.send_text(json.dumps({"type": "end"}))
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_a_transcriber_that_does_not_open_says_so():
    with app_with(relay_to(OSError("down"))).websocket_connect("/s") as ws:
        err = ws.receive_json()
        assert err["reason"] == "transcriber_unavailable"
        assert err["error"] == "the streaming transcriber did not answer"


def test_without_a_key_or_switched_off_there_is_no_stream():
    for env in ({"ELEVENLABS_API_KEY": ""}, {"ELEVENLABS_API_KEY": "k", "STT_STREAM": "0"}):
        relay = SS.SttStream(env, connect=None)
        assert not relay.ready()
        with app_with(relay).websocket_connect("/s") as ws:
            assert ws.receive_json()["type"] == "error"


def test_the_longest_question_is_ended_by_the_server(monkeypatch):
    monkeypatch.setattr(SS, "MAX_BYTES", 6400)
    fake = FakeScribe(partials=())
    with app_with(relay_to(fake)).websocket_connect("/s") as ws:
        ws.send_bytes(b"\x00\x00" * 2000)  # 4000 bytes
        ws.send_bytes(b"\x00\x00" * 2000)  # 4000 more: cut at 6400, then committed
        final = ws.receive_json()
    sent = sum(len(base64.b64decode(m["audio_base_64"])) for m in fake.sent)
    assert sent == 6400 and fake.sent[-1]["commit"] and final["type"] == "final"


def test_the_status_says_whether_streaming_is_on():
    import services.api.app as appmod

    with TestClient(appmod.app) as c:
        st = c.get("/chat/stt/status").json()
    assert st["stream"] == appmod.stt_stream.ready()
