"""
DT-3a gate: the live plant is the model, runs forever, stops and resumes cleanly, and serves what it computes.

    .venv-twin/bin/python twin/plant_check.py        (from stf-cad/line2; ~3 min)

  L1 replay        given the reference event schedule, frames 0..400 equal timeline.json EXACTLY: the visibility of
                   every row of 527 tracks, every DRAWN row, the 9 element SSR bits, power + phase currents, the zone
                   temperatures (a hidden pool slot may park another row out of sight: it is not drawn)
  L2 determinism   two runs of one command script give the same stream of every frame of 100 s (SHA-256); moving
                   one command by 10 ms changes it
  L3 endurance     2 h of production with a cyclic controller (kick every 20 s, a seal per lane every 36 s, an
                   airlock exchange every 300 s), a frame every 10 s: no unreachable delta pose, every number finite,
                   at most one live row per pool slot, live band rows <= 26 and ordered along the band
  L4 event phases  the live controller fires events at ANY phase of the geared motion; the reference sweep (motion.py)
                   saw one. Each event part's swept envelope vs every geared part's swept envelope over a full 24 s
                   machine cycle: pairs that can never meet are phase-independent; any pair that can is swept exactly
                   (geom.interfere, motion._exempt) at 8 phases
  L5 stop/resume   master off: tau ramps down in 0.5 s and freezes, the geared rows freeze, the oven keeps running;
                   master on: tau continuous (no step > one tick at V), back at rate 1 after 0.5 s
  L6 speed         stepping >= 20 x real time; a full frame <= 50 ms (best of 3 batches)
  L7 service       the FastAPI app in manual mode: commands over REST, frames over the WebSocket (changed rows only after
                   the first) rebuild exactly the rows of an independent plant given the same commands
"""
import hashlib
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LINE2 = os.path.dirname(HERE)
sys.path.insert(0, LINE2)
from twin.plant.core import POOL, TICK, Plant            # noqa: E402
import geom as G                                         # noqa: E402
import motion as Mo                                      # noqa: E402

TL = os.path.join(LINE2, "motion", "timeline.json")


def run_script(script, seconds, sample=1.0):
    """Run a plant with commands [(t, name, kwargs)] and return the SHA-256 of its frame stream + the plant."""
    p = Plant()
    h = hashlib.sha256()
    todo = sorted(script, key=lambda c: c[0])
    i = 0
    n = round(seconds / TICK)
    every = round(sample / TICK)
    for k in range(n + 1):
        while i < len(todo) and round(todo[i][0] / TICK) == k:
            p.command(todo[i][1], **todo[i][2])
            i += 1
        if k % every == 0:
            h.update(json.dumps(p.frame(), sort_keys=True).encode())
        if k < n:
            p.step()
    return h.hexdigest(), p


def check(verbose=True):
    rows, fails = [], []

    def row(name, value, limit, ok, note=""):
        rows.append((name, value, limit, ok, note))
        if not ok:
            fails.append(f"PLANT {name}: {value} vs {limit} {note}".strip())

    # L1 replay ------------------------------------------------------------------------------------------------
    tl = json.load(open(TL))
    p = Plant(events=Mo.reference_events())
    bad, n_rows = [], 0
    for k in range(tl["frames"]):
        f = p.frame()
        for name, tr in tl["track"].items():
            a, b = tr[k], f["track"][name]
            va = a[7] if isinstance(a, list) else a.get("vis", 1)
            vb = b[7] if isinstance(b, list) else b.get("vis", 1)
            if va != vb:
                bad.append((k, name, "visibility"))
            elif va:                                        # drawn: identical; hidden: not drawn, its pose is free
                n_rows += 1
                if a != b:
                    bad.append((k, name))
        for name, g in tl["glow"].items():
            if int(g["bits"][k]) != f["glow"][name]:
                bad.append((k, name))
        if tl["power"][k] != f["power"]:
            bad.append((k, "power"))
        if tl["temps"][k] != f["temps"]:
            bad.append((k, "temps"))
        p.step(10)
    row("L1 replay = timeline.json", f"{tl['frames']} frames: visibility of every row, {n_rows:,} drawn rows, bits, power, "
        f"temps; {len(bad)} differ",
        "0 (exact)", not bad, str(bad[:4]))

    # L2 determinism -------------------------------------------------------------------------------------------
    script = [(5.0, "kick", {}), (9.0, "seal", {"lane": "rot"}), (12.0, "exchange", {}), (30.0, "master", {"on": False}),
              (34.0, "master", {"on": True}), (40.0, "speed", {"factor": 0.5}), (70.0, "speed", {"factor": 1.0}),
              (80.0, "kick", {}), (95.0, "seal", {"lane": "blau"})]
    h1, _ = run_script(script, 100.0, sample=0.1)          # every frame of 100 s
    h2, _ = run_script(script, 100.0, sample=0.1)
    moved = [(c[0] + 0.01 if c[1] == "kick" and c[0] == 80.0 else c[0], c[1], c[2]) for c in script]
    h3, _ = run_script(moved, 100.0, sample=0.1)
    row("L2 determinism", f"same script: {'identical' if h1 == h2 else 'DIFFERENT'}; a kick 10 ms later: "
        f"{'different' if h3 != h1 else 'IDENTICAL'}", "identical / different", h1 == h2 and h3 != h1,
        f"sha256 {h1[:12]}")

    # L3 endurance ---------------------------------------------------------------------------------------------
    p = Plant()
    hours = 2.0
    T_END = hours * 3600
    issues, n_frames, max_live = [], 0, 0
    pitch = Mo.M.band_v() * p.period                       # mm between rows on the band (= BAND spacing)
    xs_ok = True
    t_next = dict(kick=20.0, seal=12.0, exchange=60.0)
    lane = 0
    k = 0
    while p.t < T_END:
        if p.t >= t_next["kick"] - 1e-9:
            p.command("kick")
            t_next["kick"] += 20.0
        if p.t >= t_next["seal"] - 1e-9:
            p.command("seal", lane=Mo.FLAV[lane % 3])
            lane += 1
            t_next["seal"] += 12.0
        if p.t >= t_next["exchange"] - 1e-9:
            ok, _ = p.command("exchange")
            t_next["exchange"] += 300.0
        if k % 1000 == 0:                                   # a frame every 10 s
            f = p.frame()
            n_frames += 1
            issues += f["bad"]
            for name, r in f["track"].items():
                vals = r[:7] if isinstance(r, list) else r["c"] + [r["len"], r["dia"]]
                if not all(math.isfinite(v) for v in vals):
                    issues.append(f"non-finite {name}")
            live = {}
            for name, r in f["track"].items():
                if name.startswith("band_r") and isinstance(r, dict) and r.get("vis"):
                    live.setdefault(name.split("_")[1], set()).add(round(r["c"][0], 6))
            max_live = max(max_live, len(live))
            # a row is one x (its cookies side by side); consecutive live rows are one band pitch apart
            xs = sorted(next(iter(v)) for v in live.values() if len(v) == 1)
            if any(len(v) != 1 for v in live.values()) or \
                    any(abs((b - a) - pitch) > 0.5 for a, b in zip(xs, xs[1:])):
                xs_ok = False
        p.step()
        k += 1
    row("L3 endurance 2 h", f"{n_frames} frames, {len(p.log)} commands; {len(issues)} unreachable / non-finite; "
        f"live band rows <= {max_live}, rows {'one band pitch apart' if xs_ok else 'OUT OF ORDER'}",
        f"0; <= {POOL - 1}; pitch", not issues and max_live <= POOL - 1 and xs_ok,
        str(issues[:3]))

    # L4 event phases ------------------------------------------------------------------------------------------
    base = Plant().base
    geared = set()
    f_a, _, _ = Mo.frame(0.0, base, Mo.reference_events(), None, 0.0)
    ev_parts = {"kick": ["kick_paddle", "kick_rod"]}
    for fl in Mo.FLAV:
        ev_parts[f"seal {fl}"] = [f"sealer_{fl}_head", f"sealer_{fl}_rod"]
        ev_parts[f"lift {fl}"] = [f"stacker_plate_{fl}", f"stacker_rod_{fl}"]
    ev_parts["exchange"] = [n for n, q in base.items() if q.joint == f"shuttle_{Mo.EXCH_LANE}"] + \
        ["aldoor_inner", "aldoor_out"]
    ev_all = {n for v in ev_parts.values() for n in v}
    geared = {n for n in f_a if n not in ev_all}
    env = {}

    def grow(name, q, vis=True):
        if not vis:
            return
        b = q.aabb()
        e = env.get(name)
        env[name] = b if e is None else [min(e[i], b[i]) for i in range(3)] + [max(e[i], b[i]) for i in range(3, 6)]

    no_ev = dict(kicks=[], seals={fl: [] for fl in Mo.FLAV}, lifts={fl: [] for fl in Mo.FLAV}, exchange=None)
    pp = Plant()
    for kk in range(240):                                   # a full machine cycle (24 s) of the geared parts
        tau = kk * 0.1
        now, vis, _ = Mo.frame(0.0, base, no_ev, pp._rows(tau), tau)
        for n in geared:
            if n in now:
                grow(n, now[n], vis.get(n, True))
    ev_env, ev_frames = {}, {}
    full = dict(kicks=[1.0], seals={fl: [1.0] for fl in Mo.FLAV}, lifts={fl: [3.0] for fl in Mo.FLAV}, exchange=1.0)
    for kk in range(int(45 / 0.1)):                          # every event once, at a fixed tau (its own motion)
        t = kk * 0.1
        now, vis, _ = Mo.frame(t, base, full, pp._rows(0.0), 0.0)
        for n in ev_all:
            if n in now:
                b = now[n].aabb()
                e = ev_env.get(n)
                ev_env[n] = b if e is None else [min(e[i], b[i]) for i in range(3)] + [max(e[i], b[i]) for i in range(3, 6)]
                ev_frames.setdefault(n, []).append(t)
    risky = []
    for ename in sorted(ev_all):
        for g in sorted(geared):
            if g in env and ename in ev_env and Mo.M._ovl(ev_env[ename], env[g]) and \
                    not Mo._exempt(base.get(ename, f_a[ename]), base.get(g, f_a[g])):
                risky.append((ename, g))
    hits = []
    for ename, g in risky:                                   # exact sweep at 8 phases of the 24 s cycle
        for ph in range(8):
            tau0 = ph * 3.0
            for t in ev_frames[ename][::2]:
                now, vis, _ = Mo.frame(t, base, full, pp._rows(tau0 + t), tau0 + t)
                if ename in now and g in now and vis.get(g, True) and vis.get(ename, True) and \
                        Mo.M._ovl(now[ename].aabb(), now[g].aabb()) and G.interfere(now[ename], now[g]):
                    hits.append((ename, g, tau0, t))
    row("L4 event phases", f"{len(ev_all)} event parts x {len(geared)} geared parts: {len(risky)} pairs can meet, "
        f"{len(hits)} hits at 8 phases", "0 hits", not hits,
        str(hits[:3]) if hits else ("phase-independent (envelopes disjoint)" if not risky else
                                    "pairs swept exactly: " + ", ".join(f"{a}/{b}" for a, b in risky[:4])))

    # L5 stop / resume -----------------------------------------------------------------------------------------
    p = Plant()
    p.step(1000)
    p.command("master", on=False)
    taus = []
    for _ in range(100):
        p.step()
        taus.append(p.master.tau)
    ramp_ok = abs(taus[-1] - taus[49]) < 1e-12 and taus[49] - 10.0 <= 0.25 + 1e-9
    fa = p.frame()
    temps_a = list(p.yz)
    p.step(500)
    fb = p.frame()
    frozen = all(fa["track"][n] == fb["track"][n] for n in fa["track"] if n not in ev_all)
    oven_runs = temps_a != list(p.yz)
    p.command("master", on=True)
    prev, worst = p.master.tau, 0.0
    for _ in range(100):
        p.step()
        worst = max(worst, p.master.tau - prev)
        prev = p.master.tau
    row("L5 stop / resume", f"ramp-down {taus[49] - 10.0:.3f} s of travel, then frozen; geared rows "
        f"{'frozen' if frozen else 'MOVED'}; oven {'runs' if oven_runs else 'STOPPED'}; max tau step {worst:.4f} s, "
        f"rate {p.master.rate:g}", f"<= 0.25 s; frozen; runs; <= {TICK} s; 1",
        ramp_ok and frozen and oven_runs and worst <= TICK + 1e-12 and p.master.rate == 1.0)

    # L6 speed -------------------------------------------------------------------------------------------------
    p = Plant()
    step_s, frame_s = [], []
    for _ in range(3):                                      # best of 3 batches: the code's speed, not the machine's load
        t0 = time.perf_counter()
        p.step(2000)
        step_s.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        for _ in range(10):
            p.frame()
        frame_s.append((time.perf_counter() - t0) / 10)
    step_x = 20.0 / min(step_s)
    frame_ms = min(frame_s) * 1000
    row("L6 speed", f"stepping {step_x:.0f} x real time; frame {frame_ms:.1f} ms", ">= 20 x; <= 50 ms",
        step_x >= 20 and frame_ms <= 50)

    # L7 service -----------------------------------------------------------------------------------------------
    from fastapi.testclient import TestClient
    from twin.plant.serve import Service, create_app
    svc = Service(manual=True, flow=False)                # the DT-3a plant (flow_check F9 tests the flow service)
    app = create_app(svc)
    ref = Plant()
    plan = [(0, "kick", {}), (3, "seal", {"lane": "weiss"}), (6, "master", {"on": False}), (9, "master", {"on": True}),
            (12, "exchange", {})]
    got, sizes, mism = {}, [], []
    with TestClient(app) as c, c.websocket_connect("/ws/frames") as ws:
        hello = json.loads(ws.receive_text())
        first = json.loads(ws.receive_text())
        got.update(first["track"])
        sizes.append(len(first["track"]))
        for step in range(15):
            for s, name, kw in plan:
                if s == step:
                    r = c.post("/command", json=dict(name=name, **kw))
                    assert r.status_code == 200, r.text
                    ref.command(name, **kw)
            c.post("/step", json=dict(ticks=50))
            ref.step(50)
            m = json.loads(ws.receive_text())
            got.update(m["track"])
            sizes.append(len(m["track"]))
            rf = ref.frame()
            if m["t"] != rf["t"] or any(got.get(n) != r for n, r in rf["track"].items()) or m["glow"] != rf["glow"]:
                mism.append(m["t"])
    row("L7 service (REST + WebSocket)", f"{len(sizes)} frames; first {sizes[0]} rows, then {min(sizes[1:])}-"
        f"{max(sizes[1:])} changed rows; {len(mism)} differ from an independent plant", "0",
        not mism and hello["type"] == "hello" and max(sizes[1:]) < sizes[0], str(mism[:3]))

    if verbose:
        for name, val, lim, ok, note in rows:
            print(f"  [{'ok' if ok else 'FAIL'}] {name:28s} {val:84s} {lim:24s} {note}")
        print("\n".join(fails) if fails else "ALL PLANT PROOFS PASS (replay, determinism, endurance, event phases, "
                                             "stop/resume, speed, service)")
    return rows, fails


if __name__ == "__main__":
    sys.exit(1 if check()[1] else 0)
