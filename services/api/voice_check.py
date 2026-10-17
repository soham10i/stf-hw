"""
The voice pipeline, checked end to end with the real providers - ElevenLabs only speaks and
listens; it never writes an answer:

    question (speech) --STT--> text --language model (Groq, Gemini, ...)--> answer --TTS--> speech

1. which text-to-speech and speech-to-text providers are ready, in order;
2. ElevenLabs reads a known sentence aloud (the configured voice), timed;
3. ElevenLabs Scribe - and Groq Whisper, for comparison - transcribe that audio back, timed,
   and the transcript is compared word by word with the sentence (word error rate).

The audio is kept at .cache/voice-check.mp3 to listen to. Prints no key. Costs one short
ElevenLabs speech request (the sentence's characters) and one transcription.

    PYTHONPATH=packages .venv/bin/python -m services.api.voice_check     (or `make voice-check`)
"""

from __future__ import annotations

import os
import re
import sys
import time

from . import security as sec
from .chat import dotenv
from .tts import ElevenLabsStt, ElevenLabsVoice, Stt, Tts, speakable

SENTENCE = (
    "The HBW belt warns in 0.6 shifts. Preventive maintenance renews it when its "
    "health index falls to half."
)
OUT = os.path.join(os.path.dirname(__file__), "..", "..", ".cache", "voice-check.mp3")


def wer(ref: str, hyp: str) -> float:
    """Word error rate: word edits (substitutions, insertions, deletions) per reference word."""
    a = re.findall(r"[a-z0-9']+", ref.lower())
    b = re.findall(r"[a-z0-9']+", hyp.lower())
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(b) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (a[i - 1] != b[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(b)] / max(1, len(a))


def main() -> int:
    env = {**dotenv(), **os.environ}
    s = sec.Settings.from_env()
    tts, stt = Tts(s), Stt(s)
    print(
        "text to speech:",
        ", ".join(
            f"{p['name']}{'' if p['ready'] else ' (off)'}" for p in tts.status()["providers"]
        ),
    )
    print(
        "speech to text:",
        ", ".join(
            f"{p['name']} {p['model']}{'' if p['ready'] else ' (off)'}"
            for p in stt.status()["providers"]
        ),
    )
    voice = ElevenLabsVoice(env)
    if not voice.ready():
        print("ElevenLabs: no ELEVENLABS_API_KEY - nothing to check")
        return 1
    print(f"voices: {', '.join(sorted(voice.voices))}; speaking with voice {voice.voice_no}")
    text = speakable(SENTENCE)
    t = time.monotonic()
    try:
        audio, mime, model = voice.speak(text, "")
    except Exception as e:  # noqa: BLE001 - report it
        print(f"TTS FAILED: {e}")
        return 1
    took = time.monotonic() - t
    print(f"TTS  ok  {model}: {len(text)} characters -> {len(audio) / 1024:.0f} KB in {took:.1f} s")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f:
        f.write(audio)
    bad = 0
    for name, run in (
        ("ElevenLabs", lambda: ElevenLabsStt(env).transcribe(audio, "audio/mpeg")),
        ("Groq", lambda: (stt._groq_transcribe(audio, "audio/mpeg"), f"groq {stt.groq_model}")),
    ):
        if name == "Groq" and not stt.groq_key:
            continue
        t = time.monotonic()
        try:
            heard, model = run()
        except Exception as e:  # noqa: BLE001 - report it
            print(f"STT  FAIL {name}: {e}")
            bad += name == "ElevenLabs"
            continue
        e = wer(SENTENCE, heard)
        mark = "ok  " if e <= 0.15 else "HIGH"
        print(f"STT  {mark} {model} in {time.monotonic() - t:.1f} s, word error rate {e:.0%}")
        print(f"     heard: {heard}")
        bad += name == "ElevenLabs" and e > 0.15
    print(f"audio: {os.path.relpath(OUT)}")
    print("all good" if not bad else "ElevenLabs transcription failed or was inaccurate")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
