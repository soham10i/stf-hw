// Upgrade 15: vision inspection at the sorting line. The CNN, trained only on rendered
// images (stf-cad/hbw/vision), classifies the published test images here, in the browser.
import { useEffect, useMemo, useState } from "react";
import { loadJson, useJson } from "../shared/data";
import { decode, forward, tile, verdict, type Cnn, type Verdict } from "../vision/cnn";
import { Empty, Stat } from "./kit";

const BASE = import.meta.env.BASE_URL;

type Score = { flavour_acc: number; condition_acc: number; escape_rate: number; false_reject: number; to_person: number;
               recall: Record<string, number> };
type Label = { flavour: number; condition: number; shifted: boolean };
type Results = {
  model: { params: number; onnx_bytes: number; browser_max_abs_err: number };
  data: { train: number }; results: { in_domain: Score; shifted: Score };
  steps: { narrow: { shifted: Score }; wide: { shifted: Score } };
  sheet: { cols: number; tile: number; labels: Label[] };
};
type Out = { v: Verdict; flavour: number[]; condition: number[] };

const pct = (x: number) => `${Math.round(x * 100)} %`;

function useInference(res: Results | null) {
  const [net, setNet] = useState<Cnn | null>(null);
  const [outs, setOuts] = useState<Out[]>([]);
  const [ms, setMs] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!res) return;
    let live = true;
    (async () => {
      try {
        const n = decode(await loadJson("vision/weights.json"));
        const img = new Image();
        img.src = `${BASE}vision/test.png`;
        await img.decode();
        const cv = document.createElement("canvas");
        cv.width = img.width; cv.height = img.height;
        const cx = cv.getContext("2d")!;
        cx.drawImage(img, 0, 0);
        const px = cx.getImageData(0, 0, img.width, img.height).data;
        if (!live) return;
        setNet(n);
        const acc: Out[] = [];
        const t0 = performance.now();
        // a few images per frame, so the page stays responsive
        for (let k = 0; k < res.sheet.labels.length; k++) {
          const o = forward(n, tile(px, img.width, res.sheet.cols, res.sheet.tile, k));
          acc.push({ v: verdict(n, o.condition), flavour: o.flavour, condition: o.condition });
          if (k % 6 === 5) { setOuts([...acc]); await new Promise((r) => setTimeout(r, 0)); if (!live) return; }
        }
        setOuts(acc);
        setMs((performance.now() - t0) / res.sheet.labels.length);
      } catch (e) { if (live) setErr((e as Error).message); }
    })();
    return () => { live = false; };
  }, [res]);
  return { net, outs, ms, err };
}

export function VisionPanel() {
  const { data: res, error } = useJson<Results>("vision/results.json");
  const { net, outs, ms, err } = useInference(res);
  const [shifted, setShifted] = useState(true);
  const [sel, setSel] = useState<number | null>(null);
  const idx = useMemo(() => (res ? res.sheet.labels.map((l, i) => [l, i] as const).filter(([l]) => l.shifted === shifted).map(([, i]) => i) : []),
    [res, shifted]);
  if (error || err) return <Empty text={`No vision model: run vision/train.py (${error ?? err}).`} />;
  if (!res) return <Empty text="loading…" />;
  const F = ["chocolate", "strawberry", "vanilla"], C = ["ok", "underbaked", "burnt", "cracked", "chipped"];
  const cls = net?.classes ?? { flavour: F, condition: C };
  const sh = res.results.shifted, ind = res.results.in_domain;
  const shown = idx.filter((i) => outs[i]);
  const right = shown.filter((i) => outs[i].v !== "check" && (outs[i].v === "pass") === (res.sheet.labels[i].condition === 0)).length;
  const cols = res.sheet.cols, rows = Math.ceil(res.sheet.labels.length / cols);
  const sprite = (i: number, size: number) => ({
    backgroundImage: `url(${BASE}vision/test.png)`, backgroundSize: `${cols * size}px ${rows * size}px`,
    backgroundPosition: `-${(i % cols) * size}px -${Math.floor(i / cols) * size}px`, width: size, height: size,
  });
  const s = sel !== null && outs[sel] ? sel : null;
  const steps: [string, Score][] = [["Narrow randomisation", res.steps.narrow.shifted], ["Wide randomisation", res.steps.wide.shifted],
    ["Wide + grey reference", sh]];

  return (
    <div className="np vis">
      <div className="np-head">
        <div><b>Vision inspection</b><span>a CNN trained only on rendered images, running in your browser</span></div>
      </div>
      <div className="np-stats">
        <Stat label="Defects passed (escapes)" value={pct(sh.escape_rate)} sub={`unseen conditions · ${pct(ind.escape_rate)} like training`}
          tone={sh.escape_rate <= 0.02 ? "ok" : "warn"} />
        <Stat label="Good cookies rejected" value={pct(sh.false_reject)} sub={`unseen conditions · ${pct(ind.false_reject)} like training`}
          tone={sh.false_reject <= 0.05 ? "ok" : "warn"} />
        <Stat label="Flavour" value={pct(sh.flavour_acc)} sub="checks the colour sensor" tone="ok" />
        <Stat label="Network" value={`${Math.round(res.model.params / 1000)}k`} sub={`params · ${ms ? ms.toFixed(0) + " ms/image here" : "…"}`} />
      </div>

      <h4 className="np-h">What each step buys, under unseen conditions</h4>
      <div className="vis-steps">
        <div className="hd"><span /><b>defects right</b><b>good rejected</b><b>escapes</b></div>
        {steps.map(([name, sc]) => (
          <div key={name}><span>{name}</span><b>{pct(sc.condition_acc)}</b><b>{pct(sc.false_reject)}</b><b>{pct(sc.escape_rate)}</b></div>
        ))}
      </div>

      <div className="plc-bar">
        <div className="plc-speed" role="group" aria-label="Test images">
          <button className={!shifted ? "on" : ""} onClick={() => { setShifted(false); setSel(null); }}>Like training</button>
          <button className={shifted ? "on" : ""} onClick={() => { setShifted(true); setSel(null); }}>Unseen conditions</button>
        </div>
        <span className="tag idle">{shown.length < idx.length ? `classifying ${shown.length}/${idx.length}` : `${right}/${idx.length} right`}</span>
      </div>
      <div className="vis-grid">
        {idx.map((i) => {
          const o = outs[i], lb = res.sheet.labels[i];
          const wrong = o && o.v !== "check" && (o.v === "pass") !== (lb.condition === 0);
          return (
            <button key={i} className={`${o?.v ?? ""} ${wrong ? "wrong" : ""} ${sel === i ? "sel" : ""}`} style={sprite(i, 46)}
              onClick={() => setSel(sel === i ? null : i)} aria-label={`${F[lb.flavour]} ${C[lb.condition]}`} />
          );
        })}
      </div>
      <p className="np-foot"><i className="vis-k pass" />pass <i className="vis-k reject" />reject <i className="vis-k check" />to a person
        <i className="vis-k wrong" />wrong. Click an image.</p>

      {s !== null && (
        <div className="vis-detail">
          <div style={sprite(s, 112)} className="vis-big" />
          <div>
            <p><b>Truth</b> {cls.flavour[res.sheet.labels[s].flavour]}, {cls.condition[res.sheet.labels[s].condition]}</p>
            <p><b>Verdict</b> <span className={`vis-v ${outs[s].v}`}>{outs[s].v}</span></p>
            {cls.condition.map((c, k) => (
              <div key={c} className="np-row accent"><span>{c}</span><i><em style={{ width: pct(outs[s].condition[k]) }} /></i><b>{pct(outs[s].condition[k])}</b></div>
            ))}
            <p className="vis-fl">Flavour: {cls.flavour[outs[s].flavour.indexOf(Math.max(...outs[s].flavour))]} ({pct(Math.max(...outs[s].flavour))})</p>
          </div>
        </div>
      )}
      <p className="np-foot">Trained on {res.data.train.toLocaleString()} rendered images; the unseen set is darker and brighter light, a warmer
        lamp, a worn belt, more noise and motion blur. Same forward pass as PyTorch to {res.model.browser_max_abs_err.toExponential(0)};
        {" "}ONNX for an edge PLC: <a href={`${BASE}vision/stf_vision_cnn.onnx`} download>stf_vision_cnn.onnx</a>.
        Rendered images only: it shows the method, not the accuracy on a real camera.</p>
    </div>
  );
}
