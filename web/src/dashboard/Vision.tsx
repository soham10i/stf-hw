// Vision QC: the inspection camera on the process. Every cookie the 3D twin bakes is
// photographed by the camera in the colour hood (vision/mount.py), classified by the CNN, scored
// by the autoencoder and checked against what the simulation knows - is the model right? The
// live view is streamed while this page is open and never stored; each cookie's photo is judged
// here and stored by the API. One cookie in every 12 is damaged on purpose (QC testing).
// Ten sample photos from the process stay with the page (public/vision/samples): no training
// or test images, no rendered or augmented ones.
import { Plot } from "./Plot";
import { useEffect, useMemo, useRef, useState } from "react";
import { loadJson, useJson } from "../shared/data";
import { decodeAe, type Ae } from "../vision/ae";
import { decode, type Cnn } from "../vision/cnn";
import { LiveLine, drift, tally, type Frame } from "../vision/live";
import { prepare, useTwinCamera } from "../vision/twinCamera";
import { rgba, type RenderParams } from "../vision/render";
import { HAS_API } from "../shared/mode";

type Camera = { fov_mm: number; optics: { working_distance_mm: number; lens_angle_deg: number; trigger_delay_s: number; roi_mm: number };
                checks: { check: string; ok: boolean; detail: string }[]; why_here: string };
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

const BASE = import.meta.env.BASE_URL;

/** The twin camera's live view: the latest frame, drawn as it comes and then dropped. */
function LiveView({ frame, fps }: { frame: { bmp: ImageBitmap; lit: boolean } | null; fps: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (c && frame) c.getContext("2d")?.drawImage(frame.bmp, 0, 0, c.width, c.height);
  }, [frame]);
  return (
    <figure className="vq-feed">
      <div className="vq-feed-box">
        <canvas ref={ref} width={256} height={256} hidden={!frame} aria-label="The inspection camera's live view" />
        {!frame && (
          <div className="vq-feed-off">
            <b>The twin's camera is not streaming</b>
            <span>Open the 3D twin in a window beside this one: its camera in the colour hood shows here, live. A hidden tab pauses the twin, and the feed with it.</span>
            <a className="ui-btn" href={BASE} target="stf-twin" rel="noopener">Open the 3D twin</a>
          </div>
        )}
        {frame && <span className="vq-live-tag"><i />LIVE</span>}
      </div>
      <figcaption>{frame ? `live view · ${fps.toFixed(0)} fps · ${frame.lit ? "ring light strobing" : "waiting for a cookie"} · not recorded` : "live view · not recorded"}</figcaption>
    </figure>
  );
}

export function VisionPage() {
  const { m, err } = useModels();
  const { data: cam } = useJson<Camera>("vision/camera.json");
  const [passP, setPassP] = useState(0.5);
  const [frames, setFrames] = useState<Frame[]>([]);
  const [twinAt, setTwinAt] = useState(0);
  const line = useMemo(() => (m ? new LiveLine(m.P, m.cnn, m.ae) : null), [m]);
  const opts = useRef({ passP });
  opts.current = { passP };
  const push = (f: Frame) => setFrames((fs) => {
    // the photos held for display go with their frames
    fs.slice(0, Math.max(0, fs.length - (KEEP - 1))).forEach((o) => o.photo && URL.revokeObjectURL(o.photo));
    return [...fs.slice(-(KEEP - 1)), f];
  });
  // the 3D twin's camera: its live view, and its photo of each cookie, judged by the models
  const { frame: liveFrame, fps } = useTwinCamera((p) => {
    if (!line || !m) return;
    setTwinAt(Date.now());
    prepare(p, m.P.N, m.P.REF)
      .then(({ img }) => push({ ...line.inspect(img, p.flavour, opts.current.passP, p.truth ?? "ok"), photo: URL.createObjectURL(p.jpeg) }))
      .catch(() => { /* a photo that would not decode */ });
  });
  useEffect(() => { if (liveFrame) setTwinAt(Date.now()); }, [liveFrame]);

  if (err) return <div className="db-err">{err}</div>;
  if (!m) return <div className="db-err">loading the camera's models…</div>;
  const N = m.P.N;
  const last = frames[frames.length - 1];
  const all = tally(frames, m.P.conditions);
  const dr = drift(frames, m.ae);
  const twin = Date.now() - twinAt < 30000;
  const verdictCls = (f: Frame) => (f.truth !== "ok" && f.pred.verdict === "pass" ? "escape"
    : f.truth === "ok" && f.pred.verdict === "reject" ? "false" : f.pred.verdict === "check" ? "check" : "right");
  const errMax = m.ae.threshold * 3;
  const none = frames.length === 0;

  return (
    <>
      <div className="db-kpis">
        <div className="db-kpi"><span>inspected</span><b>{all.n}</b><em>{twin ? "the 3D twin's cookies, live" : "open the 3D twin to start"}</em></div>
        <div className={`db-kpi ${!none && all.accuracy < 0.9 ? "warn" : "ok"}`}><span>CNN right</span><b>{none ? "–" : pct(all.accuracy)}</b><em>condition · flavour {none ? "–" : pct(all.flavourAcc)}</em></div>
        <div className={`db-kpi ${all.escape > 0.05 ? "fail" : "ok"}`}><span>escapes</span><b>{none ? "–" : pct(all.escape)}</b><em>damaged cookies passed as good</em></div>
        <div className={`db-kpi ${all.falseReject > 0.1 ? "warn" : "ok"}`}><span>false rejects</span><b>{none ? "–" : pct(all.falseReject)}</b><em>good cookies thrown out</em></div>
        <div className={`db-kpi ${dr > 2 ? "fail" : dr > 1.5 ? "warn" : "ok"}`}><span>drift</span><b>{none ? "–" : `×${dr.toFixed(2)}`}</b><em>{dr > 2 ? "the line has changed: retrain" : "autoencoder error vs training"}</em></div>
      </div>

      <div className="db-grid">
        <section className="db-card wide vq-live">
          <h3>Inspection camera
            {twin ? <span className="vq-src twin"><i />3D twin's camera</span> : <span className="vq-src">waiting for the twin</span>}
            <em className="vq-count">{last ? `cookie #${last.n}` : "waiting for a cookie"}</em></h3>
          <div className="vq-cam">
            <LiveView frame={liveFrame} fps={fps} />
            {last ? (
              <div className="vq-now">
                <figure>
                  {last.photo ? <img className="vq-photo" src={last.photo} alt={`Photo of cookie #${last.n}, ${last.flavour}`} width={N * 3} height={N * 3} />
                    : <Pic img={last.img} N={N} scale={3} />}
                  <figcaption>photo · stored · {cam ? `${cam.fov_mm.toFixed(0)} mm field` : ""}</figcaption>
                </figure>
                <figure><Pic img={last.img} N={N} scale={3} /><figcaption title="The cookie found against the empty hood; everything else set to the belt's colour">as the models see it</figcaption></figure>
                <figure><Pic img={last.img} N={N} scale={3} err={last.ae.err} max={errMax} /><figcaption>autoencoder error</figcaption></figure>
                <dl className="vq-facts">
                  <div><dt>truth (simulation)</dt><dd>{last.flavour} · <b>{last.truth}</b>{last.truth === "ok" ? " (baked right)" : " (damaged for QC testing)"}</dd></div>
                  <div><dt>CNN</dt><dd>{last.pred.flavour} · <b>{last.pred.condition}</b> ({pct(last.pred.pc)})</dd></div>
                  <div><dt>decision</dt><dd className={`vq-v ${last.pred.verdict}`}>{last.pred.verdict === "pass" ? "pass" : last.pred.verdict === "reject" ? "reject" : "to a person"}
                    <span className={`vq-tag ${verdictCls(last)}`}>{{ right: "right", escape: "ESCAPE", false: "false reject", check: "unsure" }[verdictCls(last)]}</span></dd></div>
                  <div><dt>autoencoder</dt><dd>{last.ae.anomaly ? <b className="vq-bad">unusual</b> : "looks normal"} · score {(last.ae.score / m.ae.threshold).toFixed(2)}× threshold</dd></div>
                </dl>
              </div>
            ) : <p className="db-muted">No cookie yet: place an order in the 3D twin, and each cookie is photographed as it passes under the lens.</p>}
          </div>
          <div className="vq-strip">
            {frames.slice(-14).reverse().map((f) => (
              <div key={f.n} className={`vq-thumb ${verdictCls(f)}`} title={`#${f.n} ${f.flavour}: truth ${f.truth}, CNN ${f.pred.condition} → ${f.pred.verdict}${f.ae.anomaly ? ", autoencoder: unusual" : ""}`}>
                {f.photo ? <img src={f.photo} alt="" width={N} height={N} /> : <Pic img={f.img} N={N} scale={1} />}
              </div>
            ))}
          </div>
        </section>

        <section className="db-card">
          <h3>The decision</h3>
          <label className="vq-row" title="A cookie passes only if the CNN gives 'ok' at least this probability. Higher: fewer damaged cookies pass, more good ones are thrown out."><span>Pass threshold</span><input type="range" min={0.5} max={0.99} step={0.01} value={passP} onChange={(e) => setPassP(+e.target.value)} /><b>{passP.toFixed(2)}</b></label>
          <ul className="ai-verdict">
            <li><b>Pass</b>: the CNN says <i>ok</i> with at least this probability: the cookie goes to its Lagerstelle.</li>
            <li><b>Reject</b>: it does not: the cookie is held at the end of the line and the order makes it again.</li>
            <li><b>To a person</b>: no condition is sure enough (below 0.6).</li>
          </ul>
          <p className="db-muted small">QC testing: in every 12 cookies the twin bakes, one drawn at random is burnt, underbaked or cracked (Orders panel), so every rack tests the inspection.</p>
        </section>

        <section className="db-card">
          <h3>Confusion</h3>
          <table className="db-table vq-cm">
            <thead><tr><td>truth ↓ / CNN →</td>{m.P.conditions.map((c) => <td key={c} className="num">{c.slice(0, 5)}</td>)}</tr></thead>
            <tbody>{m.P.conditions.map((c, i) => (
              <tr key={c}><td>{c}</td>{all.cm[i].map((v, j) => {
                const top = Math.max(1, ...all.cm.flat());
                return <td key={j} className={`num ${v ? (i === j ? "ok" : "fail") : "vq-zero"}`}
                  style={v ? { background: `color-mix(in srgb, ${i === j ? "var(--ok)" : "var(--bad)"} ${Math.round(12 + 50 * v / top)}%, transparent)` } : undefined}>{v}</td>;
              })}</tr>
            ))}</tbody>
          </table>
          <p className="db-muted small">The cookies inspected since this page opened. Diagonal = right. {all.toPerson > 0 ? `${pct(all.toPerson)} sent to a person (unsure).` : ""}</p>
        </section>

        <Samples />

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
          <p className="hl-cap">A rise past ×2 means the line no longer looks like what the models learnt (light, belt, dough): the cue to collect photos from the line and retrain. Autoencoder on the process so far: caught {pct(all.aeDetect)} of damaged cookies, {pct(all.aeFalse)} false alarms.</p>
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

        <Photos />
      </div>
    </>
  );
}

type Sample = { file: string; n: number; flavour: string; truth: string; condition: string; verdict: string; unusual: boolean };

/** Ten photos the camera took of the 3D twin's cookies in the process, with what the models
    decided: the page's examples, kept with it (public/vision/samples). */
function Samples() {
  const { data } = useJson<{ taken: string; samples: Sample[] }>("vision/samples/samples.json");
  if (!data) return null;
  return (
    <section className="db-card wide">
      <h3>Ten photos from the process</h3>
      <div className="vq-samples">
        {data.samples.map((s) => {
          const right = (s.truth === "ok") === (s.verdict === "pass");
          return (
            <figure key={s.file} className={right ? "right" : "wrong"}>
              <img src={`${BASE}vision/samples/${s.file}`} alt={`${s.flavour} cookie, ${s.truth}`} width={96} height={96} loading="lazy" />
              <figcaption>
                <b>{s.flavour}</b>
                <span className={s.truth === "ok" ? "" : "vq-bad"}>{s.truth === "ok" ? "good" : s.truth}</span>
                <em className={`vq-v ${s.verdict}`}>CNN {s.condition} → {s.verdict === "pass" ? "pass" : s.verdict === "reject" ? "reject" : "to a person"}</em>
              </figcaption>
            </figure>
          );
        })}
      </div>
      <p className="db-muted small">Taken by the camera in the colour hood as the 3D twin baked an order ({data.taken}); the damaged one is QC testing's. Each shows the truth and what the CNN decided.</p>
    </section>
  );
}

type Capture = { id: string; t: number; flavour: string; n: number; source: string; w: number; h: number };

/** The photos the camera in the colour hood took of the 3D twin's baked cookies, as the API
    stored them (services/api/captures.py): the dataset that grows while the twin runs. */
function Photos() {
  const [d, setD] = useState<{ captures: Capture[]; store: string; enabled: boolean } | null>(null);
  useEffect(() => {
    if (!HAS_API) return;
    let live = true;
    const get = () => fetch("/vision/captures?limit=24").then((r) => (r.ok ? r.json() : null)).then((j) => { if (live && j) setD(j); }).catch(() => {});
    get();
    const id = window.setInterval(get, 10000);
    return () => { live = false; window.clearInterval(id); };
  }, []);
  const when = (t: number) => new Date(t * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" });
  return (
    <section className="db-card">
      <h3>Photos stored by the server</h3>
      {!HAS_API ? (
        <p className="db-muted small">The camera photographs every baked cookie in the 3D twin; storing the photos needs the live server.</p>
      ) : !d ? (
        <p className="db-muted small">Loading…</p>
      ) : !d.enabled ? (
        <p className="db-muted small">Photo capture is off on this server (STF_CAPTURES=0).</p>
      ) : d.captures.length === 0 ? (
        <p className="db-muted small">No photos yet: place an order in the 3D twin, and each baked cookie is photographed as it passes under the lens.</p>
      ) : (
        <>
          <div className="vq-photos">
            {d.captures.map((c) => (
              <a key={c.id} href={`/vision/captures/${c.id}.jpg`} target="_blank" rel="noreferrer" title={`#${c.n} ${c.flavour}, ${when(c.t)}`}>
                <img src={`/vision/captures/${c.id}.jpg`} alt={`${c.flavour} cookie, photo ${c.n}`} width={72} height={72} loading="lazy" />
                <span>{c.flavour}</span>
              </a>
            ))}
          </div>
          <p className="db-muted small">The newest {d.captures.length}, {d.captures[0].w}×{d.captures[0].h} px, stored {d.store === "supabase" ? "in cloud storage" : "on the server's disk"}.</p>
        </>
      )}
    </section>
  );
}
