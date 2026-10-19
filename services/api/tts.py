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

import asyncio
import base64
import hashlib
import io
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from . import gemini_pool as GP
from . import security as sec
from .chat import DailyCap, dotenv
from .logging_config import get_logger

logger = get_logger(__name__)

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
    """The answer's content only, as words: no markdown, links, formulas or headings -
    and nothing after a Sources / Resources heading (the evidence list is not read aloud)."""
    # the evidence and further-reading lists are for the eye, not the voice
    t = re.split(r"(?im)^#{1,4}\s*(sources?|resources|references|further reading)\b.*$",
                 md, maxsplit=1)[0]
    t = re.sub(r"!?\[([^\]]{1,160})\]\((https?://[^)\s]+)\)", r"\1", t)  # links keep their text
    t = re.sub(r"\[[^\]]{1,120}\]", "", t)  # [sources]
    t = re.sub(r"https?://\S+|www\.\S+", "", t)  # bare URLs
    t = re.sub(
        r"\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^$\n]{1,400}\$",
        " (formula) ",
        t,
    )  # LaTeX
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


def split_sentences(text: str, max_chars: int = 280) -> list[str]:
    """The read-aloud text as synthesis-sized pieces. A period ends a sentence only when
    followed by whitespace and a capital, digit or quote - never inside a number ("3.5 V") or
    an abbreviation ("e.g."). Tiny fragments are read with the sentence before them; what is
    still longer than ~max_chars is halved at the comma or semicolon nearest the middle, so no
    single synthesis request carries a whole paragraph."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[\"'“‘A-Z0-9])", text) if p.strip()]
    joined: list[str] = []
    for p in parts:
        if joined and len(p) < 25 and not p.endswith((".", "!", "?")):
            joined[-1] += " " + p  # a heading-like fragment: read it with the sentence before
            continue
        joined.append(p)
    out: list[str] = []
    for p in joined:
        while len(p) > max_chars:
            window = p[:max_chars]
            cut = window.rfind(", ")
            if cut < max_chars // 2:
                cut = window.rfind(" ")
            if cut <= 0:
                break
            out.append(p[:cut].strip().rstrip(","))
            p = p[cut:].strip()
        out.append(p)
    return [p for p in out if p]


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


# ------------------------------------------------------------------ the providers
class Unavailable(Exception):
    """A provider cannot speak now (no key, every model at its limit, not installed)."""


class GeminiVoice:
    """Gemini TTS, its models in turn (gemini_pool.TTS): Pro first, the flash voices next."""

    name = "gemini"

    def __init__(self, key: str | None, models: list[str], post) -> None:
        self.key, self.pool, self.post = key, GP.Pool(models), post

    def ready(self) -> bool:
        return bool(self.key)

    def _body(self, text: str, voice: str) -> dict:
        name = voice if voice in VOICES else "Kore"
        return {
            "contents": [{"parts": [{"text": STYLE + text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": name}}},
            },
        }

    def speak(self, text: str, voice: str) -> tuple[bytes, str, str]:
        if not self.key:
            raise Unavailable("no Gemini key")
        try:
            data, model = self.pool.call(
                lambda url, b: self.post(url, self.key, b), self._body(text, voice), accept=audio_of
            )
        except GP.AllBusy as e:
            raise Unavailable(f"every Gemini voice is at its limit: {e}") from None
        return audio_of(data), "audio/wav", model

    def stream(self, text: str, voice: str):
        """Yields (pcm_chunk, rate, model) as the model produces them (streamGenerateContent),
        rotating through the pool's models like speak() does."""
        if not self.key:
            raise Unavailable("no Gemini key")
        body = self._body(text, voice)
        for model in self.pool.available():
            url = GP.API.format(model=model).replace(
                ":generateContent", ":streamGenerateContent?alt=sse"
            )
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode(),
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.key,
                    "Accept": "text/event-stream",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 - fixed https URL
                    for pcm, rate in _sse_audio(r):
                        yield pcm, rate, f"gemini {model}"
                return
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 503, 404):
                    raise
                self.pool.out(model, GP.cooldown_of(e), f"HTTP {e.code}")
            except (urllib.error.URLError, TimeoutError):
                self.pool.out(model, 300.0, "no answer in time")
                raise
        raise GP.AllBusy("every Gemini voice is at its limit")


def _sse_audio(resp):
    """Yields (pcm_chunk, rate) from a streamGenerateContent SSE response: each `data:` JSON
    carries the next consecutive audio fragment as inlineData (base64, audio/L16;rate=N)."""
    rate: int | None = None
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            j = json.loads(payload)
        except ValueError:
            continue
        for c in j.get("candidates", [])[:1]:
            for p in (c.get("content") or {}).get("parts", []):
                inline = p.get("inlineData") or {}
                if not inline.get("data"):
                    continue
                m = re.search(r"rate=(\d+)", inline.get("mimeType", ""))
                rate = int(m.group(1)) if m else (rate or 24000)
                yield base64.b64decode(inline["data"]), rate


def eleven_voices(env: dict) -> dict[str, str]:
    """The ElevenLabs voices configured: ELEVENLABS_VOICE_ID_01, _02, ... by their number, and
    the older single ELEVENLABS_VOICE_ID as "00"."""
    out = {
        k.rsplit("_", 1)[1]: v
        for k, v in sorted(env.items())
        if re.fullmatch(r"ELEVENLABS_VOICE_ID_\d{1,2}", k) and v
    }
    if env.get("ELEVENLABS_VOICE_ID"):
        out.setdefault("00", env["ELEVENLABS_VOICE_ID"])
    return out


class ElevenLabsVoice:
    """ElevenLabs text to speech: reads out a text it is given - an answer another model wrote -
    and nothing else; it never writes text. One request, MP3 back.
    ELEVENLABS_API_KEY; the voice: ELEVENLABS_VOICE (which numbered voice, default 01) among
    ELEVENLABS_VOICE_ID_01, _02, ...; ELEVENLABS_MODEL."""

    name = "elevenlabs"
    URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128"
    # the streaming sibling: raw 16-bit PCM at 16 kHz - fragments concatenate cleanly, so the
    # browser can play from the first chunk instead of waiting for the whole MP3
    URL_STREAM = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream?output_format=pcm_16000"

    def __init__(self, env: dict) -> None:
        self.key = env.get("ELEVENLABS_API_KEY") or None
        self.voices = eleven_voices(env)
        pick = (env.get("ELEVENLABS_VOICE") or "01").zfill(2)
        self.voice_no = pick if pick in self.voices else next(iter(self.voices), "")
        self.voice = self.voices.get(self.voice_no, "JBFqnCBsd6RMkjVDRZzb")
        self.model = env.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")
        self.out_until = 0.0

    def ready(self) -> bool:
        return bool(self.key) and time.time() >= self.out_until

    def speak(self, text: str, voice: str) -> tuple[bytes, str, str]:
        if not self.ready():
            raise Unavailable("no ElevenLabs key" if not self.key else "ElevenLabs is at its limit")
        payload = json.dumps({"text": text, "model_id": self.model}).encode()
        headers = {
            "xi-api-key": self.key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        url = self.URL.format(voice=self.voice)
        req = urllib.request.Request(url, method="POST", data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 - fixed https URL
                return r.read(), "audio/mpeg", f"elevenlabs {self.model} voice {self.voice_no}"
        except urllib.error.HTTPError as e:
            # 401 bad key or credits used up, 402 a voice the plan does not include: an hour off
            if e.code in (401, 402, 429, 503):
                self.out_until = time.time() + (3600 if e.code in (401, 402) else 60)
                raise Unavailable(f"ElevenLabs answered HTTP {e.code}") from None
            raise

    def stream(self, text: str, voice: str):
        """Yields (pcm_chunk, 16000, model) as ElevenLabs streams raw PCM; a 429/401/402/503
        rests the provider exactly like speak() does."""
        if not self.ready():
            raise Unavailable("no ElevenLabs key" if not self.key else "ElevenLabs is at its limit")
        payload = json.dumps({"text": text, "model_id": self.model}).encode()
        req = urllib.request.Request(
            self.URL_STREAM.format(voice=self.voice),
            method="POST",
            data=payload,
            headers={
                "xi-api-key": self.key or "",
                "Content-Type": "application/json",
                "Accept": "audio/pcm",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 - fixed https URL
                while True:
                    block = r.read(16384)
                    if not block:
                        return
                    yield block, 16000, f"elevenlabs {self.model}"
        except urllib.error.HTTPError as e:
            if e.code in (401, 402, 429, 503):
                self.out_until = time.time() + (3600 if e.code in (401, 402) else 60)
            raise Unavailable(f"ElevenLabs answered HTTP {e.code}") from None


class GroqVoice:
    """Groq TTS (Canopy Labs Orpheus models): fast speech via OpenAI-compatible audio endpoint.
    GROQ_API_KEY, GROQ_TTS_MODEL (default: canopylabs/orpheus-v1-english)."""

    name = "groq"
    URL = "https://api.groq.com/openai/v1/audio/speech"

    def __init__(self, env: dict) -> None:
        self.key = env.get("GROQ_API_KEY") or env.get("GROK_API_KEY") or None
        self.model = env.get("GROQ_TTS_MODEL", "canopylabs/orpheus-v1-english")
        self.voice = env.get("GROQ_TTS_VOICE", "troy")
        self.out_until = 0.0

    def ready(self) -> bool:
        return bool(self.key) and time.time() >= self.out_until

    def speak(self, text: str, voice: str) -> tuple[bytes, str, str]:
        if not self.ready():
            raise Unavailable("no Groq key" if not self.key else "Groq TTS is resting")
        payload = json.dumps(
            {
                "model": self.model,
                "input": text[:200] if len(text) > 200 else text,
                "voice": self.voice,
                "response_format": "wav",
            }
        ).encode()
        headers = {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "User-Agent": "stf-digital-twin/1.0",
        }
        req = urllib.request.Request(self.URL, method="POST", data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310
                return r.read(), "audio/wav", f"groq {self.model}"
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read().decode())
                msg = err.get("error", {}).get("message", f"HTTP {e.code}")
            except Exception:
                msg = f"HTTP {e.code}"
            if e.code in (400, 401, 402, 403, 429, 503):
                self.out_until = time.time() + 300
                raise Unavailable(f"Groq TTS ({msg})") from None
            raise


class LocalVoice:
    """The computer's own voice (macOS `say`), offline and free: the voice when no service has
    quota. Ollama serves language models, not speech, so local speech comes from the OS."""

    name = "local"

    def ready(self) -> bool:
        return bool(shutil.which("say") and shutil.which("afconvert"))

    def speak(self, text: str, voice: str) -> tuple[bytes, str, str]:
        if not self.ready():
            raise Unavailable("no local speech engine")
        with tempfile.TemporaryDirectory() as d:
            aiff, wavf = os.path.join(d, "a.aiff"), os.path.join(d, "a.wav")
            subprocess.run(["say", "-o", aiff, "--", text], check=True, timeout=60)  # noqa: S603,S607
            subprocess.run(
                ["afconvert", "-f", "WAVE", "-d", "LEI16@22050", aiff, wavf],  # noqa: S603,S607
                check=True,
                timeout=60,
            )
            with open(wavf, "rb") as f:
                return f.read(), "audio/wav", "macOS say"


class Tts:
    """The speech pipeline: providers in order (TTS_PROVIDERS, default elevenlabs,groq,gemini,
    local); one without a key or at its limit is passed over. Any site can call POST /chat/tts
    the same way."""

    def __init__(
        self,
        settings: sec.Settings,
        key: str | None = None,
        models: list[str] | None = None,
        daily_limit: int | None = None,
        providers: list[str] | None = None,
    ) -> None:
        env = {**dotenv(), **os.environ}
        self.s = settings
        self.key = key if key is not None else (env.get("GEMINI_API_KEY") or None)
        self.post = _post
        tts_models = models or GP.models_from_env("GEMINI_TTS_MODELS", GP.TTS, env)
        self.gemini = GeminiVoice(self.key, tts_models, lambda url, k, b: self.post(url, k, b))
        self.groq = GroqVoice(env)
        self.pool = self.gemini.pool
        all_ = {
            "elevenlabs": ElevenLabsVoice(env),
            "groq": self.groq,
            "gemini": self.gemini,
            "local": LocalVoice(),
        }
        default = "elevenlabs,groq,gemini,local"
        env_order = env.get("TTS_PROVIDERS", default).split(",")
        order = providers or [p.strip() for p in env_order]
        self.providers = [all_[p] for p in order if p in all_]
        self.cap = DailyCap(daily_limit or int(env.get("GEMINI_TTS_DAILY_LIMIT", "100")))
        # per client: 3 at once, then one per 10 s
        self.limiter = sec.RateLimiter(rate=0.1, burst=3)

    def status(self) -> dict:
        return {
            "enabled": any(p.ready() for p in self.providers),
            "voices": sorted(VOICES),
            "providers": [{"name": p.name, "ready": p.ready()} for p in self.providers],
            "models": self.pool.status() if self.key else [],
        }

    def _check_origin(self, request: Request) -> None:
        origin = request.headers.get("origin")
        if (
            origin
            and origin not in self.s.allowed_origins
            and sec._host(origin.split("://", 1)[-1]) != sec._host(request.headers.get("host"))
        ):
            raise HTTPException(status_code=403, detail="origin not allowed")

    def _client_of(self, request: Request) -> str:
        client = request.client.host if request.client else "?"
        if client in ("127.0.0.1", "::1"):
            client = (request.headers.get("x-forwarded-for") or client).split(",")[0].strip()
        return client

    async def speak(self, req: TtsRequest, request: Request) -> Response:
        self._check_origin(request)
        client = self._client_of(request)
        ready = [p for p in self.providers if p.ready()]
        if not ready:
            raise HTTPException(
                status_code=503, detail="no voice on the server: use the browser's voice"
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
        why = []
        for p in ready:
            try:
                logger.debug(
                    "Attempting TTS synthesis via provider '%s' (voice='%s')",
                    p.name,
                    req.voice,
                )
                audio, mime, model = await asyncio.to_thread(p.speak, text, req.voice)
                logger.info(
                    "Synthesized speech via provider '%s' (%s, %d bytes)",
                    p.name,
                    model,
                    len(audio),
                )
                return Response(
                    audio,
                    media_type=mime,
                    headers={
                        "X-TTS-Model": model,
                        "X-TTS-Provider": p.name,
                        "Cache-Control": "no-store",
                    },
                )
            except Unavailable as e:
                logger.warning("TTS provider '%s' unavailable: %s", p.name, e)
                why.append(str(e))
            except urllib.error.HTTPError as e:
                logger.warning("TTS provider '%s' HTTP error %d", p.name, e.code)
                why.append(f"{p.name} answered HTTP {e.code}")
            except (
                urllib.error.URLError,
                TimeoutError,
                ValueError,
                subprocess.SubprocessError,
                OSError,
            ) as e:
                logger.warning("TTS provider '%s' failed: %s", p.name, e)
                why.append(f"{p.name} did not answer")
        logger.error("All ready TTS providers failed to synthesize speech: %s", "; ".join(why))
        raise HTTPException(status_code=503, detail="no voice could speak: " + "; ".join(why))

    # -------------------------------------------------------------- the streaming reader
    async def stream(self, req: TtsRequest, request: Request) -> StreamingResponse:
        """POST /chat/tts/stream: the same answer read aloud as it is synthesised - SSE of
        `meta` (pcm rate / file mime), `chunk` (base64 audio) and `end`. Chunks are raw PCM
        fragments that concatenate in order, so the browser plays from the first one instead of
        waiting for the whole file. Falls back to one `file` chunk when no provider streams."""
        self._check_origin(request)
        client = self._client_of(request)
        if not self.limiter.allow(client):
            raise HTTPException(
                status_code=429, detail="too many spoken answers: wait a few seconds"
            )
        text = speakable(req.text)
        if not text:
            raise HTTPException(status_code=400, detail="nothing to say")
        if not self.cap.take():
            raise HTTPException(status_code=429, detail="today's spoken-answer budget is used up")
        if not any(p.ready() for p in self.providers):
            raise HTTPException(
                status_code=503, detail="no voice on the server: use the browser's voice"
            )
        voice = req.voice if req.voice in VOICES else "Kore"
        return StreamingResponse(
            self._events(text, voice),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @staticmethod
    def _sse(ev: str, obj: dict) -> str:
        return f"event: {ev}\ndata: {json.dumps(obj, separators=(',', ':'))}\n\n"

    def _synth_one(self, text: str, voice: str) -> tuple[dict, bytes] | None:
        """One piece of read-aloud text, fully synthesized (blocking - runs in a worker thread).
        Returns (meta, audio): meta is {"kind": "pcm", "rate", "by"} with raw s16le PCM at that
        rate, or {"kind": "file", "mime", "by"} with one container (wav/mp3) the browser plays.
        Cached by voice+text hash: a repeated sentence costs nothing. None when no voice spoke."""
        key = hashlib.sha256(f"{voice}|{text}".encode()).hexdigest()
        hit = _cache_get(key)
        if hit:
            return hit

        # streaming providers in chain order; the first that speaks wins
        why: list[str] = []
        for p in [p for p in self.providers if p.ready() and hasattr(p, "stream")]:
            collected = bytearray()
            try:
                rate, model = 0, p.name
                for pcm, rate, model in p.stream(text, voice):
                    collected += pcm
                if collected:
                    meta = {"kind": "pcm", "rate": rate, "by": model}
                    _cache_put(key, meta, bytes(collected))
                    return meta, bytes(collected)
                why.append(f"{p.name} produced no audio")
            except GP.AllBusy as e:
                why.append(f"every Gemini voice is at its limit: {e}")
            except Unavailable as e:
                why.append(str(e))
            except urllib.error.HTTPError as e:
                why.append(f"{p.name} answered HTTP {e.code}")
            except (urllib.error.URLError, TimeoutError, ValueError, OSError) as e:
                logger.warning("Streaming TTS provider '%s' failed: %s", p.name, e)
                why.append(f"{p.name} did not answer")

        # no streaming provider could speak: one whole file from a non-streaming provider
        for p in [p for p in self.providers if p.ready() and not hasattr(p, "stream")]:
            try:
                audio, mime, model = p.speak(text, voice)
                wav_like = "L16" in mime or audio[:4] == b"RIFF"
                if wav_like:
                    raw = audio[44:] if audio[:4] == b"RIFF" else audio
                    m = re.search(r"rate=(\d+)", mime)
                    meta = {"kind": "pcm", "rate": int(m.group(1)) if m else 24000, "by": model}
                    _cache_put(key, meta, raw)
                    return meta, raw
                meta = {"kind": "file", "mime": mime, "by": model}
                return meta, audio
            except (
                Unavailable,
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                ValueError,
                subprocess.SubprocessError,
                OSError,
            ) as e:
                logger.warning("Fallback TTS provider '%s' failed: %s", p.name, e)
                why.append(f"{p.name} did not answer")
        logger.error("TTS failed everywhere: %s", "; ".join(why))
        return None

    async def _events(self, text: str, voice: str):
        """The SSE body. One short answer is a single synthesis. A long answer becomes
        sentences: up to 3 are synthesized at once (one request, one budget token) and their
        audio streams back in reading order - the first sentence plays while later ones are
        still being made, instead of waiting for the whole answer to be synthesized."""
        sentences = split_sentences(text)
        if len(sentences) <= 1:
            one = await asyncio.to_thread(self._synth_one, text, voice)
            if one is None:
                yield self._sse("error", {"detail": "no voice could speak"})
                return
            meta, audio = one
            yield self._sse("meta", meta)
            for i in range(0, len(audio), 32768):
                yield self._sse("chunk", {"b64": base64.b64encode(audio[i : i + 32768]).decode()})
            yield self._sse("end", {})
            return

        sem = asyncio.Semaphore(3)

        async def one(s: str):
            async with sem:
                try:
                    return await asyncio.to_thread(self._synth_one, s, voice)
                except Exception as e:  # a broken provider must not sink the whole answer
                    logger.warning("Sentence TTS failed for %r: %s", s[:60], e)
                    return None

        tasks = [asyncio.create_task(one(s)) for s in sentences]
        sig: tuple | None = None  # what the player's meta was last opened with
        spoken = 0
        try:
            for t in tasks:  # awaited in reading order, whatever order synthesis finished
                r = await t
                if r is None:
                    continue
                meta, audio = r
                if meta.get("kind") != "pcm":
                    continue  # a container file cannot join the PCM stream: skip it here
                new_sig = (meta["rate"], meta["by"].split()[0])
                if new_sig != sig:  # first, or the provider/rate changed mid-answer
                    yield self._sse("meta", meta)
                    sig = new_sig
                for i in range(0, len(audio), 32768):
                    yield self._sse("chunk", {"b64": base64.b64encode(audio[i : i + 32768]).decode()})
                spoken += 1
            if spoken:
                yield self._sse("end", {})
            else:
                yield self._sse("error", {"detail": "no voice could speak the answer"})
        finally:
            for t in tasks:
                t.cancel()  # the client went away: stop whatever is still synthesizing


# ------------------------------------------------------------------ the spoken cache
# Whole answers that were already synthesised, keyed by voice+text hash: a repeated phrase costs
# nothing and starts instantly. PCM plus a small meta file, in the system temp dir, pruned to
# the newest CACHE_MAX entries.
CACHE_DIR = Path(tempfile.gettempdir()) / "stf-tts-cache"
CACHE_MAX = 256


def _cache_get(key: str) -> tuple[dict, bytes] | None:
    try:
        pcm_f, meta_f = CACHE_DIR / f"{key}.pcm", CACHE_DIR / f"{key}.json"
        if pcm_f.exists() and meta_f.exists():
            return json.loads(meta_f.read_text()), pcm_f.read_bytes()
    except (OSError, ValueError):
        pass
    return None


def _cache_put(key: str, meta: dict, pcm: bytes) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{key}.pcm").write_bytes(pcm)
        (CACHE_DIR / f"{key}.json").write_text(json.dumps(meta))
        entries = sorted(CACHE_DIR.glob("*.pcm"), key=lambda f: f.stat().st_mtime)
        for old in entries[:-CACHE_MAX]:
            old.unlink(missing_ok=True)
            (CACHE_DIR / (old.stem + ".json")).unlink(missing_ok=True)
    except OSError:
        pass


# ------------------------------------------------------------------ speech to text
STT_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
]
STT_MAX_BYTES = 2_000_000  # ~1 minute of compressed speech
STT_TYPES = ("audio/webm", "audio/ogg", "audio/wav", "audio/mp4", "audio/mpeg", "audio/aac")


def _multipart(fields: dict[str, str], audio: bytes, mime: str) -> tuple[bytes, str]:
    """A multipart/form-data body: the text fields and the recording as `file`."""
    boundary = uuid.uuid4().hex
    ext = next((e for e in ("webm", "ogg", "wav", "mp4", "aac") if e in mime), "mp3")
    body = io.BytesIO()
    for k, v in fields.items():
        body.write(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        )
    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="file"; filename="audio.{ext}"\r\n'.encode())
    body.write(f"Content-Type: {mime}\r\n\r\n".encode())
    body.write(audio)
    body.write(f"\r\n--{boundary}--\r\n".encode())
    return body.getvalue(), f"multipart/form-data; boundary={boundary}"


class ElevenLabsStt:
    """ElevenLabs speech to text (Scribe): the operator's recorded question as text, which a
    language model (Groq, Gemini, ...) then answers. It transcribes and nothing else.
    ELEVENLABS_API_KEY, ELEVENLABS_STT_MODEL (default scribe_v1)."""

    name = "elevenlabs"
    URL = "https://api.elevenlabs.io/v1/speech-to-text"

    def __init__(self, env: dict) -> None:
        self.key = env.get("ELEVENLABS_API_KEY") or None
        self.model = env.get("ELEVENLABS_STT_MODEL", "scribe_v1")
        self.out_until = 0.0

    def ready(self) -> bool:
        return bool(self.key) and time.time() >= self.out_until

    def transcribe(self, audio: bytes, mime: str) -> tuple[str, str]:
        body, ctype = _multipart({"model_id": self.model, "tag_audio_events": "false"}, audio, mime)
        req = urllib.request.Request(
            self.URL,
            data=body,
            method="POST",
            headers={"xi-api-key": self.key or "", "Content-Type": ctype},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:  # noqa: S310 - fixed https URL
                return json.loads(r.read()).get("text", "").strip(), f"elevenlabs {self.model}"
        except urllib.error.HTTPError as e:
            if e.code in (401, 402, 429, 503):
                self.out_until = time.time() + (3600 if e.code in (401, 402) else 60)
            raise Unavailable(f"ElevenLabs STT answered HTTP {e.code}") from None


class Stt:
    """The Voice tab's transcription: providers in order (STT_PROVIDERS, default
    elevenlabs,groq,gemini) - ElevenLabs Scribe, Groq Whisper, then the Gemini speech models.
    A provider without a key, at its limit or failing is passed over."""

    def __init__(self, settings: sec.Settings, key: str | None = None) -> None:
        env = {**dotenv(), **os.environ}
        self.s = settings
        self.eleven = ElevenLabsStt(env)
        self.order = [
            p.strip() for p in env.get("STT_PROVIDERS", "elevenlabs,groq,gemini").split(",")
        ]
        self.key = key if key is not None else (env.get("GEMINI_API_KEY") or None)
        self.groq_key = env.get("GROQ_API_KEY") or env.get("GROK_API_KEY") or None
        self.groq_model = env.get("GROQ_STT_MODEL", "whisper-large-v3-turbo")
        self.pool = GP.Pool(GP.models_from_env("GEMINI_STT_MODELS", STT_MODELS, env))
        self.limiter = sec.RateLimiter(rate=0.2, burst=4)
        self.post = _post

    def status(self) -> dict:
        ready = {
            "elevenlabs": self.eleven.ready(),
            "groq": bool(self.groq_key),
            "gemini": bool(self.key),
        }
        models = {
            "elevenlabs": self.eleven.model,
            "groq": self.groq_model,
            "gemini": (self.pool.available() or [None])[0],
        }
        provs = [
            {"name": p, "ready": ready[p], "model": models[p]} for p in self.order if p in ready
        ]
        return {"enabled": any(p["ready"] for p in provs), "providers": provs}

    def _groq_transcribe(self, audio: bytes, mime: str) -> str:
        boundary = uuid.uuid4().hex
        ext = (
            "webm"
            if "webm" in mime
            else ("ogg" if "ogg" in mime else ("wav" if "wav" in mime else "mp3"))
        )
        body = io.BytesIO()
        body.write(f"--{boundary}\r\n".encode())
        body.write(
            f'Content-Disposition: form-data; name="model"\r\n\r\n{self.groq_model}\r\n'.encode()
        )
        body.write(f"--{boundary}\r\n".encode())
        body.write(
            f'Content-Disposition: form-data; name="file"; filename="audio.{ext}"\r\n'.encode()
        )
        body.write(f"Content-Type: {mime}\r\n\r\n".encode())
        body.write(audio)
        body.write(f"\r\n--{boundary}--\r\n".encode())

        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            data=body.getvalue(),
            headers={
                "Authorization": f"Bearer {self.groq_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "stf-digital-twin/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
            res = json.loads(r.read().decode())
            return res.get("text", "").strip()

    async def transcribe(self, request: Request) -> dict:
        import asyncio

        origin = request.headers.get("origin")
        if (
            origin
            and origin not in self.s.allowed_origins
            and sec._host(origin.split("://", 1)[-1]) != sec._host(request.headers.get("host"))
        ):
            raise HTTPException(status_code=403, detail="origin not allowed")
        if not self.status()["enabled"]:
            raise HTTPException(
                status_code=503,
                detail="no transcription on the server: use the browser's recognition",
            )
        client = request.client.host if request.client else "?"
        if not self.limiter.allow(client):
            raise HTTPException(status_code=429, detail="too many recordings: wait a few seconds")
        mime = (request.headers.get("content-type") or "").split(";")[0].strip()
        if mime not in STT_TYPES:
            raise HTTPException(status_code=415, detail=f"send one of {', '.join(STT_TYPES)}")
        audio = await request.body()
        if not audio or len(audio) > STT_MAX_BYTES:
            raise HTTPException(status_code=413, detail="a recording of at most 2 MB")

        # ElevenLabs Scribe, then Groq Whisper, then the Gemini pool (STT_PROVIDERS)
        why: list[str] = []
        for prov in self.order:
            if prov == "elevenlabs" and self.eleven.ready():
                try:
                    logger.debug("Attempting STT transcription via ElevenLabs Scribe")
                    text, model = await asyncio.to_thread(self.eleven.transcribe, audio, mime)
                    if text:
                        logger.info("Transcribed audio via ElevenLabs (%s): %r", model, text[:60])
                        return {"text": text[:500], "model": model}
                    why.append("elevenlabs heard nothing")
                except (Unavailable, urllib.error.URLError, TimeoutError, OSError) as e:
                    logger.warning("ElevenLabs STT failed: %s", e)
                    why.append(str(e) or "elevenlabs did not answer")
            elif prov == "groq" and self.groq_key:
                try:
                    logger.debug(
                        "Attempting STT transcription via Groq Whisper (%s)",
                        self.groq_model,
                    )
                    text = await asyncio.to_thread(self._groq_transcribe, audio, mime)
                    if text:
                        logger.info(
                            "Transcribed audio via Groq (%s): %r",
                            self.groq_model,
                            text[:60],
                        )
                        return {"text": text[:500], "model": f"groq {self.groq_model}"}
                except Exception as e:
                    logger.warning("Groq STT failed: %s", e)
                    why.append("groq did not transcribe")
            elif prov == "gemini" and self.key:
                break  # the Gemini pool below
        if not self.key or "gemini" not in self.order:
            logger.error("STT transcription failed on all primary providers: %s", "; ".join(why))
            raise HTTPException(
                status_code=503, detail="transcription failed: " + ("; ".join(why) or "no provider")
            )

        body = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": "Transcribe this spoken question about a factory "
                            "exactly, in its language. "
                            "Return only the words spoken, no comments."
                        },
                        {
                            "inlineData": {
                                "mimeType": mime,
                                "data": base64.b64encode(audio).decode(),
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 200},
        }

        def text_of(d: dict) -> str:
            t = "".join(
                p.get("text", "")
                for c in d.get("candidates", [])[:1]
                for p in (c.get("content") or {}).get("parts", [])
            ).strip()
            if not t:
                raise ValueError("no transcript")
            return t

        try:
            logger.debug("Attempting STT transcription via Gemini pool")
            data, model = await asyncio.to_thread(
                self.pool.call, lambda url, b: self.post(url, self.key, b), body, accept=text_of
            )
            transcript = text_of(data)
            logger.info("Transcribed audio via Gemini (%s): %r", model, transcript[:60])
            return {"text": transcript[:500], "model": model}
        except GP.AllBusy as e:
            logger.warning("All Gemini transcription models busy: %s", e)
            raise HTTPException(
                status_code=503, detail=f"every transcription model is at its limit: {e}"
            ) from None
        except urllib.error.HTTPError as e:
            logger.error("Gemini transcription HTTP error %d", e.code)
            raise HTTPException(
                status_code=502, detail=f"transcription answered HTTP {e.code}"
            ) from None
        except (urllib.error.URLError, TimeoutError) as e:
            logger.error("Gemini transcription connection error: %s", e)
            raise HTTPException(status_code=504, detail="transcription did not answer") from None
