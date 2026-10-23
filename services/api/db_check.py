"""
Is the database the API will use reachable and complete? A round trip through the same code
the API runs (guests.py, captures.py), with a throwaway guest that is removed afterwards. Prints
which database is in use and each step's result - never a key.

    PYTHONPATH=packages .venv/bin/python -m services.api.db_check     (or `make db-check`)
"""

from __future__ import annotations

import os
import secrets
import sys
import time

from . import guests as G
from .captures import store_from_env
from .chat import dotenv


def main() -> int:
    """The db-check CLI: probe every database feature and report one line each."""
    env = {**dotenv(), **os.environ}
    db, note = G.db_from_env(env)
    print(f"database: {db.name} ({note})")
    if env.get("SUPABASE_URL"):
        print(f"project:  {env['SUPABASE_URL']}")
    gid = secrets.token_hex(16)
    now = time.time()
    steps = []

    def step(name: str, fn) -> None:
        """Run one probe, recording pass/fail without stopping the sequence."""
        try:
            ok = fn()
            steps.append((name, ok is not False))
        except Exception as e:  # noqa: BLE001 - report every failure, then carry on
            steps.append((f"{name}: {type(e).__name__} {str(e)[:120]}", False))

    step("add a guest", lambda: db.add_guest(gid, now))
    step("read it back", lambda: (db.guest(gid) or {}).get("id") == gid)
    step("touch it", lambda: db.touch(gid, now + 1))
    doc = "check" + gid[:8]
    body = {"title": "db check", "turns": []}
    step("write a document", lambda: db.put("copilot", gid, doc, body))
    step(
        "list the guest's documents",
        lambda: [d["id"] for d in db.list("copilot", gid, ("title",))] == [doc],
    )
    step("forget the guest", lambda: db.forget(gid))
    step("it is gone", lambda: db.guest(gid) is None and db.list("copilot", gid, ("title",)) == [])
    cap = store_from_env(env)
    step(f"photo store ({cap.name}) lists a guest's photos", lambda: cap.list(1, gid) == [])
    for name, ok in steps:
        print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    bad = sum(not ok for _, ok in steps)
    print("all good" if not bad else f"{bad} step(s) failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
