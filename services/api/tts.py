"""
Spoken answers: the chat's text read aloud by a Gemini voice.

    POST /chat/tts   {"text": ..., "voice": "Kore"}  ->  audio/wav
                     (header X-TTS-Model: which voice model spoke)

Gemini 2.5 Pro TTS first (the best prosody), the flash voices while its quota is closed - on the
free tier the Pro voice has none, so the flash voices speak until the project is on a paid plan
(gemini_pool.TTS, GEMINI_TTS_MODELS). The text is cleaned for speech first (no markdown, no
[citation] brackets), and capped, so a long answer costs a bounded request. Models answer either
raw 16-bit PCM (audio/L16; rate=24000) or WAV; PCM is wrapped in a WAV header here, so the
browser always gets something it can play. Without a key, or with every voice at its limit, the
endpoint says so (503) and the browser speaks with its own voice instead.

  GEMINI_TTS_DAILY_LIMIT   spoken answers per day for the whole service (default 100)
"""

from __future__ import annotations

import base64
import json
import os
import re
import struct
import urllib.error
import urllib.request

from fastapi import HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import gemini_pool as GP
from . import security as sec
from .chat import DailyCap, dotenv

MAX_CHARS = 1200
VOICES = {"Kore", "Puck", "Charon", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr"}
TIMEOUT_S = 60
# short: a long instruction makes the flash voices return no audio at all (finishReason OTHER)
STYLE = "Say calmly and clearly: "
SAY = [
    (r"\s*°\s*C\b", " degrees Celsius"),
    (r"\s*%", " percent"),
    (r"€\s*(\d+(?:[.,]\d+)?)", r"\1 euros"),
    (r"\bkWh\b", "kilowatt hours"),
    (r"\bmm\b", "millimetres"),
    (r"(\d)\s*s\b", r"\1 seconds"),
    (r"\bOEE\b", "O E E"),
    (r"\bPLC\b", "P L C"),
]


class TtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str = Field(default="Kore", max_length=20)


def speakable(md: str) -> str:
    """Markdown and citations out, so the voice reads the answer, not its formatting."""
    t = re.sub(r"\[[^\]]{1,120}\]", "", md)  # [sources]
    t = re.sub(r"[*_`#>|]+", "", t)
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    t = re.sub(r"\s*\n\s*", ". ", t.strip())
    for rx, to in SAY:  # units as words, not symbols
        t = re.sub(rx, to, t)
    t = re.sub(r"\s+([.,;:])", r"\1", t)
    t = re.sub(r"\.\s*\.", ".", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    if len(t) > MAX_CHARS:
        cut = t.rfind(". ", 0, MAX_CHARS)
        t = t[: cut + 1 if cut > MAX_CHARS // 2 else MAX_CHARS]
    return t


def wav(pcm: bytes, rate: int = 24000, channels: int = 1, bits: int = 16) -> bytes:
    """Raw little-endian PCM in a RIFF/WAVE header."""
    block = channels * bits // 8
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(pcm))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * block, block, bits)
        + b"data"
        + struct.pack("<I", len(pcm))
        + pcm
    )


def audio_of(data: dict) -> bytes:
    """The answer's audio as WAV, whatever form the model returned it in."""
    for c in data.get("candidates", [])[:1]:
        for p in (c.get("content") or {}).get("parts", []):
            inline = p.get("inlineData") or {}
            if not inline.get("data"):
                continue
            raw = base64.b64decode(inline["data"])
            mime = inline.get("mimeType", "")
            if "wav" in mime or raw[:4] == b"RIFF":
                return raw
            rate = int(m.group(1)) if (m := re.search(r"rate=(\d+)", mime)) else 24000
            return wav(raw, rate)
    raise ValueError("no audio in the response")


def _post(url: str, key: str, body: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 - fixed https URL
        return json.loads(r.read())


class Tts:
    def __init__(
        self,
        settings: sec.Settings,
        key: str | None = None,
        models: list[str] | None = None,
        daily_limit: int | None = None,
    ) -> None:
        env = {**dotenv(), **os.environ}
        self.s = settings
        self.key = key if key is not None else (env.get("GEMINI_API_KEY") or None)
        self.pool = GP.Pool(models or GP.models_from_env("GEMINI_TTS_MODELS", GP.TTS, env))
        self.cap = DailyCap(daily_limit or int(env.get("GEMINI_TTS_DAILY_LIMIT", "100")))
        self.limiter = sec.RateLimiter(
            rate=0.1, burst=3
        )  # per client: 3 at once, then one per 10 s
        self.post = _post

    def status(self) -> dict:
        return {
            "enabled": bool(self.key),
            "voices": sorted(VOICES),
            "models": self.pool.status() if self.key else [],
        }

    async def speak(self, req: TtsRequest, request: Request) -> Response:
        import asyncio

        origin = request.headers.get("origin")
        if (
            origin
            and origin not in self.s.allowed_origins
            and sec._host(origin.split("://", 1)[-1]) != sec._host(request.headers.get("host"))
        ):
            raise HTTPException(status_code=403, detail="origin not allowed")
        client = request.client.host if request.client else "?"
        if client in ("127.0.0.1", "::1"):
            client = (request.headers.get("x-forwarded-for") or client).split(",")[0].strip()
        if not self.key:
            raise HTTPException(
                status_code=503, detail="no Gemini key on the server: use the browser's voice"
            )
        if not self.limiter.allow(client):
            raise HTTPException(
                status_code=429, detail="too many spoken answers: wait a few seconds"
            )
        text = speakable(req.text)
        if not text:
            raise HTTPException(status_code=400, detail="nothing to say")
        if not self.cap.take():
            raise HTTPException(status_code=429, detail="today's spoken-answer budget is used up")
        voice = req.voice if req.voice in VOICES else "Kore"
        body = {
            "contents": [{"parts": [{"text": STYLE + text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
            },
        }
        try:
            data, model = await asyncio.to_thread(
                self.pool.call, lambda url, b: self.post(url, self.key, b), body, accept=audio_of
            )
            audio = audio_of(data)
        except GP.AllBusy as e:
            raise HTTPException(
                status_code=503, detail=f"every voice is at its limit: {e}"
            ) from None
        except urllib.error.HTTPError as e:
            raise HTTPException(
                status_code=502, detail=f"the voice service answered HTTP {e.code}"
            ) from None
        except (urllib.error.URLError, TimeoutError, ValueError):
            raise HTTPException(
                status_code=504, detail="the voice service did not answer"
            ) from None
        return Response(
            audio,
            media_type="audio/wav",
            headers={"X-TTS-Model": model, "Cache-Control": "no-store"},
        )
