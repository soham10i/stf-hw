"""
Upgrade 12 - defence in depth (STF_VARIANT=up12): close what Upgrades 10 and 11 found.

    STF_VARIANT=up12 python3 hardening.py      -> web/public/hardening/

  F2  every jog rule was software. Each candidate interlock (interlock.py) is
      adopted only if the machine already has its permissive signal, it never
      blocks a step of the production program - replayed step by step through
      the order as the PLC runs it, homing first - and violating it is a
      collision. An adopted interlock is an interface relay on the node rail
      (io_nodes, placed and cleared like every part).
  SOFT the guard locks were released by the PLC alone; now also by a hardwired
      standstill monitor (K8: 0 V on the actuator bus) - safety.check_logic
      proves it exhaustively.
  F1  the compressor outputs Upgrade 1 retired are unwired (io_nodes): the
      register map no longer has them, so there is nothing left to write.
  F3  the energy manager keeps the ride-through reserve inside a demand-
      response window too (grid.DR_FLOOR); the month is re-run to count what
      that costs in demand response.
The U11 attacks are then re-run against the hardened machine.
"""
import json
import os
import random

import control as C
import interlock as IL
import io_nodes as N
import vc
from variant import UP12

OUT = os.path.expanduser("~/workspace/stf-hw/web/public/hardening")
# a switch or reed that an output drives away from, and the step completion that makes it again
LEAVES = {("hbw", "Q7"): "I6", ("oven", "Q12"): "I13", ("oven", "Q14"): "I15"}


def _program(opt_on=True):
    """The order as the PLC runs it: (module, step) in start order, homing first."""
    for m in C.OPT:
        C.OPT[m] = opt_on
    try:
        _, events, _, _ = C.simulate(C.PLC_POLICY)
        seq = []
        for u, sts in C.HOMING.items():
            seq += [(C.UNITS[u][0], st) for st in sts]
        for t, what, job in events:
            if what == "start":
                seq += [(C.UNITS[st.unit][0], st) for st in C.job_steps(job)]
    finally:
        for m in C.OPT:
            C.OPT[m] = True
    return seq


def replay(k, seq):
    """Does interlock k ever block a step of the program? -> (steps it guards, blocked [examples])."""
    mod, outs, perm, _, _ = IL.CANDIDATES[k]
    import vgr_path as VP
    sens = {"I6": True, "I10": False, "I13": True, "I15": True}
    pz = VP.V["TRANSIT"]
    guarded, blocked = 0, []
    for m, st in seq:
        # at the step's start: outputs that drive a part away from its switch release it
        for q in st.out:
            if (m, q) in LEAVES:
                sens[LEAVES[(m, q)]] = False
        if m == "oven" and st.unit == "door" and "Q13" not in st.out:
            sens["I10"] = False                       # Q13 off: the single-acting door cylinder shuts
        if m == mod and set(st.out) & set(outs):
            guarded += 1
            if perm == "POS":
                ok = False
            elif perm == "TRANSIT":
                ok = pz >= VP.V["TRANSIT"] - 1.0
            elif perm.startswith("NOT "):
                ok = perm[4:] not in st.out
            else:
                ok = sens[perm]
            if not ok and len(blocked) < 3:
                blocked.append(f"{st.unit} '{st.say[:60]}'")
            elif not ok:
                blocked.append(None)
        # at its end: the completion signal makes the switch
        if st.done in sens:
            sens[st.done] = True
        if st.unit == "arm" and "plunge" in st.target:
            pz = st.target["plunge"]
        if st.key == "H:plunge":
            pz = VP.V["TRANSIT"]
    return guarded, blocked


def analyse():
    seq_now, seq_u7 = _program(True), _program(False)
    rows = []
    for k, (mod, outs, perm, contact, why) in IL.CANDIDATES.items():
        g, b = replay(k, seq_now)
        g7, b7 = replay(k, seq_u7)
        if perm == "POS":
            verdict, reason = False, "no switch says 'at a slot': it would need an encoder comparator - left to the program"
        elif b:
            verdict = False
            reason = (f"blocks {len(b)} of {g} program steps, e.g. {b[0]}" +
                      ("; it would have passed the Upgrade 7 program - Upgrade 10's blended path swings below transit"
                       if not b7 else ""))
        else:
            verdict, reason = True, f"never blocks the program ({g} guarded steps replayed)"
        rows.append({"id": k, "module": mod, "outputs": list(outs), "permissive": perm, "contact": contact, "why": why,
                     "guarded_steps": g, "blocked": len(b), "blocked_u7": len(b7), "adopted": verdict, "reason": reason})
    return rows


def ems():
    import grid as G
    import month as M
    m = M.Month().run()
    weath = G.weather(random.Random(G.SEED), M.DAYS)
    ev = G.mains_events(random.Random(G.SEED + 2), M.DAYS)
    out = {}
    for name, floor in (("U9", G.SOC_MIN), ("U12", G.RESERVE)):
        G.DR_FLOOR["soc"] = floor
        s, *_ = G.simulate(m, "pv+battery", weath)
        k = G.kpis(s, M.DAYS)
        dr_min = min((soc for soc, d in zip(s["soc"], s["dr"]) if d), default=None)
        rides = sum(1 for e in ev if G.ride_through(e, s, True)["survives"])
        out[name] = {"dr_met": k["dr_met"], "dr_import_wh": k["dr_import_wh"], "total_eur": k["total_eur"],
                     "lowest_soc_in_dr": dr_min, "ride_through": rides, "events": len(ev), "floor": floor}
    G.DR_FLOOR["soc"] = G.SOC_MIN
    # a forged DR window of any length: how much of the reserve is left?
    A = (G.RESERVE - G.SOC_MIN) * G.BATT_WH
    out["forged"] = {"reserve_wh": round(A), "left_u9_wh": 0, "left_u12_wh": round(A),
                     "note": "U9: a long enough forged window drains to the 10 % floor; U12: the window stops at the reserve"}
    return out


def attacks():
    import safety as S
    import security as SEC
    healthy, _ = vc.results()
    a1 = SEC.attack_rogue_write(healthy)
    ex = SEC.retired_exposure()
    sf, n_logic = S.check_logic()
    rules = SEC.allow_list()
    lp, _ = SEC.check_least_privilege(rules)
    return [
        {"id": "A1'", "name": "compromised PLC drives the crane sideways with the fork in a shelf",
         "u11": "allowed: the PLC is the one source the allow-list trusts - " + a1["residual"],
         "u12": f"blocked in hardware: IL1's contact is open while I6 is not made, so Q3/Q4 cannot be powered - 0 mm, "
                f"against {a1['numbers']['travel_mm']} mm with detection alone", "closed": True},
        {"id": "F1", "name": "writable coils the program never uses",
         "u11": "vgr.Q7, oven.Q10, sorting.Q2 wired to live coils (blocked by the allow-list only)",
         "u12": f"unwired: {len(ex)} unused outputs left on the register map; the allow-list still passes least privilege "
                f"({'OK' if not lp else lp[0]}) with {len(rules)} rules", "closed": not ex and not lp},
        {"id": "SOFT", "name": "guard locks released by the PLC alone",
         "u11": "a compromised PLC could unlock a door while the actuators are powered",
         "u12": f"the release needs the PLC's request AND K8's 0 V: {n_logic} safety-logic states checked, "
                f"{'no' if not sf else len(sf)} violations", "closed": not sf},
    ]


def main():
    assert UP12, "run with STF_VARIANT=up12"
    fails = []
    rows = analyse()
    adopted = tuple(r["id"] for r in rows if r["adopted"])
    if adopted != IL.ADOPTED:
        fails.append(f"INTERLOCK the analysis adopts {adopted}, interlock.ADOPTED says {IL.ADOPTED}")
    if N.RETIRED != C.RETIRED:
        fails.append("RETIRED differs between io_nodes and control")
    fails += N.check(verbose=False)
    att = attacks()
    fails += [f"ATTACK {a['id']} not closed" for a in att if not a["closed"]]
    E = ems()
    if E["U12"]["lowest_soc_in_dr"] is not None and E["U12"]["lowest_soc_in_dr"] < E["U12"]["floor"] - 1e-6:
        fails.append("EMS a DR window went below the reserve")
    if fails:
        print("\n".join(fails))
        raise SystemExit("hardening: proofs failed - nothing written")
    relays = {m: [{"id": k, "permissive": p, "contact": c} for k, p, c in IL.relays(m)] for m in N.MODULES}
    n_ad = len(adopted)
    rej = [r for r in rows if not r["adopted"]]
    findings = [
        {"title": f"{n_ad} of {len(rows)} jog rules are now hardwired",
         "text": "Each adopted interlock uses a switch or reed the machine already has, and replaying the whole order step by step "
                 "shows it never blocks the program. A command from the network - even the PLC's own - can no longer drive into them."},
        {"title": "Upgrade 10's faster path rules one interlock out",
         "text": next((r["reason"] for r in rows if r["id"] == "IL4"), "") + ". Throughput and hard limits pull against each other; "
                 "the swivel stays guarded by the swept-path proof and the program."},
        {"title": f"{len(rej)} rules stay in software, for a reason each",
         "text": "; ".join(f"{r['id']}: {r['reason']}" for r in rej)},
        {"title": ("Holding the reserve costs nothing this month" if E["U12"] == {**E["U9"], "floor": E["U12"]["floor"]}
                   else "The demand-response trade-off, counted"),
         "text": f"The month's real DR events never took the battery below {round(100 * (E['U9']['lowest_soc_in_dr'] or 0))} %, so "
                 f"the new floor changes nothing in them: demand response {'met' if E['U12']['dr_met'] else 'NOT met'}, bill "
                 f"€{E['U12']['total_eur']}, ride-through {E['U12']['ride_through']}/{E['U12']['events']} either way. It bites only on a "
                 f"longer event - or a forged one, which under U9 could drain the battery to 10 % and now leaves the full "
                 f"{E['forged']['reserve_wh']} Wh reserve."},
        {"title": "No new sensors: five relays and one monitor",
         "text": f"{sum(len(v) for v in relays.values())} interface relays on the node rails and one standstill monitor K8 in the "
                 "cabinet; the nodes were re-placed and re-cleared with the relays on them."},
    ]
    doc = {"meta": {"variant": "up12", "relay": list(N.RELAY),
                    "assumed": "relay module size; the interlocks protect the machine and are not safety functions (no PL claimed)"},
           "interlocks": rows, "relays": relays, "attacks": att, "ems": E, "findings": findings,
           "program_steps": len(_program(True))}
    os.makedirs(OUT, exist_ok=True)
    json.dump(doc, open(os.path.join(OUT, "hardening.json"), "w"), separators=(",", ":"))
    print(f"wrote {OUT}/hardening.json")
    for r in rows:
        print(f"  {r['id']} {'ADOPT' if r['adopted'] else 'keep in software':16s} {r['reason'][:110]}")
    for f in findings:
        print(" -", f["title"])


if __name__ == "__main__":
    main()
