"""
A list of Gemini models used in order: when one reaches its limit, the next one answers.

Each Gemini model has its own quota (requests per minute, per day; on the free tier some models,
e.g. gemini-2.5-pro-preview-tts, have none at all). A pool keeps the preferred order and, when a
model answers 429 / 503 / 404, takes it out for as long as Google says - the RetryInfo delay in
the error - or a default, then tries the next. The chat and the TTS each have a pool.

    GEMINI_MODELS      chat models in order (default: CHAT below)
    GEMINI_TTS_MODELS  speech models in order (default: TTS below)
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
from dataclasses import dataclass, field

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# tool-calling chat models, fastest-good first; each has its own free-tier quota
CHAT = [
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
]
# speech: the Pro voice first (best prosody), the flash voices when its quota is closed
TTS = ["gemini-2.5-pro-preview-tts", "gemini-2.5-flash-preview-tts", "gemini-3.8-flash-tts"]

COOLDOWN = {429: 60.0, 503: 30.0, 500: 20.0, 404: 6 * 3600.0}  # seconds, when Google gives none
MAX_COOLDOWN = 24 * 3600.0


def cooldown_of(e: urllib.error.HTTPError) -> float:
    """How long a failed model stays out: Google's RetryInfo delay when the error carries one."""
    try:
        body = json.loads(e.read() or b"{}")
    except (ValueError, OSError):
        body = {}
    for d in (body.get("error") or {}).get("details", []) or []:
        m = re.match(r"^(\d+(?:\.\d+)?)s$", str(d.get("retryDelay", "")))
        if m:
            return min(MAX_COOLDOWN, float(m.group(1)) + 1.0)
    return COOLDOWN.get(e.code, 30.0)


class AllBusy(Exception):
    """Every model in the pool is out; the message says until when (safe to show)."""


@dataclass
class Pool:
    models: list[str]
    _out: dict[str, float] = field(default_factory=dict)
    _why: dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    clock: object = field(default=time.time, repr=False)

    def available(self) -> list[str]:
        now = self.clock()
        with self._lock:
            return [m for m in self.models if self._out.get(m, 0.0) <= now]

    def out(self, model: str, seconds: float, why: str) -> None:
        with self._lock:
            self._out[model] = self.clock() + seconds
            self._why[model] = why

    def call(
        self, post, body: dict, retryable=(429, 500, 503, 404), accept=None, trace=None
    ) -> tuple[dict, str]:
        """post(url, body) with the first available model; on a quota or overload error the
        model is taken out and the next one is tried. `accept(response)` may raise ValueError
        for an answer that is no use (a voice that returned no audio): that model, too, is
        passed over for a minute. Returns (response, model used)."""
        tried = []
        for m in self.available():
            tried.append(m)
            try:
                data = post(API.format(model=m), body)
                if accept:
                    accept(data)
                return data, m
            except urllib.error.HTTPError as e:
                if e.code not in retryable:
                    raise
                self.out(m, cooldown_of(e), f"HTTP {e.code}")
                if trace is not None:
                    trace.append((m, "at its limit" if e.code == 429 else f"HTTP {e.code}"))
            except (urllib.error.URLError, TimeoutError):
                # a model that times out is set aside, so the next question does not wait for it
                self.out(m, 300.0, "no answer in time")
                if trace is not None:
                    trace.append((m, "no answer in time"))
                raise
            except ValueError as e:
                self.out(m, 60.0, f"unusable answer: {e}")
                if trace is not None:
                    trace.append((m, "no usable answer"))
        nxt = min((self._out.get(m, 0.0) for m in self.models), default=0.0) - self.clock()
        raise AllBusy(
            f"every model is at its limit ({', '.join(tried) or 'none free'}); "
            f"the first is free again in {max(0, nxt):.0f} s"
        )

    def status(self) -> list[dict]:
        now = self.clock()
        return [
            {
                "model": m,
                "free": self._out.get(m, 0.0) <= now,
                **(
                    {"back_in_s": round(self._out[m] - now), "why": self._why.get(m)}
                    if self._out.get(m, 0.0) > now
                    else {}
                ),
            }
            for m in self.models
        ]


def models_from_env(name: str, default: list[str], env: dict) -> list[str]:
    raw = env.get(name, "")
    ms = [m.strip() for m in raw.split(",") if m.strip()]
    return ms or list(default)
