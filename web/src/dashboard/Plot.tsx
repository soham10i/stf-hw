// Analysis charts for the dashboard: axes with titles and units, "nice" ticks, a crosshair that
// reads every series at the pointer, a legend that hides and shows series, and labelled limit
// lines, bands and events. Plot is the x-y chart; Heat is a rows x time heat map.
import { useEffect, useId, useMemo, useRef, useState } from "react";

/** The element's width in CSS pixels, so a chart draws at true size (text never scales). */
export function useWidth<T extends HTMLElement>(fallback = 900) {
  const ref = useRef<T>(null);
  const [w, setW] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => { const v = Math.round(e.contentRect.width); if (v > 0) setW(v); });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

export type Series = {
  name: string; x: number[]; y: (number | null)[]; color: string;
  kind?: "line" | "area" | "step" | "dots"; dash?: boolean; width?: number; fmt?: (v: number) => string;
};
export type Band = { y0: number; y1: number; color: string; label?: string };
export type HLine = { y: number; color: string; label: string };
export type VMark = { x: number; color: string; label: string };

/** 1-2-5 ticks covering [a, b]. */
export function niceTicks(a: number, b: number, n = 5) {
  if (!(b > a)) return [a];
  const raw = (b - a) / n, mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(a / step - 1e-9) * step; v <= b + step * 1e-9; v += step) out.push(+v.toPrecision(12));
  return out;
}
export const fmtNum = (v: number) => {
  const a = Math.abs(v);
  if (a >= 1e6) return `${+(v / 1e6).toFixed(1)}M`;
  if (a >= 1e4) return `${+(v / 1e3).toFixed(0)}k`;
  if (a >= 1e3) return `${+(v / 1e3).toFixed(1)}k`;
  if (a >= 100) return v.toFixed(0);
  if (a >= 10) return +v.toFixed(1) + "";
  return +v.toFixed(2) + "";
};

/** A label cut to fit `px` pixels of 12 px text, with an ellipsis. */
export const fit = (s: string, px: number) => { const n = Math.floor(px / 6.6); return s.length > n ? s.slice(0, Math.max(1, n - 1)) + "…" : s; };

/** index of the x nearest to v (x sorted ascending) */
function nearest(x: number[], v: number) {
  let lo = 0, hi = x.length - 1;
  if (hi < 0) return -1;
  while (hi - lo > 1) { const m = (lo + hi) >> 1; if (x[m] < v) lo = m; else hi = m; }
  return Math.abs(x[lo] - v) <= Math.abs(x[hi] - v) ? lo : hi;
}

export function Plot({ series, xTitle, yTitle, xFmt = fmtNum, yFmt = fmtNum, xMin, xMax, yMin, yMax, bands = [], hlines = [], vmarks = [],
  now, h = 240, legend = true, tipTitle, tipExtra, xTicks }: {
  series: Series[]; xTitle: string; yTitle: string; xFmt?: (v: number) => string; yFmt?: (v: number) => string;
  xMin?: number; xMax?: number; yMin?: number; yMax?: number; bands?: Band[]; hlines?: HLine[]; vmarks?: VMark[];
  now?: { x: number; label?: string }; h?: number; legend?: boolean; tipTitle?: (x: number) => string;
  /** more lines for the read-out at x */
  tipExtra?: (x: number) => [string, string][];
  /** fixed x ticks (otherwise 1-2-5 ticks) */
  xTicks?: number[];
}) {
  const [off, setOff] = useState<Set<string>>(new Set());
  const [hx, setHx] = useState<number | null>(null);
  const [box, W] = useWidth<HTMLDivElement>();
  const gid = `pl${useId().replace(/:/g, "")}`;  // gradient ids, unique per chart
  const L = 58, R = 16, T = 14, B = 42;
  const vis = series.filter((s) => !off.has(s.name));
  const dom = useMemo(() => {
    const xs = series.flatMap((s) => s.x), ys = vis.flatMap((s) => s.y.filter((v): v is number => v !== null && isFinite(v)));
    // an empty chart (no points yet) still gets a finite axis
    const x0 = xMin ?? (xs.length ? Math.min(...xs) : 0), x1 = xMax ?? (xs.length ? Math.max(...xs) : 1);
    let y0 = yMin ?? Math.min(...ys, ...hlines.map((l) => l.y)), y1 = yMax ?? Math.max(...ys, ...hlines.map((l) => l.y));
    if (!isFinite(y0) || !isFinite(y1)) { y0 = 0; y1 = 1; }
    const pad = (y1 - y0) * 0.06 || 1;
    if (yMin === undefined) y0 -= pad;
    if (yMax === undefined) y1 += pad;
    return { x0, x1: x1 > x0 ? x1 : x0 + 1, y0, y1 };
  }, [series, vis, xMin, xMax, yMin, yMax, hlines]);
  const X = (x: number) => L + ((x - dom.x0) / (dom.x1 - dom.x0)) * (W - L - R);
  const Y = (y: number) => T + (1 - (Math.min(Math.max(y, dom.y0), dom.y1) - dom.y0) / (dom.y1 - dom.y0)) * (h - T - B);
  const path = (s: Series) => {
    let d = "", pen = false, py = 0;
    const step = Math.max(1, Math.floor(s.x.length / 1200));
    for (let i = 0; i < s.x.length; i += step) {
      const y = s.y[i];
      if (y === null || !isFinite(y)) { pen = false; continue; }
      if (s.kind === "step" && pen) d += `L${X(s.x[i]).toFixed(1)},${py.toFixed(1)}`;
      py = Y(y);
      d += `${pen ? "L" : "M"}${X(s.x[i]).toFixed(1)},${py.toFixed(1)}`;
      pen = true;
    }
    return d;
  };
  const xt = xTicks ?? niceTicks(dom.x0, dom.x1, W < 560 ? 3 : 6), yt = niceTicks(dom.y0, dom.y1, 4);
  const move = (e: React.MouseEvent) => {
    const r = box.current!.getBoundingClientRect();
    const vx = ((e.clientX - r.left) / r.width) * W;
    if (vx < L || vx > W - R) { setHx(null); return; }
    setHx(dom.x0 + ((vx - L) / (W - L - R)) * (dom.x1 - dom.x0));
  };
  const read = hx === null ? [] : vis.map((s) => { const i = nearest(s.x, hx); return { s, i, x: s.x[i], y: i >= 0 ? s.y[i] : null }; })
    .filter((r) => r.y !== null && isFinite(r.y as number));
  const tipLeft = hx === null ? 0 : (X(hx) / W) * 100;
  return (
    <div className="pl">
      <div className="pl-box" ref={box} onMouseMove={move} onMouseLeave={() => setHx(null)}>
        <svg viewBox={`0 0 ${W} ${h}`}>
          {bands.map((b, i) => <g key={i}><rect x={L} width={W - L - R} y={Y(Math.min(b.y1, dom.y1))} height={Math.max(0, Y(Math.max(b.y0, dom.y0)) - Y(Math.min(b.y1, dom.y1)))} fill={b.color} opacity={0.09} />
            {b.label && <text x={L + 6} y={Y(Math.min(b.y1, dom.y1)) + 12} className="pl-band" style={{ fill: b.color }}>{b.label}</text>}</g>)}
          {yt.map((v) => <g key={v}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} className="pl-grid" /><text x={L - 7} y={Y(v) + 3.5} textAnchor="end" className="pl-tick">{yFmt(v)}</text></g>)}
          {xt.map((v) => <g key={v}><line x1={X(v)} x2={X(v)} y1={h - B} y2={h - B + 4} className="pl-axis" /><text x={X(v)} y={h - B + 16} textAnchor="middle" className="pl-tick">{xFmt(v)}</text></g>)}
          <line x1={L} x2={W - R} y1={h - B} y2={h - B} className="pl-axis" />
          <text x={(L + W - R) / 2} y={h - 6} textAnchor="middle" className="pl-title">{xTitle}</text>
          <text transform={`translate(13 ${(T + h - B) / 2}) rotate(-90)`} textAnchor="middle" className="pl-title">{yTitle}</text>
          {hlines.filter((l) => l.y >= dom.y0 && l.y <= dom.y1).map((l) => <g key={l.label}>
            <line x1={L} x2={W - R} y1={Y(l.y)} y2={Y(l.y)} stroke={l.color} strokeDasharray="6 4" strokeWidth={1.3} />
            <text x={W - R - 4} y={Y(l.y) - 5} textAnchor="end" className="pl-lab" style={{ fill: l.color }}>{l.label} · {yFmt(l.y)}</text></g>)}
          {vis.map((s, k) => s.kind === "dots"
            ? <g key={s.name}>{s.x.map((x, i) => s.y[i] !== null && <circle key={i} cx={X(x)} cy={Y(s.y[i]!)} r={1.8} fill={s.color} opacity={0.6} />)}</g>
            : <g key={s.name}>
                {s.kind === "area" && <>
                  {/* the fill fades from the line to the baseline */}
                  <defs><linearGradient id={`${gid}-${k}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0" style={{ stopColor: s.color, stopOpacity: 0.34 }} /><stop offset="1" style={{ stopColor: s.color, stopOpacity: 0.02 }} />
                  </linearGradient></defs>
                  <path d={`${path(s)}L${X(s.x[s.x.length - 1])},${Y(Math.max(dom.y0, 0))}L${X(s.x[0])},${Y(Math.max(dom.y0, 0))}Z`} fill={`url(#${gid}-${k})`} />
                </>}
                <path d={path(s)} fill="none" stroke={s.color} strokeWidth={s.width ?? 2} strokeDasharray={s.dash ? "5 4" : undefined}
                  strokeLinejoin="round" strokeLinecap="round" />
              </g>)}
          {(() => {
            // each event label takes the lowest row where it does not overlap another label
            const rows: [number, number][][] = [];
            return vmarks.map((m, i) => {
              const right = X(m.x) > W * 0.75, w = m.label.length * 6.4;
              const x0 = right ? X(m.x) - 5 - w : X(m.x) + 5;
              let r = 0;
              while (m.label && (rows[r] ?? []).some(([a, b]) => x0 < b + 6 && a < x0 + w + 6)) r++;
              (rows[r] ??= []).push([x0, x0 + w]);
              return <g key={i}><line x1={X(m.x)} x2={X(m.x)} y1={T} y2={h - B} stroke={m.color} strokeWidth={1.4} />
                {m.label && <text x={right ? X(m.x) - 5 : X(m.x) + 5} y={h - B - 8 - r * 14} textAnchor={right ? "end" : "start"} className="pl-lab" style={{ fill: m.color }}>{m.label}</text>}</g>;
            });
          })()}
          {now && <g><line x1={X(now.x)} x2={X(now.x)} y1={T} y2={h - B} className="pl-now" />
            <text x={X(now.x) + 4} y={T + 11} className="pl-lab pl-now-t">{now.label ?? "now"}</text></g>}
          {hx !== null && <g><line x1={X(hx)} x2={X(hx)} y1={T} y2={h - B} className="pl-cross" />
            {read.map((r) => <circle key={r.s.name} cx={X(r.x)} cy={Y(r.y!)} r={4} fill={r.s.color} className="pl-dot" />)}</g>}
        </svg>
        {hx !== null && read.length > 0 && (
          <div className="pl-tip" style={{ left: `${tipLeft}%`, transform: `translateX(${tipLeft > 60 ? "calc(-100% - 12px)" : "12px"})` }}>
            <b>{tipTitle ? tipTitle(read[0].x) : `${xTitle.split(" (")[0]}: ${xFmt(read[0].x)}`}</b>
            {read.map((r) => <div key={r.s.name}><i style={{ background: r.s.color }} />{r.s.name}<em>{(r.s.fmt ?? yFmt)(r.y!)}</em></div>)}
            {tipExtra?.(read[0].x).map(([k, v]) => <div key={k}><i />{k}<em>{v}</em></div>)}
          </div>
        )}
      </div>
      {legend && series.length > 1 && (
        <div className="pl-legend">{series.map((s) => (
          <button key={s.name} className={off.has(s.name) ? "off" : ""} title="Show / hide"
            onClick={() => setOff((o) => { const n = new Set(o); if (n.has(s.name)) n.delete(s.name); else n.add(s.name); return n; })}>
            <i style={{ background: s.color, opacity: s.dash ? 0.6 : 1 }} />{s.name}</button>))}</div>
      )}
    </div>
  );
}

/** Health colour: red (0) -> amber (50) -> green (100). */
export function hiColor(v: number) {
  const t = Math.max(0, Math.min(1, v / 100));
  const c = t < 0.5 ? [224 + (224 - 224) * t * 2, 80 + (160 - 80) * t * 2, 58 + (42 - 58) * t * 2]
    : [224 + (34 - 224) * (t - 0.5) * 2, 160 + (176 - 160) * (t - 0.5) * 2, 42 + (125 - 42) * (t - 0.5) * 2];
  return `rgb(${c.map((x) => Math.round(x)).join(",")})`;
}

/** Rows x time heat map: one row per item, colour = value (0..100), with a "now" line. */
export function Heat({ rows, x0, x1, xTitle, xFmt = fmtNum, now, cell, sel, pick, tip, xTicks, rh = 20 }: {
  rows: { id: string; label: string; v: number[] }[]; x0: number; x1: number; xTitle: string; xFmt?: (v: number) => string;
  now?: number; cell?: (v: number) => string; sel?: string; pick?: (id: string) => void; tip: (row: string, x: number, v: number) => string;
  xTicks?: number[]; rh?: number;
}) {
  const [hov, setHov] = useState<{ r: number; c: number } | null>(null);
  const [box, W] = useWidth<HTMLDivElement>();
  const L = W < 560 ? 112 : 160, R = 16, T = 6, RH = rh, B = 40, n = rows[0]?.v.length ?? 1;
  const h = T + rows.length * RH + B;
  const cw = (W - L - R) / n;
  const X = (x: number) => L + ((x - x0) / (x1 - x0)) * (W - L - R);
  const color = cell ?? hiColor;
  return (
    <div className="pl">
      <div className="pl-box" ref={box} onMouseLeave={() => setHov(null)}>
        <svg viewBox={`0 0 ${W} ${h}`}>
          {rows.map((r, i) => (
            <g key={r.id} onClick={() => pick?.(r.id)} style={{ cursor: pick ? "pointer" : undefined }}>
              <text x={L - 8} y={T + i * RH + RH / 2 + 4} textAnchor="end" className={`pl-row ${sel === r.id ? "on" : ""}`}>{fit(r.label, L - 12)}<title>{r.label}</title></text>
              {r.v.map((v, k) => <rect key={k} x={L + k * cw} y={T + i * RH + 1} width={cw + 0.4} height={RH - 2} fill={color(v)}
                onMouseEnter={() => setHov({ r: i, c: k })} />)}
              {sel === r.id && <rect x={L - 1} y={T + i * RH} width={W - L - R + 2} height={RH} className="pl-heat-sel" />}
            </g>))}
          {(xTicks ?? niceTicks(x0, x1, 6)).map((v) => <g key={v}><line x1={X(v)} x2={X(v)} y1={T + rows.length * RH} y2={T + rows.length * RH + 4} className="pl-axis" />
            <text x={X(v)} y={T + rows.length * RH + 16} textAnchor="middle" className="pl-tick">{xFmt(v)}</text></g>)}
          <text x={(L + W - R) / 2} y={h - 6} textAnchor="middle" className="pl-title">{xTitle}</text>
          {now !== undefined && <line x1={X(now)} x2={X(now)} y1={T - 2} y2={T + rows.length * RH + 2} className="pl-now heat" />}
        </svg>
        {hov && (() => {
          const r = rows[hov.r], x = x0 + ((hov.c + 0.5) / n) * (x1 - x0), left = ((L + (hov.c + 0.5) * cw) / W) * 100;
          return <div className="pl-tip" style={{ left: `${left}%`, top: (T + hov.r * RH) / h * 100 + "%", transform: `translateX(${left > 60 ? "calc(-100% - 12px)" : "12px"})` }}>
            <b>{r.label}</b><div>{tip(r.id, x, r.v[hov.c])}</div></div>;
        })()}
      </div>
    </div>
  );
}

/** Categorical bars with a y axis that need not start at 0 (`yMin`), reference lines and a
    read-out per bar. */
export function Bars({ bars, xTitle, yTitle, yMin, yMax, hlines = [], h = 220, yFmt = fmtNum, xLabelEvery = 1, base }: {
  bars: { key: string; label: string; v: number; color: string; tip: [string, string][] }[];
  xTitle: string; yTitle: string; yMin?: number; yMax?: number; hlines?: HLine[]; h?: number; yFmt?: (v: number) => string; xLabelEvery?: number;
  /** bars grow from this value (default: the bottom of the axis); 0 for signed values */
  base?: number;
}) {
  const [box, W] = useWidth<HTMLDivElement>();
  const [hov, setHov] = useState<number | null>(null);
  const L = 58, R = 16, T = 14, B = 42;
  const vs = bars.map((b) => b.v);
  const y0 = yMin ?? Math.min(0, ...vs), y1 = yMax ?? (Math.max(...vs, ...hlines.map((l) => l.y), 0) * 1.04 || 1);
  const b0 = base ?? y0;
  const Y = (v: number) => T + (1 - (Math.min(Math.max(v, y0), y1) - y0) / (y1 - y0)) * (h - T - B);
  const bw = (W - L - R) / bars.length;
  const every = W < 560 ? Math.max(xLabelEvery, 5) : xLabelEvery;
  return (
    <div className="pl">
      <div className="pl-box" ref={box} onMouseLeave={() => setHov(null)}>
        <svg viewBox={`0 0 ${W} ${h}`}>
          {niceTicks(y0, y1, 4).map((v) => <g key={v}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} className="pl-grid" />
            <text x={L - 7} y={Y(v) + 3.5} textAnchor="end" className="pl-tick">{yFmt(v)}</text></g>)}
          {bars.map((b, i) => <g key={b.key} onMouseEnter={() => setHov(i)}>
            <rect x={L + i * bw} y={T} width={bw} height={h - T - B} fill="transparent" />
            <rect x={L + i * bw + bw * 0.15} y={Math.min(Y(b.v), Y(b0))} width={bw * 0.7} height={Math.max(1, Math.abs(Y(b0) - Y(b.v)))} rx={2} fill={b.color} opacity={hov === null || hov === i ? 0.9 : 0.45} />
            {i % every === 0 && <text x={L + i * bw + bw / 2} y={h - B + 15} textAnchor="middle" className="pl-tick">{b.label}</text>}
          </g>)}
          <line x1={L} x2={W - R} y1={h - B} y2={h - B} className="pl-axis" />
          {hlines.map((l) => <g key={l.label}><line x1={L} x2={W - R} y1={Y(l.y)} y2={Y(l.y)} stroke={l.color} strokeDasharray="6 4" strokeWidth={1.3} />
            <text x={W - R - 4} y={Y(l.y) - 5} textAnchor="end" className="pl-lab" style={{ fill: l.color }}>{l.label} · {yFmt(l.y)}</text></g>)}
          <text x={(L + W - R) / 2} y={h - 6} textAnchor="middle" className="pl-title">{xTitle}</text>
          <text transform={`translate(13 ${(T + h - B) / 2}) rotate(-90)`} textAnchor="middle" className="pl-title">{yTitle}</text>
        </svg>
        {hov !== null && (() => {
          const b = bars[hov], left = ((L + (hov + 0.5) * bw) / W) * 100;
          return <div className="pl-tip" style={{ left: `${left}%`, transform: `translateX(${left > 60 ? "calc(-100% - 12px)" : "12px"})` }}>
            <b>{b.tip[0][1]}</b>{b.tip.slice(1).map(([k, v]) => <div key={k}><i />{k}<em>{v}</em></div>)}</div>;
        })()}
      </div>
    </div>
  );
}

/** Labelled points on two measures, with the better corner marked. */
export function Scatter({ pts, xTitle, yTitle, xFmt = fmtNum, yFmt = fmtNum, xMin = 0, yMin, yMax, better, h = 260 }: {
  pts: { label: string; x: number; y: number; color: string; tip: [string, string][] }[];
  xTitle: string; yTitle: string; xFmt?: (v: number) => string; yFmt?: (v: number) => string; xMin?: number; yMin?: number; yMax?: number;
  /** where the better corner is */ better: "top-left" | "top-right"; h?: number;
}) {
  const [box, W] = useWidth<HTMLDivElement>();
  const [hov, setHov] = useState<number | null>(null);
  const L = 58, R = 24, T = 18, B = 42;
  const x1 = Math.max(...pts.map((p) => p.x)) * 1.15 || 1;
  const y0 = yMin ?? Math.min(...pts.map((p) => p.y)) * 0.9, y1 = yMax ?? Math.max(...pts.map((p) => p.y)) * 1.05;
  const X = (v: number) => L + ((v - xMin) / (x1 - xMin)) * (W - L - R);
  const Y = (v: number) => T + (1 - (v - y0) / (y1 - y0)) * (h - T - B);
  const left = better === "top-left";
  return (
    <div className="pl">
      <div className="pl-box" ref={box} onMouseLeave={() => setHov(null)}>
        <svg viewBox={`0 0 ${W} ${h}`}>
          <rect x={left ? L : (L + W - R) / 2} y={T} width={(W - L - R) / 2} height={(h - T - B) / 2} className="sc-better" />
          <text x={left ? L + 8 : W - R - 8} y={T + 14} textAnchor={left ? "start" : "end"} className="sc-better-t">better {left ? "↖" : "↗"}</text>
          {niceTicks(y0, y1, 4).map((v) => <g key={v}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} className="pl-grid" />
            <text x={L - 7} y={Y(v) + 3.5} textAnchor="end" className="pl-tick">{yFmt(v)}</text></g>)}
          {niceTicks(xMin, x1, W < 560 ? 3 : 6).map((v) => <text key={v} x={X(v)} y={h - B + 16} textAnchor="middle" className="pl-tick">{xFmt(v)}</text>)}
          <line x1={L} x2={W - R} y1={h - B} y2={h - B} className="pl-axis" />
          <text x={(L + W - R) / 2} y={h - 6} textAnchor="middle" className="pl-title">{xTitle}</text>
          <text transform={`translate(13 ${(T + h - B) / 2}) rotate(-90)`} textAnchor="middle" className="pl-title">{yTitle}</text>
          {(() => {
            // labels of points that sit close together are stacked below one another
            const placed: { x: number; y: number; w: number }[] = [];
            return pts.map((p, i) => {
              const right = X(p.x) > W * 0.7;
              const wl = p.label.length * 6.8, x0 = right ? X(p.x) - 12 - wl : X(p.x) + 12;
              const hits = (y: number) => placed.some((q) => Math.abs(q.y - y) < 15 && q.x < x0 + wl && x0 < q.x + q.w)
                || pts.some((o, j) => j !== i && X(o.x) > x0 - 8 && X(o.x) < x0 + wl + 8 && Math.abs(Y(o.y) - (y - 4)) < 12);
              const ly = [4, -14, 22, -32, 40].map((d) => Y(p.y) + d).find((y) => !hits(y)) ?? Y(p.y) + 4;
              placed.push({ x: x0, y: ly, w: wl });
              return <g key={p.label} onMouseEnter={() => setHov(i)}>
                <circle cx={X(p.x)} cy={Y(p.y)} r={hov === i ? 9 : 7} fill={p.color} className="pl-dot" />
                {ly !== Y(p.y) + 4 && <line x1={X(p.x)} y1={Y(p.y)} x2={X(p.x) + (right ? -10 : 10)} y2={ly - 4} className="pl-axis" />}
                <text x={X(p.x) + (right ? -12 : 12)} y={ly} textAnchor={right ? "end" : "start"} className="sc-lab">{p.label}</text>
              </g>;
            });
          })()}
        </svg>
        {hov !== null && (() => {
          const p = pts[hov], lx = (X(p.x) / W) * 100;
          return <div className="pl-tip" style={{ left: `${lx}%`, top: `${(Y(p.y) / h) * 100}%`, transform: `translateX(${lx > 60 ? "calc(-100% - 14px)" : "14px"})` }}>
            <b>{p.label}</b>{p.tip.map(([k, v]) => <div key={k}><i />{k}<em>{v}</em></div>)}</div>;
        })()}
      </div>
    </div>
  );
}

/** Outcome shares per row as one 100 % bar each (e.g. warned in time / late / missed). */
export function Stacked({ rows, parts, unit = "" }: {
  rows: { label: string; v: number[]; on?: boolean }[]; parts: { name: string; color: string }[]; unit?: string;
}) {
  return (
    <div className="st">
      {rows.map((r) => {
        const tot = r.v.reduce((a, b) => a + b, 0) || 1;
        return (
          <div key={r.label} className={`st-row ${r.on ? "on" : ""}`}>
            <span className="st-name" title={r.label}>{r.label}</span>
            <span className="st-bar">{r.v.map((v, i) => v > 0 && (
              <i key={i} style={{ width: `${(v / tot) * 100}%`, background: parts[i].color }} title={`${parts[i].name}: ${v}${unit} (${Math.round((v / tot) * 100)} %)`}>
                {v / tot > 0.07 ? v : ""}</i>))}</span>
          </div>
        );
      })}
      <div className="pl-legend static">{parts.map((p) => <span key={p.name}><i style={{ background: p.color }} />{p.name}</span>)}</div>
    </div>
  );
}

/** Two values per row on one 0..1 scale, joined by a line: the gap is the story. */
export function Dumbbell({ rows, a, b, xTitle, fmt = (v: number) => `${Math.round(v * 100)} %`, max = 1, min = 0 }: {
  rows: { label: string; a: number; b: number; note?: string }[]; a: { name: string; color: string }; b: { name: string; color: string };
  xTitle: string; fmt?: (v: number) => string; /** the axis runs min..max */ max?: number; min?: number;
}) {
  const [box, W] = useWidth<HTMLDivElement>();
  const L = Math.min(W < 560 ? 120 : 220, Math.max(...rows.map((r) => r.label.length)) * 6.6 + 14), R = 20, T = 6, RH = 24, B = 38, h = T + rows.length * RH + B;
  const X = (v: number) => L + ((v - min) / (max - min)) * (W - L - R);
  return (
    <div className="pl">
      <div className="pl-box" ref={box}><svg viewBox={`0 0 ${W} ${h}`}>
        {(max === 1 && min === 0 ? [0, 0.25, 0.5, 0.75, 1] : niceTicks(min, max, W < 560 ? 3 : 5)).map((v) => <g key={v}><line x1={X(v)} x2={X(v)} y1={T} y2={T + rows.length * RH} className="pl-grid" />
          <text x={X(v)} y={T + rows.length * RH + 14} textAnchor="middle" className="pl-tick">{fmt(v)}</text></g>)}
        <text x={(L + W - R) / 2} y={h - 6} textAnchor="middle" className="pl-title">{xTitle}</text>
        {rows.map((r, i) => {
          const y = T + i * RH + RH / 2;
          return <g key={r.label}><title>{`${r.label}: ${a.name} ${fmt(r.a)}, ${b.name} ${fmt(r.b)}${r.note ? ` · ${r.note}` : ""}`}</title>
            <rect x={0} y={y - RH / 2} width={W} height={RH} fill="transparent" />
            <text x={L - 10} y={y + 4} textAnchor="end" className="pl-row">{fit(r.label, L - 14)}</text>
            <line x1={X(r.a)} x2={X(r.b)} y1={y} y2={y} className="db-gap" />
            <circle cx={X(r.b)} cy={y} r={6} fill={b.color} className="pl-dot" />
            <circle cx={X(r.a)} cy={y} r={6} fill={a.color} className="pl-dot" />
          </g>;
        })}
      </svg></div>
      <div className="pl-legend static"><span><i style={{ background: a.color, borderRadius: 4 }} />{a.name}</span><span><i style={{ background: b.color, borderRadius: 4 }} />{b.name}</span></div>
    </div>
  );
}

/** Horizontal bars on a value axis, with reference lines (e.g. before / after). */
export function HBar({ rows, xTitle, refs = [], fmt = fmtNum, x0 = 0, x1 }: {
  rows: { label: string; v: number; color: string; on?: boolean; tip?: string }[]; xTitle: string;
  refs?: { v: number; label: string; color: string }[]; fmt?: (v: number) => string; x0?: number; x1?: number;
}) {
  const [box, W] = useWidth<HTMLDivElement>();
  const L = Math.min(W < 560 ? 130 : 230, Math.max(...rows.map((r) => r.label.length)) * 6.6 + 14), R = 64, T = 18, RH = 24, B = 38;
  const h = T + rows.length * RH + B, top = x1 ?? Math.max(...rows.map((r) => r.v), ...refs.map((r) => r.v)) * 1.05;
  const X = (v: number) => L + ((v - x0) / (top - x0)) * (W - L - R);
  return (
    <div className="pl"><div className="pl-box" ref={box}><svg viewBox={`0 0 ${W} ${h}`}>
      {niceTicks(x0, top, W < 560 ? 3 : 5).map((v) => <g key={v}><line x1={X(v)} x2={X(v)} y1={T} y2={T + rows.length * RH} className="pl-grid" />
        <text x={X(v)} y={T + rows.length * RH + 14} textAnchor="middle" className="pl-tick">{fmt(v)}</text></g>)}
      <text x={(L + W - R) / 2} y={h - 6} textAnchor="middle" className="pl-title">{xTitle}</text>
      {rows.map((r, i) => {
        const y = T + i * RH;
        return <g key={r.label}><title>{r.tip ?? `${r.label}: ${fmt(r.v)}`}</title>
          {r.on && <rect x={0} y={y} width={W} height={RH} className="rw-hit on" />}
          <text x={L - 10} y={y + RH / 2 + 4} textAnchor="end" className={`pl-row ${r.on ? "on" : ""}`}>{fit(r.label, L - 14)}</text>
          <rect x={X(x0)} y={y + 5} width={Math.max(1, X(r.v) - X(x0))} height={RH - 10} rx={3} fill={r.color} opacity={0.85} />
          <text x={X(r.v) + 6} y={y + RH / 2 + 4} className="hb-v">{fmt(r.v)}</text></g>;
      })}
      {refs.map((r, i) => <g key={r.label}><line x1={X(r.v)} x2={X(r.v)} y1={T - 4} y2={T + rows.length * RH} stroke={r.color} strokeDasharray="5 3" strokeWidth={1.4} />
        <text x={X(r.v)} y={T - 6 - (i % 2) * 0} textAnchor={i % 2 ? "start" : "end"} dx={i % 2 ? 4 : -4} className="pl-lab" style={{ fill: r.color }}>{r.label}</text></g>)}
    </svg></div></div>
  );
}
