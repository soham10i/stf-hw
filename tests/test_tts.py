"""Spoken answers (services/api/tts.py): the text is cleaned for speech, PCM becomes a playable
WAV, and the Pro voice hands over to a flash voice when its quota is closed. No network."""

import asyncio
import base64
import io
import json
import struct
import urllib.error

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

from services.api import security as sec  # noqa: E402
from services.api import tts as V  # noqa: E402

KEY = "test-key-not-real"


def req(client="127.0.0.1"):
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/chat/tts",
            "headers": [(b"host", b"localhost:8000")],
            "client": (client, 5000),
        }
    )


def speak(t, text="**The oven** is at temperature [Machine: Oven].\n- door shut"):
    return asyncio.run(t.speak(V.TtsRequest(text=text), req()))


def test_speakable_drops_markdown_and_citations():
    s = V.speakable("**OEE** is 30.8 % [virtual commissioning].\n- availability 63 %\n# Heading")
    assert "[" not in s and "*" not in s and "#" not in s
    assert "O E E is 30.8 percent" in s and "availability 63 percent" in s
    assert (
        V.speakable("The oven is at 176 °C and costs €6.16.")
        == "The oven is at 176 degrees Celsius and costs 6.16 euros."
    )


def test_pcm_becomes_a_valid_wav():
    pcm = b"\x01\x00" * 2400
    w = V.wav(pcm, 24000)
    assert w[:4] == b"RIFF" and w[8:12] == b"WAVE"
    ch, rate, bits = (
        struct.unpack("<H I", w[22:28])[0],
        struct.unpack("<I", w[24:28])[0],
        struct.unpack("<H", w[34:36])[0],
    )
    assert (ch, rate, bits) == (1, 24000, 16) and len(w) == 44 + len(pcm)


def _audio(mime, raw):
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"inlineData": {"mimeType": mime, "data": base64.b64encode(raw).decode()}}
                    ]
                }
            }
        ]
    }


def test_pro_voice_at_its_limit_hands_over_to_flash():
    t = V.Tts(sec.Settings.from_env(), key=KEY, models=["pro-tts", "flash-tts"], daily_limit=10)
    hit = []

    def fake(url, k, body):
        m = url.split("/models/")[1].split(":")[0]
        hit.append(m)
        assert k == KEY and "[" not in body["contents"][0]["parts"][0]["text"]
        if m == "pro-tts":
            err = {"error": {"details": [{"retryDelay": "40026s"}]}}
            raise urllib.error.HTTPError(
                "x", 429, "quota", {}, io.BytesIO(json.dumps(err).encode())
            )
        return _audio("audio/L16;codec=pcm;rate=24000", b"\x00\x00" * 100)

    t.post = fake
    r = speak(t)
    assert hit == ["pro-tts", "flash-tts"] and r.headers["X-TTS-Model"] == "flash-tts"
    assert r.media_type == "audio/wav" and r.body[:4] == b"RIFF"
    hit.clear()
    speak(t)
    assert hit == ["flash-tts"], "the Pro voice is skipped while its quota is closed"


def test_a_wav_answer_passes_through():
    t = V.Tts(sec.Settings.from_env(), key=KEY, models=["w"], daily_limit=10)
    t.post = lambda url, k, body: _audio("audio/wav", V.wav(b"\x00\x00" * 10))
    assert speak(t).body[:4] == b"RIFF"


def test_no_key_and_all_voices_busy_are_explained():
    with pytest.raises(HTTPException) as e:
        speak(V.Tts(sec.Settings.from_env(), key="", models=["x"], daily_limit=10))
    assert e.value.status_code == 503
    t = V.Tts(sec.Settings.from_env(), key=KEY, models=["a"], daily_limit=10)

    def busy(url, k, body):
        raise urllib.error.HTTPError("x", 429, "q", {}, io.BytesIO(b"{}"))

    t.post = busy
    with pytest.raises(HTTPException) as e:
        speak(t)
    assert e.value.status_code == 503 and KEY not in e.value.detail


def test_a_voice_that_returns_no_audio_is_passed_over():
    t = V.Tts(sec.Settings.from_env(), key=KEY, models=["silent", "speaks"], daily_limit=10)
    t.post = lambda url, k, body: (
        {"candidates": [{"finishReason": "OTHER", "index": 0}]}
        if "/silent:" in url
        else _audio("audio/L16;codec=pcm;rate=24000", b"\x00\x00" * 10)
    )
    r = speak(t)
    assert r.headers["X-TTS-Model"] == "speaks" and r.body[:4] == b"RIFF"
