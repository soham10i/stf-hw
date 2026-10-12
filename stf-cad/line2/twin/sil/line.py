"""
DT-4b: the product side of the plant - the cookies, from the die to the lanes - for the compiled PLC's stations.

The plant is the physics and the luck; the PLC decides. What the PLC never knows in advance, the plant draws, with
line_sim's KEYED draws (line_sim.keyed: the same luck for the same cookie, whatever the order of the events):

  band      every row the depositor really cuts (SilPlant._cut) puts its cookies on the band (row = deposit index,
            the line_sim name); a cookie leaves the pick window at the nose ({travel}+{W} mm of band): lost
  delta C   a new stDeltaC job: the cup touches the cookie (band row fRowPos, column nCol) as the puck arrives (fStart):
            it must be in the window, the puck there and empty; it holds with P(PICK_OK) -> the cookie is in the puck
  pucks     on the loop at s = master + k x P (mod the loop); I1 = the puck at the transfer is full
  camera    a filled puck passing QC: the verdict (defect drawn at the load; recall / false reject), to the PLC
            (stQc) AI_LATENCY later, as the edge PC would
  kicker    a rising qQ18 with a puck at the kicker: the cookie leaves with P(kick_ok)
  delta A/B a new stDeltaX job: at fStart the cup touches the cookie of puck nPuck (it must be in reach, the PLC's
            cookie): it holds with P(PICK_OK); at fStart + T_PICK it is placed in lane nLane (the lane must stand)
  vacuum    ioldelta_X_VAC_P (mbar): VAC_HELD while a cup holds a cookie with its valve open, VAC_OPEN when open on
            nothing, 0 when closed
  lanes     an index move of axQ20..22 starting = a pack (MC_MoveRelative)

Everything that happened is in .log [(t, kind, data)], in line_sim's time (t = 0: line_sim's start); anything the PLC
asked that cannot physically happen is in .errors. Start: a hot oven, the line running, the band empty, timed so
the band's rows are cut where line_sim deposits them (r x t_row); the HMI starts production (xHmiLoad) at t = 0.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LINE2 = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, LINE2)
import line_model as M                                     # noqa: E402
import line_sim as LS                                      # noqa: E402
from twin.sil.plant import SilPlant                        # noqa: E402

L = M.L
VAC_HELD, VAC_OPEN = -620, -40                              # mbar: a sealed cup / an open cup on nothing [assumed]
DELTAS = ("C", "A", "B")


class Arrivals:
    """The pucks passing one loop position (the PLC's FB_Arrivals, here for the plant's sensors)."""

    def __init__(self, st, m):
        self.st, self.Lp, self.P, self.N = st, M.loop_len(), L["PITCH"], L["N"]
        self.next_k, self.next_m = min(((k, m + (st - k * self.P - m) % self.Lp) for k in range(self.N)),
                                       key=lambda x: x[1])
        self.last = None                                     # (puck, master mm) of the last arrival

    def advance(self, m):
        out = []
        while m >= self.next_m:
            out.append((self.next_k, self.next_m))
            self.last = (self.next_k, self.next_m)
            k = (self.next_k - 1) % self.N
            self.next_m = self.next_m + (self.st - k * self.P - self.next_m) % self.Lp
            self.next_k = k
        return out


class SilLine(SilPlant):
    def __init__(self, seed=7, lib=None):
        rows, takt = L["BAND"]["rows"], M.takt()
        self.V, self.Lp, self.P = L["V"], M.loop_len(), L["PITCH"]
        self.t_row = rows * takt
        self.vb = M.band_v()
        sb = M.stations()
        self.travel = sb["pick"][0] - sb["dep"]
        self.W = L["PICK_W"]
        r0 = -int(self.travel / self.vb // self.t_row) - 2   # line_sim's first row (on the band at its t = 0)
        self.r_s = r0 - 3                                    # start 3 rows earlier: the PLC needs 61 s to be ready
        t_s = self.r_s * self.t_row
        self.m_off = (math.ceil(-self.V * t_s / self.Lp) + 1) * self.Lp   # master = V t + m_off (> 0)
        self.KB = 100                                        # band = (row + KB) x pitch at the row's cut (> 0)
        pitch = self.vb * self.t_row
        super().__init__(lib=lib, running=(self.V * t_s + self.m_off, (self.r_s + self.KB) * pitch))
        self.st = LS.stations()
        m0 = self.ax["axMasterEnc"].pos
        self.trk = {k: Arrivals(self.st[k], m0) for k in ("transfer", "qc", "kick")}
        self.m_prev = m0
        self.band = []                                       # cookies in row order: dict(row, col, flav, cut)
        self.puck = [None] * L["N"]
        self.kd = LS.keyed(seed)
        self.tries = {}
        self.jobs = {d: [] for d in DELTAS}                  # accepted, not finished
        self.seen = {d: self.plc[f"sil_stDelta{d}_nJob"] for d in DELTAS}
        self.hold_ck = {d: None for d in DELTAS}             # the cookie a cup holds
        self.qc_seq, self.qc_out, self.qc_pending = 0, (0, 0), []
        self.kick_prev = 0
        self.lane_target = {a: None for a in ("axQ20", "axQ21", "axQ22")}
        self.log, self.errors = [], []
        self._inputs()

    # ------------------------------------------------------------ helpers
    def tl(self, m):
        """line_sim time of master position m."""
        return (m - self.m_off) / self.V

    def chance(self, kind, row, col, *more):
        k = (kind, row, col) + more
        n = self.tries.get(k, 0)
        self.tries[k] = n + 1
        return self.kd(*k, n)

    def s_of(self, pk, m):
        return (m + pk * self.P) % self.Lp

    def band_at(self, m):
        """band position at master position m (geared: band = ratio x master + offset)."""
        ax = self.ax["axQ40"]
        return ax.pos - (self.ax["axMasterEnc"].pos - m) * self.plc["sil_axQ40_Ratio"]

    def err(self, m, what):
        self.errors.append((round(self.tl(m), 3), what))

    # ------------------------------------------------------------ SilPlant hooks
    def _cut(self, pos):
        row = round(pos / self.pitch) - self.KB
        m = self.ax["axMasterEnc"].pos - (self.ax["axQ40"].pos - pos) / self.plc["sil_axQ40_Ratio"]
        self.log.append((self.tl(m), "deposit", dict(row=row)))       # when the band passed the cut
        for j in range(L["BAND"]["rows"]):
            self.band.append(dict(row=row, col=j, flav=M.row_flavour(j), cut=pos))

    def _inputs(self):
        super()._inputs()
        if not hasattr(self, "log"):                          # SilPlant.__init__ calls this before the line exists
            return
        p = self.plc
        last = self.trk["transfer"].last
        p["iI1"] = 1 if (last is not None and self.puck[last[0]] is not None) else 0
        for d in DELTAS:
            valve = p[f"qdelta_{d}_VAC"]
            p[f"ioldelta_{d}_VAC_P"] = 0 if not valve else (VAC_HELD if self.hold_ck[d] is not None else VAC_OPEN)
        p["sil_stQc_nSeq"], (p["sil_stQc_nPuck"], p["sil_stQc_nVerdict"]) = self.qc_seq, self.qc_out
        p["xHmiLoad"] = 1 if self.tl(self.ax["axMasterEnc"].pos) >= 0.0 else 0

    def _products(self):
        p = self.plc
        m_a, m_b = self.m_prev, self.ax["axMasterEnc"].pos
        ev = []
        for d in DELTAS:                                     # new jobs
            n = p[f"sil_stDelta{d}_nJob"]
            if n != self.seen[d]:
                self.seen[d] = n
                job = dict(d=d, puck=p[f"sil_stDelta{d}_nPuck"], col=p[f"sil_stDelta{d}_nCol"],
                           lane=p[f"sil_stDelta{d}_nLane"], row_pos=p[f"sil_stDelta{d}_fRowPos"],
                           start=p[f"sil_stDelta{d}_fStart"], state="new")
                self.jobs[d].append(job)
        for d in DELTAS:
            for job in self.jobs[d]:
                if job["state"] == "new" and job["start"] <= m_b:
                    ev.append((max(job["start"], m_a), 0, "grip", job))
                if job["state"] in ("new", "held", "empty") and job["start"] + L["T_GRAB"] * self.V <= m_b:
                    ev.append((job["start"] + L["T_GRAB"] * self.V, 1, "vac_check", job))
                if job["state"] in ("new", "held", "empty", "checked") and job["start"] + L["T_PICK"] * self.V <= m_b:
                    ev.append((job["start"] + L["T_PICK"] * self.V, 2, "place", job))
        for k, m in self.trk["qc"].advance(m_b):
            ev.append((m, 3, "camera", k))
        for pub in [x for x in self.qc_pending if x[0] <= m_b]:
            ev.append((pub[0], 4, "verdict", pub))
        ev.sort(key=lambda e: (e[0], e[1]))
        for m, _, kind, x in ev:
            getattr(self, "_" + kind)(m, x)
        for d in DELTAS:
            self.jobs[d] = [j for j in self.jobs[d] if j["state"] not in ("done",)]
        self.trk["transfer"].advance(m_b)
        self.trk["kick"].advance(m_b)
        if p["qQ18"] and not self.kick_prev:                 # the kicker fires
            self._kick(m_a)
        self.kick_prev = p["qQ18"]
        for i, a in enumerate(("axQ20", "axQ21", "axQ22")):  # a lane index starts: a pack
            if p[f"sil_{a}_Mode"] == 5 and p[f"sil_{a}_Target"] != self.lane_target[a]:
                self.lane_target[a] = p[f"sil_{a}_Target"]
                self.log.append((self.tl(m_a), "pack", dict(lane=i)))
        b = self.band_at(m_a)                                # past the nose: into the crumb pan
        while self.band and b - self.band[0]["cut"] >= self.travel + self.W:
            c = self.band.pop(0)
            self.log.append((self.tl(m_a), "band_lost", dict(row=c["row"], col=c["col"])))
        self.m_prev = m_b

    # ------------------------------------------------------------ events
    def _grip(self, m, job):
        d, pk = job["d"], job["puck"]
        t0 = self.tl(job["start"])
        if d == "C":
            ck = next((c for c in self.band if abs(c["cut"] - job["row_pos"]) < 1e-3 and c["col"] == job["col"]), None)
            if ck is None:
                job["state"] = "done"
                return self.err(m, f"C: no cookie at row {job['row_pos']:.1f} col {job['col']}")
            dist = self.band_at(job["start"]) - ck["cut"]
            if not (self.travel - 1e-6 <= dist < self.travel + self.W):
                self.err(m, f"C: cookie row {ck['row']} col {ck['col']} outside the window ({dist:.2f} mm)")
            off = (self.s_of(pk, job["start"]) - self.st["transfer"]) % self.Lp
            if min(off, self.Lp - off) > 0.25:
                self.err(m, f"C: puck {pk} not at the transfer")
            if self.puck[pk] is not None:
                self.err(m, f"C: puck {pk} is full")
            if self.chance("transfer", ck["row"], ck["col"]) > L["PICK_OK"]:
                job["state"] = "empty"
                return self.log.append((t0, "grip_fail", dict(pk=pk, row=ck["row"], col=ck["col"])))
            self.band.remove(ck)
            ck["defect"] = self.chance("defect", ck["row"], ck["col"]) < LS.RATES["p_defect"]
            self.puck[pk] = ck
            self.hold_ck[d] = ck
            job["state"] = "held"
            return self.log.append((t0, "load", dict(pk=pk, row=ck["row"], col=ck["col"])))
        ck = self.puck[pk]
        lo, hi = self.st[f"d{'AB'.index(d)}_in"], self.st[f"d{'AB'.index(d)}_out"]
        for mm in (job["start"], job["start"] + L["T_GRAB"] * self.V):
            if not (lo - 1e-6 <= self.s_of(pk, mm) <= hi + 1e-6):
                self.err(m, f"{d}: puck {pk} out of reach at {self.tl(mm):.2f} s")
        if ck is None or abs(ck["cut"] - job["row_pos"]) > 1e-3 or ck["col"] != job["col"]:
            job["state"] = "done"
            return self.err(m, f"{d}: puck {pk} does not hold the PLC's cookie")
        if self.chance("pick", ck["row"], ck["col"], "AB".index(d)) > L["PICK_OK"]:
            job["state"] = "empty"
            return self.log.append((t0, "pick_fail", dict(pk=pk, d="AB".index(d))))
        self.puck[pk] = None
        self.hold_ck[d] = ck
        job["state"] = "held"
        self.log.append((t0, "pick", dict(pk=pk, d="AB".index(d), lane=job["lane"], row=ck["row"], col=ck["col"])))

    def _vac_check(self, m, job):
        if job["state"] == "held" and not self.plc[f"qdelta_{job['d']}_VAC"]:
            self.err(m, f"{job['d']}: the cup holds a cookie but its valve is closed")
        job["state"] = "checked" if job["state"] == "held" else "done"

    def _place(self, m, job):
        d = job["d"]
        ck = self.hold_ck[d]
        job["state"] = "done"
        if ck is None:
            return
        self.hold_ck[d] = None
        if not self.plc[f"qdelta_{d}_VAC"]:
            return self.err(m, f"{d}: cookie dropped (valve closed before the place)")
        if d == "C":
            return
        lane = ("axQ20", "axQ21", "axQ22")[job["lane"]]
        if abs(self.ax[lane].vel) > 1e-9:
            self.err(m, f"{d}: placed into lane {job['lane']} while it indexes")
        self.log.append((self.tl(m), "place", dict(lane=job["lane"], d="AB".index(d))))

    def _camera(self, m, pk):
        ck = self.puck[pk]
        if ck is None:
            return
        bad = ck["defect"]
        u = self.chance("qc", ck["row"], ck["col"])
        rej = u < (LS.RATES["recall"] if bad else LS.RATES["false_reject"])
        self.log.append((self.tl(m), "qc", dict(pk=pk, verdict="reject" if rej else "pass")))
        self.qc_pending.append((m + L["AI_LATENCY"] * self.V, pk, 2 if rej else 1))

    def _verdict(self, m, pub):
        self.qc_pending.remove(pub)
        self.qc_seq = (self.qc_seq + 1) % 10000
        self.qc_out = (pub[1], pub[2])

    def _kick(self, m):
        last = self.trk["kick"].last
        if last is None or m - last[1] > 0.25:
            return self.err(m, "kicker fired with no puck in front of it")
        pk = last[0]
        ck = self.puck[pk]
        if ck is None:
            return self.err(m, f"kicker fired at the empty puck {pk}")
        if self.chance("kick", ck["row"], ck["col"]) < LS.RATES["kick_ok"]:
            self.puck[pk] = None
            self.log.append((self.tl(m), "kick", dict(pk=pk)))
        else:
            self.log.append((self.tl(m), "kick_fail", dict(pk=pk)))

    def run_to(self, t_line):
        while self.tl(self.ax["axMasterEnc"].pos) < t_line:
            self.step(100)
