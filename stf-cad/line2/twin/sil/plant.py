"""
DT-4a: the plant the compiled PLC runs against (software in the loop) - what the PLC's I/O sees, at its own 10 ms scan.

  NC        the axes the PLC commands through SIM_MC (port.py R4/R5): power (Enable -> Enabled), velocity mode with an
            acceleration limit, gearing to the master (Mode 2, Ratio), halt (Mode 3), decoupled free running (Mode 4,
            PLCopen: the slave keeps its velocity). axMasterEnc = the measuring wheel B1 on the master (no slip here).
  Band      the mesh band moves with axQ40. A row is cut every band pitch WHILE THE DEPOSITOR ROLLS (axQ41) TURN and
            there is dough - the physical truth, independent of what FB_Band believes.
  Hopper    the dough stock (kg): every row cut takes rows x DOUGH_M; refill() is the AMR tipping a tub. IOL1 (ToF) reads
            the distance to the dough, 0.1 mm (line_model.hopper_tof).
  Oven      oven_ctrl.Plant's zone model (or Mismatch: the real oven differs) integrated every 10 ms with the power of
            the elements whose SSR output is on at that scan (broken elements give none); the zone-to-zone exchange G;
            the thermocouple lag TC_TAU -> tcTCn (0.1 C); the phase currents of the conducting elements + fans
            (sqrt(power ratio) for the supply) through the transducer (first-order t_resp / 3, accuracy acc of range
            with a chosen sign) -> aiBCn (0..32767 = 0..20 A).
  Safety    xSafeRunPermit: TRUE unless a test drops it (the TwinSAFE side is DT-4c).
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LINE2 = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, LINE2)
import hardware as H                                       # noqa: E402
import line_model as M                                     # noqa: E402
import oven_ctrl as OC                                     # noqa: E402
from twin.sil.runtime import PLC                           # noqa: E402

L = M.L
DT = 0.01                                                  # s, the PLC task


class Axis:
    def __init__(self, name):
        self.name, self.pos, self.vel, self.off = name, 0.0, 0.0, None


class SilPlant:
    def __init__(self, T0=None, true=None, ct_sign=-1.0, dough=True, lib=None):
        """dough: True = the hopper is kept full (an endless supply), False = empty, a number = kg in the hopper."""
        self.plc = PLC(lib)
        self.pl = OC.Plant()
        self.tp = true or self.pl
        self.n = self.pl.n
        self.T = list(T0 if T0 is not None else self.pl.Ts)
        self.y = list(self.T)
        self.tc_tau = getattr(self.tp, "tc_tau", OC.CTRL["TC_TAU"])
        self.G = OC.CTRL["ZONE_G"]
        # elements in FB_Oven's order (= oven_ctrl's): their output, zone, phase, W
        self.els = [(f"qE{e['tag'][1:]}", k, self.pl.phase[e["tag"]], e["P"], e["tag"])
                    for k, z in enumerate(self.pl.zel) for e in z]
        self.fans = [(f"q{t}", self.pl.phase[t], w) for t, w in self.pl.fans.items()]
        self.phases = sorted({ph for _, _, ph, _, _ in self.els})
        self.ct = H.CT_AC
        self.ct_err = ct_sign * self.ct["acc"] * self.ct["range"]
        self.I_lag = {ph: 0.0 for ph in self.phases}
        self.broken = set()
        self.permit = True
        self.endless = dough is True
        self.stock = L["DOUGH_KG"] if dough is True else float(dough or 0.0)
        self.tof = M.hopper_tof()
        self.row_kg = L["BAND"]["rows"] * L["DOUGH_M"]
        self.ax = {a: Axis(a) for a in ("axQ1", "axQ40", "axQ41", "axMasterEnc")}
        self.ax["axQ1"].vel = 0.0
        st = M.stations()
        self.z_off = [z - st["dep"] for z in st["zones"]]
        self.zlen = M.zone_len()
        self.pitch = M.band_v() * L["BAND"]["rows"] * M.takt()
        self.rows_full = self.zlen / self.pitch
        self.cuts = []                                       # band positions of the rows really cut
        self.last_cut = 0.0
        self.t = 0.0
        self.scans = 0
        self._inputs()

    # ------------------------------------------------------------ the I/O image
    def _inputs(self):
        p = self.plc
        p["xSafeRunPermit"] = 1 if self.permit else 0
        tf = self.tof
        p["iolIOL1"] = int(round((tf["d_empty"] - self.stock / tf["kg_mm"]) / tf["unit"]))
        for k in range(self.n):
            p[f"tcTC{k + 1}"] = int(round(self.y[k] * 10.0))
        for j, ph in enumerate(self.phases):
            amps = max(0.0, self.I_lag[ph] + self.ct_err)
            p[f"aiBC{j + 1}"] = int(round(min(amps, self.ct["range"]) / self.ct["range"] * 32767))
        self.band_in = self.ax["axQ40"].pos                 # the band position the PLC sees this scan
        for a, ax in self.ax.items():
            p[f"sil_{a}_ActPos"] = ax.pos
            p[f"sil_{a}_ActVelo"] = ax.vel
            p[f"sil_{a}_Enabled"] = 1 if (a != "axQ1" or p["sil_axQ1_Enable"]) else 0

    def content(self, band=None):
        """The TRUE band content per zone (0..1): rows really on the band between each zone's walls (at the band's
        position now, or at band - e.g. band_in, the position the PLC read in its last scan)."""
        band = self.ax["axQ40"].pos if band is None else band
        f = [0.0] * self.n
        for c in self.cuts:
            d = band - c
            for k, z in enumerate(self.z_off):
                if z <= d < z + self.zlen:
                    f[k] += 1.0 / self.rows_full
        return [min(v, 1.0) for v in f]

    def _nc(self):
        p = self.plc
        m = self.ax["axQ1"]
        target = p["sil_axQ1_Velocity"] if (p["sil_axQ1_Enable"] and p["sil_axQ1_Mode"] == 1) else 0.0
        acc = max(p["sil_axQ1_Accel"], 1e-9)
        dv = max(-acc * DT, min(acc * DT, target - m.vel))
        v0 = m.vel
        m.vel += dv
        m.pos += (v0 + m.vel) / 2 * DT
        enc = self.ax["axMasterEnc"]
        enc.pos, enc.vel = m.pos, m.vel
        for a in ("axQ40", "axQ41"):
            ax, mode = self.ax[a], p[f"sil_{a}_Mode"]
            if mode == 2:                                    # geared: slave = ratio x master (from the coupling)
                if ax.off is None:
                    ax.off = ax.pos - p[f"sil_{a}_Ratio"] * enc.pos
                new = p[f"sil_{a}_Ratio"] * enc.pos + ax.off
                ax.vel = (new - ax.pos) / DT
                ax.pos = new
                continue
            ax.off = None
            if mode == 3:                                    # halt: decelerate to standstill
                d = max(p[f"sil_{a}_Accel"], 1e-9) * DT
                ax.vel = 0.0 if abs(ax.vel) <= d else ax.vel - math.copysign(d, ax.vel)
            elif mode == 0:
                ax.vel = 0.0
            ax.pos += ax.vel * DT                             # mode 4: free running at the last velocity

    def _band(self):
        band, rolls = self.ax["axQ40"].pos, self.ax["axQ41"]
        if band - self.last_cut >= self.pitch:
            self.last_cut += self.pitch
            if abs(rolls.vel) > 1e-9 and self.stock >= self.row_kg:   # the wire cuts a slug only from turning rolls
                self.cuts.append(self.last_cut)
                if not self.endless:
                    self.stock -= self.row_kg
        far = self.z_off[-1] + self.zlen
        self.cuts = [c for c in self.cuts if band - c < far + self.pitch]

    def _oven(self):
        p = self.plc
        on = {tag: bool(p[q]) and tag not in self.broken for q, k, ph, w, tag in self.els}
        f = self.content()
        Tn = list(self.T)
        for k in range(self.n):
            P = sum(w * self.tp.P[k] / self.pl.P[k] for q, kk, ph, w, tag in self.els if kk == k and on[tag])
            nb = [j for j in (k - 1, k + 1) if 0 <= j < self.n]
            q_ = P - self.tp.load(k, self.T[k], f[k]) + sum(self.G * (self.T[j] - self.T[k]) for j in nb)
            Tn[k] = self.T[k] + q_ * DT / self.tp.C[k]
        self.T = Tn
        for k in range(self.n):
            self.y[k] += (self.T[k] - self.y[k]) * DT / self.tc_tau
        a = min(1.0, DT / (self.ct["t_resp"] / 3))
        for ph in self.phases:
            amps = sum(w / H.SUPPLY["U"] * math.sqrt(self.tp.P[k] / self.pl.P[k])
                       for q, k, ph_, w, tag in self.els if ph_ == ph and on[tag])
            amps += sum(w / H.SUPPLY["U"] for q, ph_, w in self.fans if ph_ == ph and p[q])
            self.I_lag[ph] += (amps - self.I_lag[ph]) * a

    def step(self, n=1):
        for _ in range(n):
            self._inputs()
            self.plc.scan()
            self._nc()
            self._band()
            self._oven()
            self.scans += 1
            self.t = round(self.scans * DT, 6)

    def refill(self, kg=None):
        """The AMR tips a tub: the hopper up to kg (default DOUGH_KG)."""
        self.stock = L["DOUGH_KG"] if kg is None else kg

    def outputs(self, names):
        return {nm: self.plc[nm] for nm in names}
