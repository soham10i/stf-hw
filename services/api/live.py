"""
The twin's live state for the chat: the open 3D twin posts a small snapshot every few seconds
(POST /twin/state); the copilot's live_state tool reads the latest. Kept in memory only, one
snapshot per guest (guests.py; per address where there is no guest), so on a shared deployment
each visitor's chat sees their own twin and nobody can feed another visitor's chat, at most
MAX_CLIENTS. A snapshot older than STALE_S
means the twin is closed, and the tool says so.
"""

from __future__ import annotations

import json
import time
from typing import Any

from . import guests

STALE_S = 15.0
MAX_BYTES = 8000
MAX_CLIENTS = 64
_by: dict[str, tuple[dict[str, Any], float]] = {}


def put(snap: dict[str, Any], client: str = "local") -> None:
    """Store a client's snapshot: flat values, small dicts and lists only, at most MAX_BYTES of
    JSON."""
    clean: dict[str, Any] = {}
    for k, v in list(snap.items())[:40]:
        if isinstance(v, (str, int, float, bool)) or v is None:
            clean[str(k)[:40]] = v if not isinstance(v, str) else v[:200]
        elif isinstance(v, dict):
            clean[str(k)[:40]] = {
                str(a)[:40]: (b if isinstance(b, (int, float, bool)) else str(b)[:80])
                for a, b in list(v.items())[:20]
            }
        elif isinstance(v, list):
            clean[str(k)[:40]] = [str(x)[:120] for x in v[:20]]
    if len(json.dumps(clean)) > MAX_BYTES:
        raise ValueError("snapshot too large")
    _by.pop(client, None)
    _by[client] = (clean, time.time())
    while len(_by) > MAX_CLIENTS:
        _by.pop(next(iter(_by)))


def latest(client: str = "local") -> tuple[dict[str, Any] | None, float]:
    """The client's latest snapshot and its age in seconds, or (None, inf) when its twin is not
    open."""
    snap, at = _by.get(guests.current() or client, (None, 0.0))
    age = time.time() - at
    return (snap, age) if snap is not None and age <= STALE_S else (None, float("inf"))


def drop(client: str) -> None:
    """Forget a guest's snapshot (DELETE /guest)."""
    _by.pop(client, None)
