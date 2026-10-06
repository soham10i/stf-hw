// Vision QC: the inspection camera's live feed. Every cookie the line makes is photographed
// (the camera in the colour hood, vision/mount.py), classified by the CNN, scored by the
// autoencoder and checked against what the simulation knows - is the model still right?
// With the 3D twin open in another tab, the feed photographs the twin's own cookies.
import { useEffect, useMemo, useRef, useState } from "react";
import { loadJson, useJson } from "../shared/data";
import { decodeAe, type Ae } from "../vision/ae";
import { decode, type Cnn } from "../vision/cnn";
import { CHANNEL, LiveLine, SCENARIOS, drift, tally, type Frame, type Scenario } from "../vision/live";
import { rgba, type RenderParams } from "../vision/render";

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

export function VisionPage() {
  const { m, err } = useModels();
  const { data: cam } = useJson<Camera>("vision/camera.json");
  const { data: cnnRes } = useJson<CnnRes>("vision/results.json");
  const [run, setRun] = useState(true);
  const [rate, setRate] = useState(40);            // cookies per minute
  const [defect, setDefect] = useState(0.1);
  const [scenario, setScenario] = useState<Scenario>("hood");
  const [age, setAge] = useState(0.5);
  const [frames, setFrames] = useState<Frame[]>([]);
  const [twinAt, setTwinAt] = useState(0);
  const line = useMemo(() => (m ? new LiveLine(m.P, m.cnn, m.ae) : null), [m]);
  const opts = useRef({ scenario, defect, age });
  opts.current = { scenario, defect, age };
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
  const dmax = Math.max(m.ae.drift_alarm / m.ae.ok_mean_error * 1.5, ...frames.slice(-120).map((f) => f.ae.mean / m.ae.ok_mean_error));
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
          <label className="vq-row"><span>Cookies per minute</span><input type="range" min={6} max={120} step={2} value={rate} onChange={(e) => setRate(+e.target.value)} /><b>{rate}</b></label>
          <p className="db-muted small">{twin ? "The 3D twin is open: its cookies are photographed as they pass the camera." : "Open the 3D twin in another tab and its cookies are photographed instead."}</p>
        </section>

        <section className="db-card">
          <h3>Confusion (last 50)</h3>
          <table className="db-table vq-cm">
            <thead><tr><td>truth ↓ / CNN →</td>{m.P.conditions.map((c) => <td key={c} className="num">{c.slice(0, 5)}</td>)}</tr></thead>
            <tbody>{m.P.conditions.map((c, i) => (
              <tr key={c}><td>{c}</td>{T.cm[i].map((v, j) => <td key={j} className={`num ${v ? (i === j ? "ok" : "fail") : "vq-zero"}`}>{v}</td>)}</tr>
            ))}</tbody>
          </table>
          <p className="db-muted small">Diagonal = right. {T.toPerson > 0 ? `${pct(T.toPerson)} sent to a person (unsure).` : ""}</p>
        </section>

        <section className="db-card wide">
          <h3>Drift: the autoencoder's error on normal-looking cookies</h3>
          <svg viewBox="0 0 600 120" className="vq-chart" preserveAspectRatio="none">
            <line x1="0" x2="600" y1={120 - (2 / dmax) * 110} y2={120 - (2 / dmax) * 110} className="vq-alarm" />
            <line x1="0" x2="600" y1={120 - (1 / dmax) * 110} y2={120 - (1 / dmax) * 110} className="vq-base" />
            {frames.slice(-120).map((f, i, a) => (
              <circle key={f.n} cx={(i / Math.max(1, a.length - 1)) * 590 + 5} cy={120 - (f.ae.mean / m.ae.ok_mean_error / dmax) * 110} r={2.2}
                className={f.ae.anomaly ? "an" : f.truth === "ok" ? "ok" : "bad"} />
            ))}
          </svg>
          <p className="db-muted small">Each dot is one cookie (red: the autoencoder found it unusual). Dashed: the training baseline (×1); solid: the
            drift alarm (×2). Switch the conditions above and watch the dots rise before the CNN's answers go wrong - the signal to collect
            images, label them and retrain or adapt the models. Autoencoder on its own: caught {pct(all.aeDetect)} of defects with {pct(all.aeFalse)} false alarms here.</p>
        </section>

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
          <table className="db-table"><thead><tr><td /><td className="num">trained-like</td><td className="num">unseen</td></tr></thead><tbody>
            {cnnRes && <>
              <tr><td>CNN right</td><td className="num">{pct(cnnRes.results.in_domain.condition_acc, 1)}</td><td className="num">{pct(cnnRes.results.shifted.condition_acc, 1)}</td></tr>
              <tr><td>CNN false rejects</td><td className="num">{pct(cnnRes.results.in_domain.false_reject, 1)}</td><td className="num">{pct(cnnRes.results.shifted.false_reject, 1)}</td></tr>
            </>}
            <tr><td>autoencoder AUROC</td><td className="num">{m.ae.meta.results.in_domain.auroc.toFixed(2)}</td><td className="num">{m.ae.meta.results.shifted.auroc.toFixed(2)}</td></tr>
            <tr><td>autoencoder false alarms</td><td className="num">{pct(m.ae.meta.results.in_domain.false_alarm, 1)}</td><td className="num">{pct(m.ae.meta.results.shifted.false_alarm, 1)}</td></tr>
            <tr><td>good-cookie error</td><td className="num">×1</td><td className="num">×{m.ae.meta.drift_ratio.toFixed(1)}</td></tr>
          </tbody></table>
          <p className="db-muted small">The CNN was taught five conditions; the autoencoder only ever saw good cookies and needs no labels. Both are trained
            on rendered images: this shows the method, not the accuracy on a real camera.</p>
        </section>
      </div>
    </>
  );
}
