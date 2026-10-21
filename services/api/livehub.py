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
MAX_PER_ROOM = 8
RATE = 40.0  # messages per second per connection (the twin sends ~4 states and ~8 frames)
TWIN_TYPES = {"hello", "state", "inspection", "frame", "photo", "order_done", "notice"}
DASH_TYPES = {"watch", "simulate", "defect"}


@dataclass
class _Conn:
    ws: WebSocket
    role: str  # "twin" | "dashboard"
    budget: float = RATE
    at: float = field(default_factory=time.monotonic)

    def allow(self) -> bool:
        now = time.monotonic()
        self.budget = min(RATE, self.budget + (now - self.at) * RATE)
        self.at = now
        if self.budget < 1:
            return False
        self.budget -= 1
        return True


@dataclass
class _Room:
    conns: list[_Conn] = field(default_factory=list)
    last_state: str | None = None


class LiveHub:
    def __init__(self) -> None:
        self.rooms: dict[str, _Room] = {}

    def counts(self, room: str) -> dict[str, int]:
        r = self.rooms.get(room)
        conns = r.conns if r else []
        return {"twins": sum(c.role == "twin" for c in conns),
                "dashboards": sum(c.role == "dashboard" for c in conns)}

    def join(self, room: str, ws: WebSocket, role: str) -> _Conn | None:
        if room not in self.rooms and len(self.rooms) >= MAX_ROOMS:
            return None
        r = self.rooms.setdefault(room, _Room())
        if len(r.conns) >= MAX_PER_ROOM:
            return None
        c = _Conn(ws, role)
        r.conns.append(c)
        return c

    def leave(self, room: str, c: _Conn) -> None:
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
        if not r:
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
