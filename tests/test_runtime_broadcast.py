"""The frame broadcast: encoded once, sent to every client at once, a slow client evicted without
holding up the others (services/api/runtime.py; measured in tests/perf/bench_backend.py)."""
from __future__ import annotations

import asyncio
import json
import time

from services.api.runtime import SimRuntime


class Client:
    def __init__(self, delay: float = 0.0, fail: bool = False):
        self.delay, self.fail, self.got = delay, fail, []

    async def send_text(self, text: str) -> None:
        if self.fail:
            raise ConnectionError("gone")
        await asyncio.sleep(self.delay)
        self.got.append(text)


def test_every_client_gets_the_same_text_encoded_once(monkeypatch):
    rt = SimRuntime()
    a, b = Client(), Client()
    rt.add_client(a)
    rt.add_client(b)
    calls = []
    real = json.dumps
    def spy_dumps(*x, **k):
        calls.append(1)
        return real(*x, **k)

    monkeypatch.setattr("services.api.runtime.json.dumps", spy_dumps)
    asyncio.run(rt._broadcast({"type": "frame", "seq": 1}))
    assert len(calls) == 1
    assert a.got == b.got == ['{"type":"frame","seq":1}']


def test_a_slow_client_is_evicted_without_delaying_the_others():
    rt = SimRuntime()
    fast = [Client() for _ in range(5)]
    slow = Client(delay=5.0)
    gone = Client(fail=True)
    for c in (*fast, slow, gone):
        rt.add_client(c)
    t = time.perf_counter()
    asyncio.run(rt._broadcast({"type": "frame"}))
    took = time.perf_counter() - t
    assert took < 0.9  # one 0.5 s timeout for everyone, not one per slow client in turn
    assert all(c.got for c in fast)
    assert rt.client_count == 5  # the slow and the dead client are gone


def test_the_loop_broadcasts_at_30_frames_a_second():
    rt = SimRuntime()
    c = Client()
    rt.add_client(c)

    async def run():
        await rt.start()
        await asyncio.sleep(2.0)
        await rt.stop()

    asyncio.run(run())
    # 2 s at 30 Hz: 60 frames (the old polling loop gave ~54)
    assert 57 <= len(c.got) <= 62
