"""
Flow simulation of the STF-2 continuous line with FINITE stock and an AMR fleet.

The chain NEVER stops: there is no stop path in this code, only losses. Every
puck passes every station at a time fixed by the master axis; each station
decides what to do with what passes it:

  feeder     loads the next flavour (heijunka W R B ...) into an EMPTY puck from
             that flavour's hopper + A/B tube buffer; a full puck (recirculating)
             is skipped; no raw stock -> the slot stays empty (starvation loss).
  oven       bakes; a cookie that passes a second time is burnt.
  QC         vision + colour + NFC verdict (recall / false-reject rates).
  kicker     drops flagged cookies through the deck into the reject drawer
             (drawer full -> it cannot, the reject recirculates and burns).
  delta A/B  tracking pickers: A first, B catches what A could not. A pick needs
             the delta up and free, inside its window, an empty box and a cassette
             that can take the pack.
  cassettes  bottom-up stacker fills the ACTIVE cassette; when full the shuttle
             swaps in the STANDBY (if empty) and the full one waits for the AMR;
             if the standby is still full the lane is blocked.
  AMR fleet  finite robots; every buffer raises a task with a DEADLINE (the
             autonomy it has left); earliest deadline first; one visit to a port
             serves every pending task at that port.

Scenarios: 1 h picker scenarios and 8 h shift scenarios for the stock/AMR loop.
"""
import heapq
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import line_model as M

L = M.L
F = M.FLAV
PORT = {"raw": "front", "reject": "front", "cassette": "right", "boxes": "left"}


def stations():
    c, _ = M.delta_window(L["DELTA_X"][0])
    st = {
        "feed": M.s_front(sum(L["MAG_X"]) / len(L["MAG_X"])),
        "oven": M.s_front(M.oven_x()[1]),
        "stamp": M.s_front(L["STAMP_X0"]),
        "qc": M.s_back(L["CAM_X"]),
        "kick": M.s_back(L["KICK_X"]),
    }
    for i, xd in enumerate(L["DELTA_X"]):
        sc = M.s_back(xd)
        st[f"d{i}_in"] = sc - c / 2
        st[f"d{i}_out"] = sc + c / 2
    return st


H1, H8 = 3600.0, 8 * 3600.0
SCENARIOS = {
    "nominal_1h": {},
    "delta_A_down_10min": {"down": {0: [(900.0, 1500.0)]}},
    "both_deltas_down_2min": {"down": {0: [(1200.0, 1320.0)], 1: [(1200.0, 1320.0)]}},
    "both_deltas_down_10min": {"down": {0: [(1200.0, 1800.0)], 1: [(1200.0, 1800.0)]}},
    "both_deltas_down_10min_AGENT": {"down": {0: [(1200.0, 1800.0)], 1: [(1200.0, 1800.0)]}, "policy": "agent"},
    "shift_2_AMR": {"horizon": H8},
    "shift_1_AMR": {"horizon": H8, "n_amr": 1},
    "shift_2_AMR_one_down_2h": {"horizon": H8, "amr_down": {0: [(7200.0, 14400.0)]}},
    "shift_fleet_down_15min": {"horizon": H8, "amr_down": {0: [(10800.0, 11700.0)], 1: [(10800.0, 11700.0)]}},
    "shift_fleet_down_45min": {"horizon": H8, "amr_down": {0: [(10800.0, 13500.0)], 1: [(10800.0, 13500.0)]}},
    "shift_no_AMR": {"horizon": H8, "n_amr": 0},
}
RATES = dict(p_defect=0.03, recall=0.98, false_reject=0.01, kick_ok=0.999)


def run(name="nominal_1h", seed=7, **kw):
    sc = {**SCENARIOS.get(name, {}), **kw}
    horizon = sc.get("horizon", H1)
    rnd = random.Random(seed)
    T, Lp, v, P = M.takt(), M.loop_len(), L["V"], L["PITCH"]
    rf = M.rate_flavour()
    st = stations()
    down = sc.get("down", {})
    amr_down = sc.get("amr_down", {})
    n_amr = sc.get("n_amr", L["N_AMR"])
    policy = sc.get("policy", "naive")

    def up(d, t0, t1, table=None):
        table = down if table is None else table
        return all(not (a < t1 and t0 < b) for a, b in table.get(d, []))

    raw = {f: M.hopper_cap() + 2 * L["MAG_CAP"] for f in F}
    raw_cap = dict(raw)
    boxes = {f: L["BOXMAG_CAP"] for f in F}
    active = {f: 0 for f in F}
    standby_full = {f: False for f in F}
    box_fill = {(f, d): 0 for f in F for d in (0, 1)}
    lane_block = {f: 0.0 for f in F}
    rej = {"lvl": 0}
    reject_cap = M.reject_cap()
    ccap = M.cass_cap()
    tasks = {}
    amr_free = [0.0] * n_amr
    amr_busy_s = [0.0] * n_amr
    pending_done = []
    late = []

    def request(kind, f, deadline):
        if (kind, f) not in tasks:
            tasks[(kind, f)] = deadline

    lock = L.get("AIRLOCK")
    staged = {f: None for f in F}          # airlock: (time the robot is ready at the out port, robot)
    waiting = {f: None for f in F}         # airlock: time the cassette became full with no robot there
    called = {f: False for f in F}         # airlock: a robot is already called for this lane's exchange
    exch_end = {f: None for f in F}        # airlock: the exchange in progress ends at this time
    if lock and L.get("CASS_STAGGER"):     # policy: lanes a third of a fill apart
        for j, f in enumerate(F):
            active[f] = j * ccap // len(F)
    buf = M.transfer_buffer()
    swap_t = M.cass_swap_t()
    pack_s = L["PACK"] / rf

    def dispatch(t):
        while tasks:
            free = [i for i in range(n_amr) if amr_free[i] <= t and up(i, t, t + 1, amr_down)]
            if not free:
                return
            i = free[0]
            (kind, f), _ = min(tasks.items(), key=lambda kv: kv[1])
            batch = [kk for kk in tasks if PORT[kk[0]] == PORT[kind]]
            # airlock: the handling at the out port IS the exchange, booked when it happens
            dur = L["AMR_TRIP"] + L["AMR_HANDLE"] * sum(1 for kk in batch if not (lock and kk[0] == "cassette"))
            done = t + dur
            for kk in batch:
                late.append(max(0.0, done - tasks[kk]))
                del tasks[kk]
            amr_free[i] = done
            amr_busy_s[i] += dur
            heapq.heappush(pending_done, (done, batch, i))

    def complete(t):
        while pending_done and pending_done[0][0] <= t:
            done, batch, i = heapq.heappop(pending_done)
            for kind, f in batch:
                if kind == "cassette" and lock:
                    staged[f] = (done, i)               # robot at the port with an empty, held there
                    amr_free[i] = float("inf")
                    continue
                if kind == "raw":
                    raw[f] = min(raw_cap[f], raw[f] + L["RAW_TOTE"])
                elif kind == "boxes":
                    boxes[f] = L["BOXMAG_CAP"]
                elif kind == "cassette":
                    standby_full[f] = False
                elif kind == "reject":
                    rej["lvl"] = 0

    def swap_if_possible(f, t):
        if lock:
            if exch_end[f] is not None and t >= exch_end[f]:      # new cassette in: the waiting packs go up
                active[f] -= ccap
                exch_end[f] = None
                called[f] = False
                k["cassettes_out"][f] += 1
            if active[f] >= ccap and exch_end[f] is None and staged[f] is not None:
                t0, i = staged[f]
                start = max(t0, t)
                end = start + swap_t
                exch_end[f] = end
                amr_busy_s[i] += end - t0
                amr_free[i] = end
                staged[f] = None
            if active[f] >= ccap and not called[f]:             # full and nobody called (should not happen)
                called[f] = True
                request("cassette", f, t)
            return
        if active[f] >= ccap and not standby_full[f]:
            active[f] = 0
            standby_full[f] = True
            k["cassettes_out"][f] += 1
            lane_block[f] = max(lane_block[f], t + L["SWAP_T"])
            request("cassette", f, t + ccap * L["PACK"] / rf)

    puck = [None] * L["N"]
    seq = [f for f, m in zip(F, L["MIX"]) for _ in range(m)]
    seq_i = 0
    busy = [0.0, 0.0]
    k = dict(loaded=0, packed={f: 0 for f in F}, rejected=0, burnt=0, escapes=0, recirc=0, empty_slots=0,
             starved_raw=0, blocked_cassette=0, blocked_boxes=0, reject_overflow=0,
             cassettes_out={f: 0 for f in F}, picks=[0, 0], stops=0, missed_pick_windows=0,
             false_rejects=0, throttled=0)
    ss_from = 600.0
    ss_packed = 0

    ev = []
    order = ["feed", "oven", "stamp", "qc", "kick", "d0_in", "d1_in"]
    for pk in range(L["N"]):
        for so, sname in enumerate(order):
            t0 = ((st[sname] - pk * P) % Lp) / v
            n = 0
            while t0 + n * Lp / v < horizon:
                heapq.heappush(ev, (t0 + n * Lp / v, so, pk, sname))
                n += 1

    while ev:
        t, _, pk, sname = heapq.heappop(ev)
        complete(t)
        for f in F:
            swap_if_possible(f, t)
        dispatch(t)
        c = puck[pk]
        if sname == "feed":
            if c is not None:
                k["recirc"] += 1
                continue
            if policy == "agent" and not (up(0, t, t + 0.01) or up(1, t, t + 0.01)):
                k["throttled"] += 1
                k["empty_slots"] += 1
                continue
            f = seq[seq_i % len(seq)]
            if raw[f] <= 0:
                k["empty_slots"] += 1
                k["starved_raw"] += 1
                continue
            raw[f] -= 1
            if raw[f] <= L["REQ_HOPPER"] * raw_cap[f]:
                request("raw", f, t + raw[f] / rf)
            puck[pk] = dict(flav=f, oven=0, defect=rnd.random() < RATES["p_defect"], qc=None)
            seq_i += 1
            k["loaded"] += 1
        elif c is None:
            continue
        elif sname == "oven":
            c["oven"] += 1
        elif sname == "qc":
            bad = c["defect"] or c["oven"] > 1
            if bad:
                c["qc"] = "reject" if rnd.random() < RATES["recall"] else "pass"
            else:
                c["qc"] = "reject" if rnd.random() < RATES["false_reject"] else "pass"
                if c["qc"] == "reject":
                    k["false_rejects"] += 1
        elif sname == "kick":
            if c["qc"] == "reject":
                if rej["lvl"] >= reject_cap:
                    k["reject_overflow"] += 1
                    continue
                if rnd.random() < RATES["kick_ok"]:
                    k["rejected"] += 1
                    k["burnt"] += c["oven"] > 1
                    puck[pk] = None
                    rej["lvl"] += 1
                    if rej["lvl"] >= L["REQ_REJECT"] * reject_cap:
                        request("reject", "-", t + (reject_cap - rej["lvl"]) / (0.05 / T))
        elif sname in ("d0_in", "d1_in"):
            d = int(sname[1])
            if c["qc"] != "pass":
                continue
            f = c["flav"]
            t_out = t + (st[f"d{d}_out"] - st[f"d{d}_in"]) / v
            start = max(t, busy[d], lane_block[f])
            can_pack = boxes[f] > 0 and (active[f] < ccap + buf if lock else
                                         not (active[f] >= ccap and standby_full[f]))
            if start + L["T_GRAB"] <= t_out and up(d, start, start + L["T_PICK"]) and can_pack:
                busy[d] = start + L["T_PICK"]
                if rnd.random() > L["PICK_OK"]:
                    continue
                puck[pk] = None
                k["picks"][d] += 1
                k["packed"][f] += 1
                if t >= ss_from:
                    ss_packed += 1
                k["escapes"] += c["defect"] or c["oven"] > 1
                box_fill[(f, d)] += 1
                if box_fill[(f, d)] >= L["PACK"]:
                    box_fill[(f, d)] = 0
                    boxes[f] -= 1
                    if boxes[f] <= L["REQ_BOXMAG"] * L["BOXMAG_CAP"]:
                        request("boxes", f, t + boxes[f] * L["PACK"] / rf)
                    lane_block[f] = busy[d] + L["T_INDEX"]
                    active[f] += 1
                    if lock and (ccap - active[f]) * pack_s <= L["CASS_LEAD"] and not called[f]:
                        called[f] = True
                        request("cassette", f, t + (ccap - active[f]) * pack_s)
                    swap_if_possible(f, t)
            elif d == 1:
                k["missed_pick_windows"] += 1
                if not can_pack:
                    k["blocked_boxes" if boxes[f] <= 0 else "blocked_cassette"] += 1
    theo = (horizon - ss_from) / T
    k.update(scenario=name, hours=horizon / 3600, stops=0,
             steady_state_per_h=round(ss_packed * 3600 / (horizon - ss_from), 1),
             theoretical_per_h=round(3600 / T, 1), line_efficiency=round(ss_packed / theo, 3),
             amr_util=[round(b / horizon, 2) for b in amr_busy_s],
             amr_max_late_min=round(max(late) / 60, 1) if late else 0.0, amr_tasks=len(late))
    return k


def main():
    res = {n: run(n) for n in SCENARIOS}
    for n, r in res.items():
        print(f"{n:30s} {r['hours']:.0f}h  eff {r['line_efficiency']:.2f} ({r['steady_state_per_h']:.0f}/h)  "
              f"burnt {r['burnt']:3d}  empty {r['empty_slots']:5d} (raw-starved {r['starved_raw']:5d})  "
              f"blocked cass/box {r['blocked_cassette']:4d}/{r['blocked_boxes']:4d}  "
              f"AMR tasks {r['amr_tasks']:3d} util {r['amr_util']} max-late {r['amr_max_late_min']} min  "
              f"STOPS {r['stops']}")
    json.dump(res, open(os.path.join(HERE, "sim_results.json"), "w"), indent=1)
    fails = []
    for nm in ("nominal_1h", "delta_A_down_10min", "shift_2_AMR", "shift_1_AMR", "shift_2_AMR_one_down_2h",
               "shift_fleet_down_15min"):
        if res[nm]["line_efficiency"] < 0.90:
            fails.append(f"{nm}: efficiency {res[nm]['line_efficiency']}")
    if any(r["stops"] for r in res.values()):
        fails.append("the chain stopped")
    fl = res["shift_fleet_down_15min"]
    loss = "without loss" if fl["burnt"] == 0 and fl["blocked_cassette"] == 0 else \
        f"at {fl['line_efficiency']:.0%} ({fl['blocked_cassette']} cookies recirculated past late cassette exchanges)"
    print("\n".join(fails) if fails else
          "SIM CLAIMS HOLD: never stops; one delta carries the line; ONE AMR carries an 8 h shift; the fleet may "
          f"vanish for 15 min {loss}; losses are counted, not hidden")
    return fails


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
