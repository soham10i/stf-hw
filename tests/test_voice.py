"""The voice pipeline (services/api/tts.py): ElevenLabs only listens (speech to text) and speaks
(text to speech) - a language model writes every answer; voice 01 is used unless another is
chosen; transcription falls back in order. No network: providers are fakes."""

import pathlib

import pytest

pytest.importorskip("fastapi")

from services.api import chat as C  # noqa: E402
from services.api import tts as V  # noqa: E402
from services.api.voice_check import wer  # noqa: E402

API = pathlib.Path(__file__).resolve().parent.parent / "services" / "api"
ENV = {
    "ELEVENLABS_API_KEY": "k",
    "ELEVENLABS_VOICE_ID_01": "voice-one",
    "ELEVENLABS_VOICE_ID_02": "voice-two",
}


def test_voice_one_is_used_unless_another_is_chosen():
    v = V.ElevenLabsVoice(ENV)
    assert (v.voice_no, v.voice) == ("01", "voice-one")
    v = V.ElevenLabsVoice({**ENV, "ELEVENLABS_VOICE": "2"})
    assert (v.voice_no, v.voice) == ("02", "voice-two")
    assert V.ElevenLabsVoice({"ELEVENLABS_VOICE_ID": "old"}).voice == "old"


def test_elevenlabs_never_writes_an_answer():
    # only the voice module talks to ElevenLabs; the chat's models are Groq, Gemini and Ollama
    for f in API.glob("*.py"):
        if f.name != "tts.py":
            assert "api.elevenlabs.io" not in f.read_text(), f.name
    chat = C.Chat(C.sec.Settings.from_env(), C.ChatSettings(key="g", model="m", daily_limit=1))
    for wanted in ("gemini", "groq", "ollama", "auto", None):
        assert "elevenlabs" not in chat._provider(wanted)
    # its two classes only speak and transcribe
    assert {m for m in vars(V.ElevenLabsVoice) if not m.startswith("_")} == {
        "name",
        "URL",
        "ready",
        "speak",
    }
    assert {m for m in vars(V.ElevenLabsStt) if not m.startswith("_")} == {
        "name",
        "URL",
        "ready",
        "transcribe",
    }


def stt_client(monkeypatch, eleven):
    from fastapi.testclient import TestClient

    import services.api.app as appmod

    s = V.Stt(appmod.settings)
    s.order = ["elevenlabs", "groq", "gemini"]
    s.eleven.key = "k"
    s.eleven.transcribe = eleven
    s.groq_key = "g"
    s._groq_transcribe = lambda audio, mime: "from groq"
    monkeypatch.setattr(appmod, "stt", s)
    return TestClient(appmod.app)


def post(client):
    return client.post(
        "/chat/stt",
        content=b"\x1a\x45\xdf\xa3 audio",
        headers={"content-type": "audio/webm", "host": "localhost:8000"},
    )


def test_elevenlabs_transcribes_first(monkeypatch):
    with stt_client(
        monkeypatch, lambda a, m: ("which part needs service?", "elevenlabs scribe_v1")
    ) as c:
        assert c.get("/chat/stt/status").json()["providers"][0] == {
            "name": "elevenlabs",
            "ready": True,
            "model": "scribe_v1",
        }
        r = post(c)
    assert r.json() == {"text": "which part needs service?", "model": "elevenlabs scribe_v1"}


def test_a_failing_elevenlabs_hands_over_to_groq(monkeypatch):
    def down(a, m):
        raise V.Unavailable("ElevenLabs STT answered HTTP 429")

    with stt_client(monkeypatch, down) as c:
        r = post(c)
    assert r.json()["model"].startswith("groq") and r.json()["text"] == "from groq"


def test_word_error_rate():
    assert wer("the belt warns in 0.6 shifts", "The belt warns in 0.6 shifts.") == 0
    assert wer("the belt warns", "the bolt warns") == pytest.approx(1 / 3)
