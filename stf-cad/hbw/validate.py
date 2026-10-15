"""
Validation of Upgrades 1-11: re-run everything, from outside the upgrades.

    ../../.venv/bin/python validate.py          (about 25 min on 10 cores)

Every upgrade proves itself before it exports. This harness checks those
proofs from the outside, in five parts:

  A REGRESSION  every variant re-exported through its own proof gates; each
                fingerprint must equal the recorded baseline (validation/baseline.json)
  B GATES       the proofs that have no export of their own: U11's security
                proofs, U10's published numbers against a fresh simulation
  C ROBUSTNESS  the Upgrade 7 and Upgrade 10 programs against a plant whose
                every step time varies at random by +-20 %: no watchdog may trip
                falsely, and U10's gain must hold across the spread
  D MUTATION    a known defect is planted in each proof; the proof must catch
                it. A mutant that survives means the proof is weaker than it says
  E DATA        month data unchanged, the grid run deterministic, the network's
                three deployments (PyTorch, ONNX, the browser's JSON weights) agree,
                pytest, and the web build

Writes docs/VALIDATION.md and web/public/validation/validation.json.
"""
import concurrent.futures as cf
import hashlib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
PY = sys.executable
PUB = os.path.join(ROOT, "web", "public")
BASE_F = os.path.join(HERE, "validation", "baseline.json")
VARIANTS = ["base", "up1", "up2", "up3", "up4", "up5", "up6", "up7", "up10", "up11", "up12"]


def sh(args, env=None, cwd=HERE, timeout=5400):
    t0 = time.time()
    p = subprocess.run(args, cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr, round(time.time() - t0)


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


# ------------------------------------------------------------ A regression
EXPORT_DIR = os.path.join(HERE, ".cache", "exports")      # re-proven exports never touch web/public


def job_export(v):
    os.makedirs(EXPORT_DIR, exist_ok=True)
    rc, out, err, s = sh([PY, "hbw_export.py"], {"STF_VARIANT": v, "STF_EXPORT_DIR": EXPORT_DIR})
    import re
    m = re.search(r"fingerprint ([0-9a-f]{16})", out)
    fp = m.group(1) if m else None
    return {"variant": v, "ok": rc == 0 and fp is not None, "fingerprint": fp, "s": s,
            "tail": (out + err).strip().splitlines()[-3:] if rc else []}


# ------------------------------------------------------ in-process jobs
# run as:  STF_VARIANT=... python validate.py --job <name>   -> one JSON line on stdout
def _job(name):
    return {"security": j_security, "throughput": j_throughput, "mc": j_mc, "mutants": j_mutants,
            "ml": j_ml}[name]()


def j_security():
    import security as S
    fails, R = S.run()
    return {"fails": fails, "rules": len(R["rules"]), "accesses": R["n_access"], "attacks": len(R["attacks"]),
            "contained": sum(a["blocked"] for a in R["attacks"]), "exposed": [f"{e['module']}.{e['signal']}" for e in R["exposed"]],
            "denied_pairs": len(R["denied"])}


def j_throughput():
    import control as C
    d = json.load(open(os.path.join(PUB, "throughput", "throughput.json")))
    out = {"fails": []}
    after = C.simulate(C.PLC_POLICY)[2]
    for m in C.OPT:
        C.OPT[m] = False
    before = C.simulate(C.PLC_POLICY)[2]
    for m in C.OPT:
        C.OPT[m] = True
    pub_b = d["ablation"][0]["model_s"]
    pub_a = d["ablation"][-1]["model_s"]
    if abs(before - pub_b) > 0.05 or abs(after - pub_a) > 0.05:
        out["fails"].append(f"published {pub_b} -> {pub_a} s, fresh {before} -> {after} s")
    n = C.explore("reuse")[0]
    if n != d["proofs"]["explored_states"]["reuse"]:
        out["fails"].append(f"explored states {n}, published {d['proofs']['explored_states']['reuse']}")
    out.update(before=before, after=after, states=n)
    return out


def j_mc():
    """+-20 % on every plant step, 25 seeds, with and without Upgrade 10."""
    import random
    import control as C
    import vc
    orig = vc.phys
    res = {}
    for name, on in (("before", False), ("after", True)):
        for m in C.OPT:
            C.OPT[m] = on
        spans, trips, worst = [], 0, 0.0
        for seed in range(25):
            rng = random.Random(seed)
            vc.phys = lambda st, _o=orig, _r=rng: _o(st) * _r.uniform(0.8, 1.2)
            try:
                r = vc.Run(C.PLC_POLICY).run()
            finally:
                vc.phys = orig
            spans.append(r.makespan)
            if r.alarms:
                trips += 1
            for b in r.bars:
                for u, key, t0, t1, lim in b["steps"]:
                    if lim:
                        worst = max(worst, (t1 - t0) / lim)
                        trips += (t1 - t0) >= lim
        spans.sort()
        res[name] = {"runs": len(spans), "min": spans[0], "median": spans[len(spans) // 2], "max": spans[-1],
                     "false_trips": trips, "worst_watchdog_use": round(worst, 3)}
    for m in C.OPT:
        C.OPT[m] = True
    fails = [f"{k}: {v['false_trips']} false watchdog trips" for k, v in res.items() if v["false_trips"]]
    if res["after"]["max"] >= res["before"]["min"]:
        fails.append("the U10 spread overlaps the U7 spread: the gain is not robust")
    return {"fails": fails, **res}


def j_mutants():
    """Plant a defect in each proof; each must be caught."""
    import control as C
    import safety as S
    import security as SEC
    import vgr_path as VP
    rows = []

    def row(mid, proof, defect, caught, how):
        rows.append({"id": mid, "proof": proof, "defect": defect, "caught": bool(caught), "how": how})

    # M1 the dispatcher gives the arm a second job while it holds a cookie
    orig = C._candidates

    def mut(s, pol):
        yield from orig(s, pol)
        bo = s["bout"]
        if s.get("cup") and bo and bo[1] is None and bo[2] == "fill":
            for bi, b in enumerate(C.BAYS):
                c = next((c for c in s["bays"][bi] if C._stage(s, c) == "return"), None)
                if c:
                    yield ("bay_to_belt", (c, b, bo[0]), ("arm", "belt"), (("bay", b),), ())
                    break
    C._candidates = mut
    try:
        _, f, _ = C.explore("reuse")
    finally:
        C._candidates = orig
    row("M1", "U4/U10 exhaustive explorer", "the arm is given a bay pick while its cup holds a cookie", f,
        f[0][:90] if f else "survived")
    # M2 the belt policy that lets two moulds on the belt
    _, f, _ = C.explore("prefetch")
    row("M2", "U4 exhaustive explorer", "prefetch: a second mould on the belt", f, (f[0][:90] if f else "survived"))
    # M3 a VGR motion step without its watchdog
    lim = C.Step.limit
    C.Step.limit = property(lambda st: None if st.unit == "arm" else lim.fget(st))
    try:
        f = C.check_sfc(C.sfc())
    finally:
        C.Step.limit = lim
    row("M3", "U4 state-machine proof", "the VGR's motion steps lose their timeouts", f, f[0][:90] if f else "survived")
    # M4 the blended crossing flown at 100 mm: inside the plunge's joint limits (84 mm), so only the
    # collision sweep can catch it - the carried cookie clips the HBW light barrier. (60 mm was first
    # tried: caught, but by the joint-limit check, not the sweep this mutant is meant to test.)
    # (80 mm lower than planned is still clear: the search never goes below the higher station,
    # so the crossing height is set by that floor, not by an obstacle - that mutant was no defect.)
    tour = [("belt", "pick", "raw", "s"), ("oven", "place", None, "t")]
    keys = VP.plan(tour)
    low = [dict(k) for k in keys]
    for k in low[10:12]:                     # the two crossing waypoints between the stations
        k["pz"] = 100.0
    op = VP.plan
    VP.plan = lambda t=None: low
    try:
        f = VP.check(verbose=False, tour=tour)
    finally:
        VP.plan = op
    row("M4", "U10 swept-path proof (SAT)", "the blended crossing flown at 100 mm (inside the joint limits)", f, f[0][:90] if f else "survived")
    # M5 a spare coil added to the Modbus allow-list; M6 one program rule removed
    rules = SEC.allow_list()
    extra = rules + [{"node": "192.168.10.12", "module": "vgr", "fc": 15, "fn": "write_coils", "start": 6, "count": 1}]
    f, _ = SEC.check_least_privilege(extra)
    row("M5", "U11 least privilege", "the retired VGR compressor coil made writable", f, f[0][:90] if f else "survived")
    f, _ = SEC.check_least_privilege(rules[1:])
    row("M6", "U11 least privilege", "the HBW write rule removed", f, f[0][:90] if f else "survived")
    # M7 an unauthenticated conduit from the internet straight into the cell
    SEC.CONDUITS.append({"id": "CX", "a": "Z5", "b": "Z1", "flow": "vendor VPN", "proto": "Modbus", "auth": "none", "dpi": "-"})
    try:
        f, _, _ = SEC.check_default_deny()
    finally:
        SEC.CONDUITS.pop()
    row("M7", "U11 default deny", "a vendor VPN straight into cell control", f, f[0][:90] if f else "survived")
    # M8 the safety relay ignores its second channel
    en = S.enable
    S.enable = lambda st: all(st["estop_ok"][0]) and all(st["door_closed"][0]) and all(st["locked"]) and \
        st["reset_since_trip"] and st["edm_closed"]
    try:
        f, _ = S.check_logic()
    finally:
        S.enable = en
    row("M8", "U2 safety logic (exhaustive)", "the relay reads only channel 1", f, f[0][:90] if f else "survived")
    # M9 the SunSpec reserve made writable by the EMS
    SEC.SUNSPEC_124[5] = ("MinRsvPct", 7, True)
    try:
        f = SEC.check_sunspec()
    finally:
        SEC.SUNSPEC_124[5] = ("MinRsvPct", 7, False)
    row("M9", "U11 SunSpec allow-list", "the EMS may write the battery reserve", f, f[0][:90] if f else "survived")
    return {"fails": [f"{r['id']} survived: {r['defect']}" for r in rows if not r["caught"]], "rows": rows}


def j_ml():
    import numpy as np
    import onnx
    import torch
    from onnx.reference import ReferenceEvaluator
    from ml import train as T
    from ml.model import Net
    W = json.load(open(os.path.join(PUB, "ml", "weights.json")))
    Mi = json.load(open(os.path.join(PUB, "ml", "month_inputs.json")))
    net = Net(T.N_IN, 1)
    net.load_state_dict(torch.load(os.path.join(HERE, "ml", "ckpt", "semi.pt"), map_location="cpu", weights_only=True))
    net.eval()
    x = np.array(Mi["x"], dtype=np.float32)
    s = T.channels(x, np.array(W["ctx_mu"], dtype=np.float32), np.array(W["ctx_sd"], dtype=np.float32))
    pad = np.concatenate([np.repeat(s[:, :1], T.WINDOW - 1, axis=1), s], axis=1)
    V = np.lib.stride_tricks.sliding_window_view(pad, T.WINDOW, axis=1)
    idx = np.linspace(0, x.shape[0] - 1, 60).astype(int)
    with torch.no_grad():
        pt = np.stack([net(torch.from_numpy(np.ascontiguousarray(V[c][idx])))[0][:, 0].numpy() for c in range(T.C)], 1)
    stored = np.array(Mi["torch_rul"])[idx]
    onx = ReferenceEvaluator(onnx.load(os.path.join(PUB, "ml", "stf_pm_tcn.onnx")))
    ox = np.stack([onx.run(None, {"x": np.ascontiguousarray(V[c][idx])})[0][:, 0] for c in range(T.C)], 1)
    js = np.stack([[_np_forward(W, V[c][i]) for c in range(T.C)] for i in idx])
    e = {"pytorch_vs_stored": float(np.abs(pt - stored).max()), "onnx_vs_pytorch": float(np.abs(ox - pt).max()),
         "json_vs_pytorch": float(np.abs(js - pt).max())}
    fails = [f"{k} = {v:.4f} orders" for k, v in e.items() if v > 0.01]
    return {"fails": fails, "checked_windows": int(len(idx) * T.C), **{k: round(v, 6) for k, v in e.items()}}


def _np_forward(W, x):
    """The browser's forward pass (web/src/dashboard/ml.ts), re-implemented in numpy from the JSON weights."""
    import numpy as np
    h, keep = np.asarray(x, dtype=np.float64), None
    for k, c in enumerate(W["conv"]):
        w, b, d = np.array(c["w"]), np.array(c["b"]), c["dil"]
        T_ = h.shape[1]
        p = np.concatenate([np.zeros((h.shape[0], 2 * d)), h], axis=1)
        y = np.stack([sum(w[o, :, j] @ p[:, j * d: j * d + T_] for j in range(3)) + b[o] for o in range(w.shape[0])])
        h = np.maximum(y, 0)
        if k == 1:
            keep = h
    h = h + keep
    z = np.concatenate([h[:, -1], h.mean(axis=1)])
    f = np.maximum(np.array(W["fc"]["w"]) @ z + np.array(W["fc"]["b"]), 0)
    return W["rul_cap"] / (1 + np.exp(-(np.array(W["rul"]["w"]) @ f + np.array(W["rul"]["b"]))[0]))


def job(name, variant):
    rc, out, err, s = sh([PY, "validate.py", "--job", name], {"STF_VARIANT": variant})
    try:
        r = json.loads(out.strip().splitlines()[-1])
    except Exception:
        r = {"fails": [f"crashed: {(err or out).strip().splitlines()[-1:] }"]}
    r["s"] = s
    return name, r


# ------------------------------------------------------------ E data
def job_data():
    out = {"fails": []}
    mj = os.path.join(PUB, "month", "month.json")
    before = sha(mj)
    base = json.load(open(BASE_F)).get("month_json")
    if base and before != base:
        out["fails"].append(f"month.json {before} differs from the baseline {base}")
    g = os.path.join(PUB, "grid", "grid.json")
    g0 = sha(g)
    rc, o, e, _ = sh([PY, "grid.py"], {"STF_VARIANT": "up7"})
    g1 = sha(g)
    if rc or g0 != g1:
        out["fails"].append(f"grid.py is not deterministic ({g0} -> {g1})" if not rc else f"grid.py failed: {e[-200:]}")
    out.update(month_json=before, grid_json=g1)
    rc, o, e, s = sh([PY, "-m", "pytest", "-q"], cwd=ROOT)
    last = (o.strip().splitlines() or ["?"])[-1]
    out["pytest"] = last
    if rc:
        out["fails"].append(f"pytest: {last}")
    rc, o, e, s = sh(["npm", "run", "build"], cwd=os.path.join(ROOT, "web"))
    out["web_build"] = "ok" if rc == 0 else (o + e).strip().splitlines()[-1]
    if rc:
        out["fails"].append(f"web build: {out['web_build']}")
    return out


# ------------------------------------------------------------------ main
def main():
    t0 = time.time()
    base = json.load(open(BASE_F))
    R = {"exports": {}, "jobs": {}}
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        fx = {ex.submit(job_export, v): v for v in VARIANTS}
        fj = [ex.submit(job, n, v) for n, v in (("security", "up11"), ("throughput", "up10"), ("mc", "up10"),
                                                ("mutants", "up11"), ("ml", "up7"))]
        for f in cf.as_completed(list(fx) + fj):
            r = f.result()
            if isinstance(r, tuple):
                R["jobs"][r[0]] = r[1]
                print(f"  {r[0]:10s} {'ok' if not r[1]['fails'] else 'FAIL'}  ({r[1]['s']} s)", flush=True)
            else:
                want = base["fingerprints"].get(r["variant"])
                r["baseline"] = want
                r["match"] = r["fingerprint"] == want
                R["exports"][r["variant"]] = r
                print(f"  export {r['variant']:5s} {r['fingerprint']}  {'= baseline' if r['match'] else 'CHANGED'}  ({r['s']} s)", flush=True)
    R["jobs"]["data"] = job_data()      # after the exports: the web build reads their files
    fails = [f"export {v}: {'gate failed' if not r['ok'] else 'fingerprint ' + str(r['fingerprint']) + ' != ' + str(r['baseline'])}"
             for v, r in R["exports"].items() if not (r["ok"] and r["match"])]
    for n, r in R["jobs"].items():
        fails += [f"{n}: {x}" for x in r["fails"]]
    R["fails"], R["minutes"] = fails, round((time.time() - t0) / 60, 1)
    R["date"] = time.strftime("%Y-%m-%d %H:%M")
    os.makedirs(os.path.join(PUB, "validation"), exist_ok=True)
    json.dump(R, open(os.path.join(PUB, "validation", "validation.json"), "w"), indent=1)
    open(os.path.join(ROOT, "docs", "VALIDATION.md"), "w").write(report(R))
    print("\n".join(fails) if fails else f"VALIDATION OK ({R['minutes']} min)")
    return 1 if fails else 0


def report(R):
    J = R["jobs"]
    L = ["# Validation of Upgrades 1-11", "", f"Run {R['date']} by `stf-cad/hbw/validate.py` in {R['minutes']} min. "
         + ("**All checks pass.**" if not R["fails"] else f"**{len(R['fails'])} checks fail** (listed at the end)."), "",
         "## A. Regression: every variant re-exported through its own proof gates", "",
         "| Variant | Proof gates | Fingerprint | Baseline |", "|---|---|---|---|"]
    for v in VARIANTS:
        r = R["exports"].get(v, {})
        L.append(f"| {v} | {'pass' if r.get('ok') else 'FAIL'} | `{r.get('fingerprint')}` | {'same' if r.get('match') else 'CHANGED'} |")
    s, t = J["security"], J["throughput"]
    L += ["", "## B. Proofs without an export of their own", "",
          f"- **U11 security:** {s['rules']} allow rules for {s['accesses']} program accesses; {s['contained']}/{s['attacks']} attacks "
          f"contained; {s['denied_pairs']} zone pairs denied; exposed and blocked: {', '.join(s['exposed'])}.",
          f"- **U10 published numbers:** fresh simulation {t['before']} → {t['after']} s and {t['states']} explored states, "
          "equal to throughput.json.", "",
          "## C. Robustness: ±20 % random variation on every plant step, 25 seeds each", "",
          "| Program | Fastest | Median | Slowest | False watchdog trips | Worst watchdog use |", "|---|---|---|---|---|---|"]
    for k in ("before", "after"):
        m = J["mc"][k]
        L.append(f"| {'Upgrade 7' if k == 'before' else 'Upgrade 10'} | {m['min']} s | {m['median']} s | {m['max']} s | "
                 f"{m['false_trips']} | {round(m['worst_watchdog_use'] * 100)} % |")
    L += ["", "## D. Mutation tests: a defect planted in each proof", "", "| # | Proof | Planted defect | Caught |", "|---|---|---|---|"]
    for r in J["mutants"]["rows"]:
        L.append(f"| {r['id']} | {r['proof']} | {r['defect']} | {'yes' if r['caught'] else '**no**'} |")
    m, d = J["ml"], J["data"]
    L += ["", "## E. Data products", "",
          f"- **Month data:** month.json `{d['month_json']}` (baseline).",
          f"- **Grid:** re-run gives the same grid.json `{d['grid_json']}`.",
          f"- **Network deployments** over {m['checked_windows']} windows: PyTorch vs stored {m['pytorch_vs_stored']:.4f}, "
          f"ONNX vs PyTorch {m['onnx_vs_pytorch']:.6f}, browser JSON weights vs PyTorch {m['json_vs_pytorch']:.6f} orders.",
          f"- **pytest:** {d['pytest']}. **Web build:** {d['web_build']}.", ""]
    if R["fails"]:
        L += ["## Failing checks", ""] + [f"- {f}" for f in R["fails"]]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--job":
        print(json.dumps(_job(sys.argv[2]), default=str))
    else:
        sys.exit(main())
