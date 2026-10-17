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

    def speak(self, text: str, voice: str) -> tuple[bytes, str, str]:
        if not self.key:
            raise Unavailable("no Gemini key")
        name = voice if voice in VOICES else "Kore"
        body = {
            "contents": [{"parts": [{"text": STYLE + text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": name}}},
            },
        }
        try:
            data, model = self.pool.call(
                lambda url, b: self.post(url, self.key, b), body, accept=audio_of
            )
        except GP.AllBusy as e:
            raise Unavailable(f"every Gemini voice is at its limit: {e}") from None
        return audio_of(data), "audio/wav", model


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
                audio, mime, model = await asyncio.to_thread(p.speak, text, req.voice)
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
                why.append(str(e))
            except urllib.error.HTTPError as e:
                why.append(f"{p.name} answered HTTP {e.code}")
            except (
                urllib.error.URLError,
                TimeoutError,
                ValueError,
                subprocess.SubprocessError,
                OSError,
            ):
                why.append(f"{p.name} did not answer")
        raise HTTPException(status_code=503, detail="no voice could speak: " + "; ".join(why))


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
                    text, model = await asyncio.to_thread(self.eleven.transcribe, audio, mime)
                    if text:
                        return {"text": text[:500], "model": model}
                    why.append("elevenlabs heard nothing")
                except (Unavailable, urllib.error.URLError, TimeoutError, OSError) as e:
                    why.append(str(e) or "elevenlabs did not answer")
            elif prov == "groq" and self.groq_key:
                try:
                    text = await asyncio.to_thread(self._groq_transcribe, audio, mime)
                    if text:
                        return {"text": text[:500], "model": f"groq {self.groq_model}"}
                except Exception:
                    why.append("groq did not transcribe")
            elif prov == "gemini" and self.key:
                break  # the Gemini pool below
        if not self.key or "gemini" not in self.order:
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
            data, model = await asyncio.to_thread(
                self.pool.call, lambda url, b: self.post(url, self.key, b), body, accept=text_of
            )
        except GP.AllBusy as e:
            raise HTTPException(
                status_code=503, detail=f"every transcription model is at its limit: {e}"
            ) from None
        except urllib.error.HTTPError as e:
            raise HTTPException(
                status_code=502, detail=f"transcription answered HTTP {e.code}"
            ) from None
        except (urllib.error.URLError, TimeoutError):
            raise HTTPException(status_code=504, detail="transcription did not answer") from None
        return {"text": text_of(data)[:500], "model": model}
