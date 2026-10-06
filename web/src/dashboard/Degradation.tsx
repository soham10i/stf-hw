// Docs: hardware degradation. The theory behind the Health page (health.py), each step as an
// equation with its source, and the model itself running live in the browser (degrade.ts) on
// any part's law, so every equation can be watched at work.
import { useEffect, useMemo, useRef, useState } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import type { HealthDoc } from "../shared/model";
import { useJson } from "../shared/data";
import { DegradeSim, type Law, type Theory } from "../shared/degrade";
import { PART_COL } from "./Health";

function TeX({ s, block }: { s: string; block?: boolean }) {
  const html = useMemo(() => katex.renderToString(s, { displayMode: !!block, throwOnError: false }), [s, block]);
  return <span className={block ? "dg-tex" : undefined} dangerouslySetInnerHTML={{ __html: html }} />;
}
const f = (x: number, d = 3) => (Math.abs(x) >= 1000 ? Math.round(x).toLocaleString() : x.toFixed(d));
/** a number inside LaTeX: the thousands comma without math spacing */
const tn = (x: number) => Math.round(x).toLocaleString("en").replace(/,/g, "{,}");
const k = (x: number) => (x >= 1000 ? `${(x / 1000).toFixed(x >= 1e5 ? 0 : 1)}k` : `${Math.round(x)}`);

// ---------------------------------------------------------------- the theory, step by step
type Step = { n: number; title: string; tex: string; say: string; refs: number[]; live?: (l: Law, T: Theory) => string; mark?: string };
const STEPS: Step[] = [
  { n: 1, title: "Normalised signal", tex: String.raw`r_n = \frac{y_n}{\bar b}`, refs: [1, 2], mark: "dots",
    say: "Each part's measurement (step time, motor current, compressor duty, colour margin) over its healthy baseline. 1 = as new." },
  { n: 2, title: "Wear path", tex: String.raw`r(n) = 1 + (r_f - 1)\left(\frac{n}{L}\right)^{p}`, refs: [3, 4, 5, 6], mark: "truth",
    say: "Power-law degradation. p = 1 linear (abrasion), p > 1 accelerating (fatigue), p = 10 sudden onset.",
    live: (l) => String.raw`p = ${l.p},\; L = ${tn(l.life)}` },
  { n: 3, title: "Failure threshold", tex: String.raw`r_f = \min_k \frac{W_k}{b_k}, \qquad T_f = \inf\{\, n : r(n) \ge r_f \,\} = L`, refs: [5], mark: "fail",
    say: "Fails when its tightest step hits its PLC watchdog W, or the breaker trips, the compressor saturates, a colour band is crossed.",
    live: (l) => String.raw`r_f = ${l.r_fail.toFixed(3)}` },
  { n: 4, title: "Measurement noise", tex: String.raw`y_n = r(n)\,(1+\varepsilon_n),\quad \varepsilon_n \sim \mathcal{N}(0,\sigma^2),\quad \sigma^2 = \sigma_p^2 + \tfrac{(\Delta/\bar b)^2}{12}`, refs: [7], mark: "dots",
    say: "2 % cycle-to-cycle spread plus the PLC scan's quantisation (scan time Δ).",
    live: (l) => String.raw`\sigma = ${(l.sigma * 100).toFixed(2)}\,\%` },
  { n: 5, title: "EWMA smoothing", tex: String.raw`z_n = z_{n-1} + \lambda\,(y_n - z_{n-1}),\qquad \sigma_z = \sigma\sqrt{\tfrac{\lambda}{2-\lambda}}`, refs: [8, 9, 10], mark: "ewma",
    say: "λ = 0.02 shrinks the noise ten-fold; a ramp is followed (1 − λ)/λ = 49 cycles late.",
    live: (l) => String.raw`\sigma_z = ${(l.sigma_z * 100).toFixed(3)}\,\%` },
  { n: 6, title: "Health index", tex: String.raw`\mathrm{HI}_n = 100\cdot \operatorname{clip}\!\left(\frac{r_f - z_n}{r_f - 1},\,0,\,1\right)`, refs: [2],
    say: "The margin to failure that is left. 100 = new, 0 = failing now." },
  { n: 7, title: "Warning 1: soft limit", tex: String.raw`z_n \ge 1 + s\,(r_f - 1) \;\Rightarrow\; n_s \approx L\,s^{1/p} + \tfrac{1-\lambda}{\lambda}`, refs: [10], mark: "soft",
    say: "Warn when half the margin is used (s = 0.5). The closed form matches the simulation within 1 %.",
    live: (l) => String.raw`n_s \approx ${tn(l.n_soft_theory)}` },
  { n: 8, title: "Warning 2: trend", tex: String.raw`\hat\beta_n = \frac{z_n - z_{n-W}}{W},\qquad \widehat{\mathrm{RUL}}_n = \frac{r_f - z_n}{\hat\beta_n} < 3\,m`, refs: [11, 12], mark: "trend",
    say: "Slope over W = 400 cycles, extrapolated to the limit; m = uses per shift. Catches sudden onset before the soft limit.",
    live: (l) => String.raw`3m = ${tn(l.rul_warn)}` },
  { n: 9, title: "No false alarms", tex: String.raw`\frac{s\,(r_f-1)}{\sigma_z},\qquad \frac{\beta^*}{\sigma_\beta},\quad \beta^* = \frac{r_f-1}{3m},\; \sigma_\beta = \frac{\sqrt2\,\sigma_z}{W}`, refs: [9],
    say: "A healthy machine's distance to each warning, in standard deviations. 60,000 healthy cycles raise none.",
    live: (l) => String.raw`${l.soft_margin_sigma}\sigma,\; ${l.trend_margin_sigma}\sigma` },
  { n: 10, title: "Lead time", tex: String.raw`\Delta_{\text{lead}} = \frac{T_f - n_{\text{warn}}}{m} \;\ge\; 1\ \text{shift}`, refs: [13],
    say: "The prognostic horizon: every warning leaves at least one shift change to renew the part.",
    live: (l) => String.raw`\Delta = ${l.lead_shifts}\ \text{shifts}` },
];

const REFS: [string, string | null][] = [
  ["ISO 13374-1:2003. Condition monitoring and diagnostics of machines — Data processing, communication and presentation — Part 1: General guidelines.", null],
  ["Jardine, A.K.S., Lin, D., Banjevic, D. (2006). A review on machinery diagnostics and prognostics implementing condition-based maintenance. Mechanical Systems and Signal Processing 20(7), 1483–1510.", "10.1016/j.ymssp.2005.09.012"],
  ["Archard, J.F. (1953). Contact and rubbing of flat surfaces. Journal of Applied Physics 24(8), 981–988.", "10.1063/1.1721448"],
  ["Paris, P., Erdogan, F. (1963). A critical analysis of crack propagation laws. Journal of Basic Engineering 85(4), 528–533.", "10.1115/1.3656900"],
  ["Lu, C.J., Meeker, W.Q. (1993). Using degradation measures to estimate a time-to-failure distribution. Technometrics 35(2), 161–174.", "10.1080/00401706.1993.10485038"],
  ["Meeker, W.Q., Escobar, L.A. (1998). Statistical Methods for Reliability Data, ch. 13: Degradation data. Wiley.", null],
  ["Widrow, B., Kollár, I. (2008). Quantization Noise: Roundoff Error in Digital Computation, Signal Processing, Control, and Communications. Cambridge University Press.", "10.1017/CBO9780511754661"],
  ["Roberts, S.W. (1959). Control chart tests based on geometric moving averages. Technometrics 1(3), 239–250.", "10.1080/00401706.1959.10489860"],
  ["Lucas, J.M., Saccucci, M.S. (1990). Exponentially weighted moving average control schemes: properties and enhancements. Technometrics 32(1), 1–12.", "10.1080/00401706.1990.10484583"],
  ["Montgomery, D.C. (2019). Introduction to Statistical Quality Control, 8th ed., ch. 9: CUSUM and EWMA charts. Wiley.", null],
  ["Si, X.-S., Wang, W., Hu, C.-H., Zhou, D.-H. (2011). Remaining useful life estimation — A review on the statistical data driven approaches. European Journal of Operational Research 213(1), 1–14.", "10.1016/j.ejor.2010.11.018"],
  ["Lei, Y., Li, N., Guo, L., Li, N., Yan, T., Lin, J. (2018). Machinery health prognostics: A systematic review from data acquisition to RUL prediction. Mechanical Systems and Signal Processing 104, 799–834.", "10.1016/j.ymssp.2017.11.016"],
  ["Saxena, A., Celaya, J., Balaban, E., Goebel, K., Saha, B., Saha, S., Schwabacher, M. (2008). Metrics for evaluating performance of prognostic techniques. Int. Conf. on Prognostics and Health Management (PHM 2008), IEEE.", "10.1109/PHM.2008.4711436"],
];

// ---------------------------------------------------------------- live charts
const MARK_COL: Record<string, string> = { dots: "var(--faint)", truth: "var(--text)", ewma: "var(--accent)", soft: "var(--warn)", fail: "var(--bad)", trend: "#c06bd6" };
/** A step number, as on the equations below. */
const N = ({ n, c }: { n: number; c?: string }) => <span className="dg-b" style={c ? { background: c } : undefined}>{n}</span>;

function SignalLive({ sim, ref0 }: { sim: DegradeSim; ref0: [number, number][] | null }) {
  const l = sim.law, W = 900, H = 260, L = 44, R = 12, T = 10, B = 24;
  const sig = l.sigma * sim.o.noise;
  const [y0, y1] = sim.o.degrade ? [1 - 3 * sig, l.r_fail * 1.08] : [1 - 4.5 * sig, 1 + 4.5 * sig];
  const X = (n: number) => L + (n / sim.nMax) * (W - L - R);
  const Y = (r: number) => T + (1 - (Math.min(Math.max(r, y0), y1) - y0) / (y1 - y0)) * (H - T - B);
  const S = sim.samples;
  const line = (g: (s: (typeof S)[0]) => number) => S.map((s, i) => `${i ? "L" : "M"}${X(s.n).toFixed(1)},${Y(g(s)).toFixed(1)}`).join("");
  const truth = sim.o.degrade ? Array.from({ length: 121 }, (_, i) => { const n = (i / 120) * sim.nMax; return `${i ? "L" : "M"}${X(n).toFixed(1)},${Y(sim.truth(n)).toFixed(1)}`; }).join("") : "";
  const trend = sim.beta !== null && sim.beta > 0 && sim.rul !== null && isFinite(sim.rul) && !sim.fail
    ? { x0: sim.n - sim.o.window, y0: sim.z - sim.beta * sim.o.window, x1: Math.min(sim.nMax, sim.n + sim.rul) } : null;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((q) => q * sim.nMax);
  return (
    <div className="mo-chart">
      <svg viewBox={`0 0 ${W} ${H}`}>
        {(sim.o.degrade ? [1, sim.soft, l.r_fail] : [y0, 1, y1]).filter((v) => v >= y0 && v <= y1).map((v) => (
          <g key={v}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} className="mo-grid" /><text x={L - 5} y={Y(v) + 3} textAnchor="end" className="mo-ax">{v.toFixed(sim.o.degrade ? 2 : 3)}</text></g>))}
        {ticks.map((n) => <text key={n} x={X(n)} y={H - 7} textAnchor="middle" className="mo-ax">{k(n)}</text>)}
        {sim.soft <= y1 && <><line x1={L} x2={W - R} y1={Y(sim.soft)} y2={Y(sim.soft)} stroke={MARK_COL.soft} strokeDasharray="6 4" />
          <text x={W - R - 2} y={Y(sim.soft) - 4} textAnchor="end" className="mo-ax" style={{ fill: MARK_COL.soft }}>soft limit (7)</text></>}
        {l.r_fail <= y1 && <><line x1={L} x2={W - R} y1={Y(l.r_fail)} y2={Y(l.r_fail)} stroke={MARK_COL.fail} strokeDasharray="6 4" />
          <text x={W - R - 2} y={Y(l.r_fail) - 4} textAnchor="end" className="mo-ax" style={{ fill: MARK_COL.fail }}>failure r_f (3)</text></>}
        {S.map((s) => <circle key={s.n} cx={X(s.n)} cy={Y(s.y)} r={1.6} fill={MARK_COL.dots} opacity={0.55} />)}
        {truth && <path d={truth} fill="none" stroke={MARK_COL.truth} strokeWidth={1} strokeDasharray="2 3" opacity={0.6} />}
        {ref0 && <path d={ref0.filter(([n]) => n <= sim.n).map(([n, z], i) => `${i ? "L" : "M"}${X(n).toFixed(1)},${Y(z).toFixed(1)}`).join("")} fill="none" stroke="var(--ok)" strokeWidth={4} opacity={0.18} />}
        <path d={line((s) => s.z)} fill="none" stroke={MARK_COL.ewma} strokeWidth={2.2} />
        {trend && <line x1={X(trend.x0)} y1={Y(trend.y0)} x2={X(trend.x1)} y2={Y(sim.z + sim.beta! * (trend.x1 - sim.n))} stroke={MARK_COL.trend} strokeWidth={1.6} strokeDasharray="5 3" />}
        {sim.warn && <g><line x1={X(sim.warn.n)} x2={X(sim.warn.n)} y1={T} y2={H - B} stroke={MARK_COL.soft} strokeWidth={1.4} />
          <text x={X(sim.warn.n) - 4} y={T + 12} textAnchor="end" className="mo-ax" style={{ fill: MARK_COL.soft }}>warning</text></g>}
        {sim.fail !== null && <g><line x1={X(sim.fail)} x2={X(sim.fail)} y1={T} y2={H - B} stroke={MARK_COL.fail} strokeWidth={1.4} />
          <text x={X(sim.fail) - 4} y={H - B - 6} textAnchor="end" className="mo-ax" style={{ fill: MARK_COL.fail }}>failure</text></g>}
        <circle cx={X(sim.n)} cy={Y(sim.z)} r={4.5} fill={MARK_COL.ewma} className="hl-dot" />
      </svg>
      <div className="mo-legend">
        <span><N n={4} c={MARK_COL.dots} />measured y</span>
        {sim.o.degrade && <span><N n={2} c={MARK_COL.truth} />true wear r(n)</span>}
        <span><N n={5} c={MARK_COL.ewma} />EWMA z</span>
        <span><N n={8} c={MARK_COL.trend} />trend → RUL</span>
        {ref0 && <span><i style={{ background: "var(--ok)", opacity: 0.4 }} />health.py's run (same law)</span>}
        <span className="dg-x">x: uses</span>
      </div>
    </div>
  );
}

function Mini({ sim, kind }: { sim: DegradeSim; kind: "hi" | "rul" }) {
  const l = sim.law, W = 440, H = 150, L = 34, R = 8, T = 10, B = 20, S = sim.samples;
  const xs = sim.nMax / l.per_shift;
  const X = (n: number) => L + (n / l.per_shift / xs) * (W - L - R);
  const top = kind === "hi" ? 100 : (l.life / l.per_shift) * 1.25;
  const Y = (v: number) => T + (1 - Math.min(Math.max(v, 0), top) / top) * (H - T - B);
  const pts = kind === "hi" ? S.map((s) => [s.n, s.hi] as const) : S.filter((s) => s.rul !== null).map((s) => [s.n, s.rul! / l.per_shift] as const);
  const d = pts.map(([n, v], i) => `${i ? "L" : "M"}${X(n).toFixed(1)},${Y(v).toFixed(1)}`).join("");
  const alpha = 0.3, Tf = l.life;
  const cone = kind === "rul" && sim.o.degrade
    ? `M${X(0)},${Y((Tf / l.per_shift) * (1 + alpha))} L${X(Tf)},${Y(0)} L${X(0)},${Y((Tf / l.per_shift) * (1 - alpha))} Z` : "";
  return (
    <div className="mo-chart">
      <svg viewBox={`0 0 ${W} ${H}`}>
        {[0, top / 2, top].map((v) => <g key={v}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} className="mo-grid" /><text x={L - 4} y={Y(v) + 3} textAnchor="end" className="mo-ax">{Math.round(v)}</text></g>)}
        <text x={L} y={H - 5} className="mo-ax">0</text><text x={W - R} y={H - 5} textAnchor="end" className="mo-ax">{xs.toFixed(0)} shifts</text>
        {kind === "hi" && <rect x={L} y={Y(50)} width={W - L - R} height={Y(0) - Y(50)} className="hl-zone warn" />}
        {cone && <path d={cone} className="dg-cone" />}
        {cone && <line x1={X(0)} y1={Y(Tf / l.per_shift)} x2={X(Tf)} y2={Y(0)} stroke="var(--text)" strokeDasharray="2 3" opacity={0.6} />}
        {kind === "rul" && <><line x1={L} x2={W - R} y1={Y(3)} y2={Y(3)} stroke={MARK_COL.soft} strokeDasharray="5 3" />
          <text x={W - R - 2} y={Y(3) - 3} textAnchor="end" className="mo-ax" style={{ fill: MARK_COL.soft }}>3 shifts</text></>}
        {kind === "hi" ? <path d={d} fill="none" stroke="var(--ok)" strokeWidth={2} />
          : pts.map(([n, v]) => <circle key={n} cx={X(n)} cy={Y(v)} r={1.8} fill={MARK_COL.trend} opacity={v > top ? 0 : 0.8} />)}
      </svg>
    </div>
  );
}

// ---------------------------------------------------------------- page
export function DegradationPage({ h }: { h: HealthDoc }) {
  const th = useJson<Theory>("health/theory.json", "No theory file yet. Run: make health-theory");
  const [part, setPart] = useState("cup");
  const [lambda, setLambda] = useState(0.02);
  const [noise, setNoise] = useState(1);
  const [degrade, setDegrade] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [play, setPlay] = useState(true);
  const [seed, setSeed] = useState(6);
  const [, tick] = useState(0);
  const simRef = useRef<DegradeSim | null>(null);
  const T = th.data;
  const law = T?.components.find((c) => c.id === part) ?? null;
  useEffect(() => {
    if (!T || !law) return;
    simRef.current = new DegradeSim(law, { lambda, soft: T.rules.soft, window: T.rules.window, noise, degrade, seed });
    tick((x) => x + 1);
  }, [T, law, lambda, noise, degrade, seed]);
  useEffect(() => {
    if (!play) return;
    let id = 0, last = performance.now();
    const loop = (now: number) => {
      const sim = simRef.current;
      if (sim && !sim.done) {
        const dt = Math.min(0.5, (now - last) / 1000);
        sim.step(Math.max(1, Math.round((sim.nMax / 36) * speed * dt)));    // one life in ~30 s at 1x
        tick((x) => x + 1);
      }
      last = now;
      id = requestAnimationFrame(loop);
    };
    id = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(id);
  }, [play, speed]);
  if (th.error) return <div className="db-err">{th.error}</div>;
  const sim = simRef.current;
  if (!T || !law || !sim) return <div className="db-err">loading the theory…</div>;
  const hc = h.components.find((c) => c.id === part)!;
  const isDefault = degrade && noise === 1 && Math.abs(lambda - T.rules.lambda) < 1e-9;
  const ref0 = isDefault ? hc.curve.map((p) => [p[0], p[1]] as [number, number]) : null;
  const status = sim.fail !== null ? "fail" : sim.warn ? "warn" : "ok";
  const rulSh = sim.rul !== null && isFinite(sim.rul) ? sim.rul / law.per_shift : null;
  const lead = sim.fail !== null && sim.warn ? (sim.fail - sim.warn.n) / law.per_shift : null;
  const idx = h.components.findIndex((c) => c.id === part);
  return (
    <div className="dg">
      <p className="dg-lede">Why a part's health falls, and how the twin knows before it fails — every step below is running live on the chart.</p>

      <section className="db-card dg-live">
        <h3>Live: {hc.name}<span className={`hl-pill ${status}`}>{status === "fail" ? `failed at ${k(sim.fail!)}` : status === "warn" ? `warned (${sim.warn!.by})` : "healthy"}</span></h3>
        <div className="dg-ctl">
          <div className="db-chips">{T.components.map((c, i) => (
            <button key={c.id} className={c.id === part ? "on" : ""} onClick={() => setPart(c.id)}>
              <i className="dg-sw" style={{ background: PART_COL[i] }} />{h.components[i].name.replace(/ \(.*\)$/, "")}</button>))}</div>
          <div className="dg-knobs">
            <button className="ui-btn icon" onClick={() => setPlay(!play)} aria-label={play ? "Pause" : "Play"}>{play ? "❚❚" : "▶"}</button>
            <button className="ui-btn" onClick={() => setSeed((s) => s + 1)}>Restart</button>
            <div className="ui-seg">{[1, 4].map((v) => <button key={v} className={speed === v ? "on" : ""} onClick={() => setSpeed(v)}>{v}×</button>)}</div>
            <div className="ui-seg"><button className={degrade ? "on" : ""} onClick={() => setDegrade(true)}>wearing</button><button className={!degrade ? "on" : ""} onClick={() => setDegrade(false)}>healthy</button></div>
            <label>λ <input type="range" min={0.005} max={0.2} step={0.005} value={lambda} onChange={(e) => setLambda(+e.target.value)} /><span className="mono">{lambda.toFixed(3)}</span></label>
            <label>noise <input type="range" min={1} max={8} step={0.5} value={noise} onChange={(e) => setNoise(+e.target.value)} /><span className="mono">{noise}×</span></label>
          </div>
        </div>
        <SignalLive sim={sim} ref0={ref0} />
        <div className="dg-row">
          <div className="dg-mini"><h4><N n={6} /> Health index</h4><Mini sim={sim} kind="hi" /></div>
          <div className="dg-mini"><h4><N n={8} c={MARK_COL.trend} /> Estimated RUL vs true <span className="db-muted">· ±30 % cone</span></h4><Mini sim={sim} kind="rul" /></div>
          <div className="dg-read">
            <div><span>cycle n</span><b>{sim.n.toLocaleString()}</b></div>
            <div><span><N n={4} /> measured y</span><b>{f(sim.y)}</b></div>
            <div><span><N n={5} c={MARK_COL.ewma} /> EWMA z</span><b>{f(sim.z)}</b></div>
            <div className="dg-eq"><TeX s={String.raw`\mathrm{HI} = 100\,(${law.r_fail.toFixed(2)} - ${sim.z.toFixed(2)})/${(law.r_fail - 1).toFixed(2)} = ${sim.hi.toFixed(0)}`} /></div>
            <div className="dg-eq">{sim.fail !== null ? <span className="db-muted">failed: no life left</span> : rulSh !== null ? <TeX s={String.raw`\widehat{\mathrm{RUL}} = (r_f - z)/\hat\beta = ${rulSh > 999 ? "\\gg 999" : rulSh.toFixed(1)}\ \text{shifts}`} /> : <span className="db-muted"><N n={8} /> trend needs W = {T.rules.window} cycles</span>}</div>
            {lead !== null && <div className={lead >= 1 ? "ok" : "bad"}><span><N n={10} /> lead time</span><b>{lead.toFixed(1)} shifts</b></div>}
            {sim.warn && <div><span>warned at · this run</span><b>{sim.warn.n.toLocaleString()}</b></div>}
            {isDefault && law.warn_sim !== null && <div><span>warned at · health.py</span><b>{law.warn_sim.toLocaleString()}</b></div>}
          </div>
        </div>
        <p className="hl-cap">Try: <b>healthy</b> — no warning ever (9) · <b>noise 8×</b> — λ has to shrink · <b>VGR gearbox</b> — the trend warns before the soft limit.</p>
      </section>

      <div className="dg-steps">
        {STEPS.map((s) => (
          <section key={s.n} className="db-card dg-step">
            <h3><N n={s.n} c={s.mark ? MARK_COL[s.mark] : undefined} />{s.title}
              <span className="dg-refs">{s.refs.map((r) => <a key={r} href={`#ref-${r}`}>[{r}]</a>)}</span></h3>
            <TeX s={s.tex} block />
            <p>{s.say}</p>
            {s.live && <div className="dg-live-v"><span style={{ color: PART_COL[idx] }}>●</span> {hc.name.replace(/ \(.*\)$/, "")}: <TeX s={s.live(law, T)} /></div>}
          </section>
        ))}
      </div>

      <section className="db-card">
        <h3>Every part: closed form vs simulation</h3>
        <table className="db-table">
          <thead><tr><td>part</td><td className="num">p</td><td className="num">life L</td><td className="num">r_f</td><td className="num">σ</td>
            <td className="num">n_s theory (7)</td><td className="num">warned (sim)</td><td className="num">lead (10)</td><td className="num">margin (9)</td></tr></thead>
          <tbody>{T.components.map((c, i) => (
            <tr key={c.id} className={c.id === part ? "on" : ""} onClick={() => setPart(c.id)} style={{ cursor: "pointer" }}>
              <td><i className="dg-sw" style={{ background: PART_COL[i] }} />{h.components[i].name.replace(/ \(.*\)$/, "")}</td>
              <td className="num">{c.p}</td><td className="num">{k(c.life)}</td><td className="num">{c.r_fail.toFixed(2)}</td><td className="num">{(c.sigma * 100).toFixed(1)} %</td>
              <td className="num">{k(c.n_soft_theory)}</td><td className="num">{c.warn_sim ? k(c.warn_sim) : "–"}{c.warn_by?.startsWith("trend") ? " ·8" : ""}</td>
              <td className="num">{c.lead_shifts} sh</td><td className="num">{Math.min(c.soft_margin_sigma, c.trend_margin_sigma)} σ</td>
            </tr>))}</tbody>
        </table>
        <p className="hl-cap">{T.fails.length ? `Check failed: ${T.fails.join("; ")}` : "All agree (health_theory.py). ·8 = warned by the trend (8), before the soft limit."} Wear laws, lives and noise are assumed, not measured.</p>
      </section>

      <section className="db-card">
        <h3>References</h3>
        <ol className="dg-ref">{REFS.map(([r, doi], i) => <li key={i} id={`ref-${i + 1}`}>{r}{doi && <> <a href={`https://doi.org/${doi}`} target="_blank" rel="noreferrer">doi:{doi}</a></>}</li>)}</ol>
      </section>
    </div>
  );
}
