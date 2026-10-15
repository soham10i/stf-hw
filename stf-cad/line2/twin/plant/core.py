"""
DT-3a: the live plant core - the STF-2 line stepped in virtual time, driven by commands, producing frames.

Time
  t      plant time (s), advanced in TICK = 10 ms steps (the PLC task). Deterministic: no wall clock inside.
  tau    machine time (s) = master axis position / V. Everything geared to the master (chain + pucks, band rows,
         cutting wire, deltas A / B / C) is a function of tau, so it stops when the master stops and continues
         from where it stopped. The oven, the airlock and the pneumatic actuators run on t.
Poses   motion.frame(t, base, ev, rows, tau) - the SAME function that wrote timeline.json (one source of truth);
         this module only supplies its clocks, its event times and the band-row pool.
Band    the scene has 27 band-row names (band_r075 .. band_r101); a row lives at most 606.5 s from deposit to its
         last pick, the pool spans 27 x 24 s = 648 s, so slot s always shows the one row r = s + 27 m that is alive
         (or the next one, hidden). Over the reference window this is exactly timeline.json.
Oven     MODE "reference": every element SSR follows motion.element_on with the steady duty (= timeline.json); the
         zone model of oven_ctrl.Plant integrated exactly as motion.py does (blocks of 0.1 s, 5 sub-steps of 20 ms,
         the SSR state at the block start, a 600 s run-in before t = 0). Power and phase currents = motion.power_at.
Frames  rows in timeline.json's own format: rigid [tx, ty, tz, qx, qy, qz, qw, vis] relative to the CAD (or to
         the spawn pose), re-shaped {c, ax, len, dia[, col, vis]}; plus glow bits, power, zone temperatures.
"""
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
LINE2 = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, LINE2)
import line_model as M                                     # noqa: E402
import motion as Mo                                        # noqa: E402

L = M.L
TICK = 0.01                                                # s, the PLC task
FRAME_DT = Mo.DT                                           # s, one frame = one timeline frame (0.1 s)
MASTER_RAMP = 0.5                                          # s, master 0 <-> V (MC_MoveVelocity / MC_Stop) [assumed]
POOL = 27                                                  # band-row names in the scene
ROW0 = 75                                                  # the first pool slot (band_r075): rows 75 .. 101
# the complete pool: every column of every slot, base + topping. The reference window (BAND_NAMES) shows only those
# it needs; an endless band needs all of them.
FULL_NAMES = [f"band_r{ROW0 + i:03d}_{c}{sfx}" for i in range(POOL) for c in range(6) for sfx in ("", "_top")]


# The plant freezes the model: L does not change during a run, so these pure functions of L are memoised in this
# process (each recomputed a bake simulation or an IK bisection on every call). The replay gate proves the frames
# are unchanged by it.
FROZEN = ("cookie_hex", "delta_reach_radius", "stations", "band_v", "takt", "transfer_times", "pick_z", "band_pick_z",
          "travel_z", "y_back", "place_z", "z_seat", "z_cookie_top", "loop_len", "zone_len", "bake_t", "duty",
          "oven_power")                                     # (callers only read its lists)


def _freeze():
    import functools
    for name in FROZEN:
        for mod in (M, Mo):
            f = getattr(mod, name, None)
            if callable(f) and not hasattr(f, "cache_info"):
                setattr(mod, name, functools.lru_cache(maxsize=None)(f))


_freeze()


class MasterAxis:
    """The electronic line shaft (Q1): enable, a speed set point (rate = v / V, 0..1), a ramp of MASTER_RAMP s
    from 0 to V. It integrates MACHINE TIME tau directly (pos = tau V): at a constant rate tau is advanced in
    closed form from the start of that segment, so the nominal run has tau == t exactly (no float drift)."""

    def __init__(self):
        self.rate, self.cmd, self.enabled = 1.0, 1.0, True
        self.tau = 0.0
        self.seg = (0.0, 0.0)                              # (t, tau) where the current constant-rate segment began

    def step(self, t0, t1):
        target = self.cmd if self.enabled else 0.0
        if self.rate == target:
            ts, taus = self.seg
            self.tau = taus + (t1 - ts) * self.rate
            return
        a = (t1 - t0) / MASTER_RAMP
        r0 = self.rate
        self.rate = target if abs(target - r0) <= a else r0 + math.copysign(a, target - r0)
        self.tau += (r0 + self.rate) / 2 * (t1 - t0)
        if self.rate == target:
            self.seg = (t1, self.tau)

    @property
    def pos(self):
        return self.tau * L["V"]

    @property
    def vel(self):
        return self.rate * L["V"]


class Plant:
    def __init__(self, oven_mode="reference", events=None, flow=None):
        """flow: a twin.plant.flow.Flow (DT-3b) - the product flow decides what exists and fires kick / seal /
        exchange; oven_mode 'pi' (default with a flow): FB_Oven's closed loop (oven_ctrl.ZoneLoop) on the band
        content the flow really put there; 'reference': the steady duty of timeline.json."""
        self.base = {p.name: p for p in M.build()}
        f0, _, _ = Mo.frame(0.0, self.base)
        self.moving = set(f0)
        self.ref = dict(self.base)
        self.spawn = []
        for n, p in f0.items():
            if n not in self.base:
                self.ref[n] = p
                self.spawn.append(n)
        self.reshape = {"kick_rod"} | {f"sealer_{f}_rod" for f in Mo.FLAV} | {f"stacker_rod_{f}" for f in Mo.FLAV} | \
            {n for n in FULL_NAMES if not n.endswith("_top")}
        # pool names the reference window never shows: their base pose (the viewer creates them from the hello)
        self.extra = []
        for n in FULL_NAMES:
            if n not in self.ref:
                q, _ = Mo.band_pose(n, 0.0)
                self.ref[n] = q
                self.extra.append(dict(name=n, kind="cyl", p=list(q.p), s=list(q.s), colour=q.colour,
                                       reshaped=not n.endswith("_top")))
        self.period = L["BAND"]["rows"] * M.takt()
        self.t_enter = M.transfer_times()[0]
        self.t = 0.0
        self.ticks = 0
        self.master = MasterAxis()
        self.ev = dict(kicks=[], seals={f: [] for f in Mo.FLAV}, lifts={f: [] for f in Mo.FLAV}, exchange=None)
        if events is not None:                             # e.g. motion.reference_events()
            self.ev = json.loads(json.dumps(events))
        self.log = []                                      # (t, command, args) - what the controller asked for
        self.flow = flow
        self.oven_mode = oven_mode if flow is None or oven_mode != "reference" else "pi"
        self.trace = []                                    # (t, [TC per zone]) of the last ~12 min: the bake logs
        self._oven_init()
        if self.oven_mode == "pi":
            self._pi_init()
        if flow is not None:
            flow.release(0.0)

    # ------------------------------------------------------------ commands (what the PLC / operator can ask)
    def command(self, name, **kw):
        """kick | seal(lane) | exchange | master(on) | speed(factor). Returns (ok, message)."""
        t = round(self.t, 6)
        if name == "kick":
            self.ev["kicks"].append(t)
        elif name == "seal":
            lane = kw.get("lane")
            if lane not in Mo.FLAV:
                return False, f"unknown lane {lane!r}"
            self.ev["seals"][lane].append(t)
            self.ev["lifts"][lane].append(t + 2.0)         # the stacker lifts the sealed pack 2 s later (FB_Lane)
        elif name == "exchange":
            if self.exchange_active():
                return False, "an airlock exchange is running"
            self.ev["exchange"] = t
        elif name == "master":
            self.master.enabled = bool(kw.get("on", True))
            if self.master.rate == (self.master.cmd if self.master.enabled else 0.0):
                self.master.seg = (round(self.t, 6), self.master.tau)
        elif name == "speed":
            f = float(kw.get("factor", 1.0))
            if not 0.0 <= f <= 1.0:
                return False, "speed factor 0..1 of the rated V"
            self.master.cmd = f
        else:
            return False, f"unknown command {name!r}"
        self.log.append((t, name, kw))
        return True, "ok"

    def exchange_active(self):
        if self.ev["exchange"] is None:
            return False
        ph = Mo.exchange(self.ev["exchange"])
        return ph[0][1] <= self.t < ph[-1][1] + ph[-1][2]

    # ------------------------------------------------------------ oven
    def _oven_init(self):
        import oven_ctrl as OC
        self.pl = OC.Plant()
        self.tc_tau = OC.CTRL["TC_TAU"]
        self.els = M.oven_power()[1]
        order = defaultdict(int)
        self.ix = []
        for e in self.els:
            self.ix.append(order[e["zone"]])
            order[e["zone"]] += 1
        self.duty = Mo.duty()
        self.Tz, self.yz = list(self.pl.Ts), list(self.pl.Ts)
        for k in range(int(600 / FRAME_DT)):               # run-in, as motion.py: the PWM ripple is periodic at t = 0
            self._oven_block(-600.0 + k * FRAME_DT)
        self._oven_block(0.0)                              # a frame shows the zones after ITS block (= motion.py)
        self.temps = [round(v, 2) for v in self.yz]

    def _oven_block(self, t):
        """One 0.1 s block from t: the SSR states at t, 5 sub-steps of 20 ms (= motion.py)."""
        sub = 0.02
        for _ in range(int(FRAME_DT / sub)):
            for k in range(self.pl.n):
                Pk = sum(e["P"] for e, i in zip(self.els, self.ix)
                         if e["zone"] == f"Z{k + 1}" and Mo.element_on(e, i, t, self.duty))
                self.Tz[k] += (Pk - self.pl.load(k, self.Tz[k], 1.0)) * sub / self.pl.C[k]
                self.yz[k] += (self.Tz[k] - self.yz[k]) * sub / self.tc_tau

    # ------------------------------------------------------------ DT-3b: the oven under FB_Oven's closed loop
    def _pi_init(self):
        import oven_ctrl as OC
        self.OC = OC
        self.gains = OC.tune(self.pl)
        self.zl = OC.ZoneLoop(self.pl, self.gains)
        st = M.stations()
        self.z0, self.zlen = st["zones"], M.zone_len()
        self.dep_x, self.vb = st["dep"], M.band_v()
        self.rows_full = self.zlen / (self.vb * self.period)   # rows a full zone holds
        full = [1.0] * self.pl.n
        for _ in range(int(600 / self.OC.CTRL["DT"])):      # run-in on a full band: the PLC has been running
            self.zl.step(full)
        self.zl.t = 0.0
        self.duties = {f"Z{k + 1}": u for k, u in enumerate(self.zl.u)}
        self.temps = [round(v, 2) for v in self.zl.y]

    def content(self, tau):
        """Band content per zone (0..1) from the rows the flow REALLY deposited and that still carry cookies."""
        f = [0.0] * self.pl.n
        cols = L["BAND"]["rows"]
        for r, present in self.flow.row_present().items():
            x = self.dep_x + self.vb * (tau - r * self.period)
            for k, z in enumerate(self.z0):
                if z <= x < z + self.zlen:
                    f[k] += len(present) / cols / self.rows_full
        return [min(v, 1.0) for v in f]

    # ------------------------------------------------------------ time
    def step(self, n=1):
        for _ in range(n):
            t0 = round(self.t, 6)
            self.ticks += 1
            self.t = round(self.ticks * TICK, 6)
            self.master.step(t0, self.t)
            if self.flow is not None:
                for et, kind, d in self.flow.release(self.master.tau):
                    if kind == "kick":
                        self.command("kick")
                    elif kind == "pack":
                        self.command("seal", lane=d["lane"])
                    elif kind == "exchange" and d["lane"] == Mo.EXCH_LANE:
                        self.command("exchange")
                    elif kind == "load":
                        self._bake_log(d["id"])
            if self.oven_mode == "pi":
                if self.ticks % round(self.OC.CTRL["DT"] / TICK) == 0:
                    self.zl.step(self.content(self.master.tau) if self.flow is not None else [1.0] * self.pl.n)
                    self.duties = {f"Z{k + 1}": u for k, u in enumerate(self.zl.u)}
                    self.temps = [round(v, 2) for v in self.zl.y]
                    self.trace.append((self.t, self.master.tau, list(self.zl.y)))
                    if len(self.trace) > 1500:
                        del self.trace[:500]
            elif self.ticks % round(FRAME_DT / TICK) == 0:  # an oven block starts on the 0.1 s grid
                self._oven_block(self.t)
                self.temps = [round(v, 2) for v in self.yz]

    def _bake_log(self, cid):
        """The cookie's zone history into its bake log (the NFC tag): the largest |TC - set point| of each zone
        while the cookie was in it, and whether that leaves the bake window (+-BAKE_MARGIN) - a flagged cookie."""
        e = self.flow.log[cid]
        if self.oven_mode != "pi" or e.get("pre"):
            return
        dev = []
        for k, z in enumerate(self.z0):
            a = e["deposit"] + (z - self.dep_x) / self.vb       # machine time it enters / leaves zone k
            b = a + self.zlen / self.vb
            seen = [abs(y[k] - self.pl.Ts[k]) for t, tau, y in self.trace if a <= tau <= b]
            dev.append(round(max(seen), 2) if seen else None)
        e["zone_dev"] = dev
        e["flagged"] = any(d is not None and d > L["BAKE_MARGIN"] for d in dev)

    # ------------------------------------------------------------ band-row pool
    def _rows(self, tau):
        def rows(name):
            r_slot = int(name[len("band_r"):].split("_")[0]) - 100
            # the row r = r_slot + POOL m alive at tau (life <= 606.5 s < POOL x period), else the next one
            m = math.floor((tau - r_slot * self.period) / (POOL * self.period))
            r = r_slot + POOL * m
            shift = (r - r_slot) * self.period                  # row r at tau looks like row r_slot at tau - shift
            # with a flow the cookie leaves the band when the flow says (it may wait for a grip retry): no schedule
            return Mo.band_pose(name, tau - shift, math.inf if self.flow is not None else None)
        return rows

    def row_of(self, name, tau):
        """The band row a pool slot shows at tau (as _rows)."""
        r_slot = int(name[len("band_r"):].split("_")[0]) - 100
        return r_slot + POOL * math.floor((tau - r_slot * self.period) / (POOL * self.period))

    def _flow_view(self, track, tau):
        """The flow decides what is drawn: cookies on pucks (with their flavour's topping), cookies on the band (and
        their topping only if they got one). Overrides the visibility in the rows; returns (paint, flow summary)."""
        fl = self.flow
        idx = fl._band_index()
        paint = {}
        for k in range(L["N"]):
            vis, flav = fl.puck_cookie(k)
            for n in (f"cookie_{k:02d}", f"cookie_{k:02d}_top"):
                if n in track:
                    track[n][7] = 1 if vis else 0
            if vis:
                paint[f"cookie_{k:02d}_top"] = L["BAKED"][Mo.FLAV.index(flav)]
        for n, r_ in list(track.items()):
            if not n.startswith("band_r"):
                continue
            row = self.row_of(n, tau)
            col = int(n.split("_")[2])
            on = topped = False
            if fl.rows.get(row) == "deposited":
                for cid, (r, c, f, tp) in idx.get(row, {}).items():
                    if c == col:
                        on, topped = True, tp
            vis = on and (topped if n.endswith("_top") else True)
            if isinstance(r_, dict):
                r_["vis"] = 1 if vis else 0
            else:
                r_[7] = 1 if vis else 0
        k = fl.counts
        summary = dict(loaded=k.get("load", 0), rejected=k.get("kick", 0), band_lost=k.get("band_lost", 0),
                       packed=sum(1 for e in fl.log.values() if e.get("end") == "packed"),
                       packs=dict(fl.packs), cassettes_out=dict(fl.cassettes_out), drawer=fl.drawer,
                       dough_kg=round(fl.dough, 3), topping_kg={f: round(v, 3) for f, v in fl.topping.items()},
                       amr={i: (None if a["busy_until"] is None else round(a["busy_until"], 1)) for i, a in fl.amr.items()},
                       on_pucks=len(fl.pucks), on_band=len(fl.band),
                       flagged=sum(1 for e in fl.log.values() if e.get("flagged")))
        return paint, summary

    # ------------------------------------------------------------ frame
    def frame(self):
        """The current frame: {track: {name: row}, glow: {name: 0/1}, power: [W, A1, A2, A3], temps: [..],
        t, tau, master: {...}, bad: [unreachable poses]} - rows in timeline.json's format."""
        t, tau = self.t, self.master.tau
        now, vis, bad = Mo.frame(t, self.base, self.ev, self._rows(tau), tau, FULL_NAMES)
        track = {}
        for n, p in now.items():
            if n in self.reshape:
                e = dict(c=[p.p[0], p.p[1], p.p[2]], ax=p.s[0], len=round(p.s[1], 3), dia=p.s[2])
                if n.startswith("band_r"):
                    e["col"] = p.colour
                    e["vis"] = 1 if vis.get(n, True) else 0
                track[n] = e
            else:
                q, tr = Mo.rigid(self.ref[n], p)
                track[n] = [round(v, 3) for v in tr] + [round(v, 6) for v in q] + [1 if vis.get(n, True) else 0]
        duty = self.duties if self.oven_mode == "pi" else self.duty
        glow = {}
        for e, i in zip(self.els, self.ix):
            glow[f"oven_heater_{e['tag']}"] = 1 if Mo.element_on(e, i, t, duty) else 0
        W, amps = Mo.power_at(t, duty)
        paint, flow = {}, None
        if self.flow is not None:
            paint, flow = self._flow_view(track, tau)
        return dict(t=t, tau=round(tau, 6), track=track, glow=glow,
                    power=[round(W), round(amps["L1"], 2), round(amps["L2"], 2), round(amps["L3"], 2)],
                    temps=list(self.temps), bad=bad, paint=paint, flow=flow,
                    duty=[round(duty[f"Z{k + 1}"], 4) for k in range(self.pl.n)],
                    master=dict(pos=round(self.master.pos, 4), vel=round(self.master.vel, 4),
                                enabled=self.master.enabled, rate=self.master.cmd))
