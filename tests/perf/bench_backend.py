"""
Measures the running backend (default http://127.0.0.1:8000) before anything is changed:

  rest       latency (p50/p95/p99) and throughput of the read endpoints, one at a time and
             with 32 requests in flight; response sizes
  stream     the /ws hot-frame stream with 1, 10 and 50 clients: frames per second each,
             the gap between frames (p50/p95/max), frame size (JSON, and gzip / msgpack
             for comparison), and the server's CPU meanwhile
  slow       one client that stops reading: what it does to every other client's stream
  encode     what one frame costs to encode, and how that grows with the clients (the
             server encodes a frame once per client)

    .venv/bin/python tests/perf/bench_backend.py [--base http://127.0.0.1:8000] [--json out.json]

Standard library + websockets only. The server's CPU is sampled with `ps` on the process
listening on the port.
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import msgpack
import websockets


def pct(xs, p):
    if not xs:
        return float("nan")
    xs = sorted(xs)
    k = min(len(xs) - 1, max(0, round(p / 100 * (len(xs) - 1))))
    return xs[k]


# ---------------------------------------------------------------- server cpu
def server_pid(port):
    """The process serving the port: with `uvicorn --reload` that is the worker, a child of the
    process that holds the socket."""
    out = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
        capture_output=True, text=True,
    ).stdout.split()
    if not out:
        return None
    pid = int(out[0])
    kids = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
    return int(kids[-1]) if kids else pid


class CpuSampler:
    """Samples a process's %CPU (ps) every 0.25 s on a thread."""

    def __init__(self, pid):
        self.pid, self.samples, self._stop = pid, [], threading.Event()

    def __enter__(self):
        def run():
            while not self._stop.is_set():
                r = subprocess.run(
                    ["ps", "-o", "%cpu=,rss=", "-p", str(self.pid)],
                    capture_output=True, text=True,
                ).stdout.split()
                if len(r) == 2:
                    self.samples.append((float(r[0]), int(r[1]) / 1024))
                self._stop.wait(0.25)
        self.t = threading.Thread(target=run, daemon=True)
        self.t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self.t.join()

    def summary(self):
        if not self.samples:
            return {}
        cpu = [s[0] for s in self.samples]
        return {"cpu_mean_pct": round(statistics.mean(cpu), 1), "cpu_max_pct": round(max(cpu), 1),
                "rss_mb": round(self.samples[-1][1], 1)}


# ---------------------------------------------------------------- rest
COOKIE = {}


def guest_cookie(base):
    """One guest for the whole run: without its cookie every request to a guest path (/twin,
    /chat, ...) would be a new visitor, which the server records in its database."""
    with urllib.request.urlopen(base + "/guest", timeout=10) as r:
        for h in r.headers.get_all("set-cookie") or []:
            COOKIE["Cookie"] = h.split(";", 1)[0]


def get(url):
    t = time.perf_counter()
    with urllib.request.urlopen(urllib.request.Request(url, headers=COOKIE), timeout=10) as r:
        body = r.read()
        status = r.status
    return time.perf_counter() - t, status, len(body)


def bench_rest(base, paths, n=200, conc=32):
    out = {}
    for path in paths:
        url = base + path
        try:
            get(url)  # warm
        except Exception as e:
            out[path] = {"error": str(e)}
            continue
        seq = [get(url) for _ in range(n)]
        t0 = time.perf_counter()
        with ThreadPoolExecutor(conc) as ex:
            par = list(ex.map(lambda _, u=url: get(u), range(n)))
        wall = time.perf_counter() - t0
        def ms(xs):
            return [x[0] * 1000 for x in xs]
        out[path] = {
            "bytes": seq[0][2],
            "seq_p50_ms": round(pct(ms(seq), 50), 2),
            "seq_p95_ms": round(pct(ms(seq), 95), 2),
            f"c{conc}_p50_ms": round(pct(ms(par), 50), 2),
            f"c{conc}_p95_ms": round(pct(ms(par), 95), 2),
            f"c{conc}_p99_ms": round(pct(ms(par), 99), 2),
            f"c{conc}_rps": round(n / wall, 0),
            "errors": sum(1 for x in seq + par if x[1] != 200),
        }
    return out


# ---------------------------------------------------------------- stream
async def client(url, seconds, rec, stall_after=None):
    """Reads frames for `seconds`; with stall_after, stops reading after that many seconds (the
    socket stays open: the server's sends back up)."""
    arrivals, sizes, frames = [], [], []
    try:
        async with websockets.connect(
            url, max_size=None, open_timeout=10, additional_headers=COOKIE
        ) as ws:
            end = time.perf_counter() + seconds
            t0 = time.perf_counter()
            while time.perf_counter() < end:
                if stall_after is not None and time.perf_counter() - t0 > stall_after:
                    await asyncio.sleep(end - time.perf_counter())
                    break
                try:
                    msg = await asyncio.wait_for(
                        ws.recv(), timeout=max(0.05, end - time.perf_counter())
                    )
                except TimeoutError:
                    break
                arrivals.append(time.perf_counter())
                sizes.append(len(msg))
                if len(frames) < 3:
                    frames.append(msg)
    except Exception as e:
        rec.append({"error": repr(e)})
        return
    rec.append({"arrivals": arrivals, "sizes": sizes, "frames": frames})


async def bench_stream(ws_url, n_clients, seconds, pid, stall=False):
    rec = []
    with CpuSampler(pid) if pid else _null() as cpu:
        tasks = [
            client(ws_url, seconds, rec, stall_after=1.0 if (stall and i == 0) else None)
            for i in range(n_clients)
        ]
        await asyncio.gather(*tasks)
    ok = [r for r in rec if "arrivals" in r]
    # skip the stalled client itself, and the first frames (the hello and the snapshot)
    readers = ok[1:] if stall else ok
    fps, gaps, sizes = [], [], []
    for r in readers:
        a = r["arrivals"][2:]
        if len(a) > 1:
            fps.append((len(a) - 1) / (a[-1] - a[0]))
            gaps += [(b - x) * 1000 for x, b in zip(a, a[1:], strict=False)]
        sizes += r["sizes"][2:]
    res = {
        "clients": n_clients, "connected": len(ok),
        "errors": [r["error"] for r in rec if "error" in r][:3],
        "fps_mean": round(statistics.mean(fps), 1) if fps else 0,
        "fps_min": round(min(fps), 1) if fps else 0,
        "gap_p50_ms": round(pct(gaps, 50), 1), "gap_p95_ms": round(pct(gaps, 95), 1),
        "gap_max_ms": round(max(gaps), 1) if gaps else 0,
        "frame_bytes": round(statistics.mean(sizes)) if sizes else 0,
        "kbit_s_per_client": (
            round(statistics.mean(sizes) * 8 * (statistics.mean(fps) if fps else 0) / 1000, 1)
            if sizes else 0
        ),
    }
    if cpu is not None:
        res.update(cpu.summary())
    frame = next(
        (f for r in ok for f in r["frames"][2:3]), None
    ) or next((f for r in ok for f in r["frames"]), None)
    return res, frame


class _null:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        pass


def encode_costs(frame_text):
    """What the server spends per frame: it encodes once per client (send_json)."""
    obj = json.loads(frame_text)
    n = 2000
    t = time.perf_counter()
    for _ in range(n):
        json.dumps(obj, separators=(",", ":"))
    js = (time.perf_counter() - t) / n * 1e6
    t = time.perf_counter()
    for _ in range(n):
        msgpack.packb(obj)
    mp = (time.perf_counter() - t) / n * 1e6
    raw = json.dumps(obj, separators=(",", ":")).encode()
    return {
        "json_bytes": len(raw),
        "json_gzip_bytes": len(gzip.compress(raw, 6)),
        "msgpack_bytes": len(msgpack.packb(obj)),
        "json_encode_us": round(js, 1), "msgpack_encode_us": round(mp, 1),
        "keys": sorted(obj.keys()),
        "per_second_at_30hz_x50_clients_ms": round(js * 30 * 50 / 1000, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--seconds", type=float, default=6.0)
    ap.add_argument("--json")
    ap.add_argument("--slow-seconds", type=float, default=20.0)
    a = ap.parse_args()
    port = int(a.base.rsplit(":", 1)[1].split("/")[0])
    pid = server_pid(port)
    ws_url = a.base.replace("http", "ws") + "/ws"
    report = {"base": a.base, "server_pid": pid}

    guest_cookie(a.base)
    print(f"backend {a.base} (pid {pid}) as one guest")
    with CpuSampler(pid) if pid else _null() as idle:
        time.sleep(2)
    report["idle"] = idle.summary() if idle else {}
    print("idle", report["idle"])

    rest_paths = ["/health", "/layout", "/orders", "/chat/status", "/twin/records"]
    report["rest"] = bench_rest(a.base, rest_paths)
    for k, v in report["rest"].items():
        print("rest", k, v)

    report["stream"] = []
    frame = None
    for n in (1, 10, 50):
        res, f = asyncio.run(bench_stream(ws_url, n, a.seconds, pid))
        frame = frame or f
        report["stream"].append(res)
        print("stream", res)
    res, _ = asyncio.run(bench_stream(ws_url, 10, a.slow_seconds, pid, stall=True))
    report["slow_client"] = res
    print("slow", res)
    if frame:
        report["encode"] = encode_costs(frame)
        print("encode", report["encode"])
    if a.json:
        json.dump(report, open(a.json, "w"), indent=1)
        print("->", a.json)


if __name__ == "__main__":
    sys.exit(main())
