# Backend performance: measured, fixed, measured again

`tests/perf/bench_backend.py` measures a running backend with the standard library and
`websockets` only:

- the read endpoints' latency and throughput, one at a time and 32 in flight;
- the frame stream with 1, 10 and 50 clients;
- a client that stops reading for 20 s;
- the server's CPU (sampled with `ps` on the worker process);
- what one frame costs to encode.

It runs as one guest, so it does not create guests in the database.

```bash
.venv/bin/python tests/perf/bench_backend.py --base http://127.0.0.1:8010 --json docs/perf/backend-after.json
```

Both runs used a measurement instance on port 8010 without `--reload`, with
`STF_WS_PER_CLIENT=200` so one machine can open 50 stream clients. The per-IP cap (default 4) is
a security limit and stays as it is. Raw results: `backend-before.json`, `backend-after.json`.

## Results

| | Before | After |
|---|---|---|
| Frame stream, 1 / 10 / 50 clients | 27.1 / 26.5 / 24.7 frames/s | **30.0 / 30.0 / 30.0** |
| Gap between frames, p95 at 50 clients | 44.1 ms | 35.8 ms |
| A client stalled 20 s, effect on the other 9 | none | none |
| Server CPU at 50 clients | 12.1 % | 11.7 % (21 % more frames) |
| `/twin/records`, one at a time (p50) | 156 ms | **85 ms** |
| `/twin/records`, 32 in flight (p50 / p99) | 1,056 / 2,089 ms | **411 / 602 ms** |
| `/twin/records` throughput | 29 requests/s | **70 requests/s** |
| `/health`, `/layout`, `/orders`, `/chat/status` | < 1.2 ms; 1,500–2,200 requests/s | unchanged |

**What was not slow:** the frame is 882 bytes of JSON and encodes in 16 µs. gzip would make it
327 bytes, msgpack 817. A binary format would save little, so the stream stays JSON.

## What was wrong, and what changed

1. **Every Supabase query opened a new HTTPS connection.**
   - Cost: 120 ms per query on a new connection against 60 ms on a kept one. The 60 ms is the
     round trip to the Supabase region.
   - Fix: `services/api/keepalive.py`, a drop-in for `urllib.request.urlopen` that keeps one
     connection per host per worker thread. It is used by the factory records, captures, guests
     and visits stores.
   - Behaviour: errors stay urllib's. A read on a connection the server dropped is sent again
     once. A write only reuses a connection idle under 15 s, because a write cannot be re-sent
     safely.
   - Tests: `tests/test_keepalive.py`.
2. **The stream ran at 26.8 frames/s, not 30.**
   - Cause: the loop slept a 60th of a second and broadcast once a 30th had passed.
   - Fix: it now ticks on fixed deadlines at 60 Hz and broadcasts every second tick.
   - The frame is now encoded once, not once per client, and sent to all clients at once, each
     with its own 0.5 s timeout. A slow client is evicted without holding up the rest; before,
     the clients were served one after another.
   - Tests: `tests/test_runtime_broadcast.py`.
3. **Blocking work on the event loop.** Anything there freezes the stream and every request.
   - **New visitors.** The guest middleware looked up and added each one in Supabase on the event
     loop (`guests.resolve`), so every new visitor's first request stalled the server for one or
     more round trips. That was the 130 ms `/chat/status` spike in the first measurement. It now
     runs in a worker thread.
   - **`/chat/status`.** It probed a local Ollama server (up to 1.5 s) on the event loop, each
     time it was called. It now runs in a worker thread, and the probe's answer is kept for 30 s.

## Not changed

- **Supabase's round trip itself (~60 ms)**, which only a nearer region or a cache can remove.
  The twin reads its records once, at load, so a cache would save little.
- **The per-IP stream limit.**
- **Several endpoints still call fast local work directly in async code:** HMAC checks, context
  variables, and the session and capture stores. They were not slow in the measurement; move them
  to threads if they become so.
