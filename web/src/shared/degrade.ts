// Upgrade 6's degradation model, cycle by cycle, in the browser: the same wear law, noise,
// EWMA, health index and two warnings as stf-cad/hbw/health.py simulate(), with each part's
// law from public/health/theory.json (health_theory.py). The docs page runs it live.
import { Rng } from "../vision/render";

export type Law = {
  id: string; p: number; life: number; r_fail: number; sigma: number; per_shift: number; rul_warn: number;
  sigma_z: number; soft_margin_sigma: number; trend_margin_sigma: number; n_soft_theory: number;
  warn_sim: number | null; warn_by: string | null; fail_sim: number | null; lead_shifts: number | null;
};
export type Theory = {
  rules: { lambda: number; soft: number; window: number; rul_warn_shifts: number; ewma_lag: number; healthy_cycles: number };
  components: Law[]; fails: string[];
};

export type Sample = { n: number; y: number; z: number; r: number; hi: number; rul: number | null };

/** r(n) = 1 + (r_f - 1)(n / L)^p */
export const wear = (l: Law, n: number) => 1 + (l.r_fail - 1) * (n / l.life) ** l.p;

export class DegradeSim {
  n = 0; z = 1; y = 1; beta: number | null = null; rul: number | null = null;
  warn: { n: number; by: "soft limit" | "trend" } | null = null;
  fail: number | null = null;
  samples: Sample[] = [];
  readonly nMax: number; readonly stride: number; readonly soft: number;
  private ring: Float64Array; private rng: Rng;

  constructor(readonly law: Law, readonly o: { lambda: number; soft: number; window: number; noise: number; degrade: boolean; seed?: number }) {
    this.nMax = Math.round(law.life * 1.2);
    this.stride = Math.max(1, Math.floor(this.nMax / 320));
    this.soft = 1 + o.soft * (law.r_fail - 1);
    this.ring = new Float64Array(o.window + 1);
    this.rng = new Rng(o.seed ?? 6);
  }

  get done() { return this.n >= this.nMax || (this.fail !== null && this.n > this.fail + 4 * this.stride); }
  get hi() { const l = this.law; return 100 * Math.max(0, Math.min(1, (l.r_fail - this.z) / (l.r_fail - 1))); }
  truth(n = this.n) { return this.o.degrade ? wear(this.law, n) : 1; }

  /** Advance k cycles. */
  step(k: number) {
    const { law: l, o } = this, W = o.window, sig = l.sigma * o.noise;
    for (let i = 0; i < k && !this.done; i++) {
      const n = this.n, r = this.truth(n);
      this.y = r * (1 + this.rng.normal() * sig);                       // y_n = r(n)(1 + eps)
      this.z = n === 0 ? this.y : this.z + o.lambda * (this.y - this.z);  // EWMA
      this.ring[n % (W + 1)] = this.z;
      if (n >= W && n % 50 === 0) {                                      // trend over the last W cycles
        this.beta = (this.z - this.ring[(n - W) % (W + 1)]) / W;
        this.rul = this.beta > 1e-12 ? (l.r_fail - this.z) / this.beta : Infinity;
      }
      if (this.warn === null && n > W) {
        if (this.z >= this.soft) this.warn = { n, by: "soft limit" };
        else if (this.rul !== null && this.rul < l.rul_warn) this.warn = { n, by: "trend" };
      }
      if (this.fail === null && r >= l.r_fail) this.fail = n;
      if (n % this.stride === 0)
        this.samples.push({ n, y: this.y, z: this.z, r, hi: this.hi, rul: this.rul !== null && isFinite(this.rul) ? this.rul : null });
      this.n++;
    }
  }
}
