// One component's health signal over its life: the ratio to its baseline, the
// soft limit that raises the warning and the limit at which it fails (health.py).
import type { HealthComp } from "./model";

const fmt0 = (x: number) => (Math.abs(x) >= 10 ? x.toFixed(0) : x.toFixed(2));

export function Curve({ c }: { c: HealthComp }) {
  const W = 260, H = 110, L = 30, B = 18;
  const nmax = c.curve[c.curve.length - 1][0] || 1;
  const rmax = c.r_fail * 1.05;
  const X = (n: number) => L + (n / nmax) * (W - L - 6);
  const Y = (r: number) => H - B - ((r - 1) / (rmax - 1)) * (H - B - 12);
  const d = c.curve.map((p, i) => `${i ? "L" : "M"}${X(p[0])},${Y(p[1])}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="bp-view u2-schem u6-curve">
      <text x={4} y={10} className="bp-small" style={{ fontWeight: 700 }}>{c.name}</text>
      <line x1={L} x2={W - 6} y1={Y(c.r_fail)} y2={Y(c.r_fail)} className="u6-fail" />
      <line x1={L} x2={W - 6} y1={Y(c.soft)} y2={Y(c.soft)} className="u6-soft" />
      <line x1={L} x2={W - 6} y1={Y(1)} y2={Y(1)} className="u4-grid" />
      <path d={d} className="u6-line" />
      {c.warn !== null && <line x1={X(c.warn)} x2={X(c.warn)} y1={12} y2={H - B} className="u6-soft" />}
      {c.fail !== null && <line x1={X(c.fail)} x2={X(c.fail)} y1={12} y2={H - B} className="u6-fail" />}
      <text x={L - 3} y={Y(c.r_fail) + 3} textAnchor="end" className="bp-small">{fmt0(c.r_fail)}</text>
      <text x={L - 3} y={Y(1) + 3} textAnchor="end" className="bp-small">1</text>
      <text x={L} y={H - 4} className="bp-small">0</text>
      <text x={W - 6} y={H - 4} textAnchor="end" className="bp-small">{nmax.toLocaleString()} uses</text>
    </svg>
  );
}
