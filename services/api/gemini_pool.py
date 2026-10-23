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

from .logging_config import get_logger

logger = get_logger(__name__)

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
    """Calculate cooldown seconds for a failed model using Google RetryInfo headers or defaults.

    Args:
        e: The HTTPError response from Google Gemini API.

    Returns:
        float: Number of seconds to temporarily remove model from the active pool.
    """
    try:
        body = json.loads(e.read() or b"{}")
    except (ValueError, OSError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    for d in (body.get("error") or {}).get("details", []) or []:
        m = re.match(r"^(\d+(?:\.\d+)?)s$", str(d.get("retryDelay", "")))
        if m:
            return min(MAX_COOLDOWN, float(m.group(1)) + 1.0)
    return COOLDOWN.get(e.code, 30.0)


class AllBusy(Exception):
    """Exception raised when every Gemini model in the pool is in cooldown."""


@dataclass
class Pool:
    """Thread-safe model pool that rotates through Gemini models and tracks quota cooldowns."""

    models: list[str]
    _out: dict[str, float] = field(default_factory=dict)
    _why: dict[str, str] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    clock: object = field(default=time.time, repr=False)

    def available(self) -> list[str]:
        """Return list of models whose cooldown period has expired."""
        now = self.clock()
        with self._lock:
            return [m for m in self.models if self._out.get(m, 0.0) <= now]

    def out(self, model: str, seconds: float, why: str) -> None:
        """Mark a model temporarily unavailable for the given duration with rationale.

        Args:
            model: Model identifier.
            seconds: Duration in seconds to exclude this model.
            why: Diagnostic description of failure.
        """
        with self._lock:
            self._out[model] = self.clock() + seconds
            self._why[model] = why
            logger.warning(
                "Gemini model %r placed on cooldown for %.1fs (reason: %s)", model, seconds, why
            )

    def call(
        self,
        post,
        body: dict,
        retryable=(429, 500, 503, 404),
        accept=None,
        trace=None,
        only: list[str] | None = None,
        rotate_timeouts: bool = False,
    ) -> tuple[dict, str]:
        """Submit request to the first available model, falling back through the pool on error.

        Args:
            post: Callable to execute HTTP POST against the model endpoint.
            body: Request payload dictionary.
            retryable: Tuple of HTTP status codes that trigger model rotation.
            accept: Optional validation callback that may raise ValueError for empty responses.
            trace: Optional list to record model rotation attempts and errors.
            only: Optional subset of models to try (the pool's order is kept).
            rotate_timeouts: When True, a model that does not answer in time is taken out and the
                next one asked, instead of the timeout ending the call.

        Returns:
            tuple[dict, str]: (Parsed response dictionary, model identifier used).

        Raises:
            AllBusy: When all models in the pool are on cooldown.
            urllib.error.HTTPError: For non-retryable HTTP errors.
        """
        tried = []
        for m in self.available():
            if only is not None and m not in only:
                continue
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
                self.out(m, 300.0, "no answer in time")
                if trace is not None:
                    trace.append((m, "no answer in time"))
                if not rotate_timeouts:
                    raise
            except ValueError as e:
                self.out(m, 60.0, f"unusable answer: {e}")
                if trace is not None:
                    trace.append((m, "no usable answer"))
        nxt = min((self._out.get(m, 0.0) for m in self.models), default=0.0) - self.clock()
        logger.error(
            "All Gemini models in pool are exhausted: tried=%s, next_free_in=%.0fs",
            tried, max(0, nxt),
        )
        raise AllBusy(
            f"every model is at its limit ({', '.join(tried) or 'none free'}); "
            f"the first is free again in {max(0, nxt):.0f} s"
        )

    def why(self, model: str) -> str:
        """Why a model is out right now ("" when it is free)."""
        return self._why.get(model, "") if self._out.get(model, 0.0) > self.clock() else ""

    def status(self) -> list[dict]:
        """Return diagnostic health and cooldown status for each model in the pool."""
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
    """Parse comma-separated model list from environment or return default."""
    raw = env.get(name, "")
    ms = [m.strip() for m in raw.split(",") if m.strip()]
    return ms or list(default)
