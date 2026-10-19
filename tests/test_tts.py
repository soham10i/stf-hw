"""Spoken answers (services/api/tts.py): the text is cleaned for speech, PCM becomes a playable
WAV, and the Pro voice hands over to a flash voice when its quota is closed. No network."""

import asyncio
import base64
import io
import json
import struct
import time as time_module
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


@pytest.fixture(autouse=True)
def _fresh_spoken_cache(tmp_path, monkeypatch):
    """Each test gets its own spoken-cache dir: the real one lives in the system temp dir and
    would otherwise leak synthesized sentences between runs."""
    monkeypatch.setattr(V, "CACHE_DIR", tmp_path / "tts-cache")


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


def test_speakable_reads_the_content_only():
    """Links keep their text, URLs and formulas go, and a Sources/Resources section is not read."""
    md = (
        "The oven holds **176 °C**.\n\n"
        "Details: [the manual](https://fischertechnik.de/manual) and https://example.com/x.\n"
        "Efficiency is $\\eta = 0.9$ today.\n\n"
        "## Sources\n1. [a](https://a.example) 2. [b](https://b.example)\n"
        "## Resources\n- [c](https://c.example)"
    )
    s = V.speakable(md)
    assert "the manual" in s                      # the link's text stays
    assert "fischertechnik.de/manual" not in s    # its URL is not read
    assert "example.com" not in s                 # bare URLs neither
    assert "(formula)" in s and "eta = 0.9" not in s and "$" not in s  # LaTeX becomes a word
    assert "Sources" not in s and "Resources" not in s
    assert "a.example" not in s and "c.example" not in s
    assert "176 degrees Celsius" in s


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
    t = V.Tts(
        sec.Settings.from_env(),
        key=KEY,
        models=["pro-tts", "flash-tts"],
        daily_limit=10,
        providers=["gemini"],
    )
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
    t = V.Tts(sec.Settings.from_env(), key=KEY, models=["w"], daily_limit=10, providers=["gemini"])
    t.post = lambda url, k, body: _audio("audio/wav", V.wav(b"\x00\x00" * 10))
    assert speak(t).body[:4] == b"RIFF"


def test_no_key_and_all_voices_busy_are_explained():
    with pytest.raises(HTTPException) as e:
        speak(
            V.Tts(
                sec.Settings.from_env(), key="", models=["x"], daily_limit=10, providers=["gemini"]
            )
        )
    assert e.value.status_code == 503
    t = V.Tts(sec.Settings.from_env(), key=KEY, models=["a"], daily_limit=10, providers=["gemini"])

    def busy(url, k, body):
        raise urllib.error.HTTPError("x", 429, "q", {}, io.BytesIO(b"{}"))

    t.post = busy
    with pytest.raises(HTTPException) as e:
        speak(t)
    assert e.value.status_code == 503 and KEY not in e.value.detail


def test_a_voice_that_returns_no_audio_is_passed_over():
    t = V.Tts(
        sec.Settings.from_env(),
        key=KEY,
        models=["silent", "speaks"],
        daily_limit=10,
        providers=["gemini"],
    )
    t.post = lambda url, k, body: (
        {"candidates": [{"finishReason": "OTHER", "index": 0}]}
        if "/silent:" in url
        else _audio("audio/L16;codec=pcm;rate=24000", b"\x00\x00" * 10)
    )
    r = speak(t)
    assert r.headers["X-TTS-Model"] == "speaks" and r.body[:4] == b"RIFF"


def test_providers_in_order_elevenlabs_then_gemini_then_local(monkeypatch):
    t = V.Tts(
        sec.Settings.from_env(),
        key=KEY,
        models=["g"],
        daily_limit=10,
        providers=["elevenlabs", "gemini", "local"],
    )
    el = t.providers[0]
    el.key = "el-test"
    el.speak = lambda text, voice: (_ for _ in ()).throw(
        V.Unavailable("ElevenLabs is at its limit")
    )
    t.post = lambda url, k, body: _audio("audio/wav", V.wav(b"\x00\x00" * 10))
    r = speak(t)
    assert r.headers["X-TTS-Provider"] == "gemini"
    el.speak = lambda text, voice: (b"ID3mp3", "audio/mpeg", "elevenlabs eleven_multilingual_v2")
    r = speak(t)
    assert r.headers["X-TTS-Provider"] == "elevenlabs" and r.media_type == "audio/mpeg"


def test_status_lists_the_providers():
    t = V.Tts(
        sec.Settings.from_env(),
        key=KEY,
        models=["g"],
        daily_limit=10,
        providers=["elevenlabs", "groq", "gemini"],
    )
    st = t.status()
    assert [p["name"] for p in st["providers"]] == ["elevenlabs", "groq", "gemini"] and st[
        "enabled"
    ]


def test_groq_tts_provider():
    t = V.Tts(
        sec.Settings.from_env(),
        key=None,
        daily_limit=10,
        providers=["groq", "local"],
    )
    grq = t.groq
    grq.key = "gsk_test"
    grq.speak = lambda text, voice: (b"RIFFwav", "audio/wav", "groq canopylabs/orpheus-v1-english")
    r = speak(t)
    assert r.headers["X-TTS-Provider"] == "groq"
    assert r.headers["X-TTS-Model"] == "groq canopylabs/orpheus-v1-english"
    assert r.body == b"RIFFwav"


def test_split_sentences_basic_and_fragments():
    # short text stays one synthesis; max_chars forces the splitter for the test
    assert V.split_sentences("Just one line.") == ["Just one line."]
    ss = V.split_sentences(
        "The oven heats to 176 °C. The conveyor moves 12 molds per cycle! Does it stop at noon?",
        max_chars=50,
    )
    assert ss == [
        "The oven heats to 176 °C.",
        "The conveyor moves 12 molds per cycle!",
        "Does it stop at noon?",
    ]
    # a fragment without sentence punctuation reads with what follows it
    ss = V.split_sentences("Status. Ready now The oven is hot.", max_chars=30)
    assert ss == ["Status.", "Ready now The oven is hot."]
    # numbers and abbreviations never split
    assert V.split_sentences("It runs at 3.5 A for 2.5 h. Then it rests.", max_chars=30) == [
        "It runs at 3.5 A for 2.5 h.",
        "Then it rests.",
    ]
    assert V.split_sentences("Use e.g. defaults here. Done now.", max_chars=30) == [
        "Use e.g. defaults here.",
        "Done now.",
    ]


def test_split_sentences_caps_long_ones():
    long_sentence = "The picker moves to the cell, " + "lifts the mold gently, " * 40 + "and rests."
    ss = V.split_sentences(long_sentence, max_chars=200)
    assert all(len(s) <= 200 for s in ss) and len(ss) > 1
    # nothing lost but the split commas, order kept (", " becomes " " at a cut)
    flat = lambda s: s.replace(" ", "").replace(",", "")
    assert flat(" ".join(ss)) == flat(long_sentence)
    short = "All good."
    assert V.split_sentences(short) == ["All good."]


class _FakeStreamer:
    """A streaming provider that yields PCM per sentence, with an artificial delay so the
    pipeline's concurrency (and not just its order) is exercised."""

    name = "fake"
    order: list[str] = []

    def __init__(self, delay: float):
        self.delay = delay

    def ready(self):
        return True

    def stream(self, text, voice):
        _FakeStreamer.order.append(text)
        time_module.sleep(self.delay)
        n = max(2, len(text) // 4)
        yield b"\x01\x00" * n, 24000, "fake fake-1"


def test_stream_pipeline_concurrent_and_in_reading_order():
    _FakeStreamer.order = []
    t = V.Tts(
        sec.Settings.from_env(), key=None, models=[], daily_limit=10, providers=["local"]
    )
    t.providers = [_FakeStreamer(delay=0.05)]

    text = " ".join(f"Sentence number {i} is here and ready." for i in range(1, 9))
    t0 = time_module.monotonic()
    events = asyncio.run(_collect_events(t, text))
    wall = time_module.monotonic() - t0

    metas = [json.loads(e.split("data: ", 1)[1]) for e in events if e.startswith("event: meta")]
    chunks = [e for e in events if e.startswith("event: chunk")]
    assert events[-1].startswith("event: end")
    assert len(metas) == 1 and metas[0]["rate"] == 24000
    # 8 sentences, each ~4-7 PCM bytes * 2 -> each yields 1 chunk of its own bytes
    assert len(chunks) == 8
    # concurrent: 8 sentences x 0.05s with 3 lanes takes ~3 waves, not 8 x 0.05s serial
    assert wall < 8 * 0.05 * 0.75, f"not concurrent enough: {wall:.2f}s"
    # every sentence was synthesized exactly once, cache apart
    assert sorted(_FakeStreamer.order) == sorted(V.split_sentences(text))
    # a repeat hits the cache: nothing is synthesized again
    _FakeStreamer.order = []
    asyncio.run(_collect_events(t, text))
    assert _FakeStreamer.order == []


async def _collect_events(t, text):
    out = []
    async for ev in t._events(text, "Kore"):
        out.append(ev)
    return out


def test_stream_pipeline_single_sentence_uses_one_synthesis():
    class OneShot:
        name = "oneshot"

        def __init__(self):
            self.calls = []

        def ready(self):
            return True

        def stream(self, text, voice):
            self.calls.append(text)
            yield b"\x02\x00" * 8, 16000, "oneshot os-1"

    t = V.Tts(sec.Settings.from_env(), key=None, models=[], daily_limit=10, providers=["local"])
    shot = OneShot()
    t.providers = [shot]
    events = asyncio.run(_collect_events(t, "Only one short line."))
    assert len(shot.calls) == 1
    assert [e.split("\n", 1)[0] for e in events] == [
        "event: meta",
        "event: chunk",
        "event: end",
    ]


def test_groq_stt_transcription():
    stt = V.Stt(sec.Settings.from_env(), key=None)
    stt.groq_key = "gsk_test"
    stt._groq_transcribe = lambda audio, mime: "What is the warehouse status?"

    req_obj = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/chat/stt",
            "headers": [(b"host", b"localhost:8000"), (b"content-type", b"audio/wav")],
            "client": ("127.0.0.1", 5000),
        }
    )
    # mock request.body
    req_obj._body = b"RIFFmockwav"
    res = asyncio.run(stt.transcribe(req_obj))
    assert res["text"] == "What is the warehouse status?"
    assert "groq" in res["model"]
