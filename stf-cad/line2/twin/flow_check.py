"""
DT-3b gate: the live plant carries the REAL product flow and the REAL oven control, and draws what they decide.

    .venv-twin/bin/python -W ignore twin/flow_check.py        (from stf-cad/line2; ~2 min)

  F1 engine        line_sim.flow() (the generator the plant runs) gives every scenario of sim_results.json exactly
  F2 oven loop     oven_ctrl.ZoneLoop stepped as the plant steps it reproduces the stored S3 trace (control.json) exactly
  F3 one hour      the plant (flow + closed-loop oven) runs 1 h; its flow KPIs = sim_results.json["nominal_1h"] exactly,
                   and the counts of the events it released agree with them
  F4 genealogy     every cookie has a bake log: deposit < load < qc < pick for each packed one (qc pass), qc reject
                   for each kicked one; every packed cookie deposited during the hour has a deviation for all 3 zones
  F5 coupling      every flow kick is a kicker stroke in the plant, every pack a seal of its lane, every weiss
                   cassette exchange an airlock exchange - at the flow's own time (within one 10 ms tick)
  F6 drawn = flow  a frame every 10 s: each cookie the flow has on a puck is drawn on that puck with its flavour's
                   topping, and nothing else is; each cookie the flow has on the band is drawn in its row's pool slot,
                   at x = depositor + v_band (tau - row period) (an independent formula), topping only if topped
  F7 oven + flow   both deltas down 10 min with the agent policy (the depositor throttles): the band empties and
                   refills, the closed loop holds every zone within the bake window, no cookie flagged
  F8 determinism   two 10 min runs: identical frame streams (SHA-256)
  F9 service       the server with the flow (manual mode): WebSocket rows, paint, flow summary and duty rebuild exactly
                   an independent plant carrying the same flow
  F10 scenarios    all 11 line_sim scenarios (1 h pickers, 8 h AMR shifts) run IN THE PLANT give sim_results.json
                   exactly; the oven, sampled over every whole run, never leaves the bake window; no cookie flagged
"""
import hashlib
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LINE2 = os.path.dirname(HERE)
sys.path.insert(0, LINE2)
from twin.plant.core import POOL, TICK, Plant            # noqa: E402
from twin.plant.flow import Flow                         # noqa: E402
import line_model as M                                   # noqa: E402
import line_sim as LS                                    # noqa: E402
import motion as Mo                                      # noqa: E402
import oven_ctrl as OC                                   # noqa: E402

L = M.L


def check(verbose=True):
    rows, fails = [], []

    def row(name, value, limit, ok, note=""):
        rows.append((name, value, limit, ok, note))
        if not ok:
            fails.append(f"FLOW {name}: {value} vs {limit} {note}".strip())

    # F1 -------------------------------------------------------------------------------------------------------
    ref = json.load(open(os.path.join(LINE2, "sim_results.json")))
    diff = [n for n in LS.SCENARIOS if json.loads(json.dumps(LS.run(n))) != ref[n]]
    row("F1 engine = sim_results", f"{len(LS.SCENARIOS) - len(diff)} of {len(LS.SCENARIOS)} scenarios identical",
        "all", not diff, ", ".join(diff))

    # F2 -------------------------------------------------------------------------------------------------------
    pl = OC.Plant()
    gains = OC.tune(pl)
    stored = json.load(open(os.path.join(LINE2, "oven", "control.json")))["scenarios"]["S3 depositor stop 10 min"]
    content = OC.content_fn((0.0, 600.0))
    zl = OC.ZoneLoop(pl, gains)
    got, nxt = [], 0.0
    while zl.t <= 2400.0 + 1e-9:
        t = zl.t
        zl.step(content(t))
        if t >= nxt - 1e-9:
            got.append([round(v, 2) for v in zl.T])
            nxt += 10.0
    row("F2 oven loop = control.json S3", f"{len(got)} samples, {sum(a != b for a, b in zip(got, stored['T']))} differ",
        "0", got == stored["T"])

    # F3 -------------------------------------------------------------------------------------------------------
    t0 = time.perf_counter()
    p = Plant(flow=Flow("nominal_1h"))
    frames = []
    for k in range(360):                                  # 1 h, a frame every 10 s for F6
        p.step(1000)
        frames.append((p.master.tau, p.frame(), {k_: v for k_, v in p.flow.pucks.items()},
                       {c: v for c, v in p.flow.band.items()}, dict(p.flow.rows)))
    p.flow.release(3600.0 + 60.0)                         # drain to the horizon: line_sim ends at 1 h
    dt_run = time.perf_counter() - t0
    kpi = json.loads(json.dumps(p.flow.kpi))
    c = p.flow.counts
    picks = {f: sum(1 for e in p.flow.log.values() if e.get("lane") == f) for f in LS.F}
    agree = c.get("load", 0) == kpi["loaded"] and c.get("kick", 0) == kpi["rejected"] and \
        c.get("band_lost", 0) == kpi["band_lost"] and picks == kpi["packed"]
    row("F3 one hour = nominal_1h", f"KPIs {'identical' if kpi == ref['nominal_1h'] else 'DIFFERENT'}; events: "
        f"{c.get('load', 0)} loads, {c.get('kick', 0)} kicks, {c.get('band_lost', 0)} band losses, picks {picks}; "
        f"{dt_run:.0f} s incl. 360 frames", "identical; agree", kpi == ref["nominal_1h"] and agree)

    # F4 -------------------------------------------------------------------------------------------------------
    bad = []
    n_packed = n_rej = n_dev = 0
    for e in p.flow.log.values():
        ev = dict(e["events"][::-1])                      # first time of each kind
        times = {k_: t for k_, t in reversed(e["events"])}
        if e.get("end") == "packed":
            n_packed += 1
            order = [times.get(k_) for k_ in ("deposit", "load", "qc", "pick")]
            if None in order or order != sorted(order) or e.get("qc") != "pass":
                bad.append((e["id"], "packed", order, e.get("qc")))
            if not e["pre"] and 0 <= e["deposit"]:
                n_dev += 1
                if not e.get("zone_dev") or None in e["zone_dev"]:
                    bad.append((e["id"], "no zone history"))
        elif e.get("end") == "rejected":
            n_rej += 1
            if e.get("qc") != "reject":
                bad.append((e["id"], "kicked without a reject verdict"))
        del ev
    row("F4 genealogy (bake logs)", f"{len(p.flow.log)} cookies: {n_packed} packed, {n_rej} rejected; {n_dev} with a "
        f"3-zone history; {len(bad)} incomplete", "0", not bad, str(bad[:3]))

    # F5 -------------------------------------------------------------------------------------------------------
    rel = p.flow.released
    want = sorted(round(t, 2) for t, k_, d in rel if k_ == "kick")
    have = sorted(round(t, 2) for t, k_, kw in p.log if k_ == "kick")
    w_seal = sorted((d["lane"], round(t, 2)) for t, k_, d in rel if k_ == "pack")
    h_seal = sorted((kw["lane"], round(t, 2)) for t, k_, kw in p.log if k_ == "seal")
    w_ex = sorted(round(t, 2) for t, k_, d in rel if k_ == "exchange" and d["lane"] == Mo.EXCH_LANE)
    h_ex = sorted(round(t, 2) for t, k_, kw in p.log if k_ == "exchange")

    def near(a, b):
        return len(a) == len(b) and all(abs((x[1] if isinstance(x, tuple) else x) - (y[1] if isinstance(y, tuple) else y))
                                        <= TICK + 1e-6 and (not isinstance(x, tuple) or x[0] == y[0])
                                        for x, y in zip(a, b))
    row("F5 flow -> actuators", f"{len(have)}/{len(want)} kicks, {len(h_seal)}/{len(w_seal)} seals, {len(h_ex)}/"
        f"{len(w_ex)} weiss exchanges at the flow's time", "all, within one tick",
        near(want, have) and near(w_seal, h_seal) and near(w_ex, h_ex))

    # F6 -------------------------------------------------------------------------------------------------------
    st = M.stations()
    vb, period = M.band_v(), L["BAND"]["rows"] * M.takt()
    r_min = 75 - 100
    wrong, n_puck, n_band = [], 0, 0
    for tau, f, pucks, band, rws in frames:
        tr = f["track"]
        for k in range(L["N"]):
            on = k in pucks
            n_puck += 1
            if tr[f"cookie_{k:02d}"][7] != on or tr[f"cookie_{k:02d}_top"][7] != on:
                wrong.append((round(tau), f"puck {k}", on))
            if on:
                flav = p.flow.log[pucks[k]]["flav"]
                if f["paint"].get(f"cookie_{k:02d}_top") != L["BAKED"][Mo.FLAV.index(flav)]:
                    wrong.append((round(tau), f"puck {k} colour"))
        drawn = {n for n, r in tr.items() if n.startswith("band_r") and not n.endswith("_top")
                 and isinstance(r, dict) and r["vis"]}
        expect = set()
        for cid, (r, col, fl, topped) in band.items():
            if rws.get(r) != "deposited":
                continue
            slot = (r - r_min) % POOL + r_min                  # independent of the plant's pool code
            name = f"band_r{slot + 100:03d}_{col}"
            expect.add(name)
            n_band += 1
            x = st["dep"] + vb * (tau - r * period)
            if name not in tr or abs(tr[name]["c"][0] - M.g1(x)) > 0.51:
                wrong.append((round(tau), name, "x", tr.get(name, {}).get("c"), round(x, 2)))
            top = tr.get(f"{name}_top")
            if top is not None and bool(top[7]) != bool(topped):
                wrong.append((round(tau), name, "topping"))
        if drawn != expect:
            wrong.append((round(tau), "band", sorted(drawn ^ expect)[:3]))
    row("F6 drawn = flow", f"360 frames: {n_puck} puck checks, {n_band} band cookies placed by row; {len(wrong)} wrong",
        "0", not wrong, str(wrong[:3]))

    # F7 -------------------------------------------------------------------------------------------------------
    q = Plant(flow=Flow("both_deltas_down_10min_AGENT"))
    worst, cmin, cmax = 0.0, 1.0, 0.0
    for k in range(3600):
        q.step(100)
        worst = max(worst, max(abs(y - s) for y, s in zip(q.zl.y, q.pl.Ts)))
        cf = q.content(q.master.tau)
        cmin, cmax = min(cmin, min(cf)), max(cmax, max(cf))
    q.flow.release(3600.0 + 60.0)
    flagged = sum(1 for e in q.flow.log.values() if e.get("flagged"))
    thr = q.flow.kpi["throttled"]
    row("F7 oven under the real flow", f"agent throttles {thr} cookies: zone content {cmin:.2f}..{cmax:.2f}; worst TC "
        f"{worst:.2f} K off its set point; {flagged} cookies flagged", f"<= {L['BAKE_MARGIN']:g} K, 0 flagged",
        worst <= L["BAKE_MARGIN"] and flagged == 0 and cmin < 0.5)

    # F8 -------------------------------------------------------------------------------------------------------
    def stream():
        r = Plant(flow=Flow("nominal_1h"))
        h = hashlib.sha256()
        for _ in range(600):
            r.step(100)
            h.update(json.dumps(r.frame(), sort_keys=True).encode())
        return h.hexdigest()
    h1, h2 = stream(), stream()
    row("F8 determinism", f"10 min, a frame every second: {'identical' if h1 == h2 else 'DIFFERENT'}", "identical",
        h1 == h2, f"sha256 {h1[:12]}")

    # F9 -------------------------------------------------------------------------------------------------------
    from fastapi.testclient import TestClient
    from twin.plant.serve import Service, create_app
    svc = Service(manual=True, flow=True, hours=0.5)
    ref9 = Plant(flow=Flow("nominal_1h", horizon=1800.0))
    got, mism, n9 = {}, [], 0
    with TestClient(create_app(svc)) as c, c.websocket_connect("/ws/frames") as ws:
        hello = json.loads(ws.receive_text())
        got.update(json.loads(ws.receive_text())["track"])
        for _ in range(40):
            c.post("/step", json=dict(ticks=1500))         # 15 s per step: 10 min
            ref9.step(1500)
            m = json.loads(ws.receive_text())
            got.update(m["track"])
            rf = ref9.frame()
            n9 += 1
            if m["t"] != rf["t"] or any(got.get(n) != r for n, r in rf["track"].items()) or m["paint"] != rf["paint"] \
                    or m["flow"] != json.loads(json.dumps(rf["flow"])) or m["duty"] != rf["duty"]:
                mism.append(m["t"])
    row("F9 flow service (WebSocket)", f"{n9} frames over 10 min: rows, paint, flow panel, duty; {len(mism)} differ "
        f"from an independent plant; hello lists {len(hello['extra'])} extra pool cylinders", "0", not mism,
        str(mism[:3]))

    # F10 ------------------------------------------------------------------------------------------------------
    same, worst10, flagged10, n10 = [], 0.0, 0, 0
    for name in LS.SCENARIOS:
        hz = LS.SCENARIOS[name].get("horizon", LS.H1)
        q = Plant(flow=Flow(name))
        for _ in range(round(hz / 10.0)):                  # the whole run, the oven sampled every 10 s
            q.step(1000)
            worst10 = max(worst10, max(abs(y - s_) for y, s_ in zip(q.zl.y, q.pl.Ts)))
        q.flow.release(hz + 60.0)
        n10 += len(q.flow.log)
        flagged10 += sum(1 for e in q.flow.log.values() if e.get("flagged"))
        if json.loads(json.dumps(q.flow.kpi)) == ref[name]:
            same.append(name)
    row("F10 every scenario in the plant", f"{len(same)} of {len(LS.SCENARIOS)} = sim_results (incl. 8 h shifts, "
        f"{n10:,} cookies); oven worst {worst10:.2f} K over every run; {flagged10} flagged",
        f"all; <= {L['BAKE_MARGIN']:g} K; 0", len(same) == len(LS.SCENARIOS) and worst10 <= L["BAKE_MARGIN"] and
        flagged10 == 0, ", ".join(sorted(set(LS.SCENARIOS) - set(same))))

    if verbose:
        for name, val, lim, ok, note in rows:
            print(f"  [{'ok' if ok else 'FAIL'}] {name:30s} {val:96s} {lim:22s} {note}")
        print("\n".join(fails) if fails else "ALL FLOW PROOFS PASS (engine, oven loop, one hour, genealogy, coupling, "
                                             "drawn = flow, oven + flow, determinism, service, every scenario)")
    return rows, fails


if __name__ == "__main__":
    sys.exit(1 if check()[1] else 0)
