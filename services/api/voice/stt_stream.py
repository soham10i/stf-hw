"""
The spoken question as text while it is being said: the browser streams the microphone to
WS /chat/stt/stream, this relay passes it on to ElevenLabs Scribe Realtime, and the words come
back as they are recognised. The ElevenLabs key stays on the server; the browser never sees it.

    browser                         this relay                         Scribe Realtime
    binary frames: PCM 16 kHz  ->   {"message_type": "input_audio_chunk",
    mono 16-bit little-endian       "audio_base_64", "commit": false, "sample_rate": 16000}  ->
    {"type": "end"}            ->   the same with "commit": true and no audio                  ->
                               <-   {"type": "partial", "text"}     <-  partial_transcript
                               <-   {"type": "final", "text",       <-  committed_transcript
                                     "heard"?, "model"}
                               <-   {"type": "error", "code",       <-  any error message, or ours
                                     "reason", "message", ...}         (core/errors.py's body)

The commit is manual: the browser decides when the question has ended (its end-of-speech
detector, or a tap), so a pause in the middle of a sentence never cuts it in two. The final
text is written in the factory's names (spoken.py) before the browser asks it.

Bounds, so one visitor cannot hold the transcriber: MAX_S of audio per question, AT_ONCE
streams on the server, the transcription rate limit shared with POST /chat/stt (Stt.limiter,
checked by the endpoint), and FINAL_WAIT_S for the final text after the end - past it, the last
partial text is taken as the question. A transcriber that fails mid-question ends the stream
with an error; the browser then uploads the recording it kept (Voice.tsx).

  ELEVENLABS_API_KEY        the key (the same as the voice and the one-shot transcriber)
  ELEVENLABS_STT_RT_MODEL   default scribe_v2_realtime
  ELEVENLABS_STT_RT_URL     default wss://api.elevenlabs.io/v1/speech-to-text/realtime
  STT_STREAM                0 turns the stream off (the browser then records and uploads)
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import urllib.parse
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from services.api.agent.chat import dotenv
from services.api.core.errors import Reason, error_body
from services.api.core.logging_config import get_logger
from services.api.voice import spoken

logger = get_logger(__name__)

RATE = 16000                 # samples a second, 16-bit mono: 32000 bytes a second
MAX_S = 30                   # the longest question streamed
MAX_BYTES = MAX_S * RATE * 2
FINAL_WAIT_S = 5.0           # the final text after the end, at most
OPEN_WAIT_S = 6.0            # the transcriber's session to start, at most
AT_ONCE = 8                  # streams open on this server together


def _connect(url: str, key: str):
    """A WebSocket to the transcriber (websockets' client), to be awaited; replaced in the tests."""
    import websockets

    return websockets.connect(url, additional_headers={"xi-api-key": key}, max_size=2**20,
                              open_timeout=OPEN_WAIT_S)


class SttStream:
    """The relay's settings and its one entry point, `serve`."""

    def __init__(self, env: dict | None = None, connect: Callable[[str, str], Any] = _connect):
        env = {**dotenv(), **os.environ} if env is None else env
        self.key = env.get("ELEVENLABS_API_KEY") or None
        self.model = env.get("ELEVENLABS_STT_RT_MODEL", "scribe_v2_realtime")
        self.base = env.get(
            "ELEVENLABS_STT_RT_URL", "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
        )
        self.on = env.get("STT_STREAM", "1").strip().lower() not in ("0", "false", "no")
        self.connect = connect
        self.open = 0  # streams open now

    def ready(self) -> bool:
        return self.on and bool(self.key)

    def url(self) -> str:
        q = {"model_id": self.model, "audio_format": f"pcm_{RATE}", "commit_strategy": "manual"}
        return f"{self.base}?{urllib.parse.urlencode(q)}"

    async def serve(self, ws: WebSocket) -> None:
        """One question: relay audio up and text down until the final text, then close."""
        await ws.accept()
        if not self.ready() or self.open >= AT_ONCE:
            why = "busy: try again" if self.ready() else "no streaming transcriber on the server"
            await _fail(ws, Reason.TRANSCRIBER_UNAVAILABLE, why)
            await ws.close(code=1013)
            return
        self.open += 1
        try:
            await self._relay(ws)
        finally:
            self.open -= 1

    async def _relay(self, ws: WebSocket) -> None:
        try:
            up = await asyncio.wait_for(self.connect(self.url(), self.key), OPEN_WAIT_S)
        except Exception as e:  # noqa: BLE001 - any failure to open is "use the upload instead"
            logger.warning("Scribe Realtime did not open: %s", e)
            await _fail(
                ws, Reason.TRANSCRIBER_UNAVAILABLE, "the streaming transcriber did not answer"
            )
            await ws.close(code=1011)
            return
        state = {"partial": "", "final": None, "ended": False, "failed": False, "sent": 0}
        done = asyncio.Event()
        try:
            down = asyncio.create_task(self._down(ws, up, state, done))
            await self._up(ws, up, state, done)
            # the end was sent (or the browser left): wait for the final text, briefly
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(done.wait(), FINAL_WAIT_S)
            down.cancel()
            text = state["final"] if state["final"] is not None else state["partial"]
            if state["ended"] and not state["failed"]:
                out = spoken.heard(
                    {"text": (text or "").strip()[:500], "model": f"elevenlabs {self.model}"}
                )
                await _send(ws, {"type": "final", **out})
        except WebSocketDisconnect:
            pass
        finally:
            with contextlib.suppress(Exception):
                await up.close()
            with contextlib.suppress(Exception):
                await ws.close()

    async def _up(self, ws: WebSocket, up, state: dict, failed: asyncio.Event) -> None:
        """The browser's audio to the transcriber, until its end message, the bounds, or the
        transcriber failing (`failed` is set by _down)."""
        while not failed.is_set():
            got = asyncio.ensure_future(ws.receive())
            stop = asyncio.ensure_future(failed.wait())
            await asyncio.wait({got, stop}, return_when=asyncio.FIRST_COMPLETED)
            stop.cancel()
            if not got.done():
                got.cancel()
                return
            msg = got.result()
            if msg.get("type") == "websocket.disconnect":
                return
            data = msg.get("bytes")
            if data is not None:
                if state["sent"] + len(data) > MAX_BYTES:
                    data = data[: max(0, MAX_BYTES - state["sent"])]
                if data:
                    state["sent"] += len(data)
                    await up.send(json.dumps(_chunk(data)))
                if state["sent"] >= MAX_BYTES:  # the longest question: end it here
                    await self._end(up, state)
                    return
                continue
            try:
                body = json.loads(msg.get("text") or "{}")
            except ValueError:
                continue
            if body.get("type") == "end":
                await self._end(up, state)
                return

    async def _end(self, up, state: dict) -> None:
        state["ended"] = True
        await up.send(json.dumps(_chunk(b"", commit=True)))

    async def _down(self, ws: WebSocket, up, state: dict, done: asyncio.Event) -> None:
        """The transcriber's words to the browser: partials as they come, the committed text
        once the end was sent."""
        async for raw in up:
            try:
                m = json.loads(raw)
            except (TypeError, ValueError):
                continue
            kind = m.get("message_type")
            if kind == "partial_transcript":
                text = (m.get("text") or "").strip()
                if text and text != state["partial"]:
                    state["partial"] = text
                    await _send(ws, {"type": "partial", "text": text})
            elif kind == "committed_transcript":
                text = (m.get("text") or "").strip()
                # a commit before the end (none is asked for, but one may come) joins the rest
                state["final"] = f"{state['final']} {text}".strip() if state["final"] else text
                if state["ended"]:
                    done.set()
                    return
            elif "error" in m:
                logger.warning("Scribe Realtime: %s: %s", kind, m.get("error"))
                await _fail(ws, Reason.TRANSCRIBER_FAILED, f"transcriber: {kind}")
                state["failed"] = True
                done.set()
                return
        if not state["ended"]:
            state["failed"] = True  # closed before the question ended
        done.set()


def _chunk(data: bytes, commit: bool = False) -> dict:
    return {
        "message_type": "input_audio_chunk",
        "audio_base_64": base64.b64encode(data).decode(),
        "commit": commit,
        "sample_rate": RATE,
    }


async def _fail(ws: WebSocket, reason: Reason, message: str) -> None:
    await _send(ws, {"type": "error", **error_body(reason.code, message, reason)})


async def _send(ws: WebSocket, body: dict) -> None:
    with contextlib.suppress(Exception):
        await ws.send_text(json.dumps(body))
