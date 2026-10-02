// Upgrade 6 helpers: where each component stands after a given machine age,
// every component following its own injected wear law (health.py curves).
import type { HealthComp } from "../shared/model";

export type CompNow = { c: HealthComp; n: number; ewma: number; hi: number; rulShifts: number | null;
                        status: "ok" | "warn" | "fail"; serviced: number };

/** Where a component stands after `shifts` of running. With `maintained`, it is
 *  serviced (worn part renewed) every time its U6 warning comes, so its wear
 *  starts again from new and it never reaches the failure. */
export function compAt(c: HealthComp, shifts: number, maintained = false): CompNow {
  let n = shifts * c.per_shift;
  let serviced = 0;
  if (maintained && c.warn) {
    serviced = Math.floor(n / c.warn);
    n -= serviced * c.warn;
  }
  const cv = c.curve;
  let k = cv.findIndex((p) => p[0] >= n);
  if (k < 0) k = cv.length - 1;
  const p = cv[Math.max(0, k)];
  const status = c.fail !== null && n >= c.fail ? "fail" : c.warn !== null && n >= c.warn ? "warn" : "ok";
  const rul = c.fail !== null ? Math.max(0, (c.fail - n) / c.per_shift) : null;
  return { c, n, ewma: p[1], hi: status === "fail" ? 0 : p[2], rulShifts: rul, status, serviced };
}

export function maxShifts(cs: HealthComp[]) {
  return Math.max(...cs.map((c) => (c.fail ?? c.life) / c.per_shift)) * 1.05;
}

export const STATUS_TXT = { ok: "healthy", warn: "service due", fail: "failed" };

/** A small sparkline of the health index up to the current cycle count. */
export function spark(c: HealthComp, n: number, w = 120, h = 26) {
  const pts = c.curve.filter((p) => p[0] <= n);
  const nmax = c.curve[c.curve.length - 1][0] || 1;
  return pts.map((p, i) => `${i ? "L" : "M"}${(p[0] / nmax) * w},${h - (p[2] / 100) * h}`).join(" ");
}
