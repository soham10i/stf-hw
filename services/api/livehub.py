"""
The live link between the 3D twin and the dashboard: WebSocket /twin/live.

The simulation runs in the visitor's browser (the 3D twin's cell coordinator). While it runs,
the twin publishes what the cell is doing - every unit's state and step, the order's progress,
each inspected cookie and the inspection camera's frames - and every dashboard the same visitor
has open receives it at once. A dashboard talks back on the same socket: "simulate an order",
"break the next cookie", "I am watching the camera" - the twin carries them out.

Rooms are per guest (guests.py: the signed stf_guest cookie, else the client address), so a
visitor only ever sees and steers their own twin. The hub relays and keeps the newest state
message per room (a dashboard that opens mid-order draws at once); it stores nothing else.

Message envelope (JSON, at most MAX_MSG bytes): {"type": ..., ...}
  twin -> dashboards   hello, state, inspection, frame, photo, order_done, notice
  dashboard -> twin    watch, simulate, defect
  hub -> client        peers {"twins": n, "dashboards": n}, and the room's last state on join
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from .logging_config import get_logger

logger = get_logger(__name__)

MAX_MSG = 320_000  # a camera photo with its empty-hood reference, base64
MAX_ROOMS = 200
# per room, by role: a visitor's twin tab (a second one while the first reloads) and a few
# dashboards. Everything a twin sends is fanned out to every dashboard, so these bound the
# relay's egress as much as the room's memory.
MAX_TWINS = 2
MAX_DASHBOARDS = 4
RATE = 40.0  # messages per second per connection (the twin sends ~4 states and ~8 frames)
# bytes a room may take in per second, all its senders together (token bucket, with a burst of
# BURST_S seconds): the camera feed is ~0.3 MB/s, a photo 0.3 MB. Over it, messages are dropped.
ROOM_BYTES_PER_S = 1_500_000
BURST_S = 2.0
TWIN_TYPES = {"hello", "state", "inspection", "frame", "photo", "order_done", "notice"}
DASH_TYPES = {"watch", "simulate", "defect"}


@dataclass
class _Conn:
    """One websocket connection: its role and a per-message token bucket."""

    ws: WebSocket
    role: str  # "twin" | "dashboard"
    budget: float = RATE
    at: float = field(default_factory=time.monotonic)

    def allow(self) -> bool:
        """Take one message token; False when the connection is over its message rate."""
        now = time.monotonic()
        self.budget = min(RATE, self.budget + (now - self.at) * RATE)
        self.at = now
        if self.budget < 1:
            return False
        self.budget -= 1
        return True


@dataclass
class _Room:
    """One live-twin room: its connections, replayable state, and a relay byte budget."""

    conns: list[_Conn] = field(default_factory=list)
    last_state: str | None = None
    budget: float = ROOM_BYTES_PER_S * BURST_S
    at: float = field(default_factory=time.monotonic)

    def take(self, n: int) -> bool:
        """Spend `n` bytes of the room's relay budget; False (drop the message) when it is out."""
        now = time.monotonic()
        full = ROOM_BYTES_PER_S * BURST_S
        self.budget = min(full, self.budget + (now - self.at) * ROOM_BYTES_PER_S)
        self.at = now
        if n > self.budget:
            return False
        self.budget -= n
        return True


class LiveHub:
    """The live-twin relay: role-checked websocket rooms with rate and byte budgets.

    A twin publishes frames; dashboards subscribe. One hub instance is shared by the
    app; every room is independent (per-guest isolation).
    """

    def __init__(self) -> None:
        self.rooms: dict[str, _Room] = {}

    def counts(self, room: str) -> dict[str, int]:
        """Connected twins and dashboards in a room (for /health and metrics)."""
        r = self.rooms.get(room)
        conns = r.conns if r else []
        return {"twins": sum(c.role == "twin" for c in conns),
                "dashboards": sum(c.role == "dashboard" for c in conns)}

    def join(self, room: str, ws: WebSocket, role: str) -> _Conn | None:
        """Admit a connection to a room, or None when room/role caps are full."""
        if room not in self.rooms and len(self.rooms) >= MAX_ROOMS:
            return None
        r = self.rooms.setdefault(room, _Room())
        cap = MAX_TWINS if role == "twin" else MAX_DASHBOARDS
        if sum(c.role == role for c in r.conns) >= cap:
            if not r.conns:
                self.rooms.pop(room, None)
            return None
        c = _Conn(ws, role)
        r.conns.append(c)
        return c

    def leave(self, room: str, c: _Conn) -> None:
        """Remove a connection; the room (and its replay state) goes with the last twin."""
        r = self.rooms.get(room)
        if not r:
            return
        if c in r.conns:
            r.conns.remove(c)
        if not any(x.role == "twin" for x in r.conns):
            r.last_state = None  # no twin: no live state to replay
        if not r.conns:
            self.rooms.pop(room, None)

    def last_state(self, room: str) -> str | None:
        """The last state a twin published, replayed to late-joining dashboards."""
        r = self.rooms.get(room)
        return r.last_state if r else None

    @staticmethod
    def accepts(role: str, raw: str) -> dict[str, Any] | None:
        """The message if this role may send it, else None."""
        if len(raw) > MAX_MSG:
            return None
        try:
            msg = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(msg, dict):
            return None
        allowed = TWIN_TYPES if role == "twin" else DASH_TYPES
        return msg if msg.get("type") in allowed else None

    async def relay(self, room: str, sender: _Conn, msg: dict[str, Any], raw: str) -> None:
        """Send a message to the room's other side: twin -> dashboards, dashboard -> twins."""
        r = self.rooms.get(room)
        if not r or not r.take(len(raw)):
            return
        if sender.role == "twin" and msg.get("type") == "state":
            r.last_state = raw
        to = "dashboard" if sender.role == "twin" else "twin"
        for c in list(r.conns):
            if c.role != to:
                continue
            try:
                await c.ws.send_text(raw)
            except Exception as e:  # a closing socket: its own handler removes it
                logger.debug("live relay to a closing socket: %s", e)

    async def announce(self, room: str) -> None:
        """Tell everyone in the room who else is there (a dashboard shows "twin connected")."""
        r = self.rooms.get(room)
        if not r:
            return
        text = json.dumps({"type": "peers", **self.counts(room)})
        for c in list(r.conns):
            try:
                await c.ws.send_text(text)
            except Exception as e:
                logger.debug("live announce to a closing socket: %s", e)
