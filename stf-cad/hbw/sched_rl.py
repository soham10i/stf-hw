"""
Upgrade 16 - a learned scheduler behind a safety shield.

    STF_VARIANT=up12 python3 sched_rl.py        (from stf-cad/hbw; or `make sched`)

The PLC dispatches by a fixed priority list (control._candidates): at every scan it starts
the first job whose units are idle, and the exhaustive explorer proves that no timing of
the jobs ever deadlocks it. This module lets a learning agent choose instead - at every
scan, which startable job to launch next, or to wait - and asks whether it finds a faster
order without giving up that proof.

  AGENT    the most permissive candidate set (belt prefetch, mould reuse, the buffer):
           every job the program could start. Tabular Q-learning on the event-driven
           simulation, job times drawn +-SPREAD around nominal (validate.py's spread);
           reward = minus the time that passes. A (state, action) seen for the first time
           is valued by a rollout of the PLC's own policy from where it leads, so before
           any learning the agent is already a one-step improvement on the PLC
           (rollout policy improvement, Bertsekas) and learning refines it.
  SHIELD   an action is allowed only if the PLC's own policy could take over from the
           state it leads to and finish under EVERY completion order (explored
           exhaustively, memoised per state). So whatever the agent learns, it can never
           steer into a state the proven policy cannot rescue (Alshiekh et al. 2018).
  CONTROL  the same agent without the shield, to show what the shield prevents.
Scored against the PLC's policies on the same random job times; the learned order is
exported as a Gantt chart. Writes web/public/sched/rl.json.
"""
import json
import os
import random
import sys
import time
from functools import partial

import control as C

sys.setrecursionlimit(20000)
OUT = os.path.join(os.path.dirname(__file__), "..", "..", "web", "public", "sched", "rl.json")
AGENT, FALLBACK = "agent", C.PLC_POLICY
C.POLICIES[AGENT] = dict(belt="prefetch", reuse=True, buffer=True, say="the learning agent's candidate set: every job")
EPISODES = 1000
SPREAD = 0.20
ALPHA, GAMMA = 0.2, 1.0
EPS0, EPS1 = 0.3, 0.02
EVAL_RUNS = 25
SEED = 16
WAIT = ("wait",)
_DUR = {}


def dur(job):
    if job not in _DUR:
        _DUR[job] = C._dur(job)
    return _DUR[job]


def wide(s):
    """The PLC's candidates, opened up where the program fixes a choice the scheduler could
    make: which free slot a mould is stored in, which raw cookie is retrieved next, which
    empty mould is fetched. (The program takes the first free slot and the production order.)"""
    L, out = s["leave"], []
    free = [i for i in range(len(C.SLOTS)) if C._free(s, ("slot", i))]
    raw = [(i, sl) for i, sl in enumerate(s["slots"]) if sl and sl[1] and C._stage(s, sl[1]) == "raw" and ("slot", i) not in L]
    empty = [(i, sl) for i, sl in enumerate(s["slots"]) if sl and sl[1] is None and ("slot", i) not in L]
    for j in C._candidates(s, AGENT):
        name, b, units, src, dst = j
        if name == "store":
            out += [(name, (b[0], b[1], C.SLOTS[i]), units, src, (("slot", i),)) for i in free]
        elif name == "retrieve":
            out += [(name, (sl[1], sl[0], C.SLOTS[i]), units, (("slot", i),), dst) for i, sl in raw]
        elif name == "fetch_empty":
            out += [(name, (sl[0], C.SLOTS[i]), units, (("slot", i),), dst) for i, sl in empty]
        elif name == "store_retrieve":
            out += [(name, (b[0], b[1], C.SLOTS[i], sl[1], sl[0], C.SLOTS[k]), units, (("bin",), ("slot", k)), (("slot", i), ("bin",)))
                    for i in free for k, sl in raw]
        else:
            out.append(j)
    return list(dict.fromkeys(out))


def startable(s):
    """Every job the agent may start now: the widened candidates whose units are idle."""
    return [j for j in wide(s) if not any(u in s["busy"] for u in j[2])]


def start(s, job):
    s = dict(s)
    s["busy"] = tuple(sorted(s["busy"] + job[2]))
    s["res"] = tuple(sorted(s["res"] + job[4]))
    s["leave"] = tuple(sorted(s["leave"] + job[3]))
    s["run"] = tuple(sorted(s["run"] + (job,), key=repr))
    return s


# ------------------------------------------------------------------- shield
_SAFE = {}
STATS = {"checked": 0, "explored": 0}


def _fb_safe(f):
    """From this state the fallback policy finishes the order under every completion
    order (invariants hold all the way, no deadlock). Memoised."""
    if f in _SAFE:
        return _SAFE[f]
    STATS["explored"] += 1
    s = C._thaw(f)
    if C.invariants(s):
        ok = False
    elif not s["run"]:
        ok = C.goal(s)
    else:
        ok = all(_fb_safe(C._freeze(C.dispatch(C.complete(s, j, FALLBACK), FALLBACK))) for j in s["run"])
    _SAFE[f] = ok
    return ok


def rescuable(s):
    """The fallback could take over right now and finish."""
    STATS["checked"] += 1
    return _fb_safe(C._freeze(C.dispatch(s, FALLBACK)))


def allowed(s, shield=True):
    """The agent's options at a decision point: startable jobs, and waiting if anything
    runs - with the shield, only those after which the fallback could still finish."""
    opts = startable(s) + ([WAIT] if s["run"] else [])
    if not shield:
        return opts, 0
    ok = [a for a in opts if rescuable(s if a == WAIT else start(s, a))]
    return ok, len(opts) - len(ok)


def key(a):
    return a if a == WAIT else (a[0], a[1])


def rollout(s, a, ends, t):
    """Time from now until the order is done if the agent takes `a` and the PLC's own
    policy decides everything after it (nominal times for the jobs it starts)."""
    ends = dict(ends)
    if a != WAIT:
        s = start(s, a)
        ends[a] = t + dur(a)
    else:
        if not s["run"]:
            return 1e4
    first = True
    while True:
        if not first:
            s = C.dispatch(s, FALLBACK)
            for j in s["run"]:
                ends.setdefault(j, t + dur(j))
        first = False
        if not s["run"]:
            return (t if C.goal(s) else 1e4) - T0[0]
        j = min(s["run"], key=lambda q: (ends[q], repr(q)))
        t = ends.pop(j)
        s = C.complete(s, j, AGENT)


T0 = [0.0]


def value(Q, f, s, a, ends, t):
    """Q, initialised on first sight from the PLC rollout (negative time still to go)."""
    k = (f, key(a))
    if k not in Q:
        T0[0] = t
        Q[k] = -rollout(s, a, ends, t)
    return Q[k]


# ------------------------------------------------------------------- episodes
def episode(Q, rng, eps, shield=True, learn=True, spread=SPREAD, record=False):
    """One order. Returns (makespan or None if deadlocked, shield interventions, bars)."""
    s, t, ends, blocked, bars = C.initial(), 0.0, {}, 0, []
    prev = None                               # (state key, action key, time) awaiting its target
    while True:
        # decision phase: the agent may start several jobs at the same instant
        while True:
            opts, b = allowed(s, shield)
            blocked += b
            if not opts:
                break
            f = C._freeze(s)
            if learn and rng.random() < eps:
                a = rng.choice(opts)
            else:
                a = max(opts, key=lambda o: value(Q, f, s, o, ends, t))
            if learn and prev is not None:
                pf, pa, pt = prev
                target = -(t - pt) + GAMMA * max(value(Q, f, s, o, ends, t) for o in opts)
                Q[(pf, pa)] += ALPHA * (target - Q[(pf, pa)])
            prev = (f, key(a), t)
            if a == WAIT:
                break
            s = start(s, a)
            d = dur(a) * (1 + rng.uniform(-spread, spread))
            ends[a] = t + d
            if record:
                bars.append({"job": a[0], "bind": [str(x) for x in a[1]], "units": list(a[2]), "t0": round(t, 2), "t1": round(t + d, 2)})
        if not s["run"]:
            done = C.goal(s)
            if learn and prev is not None:
                pf, pa, pt = prev
                final = -(t - pt) + (0.0 if done else -2000.0)        # a deadlock costs far more than any order
                Q[(pf, pa)] += ALPHA * (final - Q[(pf, pa)])
            return (round(t, 1) if done else None), blocked, bars
        job = min(s["run"], key=lambda j: (ends[j], repr(j)))
        t = ends.pop(job)
        s = C.complete(s, job, AGENT)
        if C.invariants(s):
            return None, blocked, bars


def fixed(pol, rng, spread=SPREAD):
    """A PLC policy on the same kind of random job times."""
    s, t, ends = C.dispatch(C.initial(), pol), 0.0, {}

    def new(s, t):
        for j in s["run"]:
            if j not in ends:
                ends[j] = t + dur(j) * (1 + rng.uniform(-spread, spread))
    new(s, t)
    while s["run"]:
        job = min(s["run"], key=lambda j: (ends[j], repr(j)))
        t = ends.pop(job)
        s = C.dispatch(C.complete(s, job, pol), pol)
        new(s, t)
    return round(t, 1) if C.goal(s) else None


def compare():
    """Paired on identical job times: the rollout scheduler against the PLC's policy, run by run
    (the rollout scheduler needs no training, so this can be re-run on its own)."""
    runs = [(episode({}, random.Random(1000 + k), 0.0, learn=False)[0], fixed(FALLBACK, random.Random(1000 + k)))
            for k in range(EVAL_RUNS)]
    diffs = [round(a - b, 2) for a, b in runs if a is not None and b is not None]
    return {"runs": len(diffs), "wins": sum(d < 0 for d in diffs), "ties": sum(abs(d) < 0.05 for d in diffs),
            "mean_diff_s": round(sum(diffs) / len(diffs), 2), "worst_diff_s": max(diffs), "best_diff_s": min(diffs),
            "diffs": diffs}


def stats(xs):
    ok = [x for x in xs if x is not None]
    return {"runs": len(xs), "deadlocks": len(xs) - len(ok), "mean": round(sum(ok) / len(ok), 1) if ok else None,
            "min": min(ok) if ok else None, "max": max(ok) if ok else None}


def main():
    t0 = time.time()
    rng = random.Random(SEED)
    Q = {}
    curve = []
    for ep in range(EPISODES):
        eps = EPS0 + (EPS1 - EPS0) * ep / EPISODES
        m, b, _ = episode(Q, rng, eps)
        curve.append({"episode": ep + 1, "makespan": m, "blocked": b})
    train_s = round(time.time() - t0, 1)
    # the same agent without the shield: how often it deadlocks while it learns
    Qu, ru = {}, random.Random(SEED)
    unshielded = []
    for ep in range(EPISODES // 3):
        eps = EPS0 + (EPS1 - EPS0) * ep / (EPISODES // 3)
        m, _, _ = episode(Qu, ru, eps, shield=False)
        unshielded.append(m)
    # evaluation: greedy, on fresh random job times, against the PLC's policies on the same seeds
    ev = {}
    for name, run in [("learned (shielded)", lambda r: episode(Q, r, 0.0, learn=False)[0]),
                      ("rollout, no learning", lambda r: episode({}, r, 0.0, learn=False)[0])] + \
            [(p, partial(fixed, p)) for p in ("single", "reuse", "buffer", "prefetch")]:
        ev[name] = stats([run(random.Random(1000 + k)) for k in range(EVAL_RUNS)])
    nominal = {"learned (shielded)": episode(Q, random.Random(0), 0.0, learn=False, spread=0.0)[0],
               "rollout, no learning": episode({}, random.Random(0), 0.0, learn=False, spread=0.0)[0]}
    for p in ("single", "reuse", "buffer", "prefetch"):
        nominal[p] = fixed(p, random.Random(0), spread=0.0)
    for k in ev:
        ev[k]["nominal"] = nominal[k]
    paired = compare()
    _, _, bars = episode({}, random.Random(0), 0.0, learn=False, spread=0.0, record=True)
    plc_bars = C.simulate(FALLBACK)[0]
    crane = {"rollout": round(sum(b["t1"] - b["t0"] for b in bars if "crane" in b["units"]), 1),
             "plc": round(sum(b["t1"] - b["t0"] for b in plc_bars if "crane" in b["units"]), 1)}
    slots = {"rollout": [(b["job"], b["bind"]) for b in bars if b["job"] in ("store", "retrieve", "fetch_empty", "store_retrieve")],
             "plc": [(b["job"], b["bind"]) for b in plc_bars if b["job"] in ("store", "retrieve", "fetch_empty", "store_retrieve")]}
    win = [c["makespan"] for c in curve if c["makespan"] is not None]
    out = {
        "meta": {"episodes": EPISODES, "spread": SPREAD, "alpha": ALPHA, "eps": [EPS0, EPS1], "eval_runs": EVAL_RUNS,
                 "q_entries": len(Q), "train_s": train_s, "fallback": FALLBACK,
                 "shield_states_explored": STATS["explored"], "shield_checks": STATS["checked"],
                 "method": "tabular Q-learning over the PLC's job choices; shield = the fallback policy can take over and "
                           "finish under every completion order (exhaustive, memoised)",
                 "limits": "simulated job times (+-20 % around the plant model); one order of 12 cookies"},
        "curve": [{"episode": c["episode"], "makespan": c["makespan"], "blocked": c["blocked"]} for c in curve],
        "unshielded": {"episodes": len(unshielded), "deadlocks": sum(1 for m in unshielded if m is None),
                       "first_deadlock_free_from": next((i + 1 for i in range(len(unshielded))
                                                         if all(m is not None for m in unshielded[i:])), None)},
        "eval": ev, "paired": paired, "crane_busy_s": crane, "crane_jobs": slots, "gantt": bars, "gantt_plc": plc_bars,
        "units": list(C.UNITS),
        "best_training": min(win) if win else None,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w"), separators=(",", ":"))
    print(f"trained {EPISODES} episodes in {train_s} s; Q {len(Q)} entries; shield explored {STATS['explored']} states, "
          f"{STATS['checked']} checks; training deadlocks: {sum(1 for c in curve if c['makespan'] is None)}")
    print(f"unshielded: {out['unshielded']['deadlocks']} deadlocks in {len(unshielded)} episodes")
    for k, v in ev.items():  # noqa: B007
        print(f"  {k:20s} nominal {v['nominal']}  random: mean {v['mean']} [{v['min']}, {v['max']}]  deadlocks {v['deadlocks']}/{v['runs']}")
    print(f"paired vs {FALLBACK}: {paired}; crane busy {crane}")
    fails = []
    if any(c["makespan"] is None for c in curve):
        fails.append("SHIELD: a shielded training episode deadlocked")
    if ev["learned (shielded)"]["deadlocks"]:
        fails.append("SHIELD: the learned policy deadlocked in evaluation")
    print("\n".join(fails) if fails else "SCHED OK (the shielded agent never deadlocked)")
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
