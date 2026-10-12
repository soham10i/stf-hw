// Vision QC: the inspection camera's live feed. Every cookie the line makes is photographed
// (the camera in the colour hood, vision/mount.py), classified by the CNN, scored by the
// autoencoder and checked against what the simulation knows - is the model still right?
// With the 3D twin open in another tab, the feed photographs the twin's own cookies.
import { Dumbbell, Plot } from "./Plot";
import { roll } from "./Month";
import { useEffect, useMemo, useRef, useState } from "react";
import { loadJson, useJson } from "../shared/data";
import { decodeAe, type Ae } from "../vision/ae";
import { decode, type Cnn } from "../vision/cnn";
import { CHANNEL, LiveLine, SCENARIOS, drift, tally, type Frame, type Scenario } from "../vision/live";
import { chw, rgba, type RenderParams } from "../vision/render";
import { OnlineBn, decodeAdapt, forwardBn, verdictOf, type AdaptNet, type Domain } from "../vision/adapt";
import { HBar } from "./Plot";

type Camera = { fov_mm: number; optics: { working_distance_mm: number; lens_angle_deg: number; trigger_delay_s: number; roi_mm: number };
                checks: { check: string; ok: boolean; detail: string }[]; why_here: string };
type CnnRes = { results: Record<"in_domain" | "shifted", { condition_acc: number; escape_rate: number; false_reject: number }> };
const pct = (x: number, d = 0) => `${(100 * x).toFixed(d)} %`;
const KEEP = 400;

function useModels() {
  const [m, setM] = useState<{ cnn: Cnn; ae: Ae; P: RenderParams } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([loadJson("vision/weights.json"), loadJson("vision/autoencoder.json"), loadJson<RenderParams>("vision/render.json")])
      .then(([w, a, P]) => setM({ cnn: decode(w as never), ae: decodeAe(a as never), P }))
      .catch((e) => setErr((e as Error).message));
  }, []);
  return { m, err };
}

function Pic({ img, N, scale, err, max }: { img: Float32Array; N: number; scale: number; err?: Float32Array; max?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const cx = cv.getContext("2d")!;
    const data = err
      ? (() => {                       // the error map: dark = rebuilt well, hot = not
          const o = new Uint8ClampedArray(N * N * 4);
          for (let i = 0; i < N * N; i++) {
            const v = Math.min(1, err[i] / (max ?? 1));
            o[i * 4] = 255 * Math.min(1, v * 2); o[i * 4 + 1] = 255 * Math.max(0, v * 2 - 1); o[i * 4 + 2] = 40 + 80 * (1 - v); o[i * 4 + 3] = 255;
          }
          return o;
        })()
      : rgba(img, N);
    cx.putImageData(new ImageData(data, N, N), 0, 0);
  }, [img, N, err, max]);
  return <canvas ref={ref} width={N} height={N} className="vq-pic" style={{ width: N * scale, height: N * scale }} />;
}

type Arm = { right: boolean; verdict: "pass" | "reject" | "check" };
type AB = { n: number; truth: string; scenario: Scenario; src: Arm; ada: Arm; shift: number };

/** Every frame classified twice: with the training statistics, and with statistics adapted
    online from the frames themselves (AdaBN, no labels). */
function useAdaptation(frames: Frame[], on: boolean, net: AdaptNet | null, epoch: number) {
  const [ab, setAb] = useState<AB[]>([]);
  const est = useRef<OnlineBn | null>(null);
  const seen = useRef(0);
  useEffect(() => { est.current = net ? new OnlineBn(net) : null; setAb([]); }, [net, epoch]);
  useEffect(() => {
    const f = frames[frames.length - 1];
    if (!net || !est.current || !f || f.n <= seen.current) return;
    seen.current = f.n;
    const x = chw(f.img, net.size), ci = net.classes.condition;
    const arm = (o: ReturnType<typeof forwardBn>): Arm => ({ right: ci[o.condition.indexOf(Math.max(...o.condition))] === f.truth, verdict: verdictOf(net, o.condition) });
    const s = forwardBn(net, x, net.bn.map((b) => ({ mean: b.mean, var: b.var })));
    const a = forwardBn(net, x, est.current.stats());
    if (on) est.current.add(a.moments);                          // classify first, then learn from the frame
    setAb((v) => [...v.slice(-(KEEP - 1)), { n: f.n, truth: f.truth, scenario: f.scenario, src: arm(s), ada: arm(on ? a : s), shift: est.current!.shift() }]);
  }, [frames, net, on]);
  return ab;
}

function rate(ab: AB[], k: "src" | "ada") {
  const good = ab.filter((x) => x.truth === "ok");
  return { right: ab.filter((x) => x[k].right).length / Math.max(1, ab.length), fr: good.filter((x) => x[k].verdict === "reject").length / Math.max(1, good.length) };
}

const MNAME: Record<string, string> = { deployed: "as deployed", source: "settled statistics", adabn: "AdaBN (no labels)", "adabn, balanced": "AdaBN, balanced (no labels)",
  tent: "TENT (no labels)", "self-training": "self-training (no labels)", "few labels": "10 labels per condition", retrained: "retrained with new data" };
const MCOL = (k: string) => (k === "deployed" ? "#9aa7b4" : k === "source" ? "#6c7884" : k === "retrained" ? "#b07ad6" : k === "few labels" ? "#4f8fd6" : "#e0a02a");

function Adaptation({ ab, net, on, setOn, reset }: { ab: AB[]; net: AdaptNet; on: boolean; setOn: (v: boolean) => void; reset: () => void }) {
  const W50 = ab.slice(-50), s = rate(W50, "src"), a = rate(W50, "ada");
  const R = net.results, D: Domain = "new line, as delivered", OLD: Domain = "old line";
  const keys = ["deployed", "source", "adabn", "adabn, balanced", "tent", "self-training", "few labels", "retrained"].filter((k) => R[k]);
  const src = R.source[D], ret = R.retrained[D], dep = R.deployed[D], G = net.guard;
  const chip = R.source["new line"].recall.chipped;
  return (
    <>
      <section className="db-card wide"><h3>When the drift alarm rings: what actually helps</h3>
        <div className="vq-find four">
          <div><b>The deployed network fails safe.</b> On the new line it rejects {pct(dep.false_reject)} of good cookies but passes only {pct(dep.escape_rate)} of defects.
            With its statistics settled it is perfect on the old line, yet passes {pct(src.escape_rate)} of defects here: it fails unsafe.</div>
          <div><b>Adapting without labels hurts.</b> The line delivers {Math.round((1 - net.meta.defect_rate) * 100)} % good cookies; training was balanced.
            Statistics re-estimated on the line absorb that change of mix, and good cookies get rejected.</div>
          <div><b>The weak spot is one defect.</b> Only {pct(chip)} of chipped cookies are caught under the new conditions: blur and a lighter belt hide the edge.
            Labelled chips fix it (retrained: {pct(R.retrained["new line"].recall.chipped)}); no label-free method can.</div>
          <div><b>Until labels arrive: a safeguard.</b> What the autoencoder finds unusual goes to a person. Escapes {pct(G.source["CNN alone"].escapes, 1)} → {pct(G.source["CNN + autoencoder"].escapes, 1)}
            {" "}for {pct(G.source["CNN + autoencoder"].good_to_person)} of good cookies checked by hand.</div>
        </div>
        <div className="gr-four">
          <div><h4>new line, as delivered: right (%)</h4>
            <HBar xTitle="" x1={100} fmt={(v) => `${v.toFixed(1)}`} refs={[{ v: dep.condition_acc * 100, label: "as deployed", color: "#9aa7b4" }]}
              rows={keys.map((k) => ({ label: MNAME[k], v: R[k][D].condition_acc * 100, color: MCOL(k), on: k === "deployed", tip: net.meta.methods[k] }))} /></div>
          <div><h4>good cookies thrown out (%)</h4>
            <HBar xTitle="" fmt={(v) => `${v.toFixed(1)}`} rows={keys.map((k) => ({ label: MNAME[k], v: R[k][D].false_reject * 100, color: MCOL(k), on: k === "deployed" }))} /></div>
          <div><h4>defects passed as good (%)</h4>
            <HBar xTitle="" fmt={(v) => `${v.toFixed(1)}`} rows={keys.map((k) => ({ label: MNAME[k], v: R[k][D].escape_rate * 100, color: MCOL(k), on: k === "deployed" }))} /></div>
          <div><h4>old line still right (%)</h4>
            <HBar xTitle="" x1={100} fmt={(v) => `${v.toFixed(1)}`} rows={keys.map((k) => ({ label: MNAME[k], v: R[k][OLD].condition_acc * 100, color: MCOL(k), on: k === "deployed" }))} /></div>
        </div>
        <p className="hl-cap">Held-out rendered images of the changed line, in the mix the line delivers. Hover a method for what it does.</p>
      </section>
      <section className="db-card hl-span2"><h3>The pass threshold: escapes against false rejects</h3>
        <Plot h={250} xTitle="good cookies thrown out (%)" yTitle="defects passed (%)" yMin={0} xMin={0} yFmt={(v) => v.toFixed(0)} xFmt={(v) => v.toFixed(0)}
          series={(["deployed", "source", "retrained"] as const).map((k) => ({ name: MNAME[k], x: net.tradeoff[k].map((t) => t.false_rejects * 100), y: net.tradeoff[k].map((t) => t.escapes * 100),
            color: MCOL(k), width: 2.4, fmt: (v: number) => `${v.toFixed(1)} %` }))}
          tipTitle={(x) => { const t = net.tradeoff.source.reduce((p, q) => (Math.abs(q.false_rejects * 100 - x) < Math.abs(p.false_rejects * 100 - x) ? q : p)); return `pass if p(ok) ≥ ${t.p}`; }} />
        <p className="hl-cap">Each point is a pass threshold from {net.tradeoff.source[0].p} to {net.tradeoff.source[net.tradeoff.source.length - 1].p}. Set it live above (“Pass threshold”). Retraining with new data moves the whole curve down.</p>
      </section>
      <section className="db-card"><h3>How many labels are worth it</h3>
        <Plot h={250} xTitle="labelled frames of the new line" yTitle="defects passed (%)" yMin={0} yFmt={(v) => v.toFixed(0)}
          series={[{ name: "final layers tuned", x: net.curve.map((c) => c.labels), y: net.curve.map((c) => c[D].escape_rate * 100), color: "#4f8fd6", width: 2.6, fmt: (v) => `${v.toFixed(1)} %` }]}
          hlines={[{ y: src.escape_rate * 100, color: "#6c7884", label: "settled, no labels" }, { y: ret.escape_rate * 100, color: "#b07ad6", label: "retrained" }]}
          tipExtra={(x) => { const c = net.curve.find((q) => q.labels === x); return c ? [["right", pct(c[D].condition_acc, 1)], ["false rejects", pct(c[D].false_reject, 1)], ["old line right", pct(c[OLD].condition_acc, 1)]] : []; }} legend={false} />
        <p className="hl-cap">Tuning only the final layers is safe for the old line, but a few labels cannot teach the feature extractor to see a blurred chip.</p>
      </section>
      <section className="db-card wide"><h3>The safeguard: unusual cookies to a person once the alarm rings</h3>
        {(() => {
          const rows = (["deployed", "source"] as const).flatMap((k) => (["CNN alone", "CNN + autoencoder"] as const).map((r) => ({ k, r, g: G[k][r] })));
          const chart = (title: string, get: (g: (typeof rows)[0]["g"]) => number, col: string) => (
            <div><h4>{title}</h4>
              <HBar xTitle="" fmt={(v) => `${v.toFixed(1)}`} rows={rows.map(({ k, r, g }) => ({ label: `${MNAME[k]} · ${r === "CNN alone" ? "alone" : "+ autoencoder"}`, v: get(g) * 100, color: col, on: r !== "CNN alone" }))} /></div>);
          return <div className="gr-four three">
            {chart("defects passed (% of defects)", (g) => g.escapes, "var(--bad)")}
            {chart("checked by a person (% of all cookies)", (g) => g.to_person, "var(--warn)")}
            {chart("good cookies rejected (% of good)", (g) => g.false_rejects, "#6c7884")}
          </div>;
        })()}
        <p className="hl-cap">New line, as delivered. The person sees a share of all cookies (amber) and decides; the autoencoder never saw a defect, so this needs no labels.</p>
      </section>
      <section className="db-card wide">
        <h3>Experiment: label-free adaptation, live
          <div className="ui-seg db-mini-seg"><button className={on ? "on" : ""} onClick={() => setOn(true)}>on</button><button className={!on ? "on" : ""} onClick={() => setOn(false)}>off</button></div>
          <button className="ui-btn" onClick={reset}>Reset</button></h3>
        <div className="vq-ab">
          <div><span>settled network</span><b>{pct(s.right)}</b><em>right · false rejects {pct(s.fr)}</em></div>
          <div className={on ? "on" : ""}><span>adapted online (AdaBN)</span><b>{on ? pct(a.right) : "off"}</b><em>{on ? `right · false rejects ${pct(a.fr)}` : "switch on to try it"}</em></div>
          <div><span>statistics moved</span><b>{ab.length ? ab[ab.length - 1].shift.toFixed(2) : "–"}</b><em>first layer, training σ units</em></div>
        </div>
        {ab.length > 2 && (
          <Plot h={210} xTitle="cookie number" yTitle="right, 30-cookie mean (%)" yMin={0} yMax={100} yFmt={(v) => `${Math.round(v)}`}
            series={[{ name: "settled network", x: ab.map((x) => x.n), y: roll(ab.map((x) => (x.src.right ? 100 : 0)), 30), color: "#6c7884", width: 2.2, fmt: (v) => `${v.toFixed(0)} %` },
                     ...(on ? [{ name: "adapted online", x: ab.map((x) => x.n), y: roll(ab.map((x) => (x.ada.right ? 100 : 0)), 30), color: "#e0a02a", width: 2.4, fmt: (v: number) => `${v.toFixed(0)} %` }] : [])]}
            vmarks={ab.filter((x, i) => i > 0 && x.scenario !== ab[i - 1].scenario).map((x) => ({ x: x.n, color: "var(--muted)", label: SCENARIOS[x.scenario].label }))}
            tipTitle={(x) => `cookie #${Math.round(x)}`} />
        )}
        <p className="hl-cap">The same cookies, classified twice; the adapted network re-estimates its statistics cookie by cookie, without labels. Switch it on and watch it reject good cookies: the line's mix is not the training mix. Kept as a demonstration, not deployed.</p>
      </section>
    </>
  );
}

export function VisionPage() {
  const { m, err } = useModels();
  const { data: cam } = useJson<Camera>("vision/camera.json");
  const { data: cnnRes } = useJson<CnnRes>("vision/results.json");
  const { data: adaptRaw } = useJson<unknown>("vision/adapt.json");
  const adaptNet = useMemo(() => (adaptRaw ? decodeAdapt(adaptRaw) : null), [adaptRaw]);
  const [adaptOn, setAdaptOn] = useState(false);
  const [passP, setPassP] = useState(0.5);
  const [adaptEpoch, setAdaptEpoch] = useState(0);
  const [run, setRun] = useState(true);
  const [rate, setRate] = useState(40);            // cookies per minute
  const [defect, setDefect] = useState(0.1);
  const [scenario, setScenario] = useState<Scenario>("hood");
  const [age, setAge] = useState(0.5);
  const [frames, setFrames] = useState<Frame[]>([]);
  const [twinAt, setTwinAt] = useState(0);
  const line = useMemo(() => (m ? new LiveLine(m.P, m.cnn, m.ae) : null), [m]);
  const opts = useRef({ scenario, defect, age, passP });
  opts.current = { scenario, defect, age, passP };
  const push = (f: Frame) => setFrames((fs) => [...fs.slice(-(KEEP - 1)), f]);

  // the simulated line: a cookie every 60/rate s, flavours in turn - paused while the twin feeds us
  useEffect(() => {
    if (!line || !run) return;
    let k = 0;
    const id = window.setInterval(() => {
      if (Date.now() - twinAt < 30000) return;
      push(line.capture(m!.P.flavours[k++ % m!.P.flavours.length], { ...opts.current, source: "line" }));
    }, 60000 / rate);
    return () => window.clearInterval(id);
  }, [line, run, rate, twinAt, m]);
  // the 3D twin's cookies, as its camera photographs them
  useEffect(() => {
    if (!line) return;
    let ch: BroadcastChannel | null = null;
    try { ch = new BroadcastChannel(CHANNEL); } catch { return; }
    ch.onmessage = (e) => {
      if (!run) return;
      setTwinAt(Date.now());
      push(line.capture(e.data.flavour, { ...opts.current, source: "twin" }));
    };
    return () => ch?.close();
  }, [line, run]);

  const ab = useAdaptation(frames, adaptOn, adaptNet, adaptEpoch);
  if (err) return <div className="db-err">{err}</div>;
  if (!m) return <div className="db-err">loading the camera's models…</div>;
  const N = m.P.N;
  const last = frames[frames.length - 1];
  const window50 = frames.slice(-50);
  const T = tally(window50, m.P.conditions), all = tally(frames, m.P.conditions);
  const dr = drift(frames, m.ae);
  const twin = Date.now() - twinAt < 30000;
  const verdictCls = (f: Frame) => (f.truth !== "ok" && f.pred.verdict === "pass" ? "escape"
    : f.truth === "ok" && f.pred.verdict === "reject" ? "false" : f.pred.verdict === "check" ? "check" : "right");
  const errMax = m.ae.threshold * 3;

  return (
    <>
      <div className="db-kpis">
        <div className="db-kpi"><span>inspected</span><b>{all.n}</b><em>{twin ? "the 3D twin's cookies" : "simulated line"} · {SCENARIOS[scenario].label}</em></div>
        <div className={`db-kpi ${T.accuracy < 0.9 ? "warn" : "ok"}`}><span>CNN right (last 50)</span><b>{pct(T.accuracy)}</b><em>condition · flavour {pct(T.flavourAcc)}</em></div>
        <div className={`db-kpi ${T.escape > 0.05 ? "fail" : "ok"}`}><span>escapes</span><b>{pct(T.escape)}</b><em>defects passed as good (last 50)</em></div>
        <div className={`db-kpi ${T.falseReject > 0.1 ? "warn" : "ok"}`}><span>false rejects</span><b>{pct(T.falseReject)}</b><em>good cookies thrown out (last 50)</em></div>
        <div className={`db-kpi ${dr > 2 ? "fail" : dr > 1.5 ? "warn" : "ok"}`}><span>drift</span><b>×{dr.toFixed(2)}</b><em>{dr > 2 ? "the line has changed: retrain" : "autoencoder error vs training"}</em></div>
      </div>

      <div className="db-grid">
        <section className="db-card wide vq-live">
          <h3>Live camera <span className={`vq-dot ${run ? "on" : ""}`} />{last ? `cookie #${last.n}` : "waiting for a cookie"}</h3>
          {last ? (
            <div className="vq-now">
              <figure><Pic img={last.img} N={N} scale={3} /><figcaption>camera · {cam ? `${cam.fov_mm.toFixed(0)} mm field` : ""}</figcaption></figure>
              <figure><Pic img={last.img} N={N} scale={3} err={last.ae.err} max={errMax} /><figcaption>autoencoder error</figcaption></figure>
              <dl className="vq-facts">
                <div><dt>truth (simulation)</dt><dd>{last.flavour} · <b>{last.truth}</b></dd></div>
                <div><dt>CNN</dt><dd>{last.pred.flavour} · <b>{last.pred.condition}</b> ({pct(last.pred.pc)})</dd></div>
                <div><dt>decision</dt><dd className={`vq-v ${last.pred.verdict}`}>{last.pred.verdict === "pass" ? "pass" : last.pred.verdict === "reject" ? "reject" : "to a person"}
                  <span className={`vq-tag ${verdictCls(last)}`}>{{ right: "right", escape: "ESCAPE", false: "false reject", check: "unsure" }[verdictCls(last)]}</span></dd></div>
                <div><dt>autoencoder</dt><dd>{last.ae.anomaly ? <b className="vq-bad">unusual</b> : "looks normal"} · score {(last.ae.score / m.ae.threshold).toFixed(2)}× threshold</dd></div>
                <div><dt>source</dt><dd>{last.source === "twin" ? "a cookie the 3D twin baked" : "the simulated line"}</dd></div>
              </dl>
            </div>
          ) : <p className="db-muted">The first cookie reaches the camera in a moment.</p>}
          <div className="vq-strip">
            {frames.slice(-14).reverse().map((f) => (
              <div key={f.n} className={`vq-thumb ${verdictCls(f)}`} title={`#${f.n} ${f.flavour}: truth ${f.truth}, CNN ${f.pred.condition} → ${f.pred.verdict}${f.ae.anomaly ? ", autoencoder: unusual" : ""}`}>
                <Pic img={f.img} N={N} scale={1} />
              </div>
            ))}
          </div>
        </section>

        <section className="db-card">
          <h3>The line</h3>
          <div className="vq-ctl">
            <button className="ui-btn" onClick={() => setRun(!run)}>{run ? "Pause" : "Run"}</button>
            <button className="ui-btn ghost" onClick={() => setFrames([])}>Reset</button>
          </div>
          <label className="vq-row"><span>Conditions</span>
            <select className="ui-select" value={scenario} onChange={(e) => setScenario(e.target.value as Scenario)}>
              {Object.entries(SCENARIOS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select></label>
          <p className="db-muted small">{SCENARIOS[scenario].say}</p>
          {scenario === "lamp" && (
            <label className="vq-row"><span>Light's age</span><input type="range" min={0} max={1} step={0.05} value={age} onChange={(e) => setAge(+e.target.value)} /><b>{pct(age)}</b></label>
          )}
          <label className="vq-row"><span>Defect rate</span><input type="range" min={0} max={0.4} step={0.01} value={defect} onChange={(e) => setDefect(+e.target.value)} /><b>{pct(defect)}</b></label>
          <label className="vq-row" title="A cookie passes only if the CNN gives 'ok' at least this probability. Higher: fewer defects escape, more good cookies are thrown out."><span>Pass threshold</span><input type="range" min={0.5} max={0.99} step={0.01} value={passP} onChange={(e) => setPassP(+e.target.value)} /><b>{passP.toFixed(2)}</b></label>
          <label className="vq-row"><span>Cookies per minute</span><input type="range" min={6} max={120} step={2} value={rate} onChange={(e) => setRate(+e.target.value)} /><b>{rate}</b></label>
          <p className="db-muted small">{twin ? "The 3D twin is open: its cookies are photographed as they pass the camera." : "Open the 3D twin in another tab and its cookies are photographed instead."}</p>
        </section>

        <section className="db-card">
          <h3>Confusion (last 50)</h3>
          <table className="db-table vq-cm">
            <thead><tr><td>truth ↓ / CNN →</td>{m.P.conditions.map((c) => <td key={c} className="num">{c.slice(0, 5)}</td>)}</tr></thead>
            <tbody>{m.P.conditions.map((c, i) => (
              <tr key={c}><td>{c}</td>{T.cm[i].map((v, j) => {
                const top = Math.max(1, ...T.cm.flat());
                return <td key={j} className={`num ${v ? (i === j ? "ok" : "fail") : "vq-zero"}`}
                  style={v ? { background: `color-mix(in srgb, ${i === j ? "var(--ok)" : "var(--bad)"} ${Math.round(12 + 50 * v / top)}%, transparent)` } : undefined}>{v}</td>;
              })}</tr>
            ))}</tbody>
          </table>
          <p className="db-muted small">Diagonal = right. {T.toPerson > 0 ? `${pct(T.toPerson)} sent to a person (unsure).` : ""}</p>
        </section>

        <section className="db-card wide">
          <h3>Drift: the autoencoder's error on normal-looking cookies</h3>
          {(() => {
            const F = frames.slice(-150), r = (f: (typeof F)[0]) => f.ae.mean / m.ae.ok_mean_error;
            const run = F.map((_, i) => drift(F.slice(0, i + 1), m.ae));
            return <Plot h={230} xTitle="cookie number" yTitle="error ÷ training baseline" yMin={0} yMax={Math.max(2.6, ...F.map(r)) * 1.05}
              yFmt={(v) => `×${v.toFixed(1)}`}
              series={[{ name: "normal-looking cookie", x: F.map((f) => f.n), y: F.map((f) => (f.ae.anomaly ? null : r(f))), color: "#9fd0ff", kind: "dots", fmt: (v) => `×${v.toFixed(2)}` },
                       { name: "flagged unusual", x: F.map((f) => f.n), y: F.map((f) => (f.ae.anomaly ? r(f) : null)), color: "#e0503a", kind: "dots", fmt: (v) => `×${v.toFixed(2)}` },
                       { name: "drift (20-cookie mean)", x: F.map((f) => f.n), y: run, color: "var(--warn)", width: 2.6, fmt: (v) => `×${v.toFixed(2)}` }]}
              hlines={[{ y: 1, color: "var(--muted)", label: "training" }, { y: 2, color: "var(--bad)", label: "drift alarm" }]}
              tipTitle={(x) => `cookie #${Math.round(x)}`} />;
          })()}
          <p className="hl-cap">Switch the conditions above: the line rises past ×2 before the CNN's answers go wrong — the cue to collect images and retrain. Autoencoder here: caught {pct(all.aeDetect)} of defects, {pct(all.aeFalse)} false alarms.</p>
        </section>

        {adaptNet && <Adaptation ab={ab} net={adaptNet} on={adaptOn} setOn={setAdaptOn} reset={() => setAdaptEpoch((e) => e + 1)} />}
        <section className="db-card">
          <h3>The camera</h3>
          {cam && (
            <table className="db-table"><tbody>
              <tr><td>where</td><td>inside the colour hood, 40 mm before the colour sensor</td></tr>
              <tr><td>why there</td><td>{cam.why_here}</td></tr>
              <tr><td>lens</td><td>{cam.optics.lens_angle_deg}° at {cam.optics.working_distance_mm.toFixed(0)} mm</td></tr>
              <tr><td>trigger</td><td>I2 + {cam.optics.trigger_delay_s.toFixed(2)} s</td></tr>
              <tr><td>mount checks</td><td>{cam.checks.filter((c) => c.ok).length}/{cam.checks.length} pass</td></tr>
            </tbody></table>
          )}
        </section>

        <section className="db-card">
          <h3>The models, tested offline</h3>
          <Dumbbell xTitle="trained-like conditions vs unseen ones" a={{ name: "trained-like", color: "var(--ok)" }} b={{ name: "unseen", color: "var(--bad)" }}
            fmt={(v) => `${Math.round(v * 100)}`}
            rows={[...(cnnRes ? [{ label: "CNN right (%)", a: cnnRes.results.in_domain.condition_acc, b: cnnRes.results.shifted.condition_acc },
                                 { label: "CNN false rejects (%)", a: cnnRes.results.in_domain.false_reject, b: cnnRes.results.shifted.false_reject }] : []),
                   { label: "autoencoder AUROC (×100)", a: m.ae.meta.results.in_domain.auroc, b: m.ae.meta.results.shifted.auroc },
                   { label: "autoencoder false alarms (%)", a: m.ae.meta.results.in_domain.false_alarm, b: m.ae.meta.results.shifted.false_alarm }]} />
          <p className="hl-cap">Under unseen light the CNN's false rejects jump; the autoencoder's good-cookie error rises ×{m.ae.meta.drift_ratio.toFixed(1)} — the drift signal.</p>
          <p className="db-muted small">The CNN was taught five conditions; the autoencoder only ever saw good cookies and needs no labels. Both are trained
            on rendered images: this shows the method, not the accuracy on a real camera.</p>
        </section>
      </div>
    </>
  );
}
