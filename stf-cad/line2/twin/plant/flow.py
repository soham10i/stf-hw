"""
DT-3b: the product flow inside the live plant - line_sim's own event engine, advanced in step with machine time.

line_sim.flow() is the proven flow model (sim_results.json) as a generator of events. This driver runs it a little
ahead (LOOK s of machine time) into a time-ordered queue and releases each event when the plant's machine time tau
reaches it. Nothing here decides anything about the product: every decision (which cookie, which puck, QC verdict,
kick, pick, pack, cassette, AMR) is line_sim's; the plant turns them into motion, sensors and the oven's load.

State it keeps (for frames, sensors, the dashboard):
  pucks      pk -> cookie id on that puck
  band       cookie id -> (row, col, flavour, topped) while on the band (deposit .. load / band_lost)
  rows       row -> 'deposited' | 'starved' | 'throttled'
  stock      dough kg, topping kg per flavour (from the deposit events), reject drawer count, boxes per lane
  lanes      packs sealed per lane, cassettes out
  amr        robot -> busy until / batch
  log        cookie id -> its genealogy (the NFC bake log): deposit, load, qc, kick | pick, pack lane, flags
"""
import heapq
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LINE2 = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, LINE2)
import line_sim as LS                                       # noqa: E402

LOOK = 10.0                                                 # s of machine time the engine runs ahead
CLOCKED = {"deposit", "starved", "throttled", "band_lost", "grip_fail", "load", "recirc", "qc", "kick", "kick_fail",
           "kick_blocked", "missed"}                        # kinds reported at the engine's own processing time


class Flow:
    def __init__(self, scenario="nominal_1h", seed=7, horizon=None):
        kw = {} if horizon is None else dict(horizon=horizon)
        self.gen = LS.flow(scenario, seed, **kw)
        self.scenario, self.seed = scenario, seed
        self.q, self.seq = [], 0
        self.frontier = -1e18                               # machine time the engine has processed up to
        self.kpi = None                                     # line_sim's KPIs once the horizon is reached
        self.pucks, self.band, self.rows, self.log = {}, {}, {}, {}
        self.dough, self.topping = LS.L["DOUGH_KG"], {f: LS.L["TOP_KG"] for f in LS.F}
        self.drawer, self.packs, self.cassettes_out = 0, {f: 0 for f in LS.F}, {f: 0 for f in LS.F}
        self.amr = {}
        self.released = []                                  # (t, kind, data) in release order - the audit trail
        self.counts = {}

    def _pull(self, upto):
        while self.kpi is None and self.frontier < upto:
            try:
                t, kind, data = next(self.gen)
            except StopIteration as e:
                self.kpi = e.value
                break
            if kind in CLOCKED:
                self.frontier = max(self.frontier, t)
            if kind == "exchange":
                t = data["start"]                           # the exchange begins when the robot and the lane are ready
            self.seq += 1
            heapq.heappush(self.q, (t, self.seq, kind, data))

    def release(self, tau):
        """Events with t <= tau, applied to the state, in time order. Returns them (the plant acts on kick / pack /
        exchange)."""
        self._pull(tau + LOOK)
        out = []
        while self.q and self.q[0][0] <= tau + 1e-9:
            t, _, kind, data = heapq.heappop(self.q)
            self._apply(t, kind, data)
            self.released.append((t, kind, data))
            self.counts[kind] = self.counts.get(kind, 0) + 1
            out.append((t, kind, data))
        return out

    def _apply(self, t, kind, d):
        lg = self.log
        if kind == "deposit":
            self.rows[d["row"]] = "deposited"
            for c in d["cookies"]:
                self.band[c["id"]] = (d["row"], c["col"], c["flav"], c["topped"])
                lg[c["id"]] = dict(id=c["id"], row=d["row"], col=c["col"], flav=c["flav"], topped=c["topped"],
                                   deposit=t, pre=d["pre"], events=[("deposit", t)])
            self.dough, self.topping = d["dough"], dict(d["topping"])
        elif kind in ("starved", "throttled"):
            self.rows[d["row"]] = kind
        elif kind == "band_lost":
            self.band.pop(d["id"], None)
            lg[d["id"]]["events"].append(("band_lost", t))
            lg[d["id"]]["end"] = "band_lost"
        elif kind == "load":
            self.band.pop(d["id"], None)
            self.pucks[d["pk"]] = d["id"]
            e = lg[d["id"]]
            e.update(puck=d["pk"], defect=d["defect"], load=t)
            e["events"].append(("load", t))
        elif kind == "qc":
            lg[d["id"]]["qc"] = d["verdict"]
            lg[d["id"]]["events"].append(("qc", t))
        elif kind == "kick":
            self.pucks.pop(d["pk"], None)
            self.drawer = d["drawer"]
            lg[d["id"]]["events"].append(("kick", t))
            lg[d["id"]]["end"] = "rejected"
        elif kind == "pick":
            self.pucks.pop(d["pk"], None)
            e = lg[d["id"]]
            e.update(lane=d["lane"], delta="AB"[d["d"]], pick=t)
            e["events"].append(("pick", t))
            e["end"] = "packed"
        elif kind == "pack":
            self.packs[d["lane"]] += 1
        elif kind == "cassette_out":
            self.cassettes_out[d["lane"]] += 1
        elif kind == "amr_go":
            self.amr[d["robot"]] = dict(busy_until=d["done"], batch=d["batch"])
            for b in d["batch"]:
                if b[0] == "reject":
                    pass
        elif kind == "amr_done":
            self.amr[d["robot"]] = dict(busy_until=None, batch=[])
            for kind_, f in d["batch"]:
                if kind_ == "reject":
                    self.drawer = 0
                elif kind_ == "raw" and f == "dough":
                    self.dough = LS.L["DOUGH_KG"]
                elif kind_ == "raw":
                    self.topping[f] = LS.L["TOP_KG"]
        elif kind in ("recirc", "grip_fail", "kick_fail", "kick_blocked", "pick_fail", "missed"):
            if d.get("id") in lg:
                lg[d["id"]]["events"].append((kind, t))

    # ------------------------------------------------------------ what the plant draws
    def puck_cookie(self, pk):
        """(visible, flavour) of the cookie on puck pk."""
        cid = self.pucks.get(pk)
        return (cid is not None, self.log[cid]["flav"] if cid is not None else None)

    def band_cookie(self, row, col):
        """(on the band, topped) of the cookie of row / column."""
        if self.rows.get(row) != "deposited":
            return False, False
        for cid, (r, c, f, topped) in self._band_index().get(row, {}).items():
            if c == col:
                return True, topped
        return False, False

    def _band_index(self):
        idx = {}
        for cid, (r, c, f, topped) in self.band.items():
            idx.setdefault(r, {})[cid] = (r, c, f, topped)
        return idx

    def row_present(self):
        """{row: [cookie columns still on the band]} for the oven content."""
        out = {}
        for cid, (r, c, f, topped) in self.band.items():
            out.setdefault(r, []).append(c)
        return out
