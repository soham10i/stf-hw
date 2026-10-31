// Maintenance · Pre-failure window · At the edge (T4: stf-cad/hbw/edge, `make edge`, `make edge-tpu`).
// The networks quantized to int8 with integer-only arithmetic and graded on the decisions they feed;
// what each runtime costs; the TCN as a hand-written WebGPU kernel - measured again on this visitor's
// own GPU on request; and both networks compiled for a Coral Edge TPU.
import { useState } from "react";
import { Plot } from "./Plot";
import { useJson } from "../shared/data";
import type { Weights } from "./ml";
import type { BenchResult } from "../edge/bench";

type Dec = { failures: number; warned_1shift: number; late: number; missed: number; false_per_1000: number; rul_mae_orders: number;
  alarm_agreement?: number; rul_abs_diff_p99?: number };
type Vis = { escape_rate: number; false_reject: number; to_person: number; condition_acc: number; verdicts_changed?: number };
type Lat = { p50_us: number; p99_us: number };
type Run = { runtime: string; threads: number; tcn_window: Lat; tcn_order: Lat; cnn_image?: Lat; tcn_windows_per_s?: number; note?: string };
type EdgeDoc = {
  tcn: { variants: Record<string, Dec>; onnx_runtime: Record<string, Dec>;
    input: { h_levels_per_tensor: number; h_levels_equalised: number; logit_range_minmax: number[]; logit_step_minmax: number; logit_step_clipped: number } };
  cnn: { sets: Record<string, Record<string, Vis>> };
  runtimes: Run[];
  statistics: { filter_all_parts_per_order_us: number; filter_and_rul_all_parts_per_order_us: number; first_passage_draws: number; conformal_bound_us: number; parts: number };
  work: { tcn_mac: number; cnn_mac: number };
  files: Record<string, { fp32_bytes: number; int8_bytes: number }>;
};
type Op = { op: string; count: number; status: string };
type Tpu = { tf: string; tcn: TpuModel & { graded: Record<string, Dec> }; cnn: TpuModel & { graded: Record<string, Record<string, Vis>> } };
type TpuModel = { tflite_bytes: number; edgetpu: { ok: boolean; ops: Op[]; bytes: number | null; version: string; stdout: string } };

const pct = (v: number | undefined, d = 1) => (v == null ? "–" : `${(v * 100).toFixed(d)} %`);
const us = (l?: Lat) => (l ? (l.p50_us >= 1000 ? `${(l.p50_us / 1000).toFixed(2)} ms` : `${Math.round(l.p50_us)} µs`) : "–");
const kb = (b?: number | null) => (b == null ? "–" : `${(b / 1024).toFixed(0)} kB`);
const SHORT: Record<string, string> = {
  fp32: "fp32 (deployed)", "int8 weights only": "int8 weights, fp32 activations", "int8, min/max": "int8, min/max ranges",
  "int8, + logit range": "+ logit range", "int8, + logit range, input equalised": "+ input equalised",
  "int8, percentile, both": "percentile ranges, both fixes",
};

function DecRow({ name, r, hl }: { name: string; r: Dec; hl?: boolean }) {
  return (
    <tr className={hl ? "hl" : ""}>
      <td>{name}</td>
      <td className="num">{r.warned_1shift}/{r.failures}</td>
      <td className="num">{r.late}</td>
      <td className="num">{r.missed}</td>
      <td className="num">{r.false_per_1000.toFixed(2)}</td>
      <td className="num">{r.rul_mae_orders.toFixed(1)}</td>
      <td className="num">{r.alarm_agreement != null ? pct(r.alarm_agreement, 2) : "–"}</td>
    </tr>
  );
}

export function EdgeCards() {
  const { data: d, error } = useJson<EdgeDoc>("edge/edge.json", "run `make edge`");
  const { data: b } = useJson<BenchResult>("edge/browser.json");
  const { data: tpu } = useJson<Tpu>("edge/tpu.json");
  if (error) return <div className="db-err">{error}</div>;
  if (!d) return null;
  const st = d.statistics;
  const one = d.runtimes.filter((r) => r.threads === 1 && !r.note);
  const gflop = (wps: number) => (wps * 2 * d.work.tcn_mac) / 1e9;
  return (
    <>
      <section className="db-card wide">
        <h3>At the edge · the remaining-life network in int8, graded on its decisions</h3>
        <table className="db-table">
          <thead><tr><td>TCN, test machines</td><td className="num">warned a shift ahead</td><td className="num">late</td><td className="num">missed</td>
            <td className="num">false /1000</td><td className="num">life error</td><td className="num">same alarm as fp32</td></tr></thead>
          <tbody>
            {Object.entries(d.tcn.variants).map(([k, r]) => <DecRow key={k} name={SHORT[k] ?? k} r={r} hl={k === "int8, + logit range, input equalised"} />)}
            {Object.entries(d.tcn.onnx_runtime).map(([k, r]) => <DecRow key={k} name={k} r={r} />)}
            {tpu && <DecRow name="TFLite full int8 (Edge TPU model)" r={tpu.tcn.graded["tflite int8"]} />}
          </tbody>
        </table>
        <p className="hl-cap">Integer-only arithmetic (edge/int8.py): int8 weights per channel, int8 activations per tensor, fixed-point rescaling, the sigmoid as a 256-entry table.</p>
        <p className="hl-cap">Min/max spent the remaining-life logit's 256 steps on [{d.tcn.input.logit_range_minmax.map((v) => v.toFixed(0)).join(", ")}]: a step of {d.tcn.input.logit_step_minmax.toFixed(2)}, against {d.tcn.input.logit_step_clipped.toFixed(3)} over the sigmoid's working range.</p>
        <p className="hl-cap">One scale for all inputs leaves the health signal {d.tcn.input.h_levels_per_tensor} levels; equalising the input channels (exact in fp32) gives it {d.tcn.input.h_levels_equalised}.</p>
      </section>
      <section className="db-card wide">
        <h3>The inspection network in int8 · escapes and false rejects</h3>
        <table className="db-table">
          <thead><tr><td>CNN</td><td>images</td><td className="num">condition right</td><td className="num">escapes</td><td className="num">false rejects</td>
            <td className="num">to a person</td><td className="num">verdicts changed</td></tr></thead>
          <tbody>{Object.entries(d.cnn.sets).flatMap(([set, rows]) => {
            const all: [string, Vis][] = [...Object.entries(rows)];
            const t = tpu?.cnn.graded[set]?.["tflite int8"];
            if (t) all.push(["TFLite full int8", t]);
            return all.map(([k, s], j) => (
              <tr key={set + k} className={k === "fp32" ? "" : "hl"}>
                <td>{k === "fp32" ? "fp32 (deployed)" : k}</td><td>{j ? "" : set === "in_domain" ? "like training" : "unseen conditions"}</td>
                <td className="num">{pct(s.condition_acc)}</td><td className="num">{pct(s.escape_rate)}</td><td className="num">{pct(s.false_reject)}</td>
                <td className="num">{pct(s.to_person)}</td><td className="num">{s.verdicts_changed != null ? pct(s.verdicts_changed, 2) : "–"}</td>
              </tr>));
          })}</tbody>
        </table>
        <p className="hl-cap">The light correction (a division by the grey target) stays on the host; the int8 graph starts after it.</p>
      </section>
      <section className="db-card wide">
        <h3>What it costs on a CPU · one thread, as on the RevPi</h3>
        <table className="db-table">
          <thead><tr><td>runtime</td><td className="num">TCN, one window</td><td className="num">TCN, one order (all parts)</td>
            <td className="num">CNN, one image</td><td className="num">TCN windows /s</td></tr></thead>
          <tbody>{one.map((r) => (
            <tr key={r.runtime}><td>{r.runtime}</td><td className="num">{us(r.tcn_window)}</td><td className="num">{us(r.tcn_order)}</td>
              <td className="num">{us(r.cnn_image)}</td><td className="num">{r.tcn_windows_per_s?.toLocaleString() ?? "–"}</td></tr>))}
            <tr className="hl"><td>the statistics: filter + {st.first_passage_draws} first-passage draws</td><td className="num">–</td>
              <td className="num">{(st.filter_and_rul_all_parts_per_order_us / 1000).toFixed(2)} ms</td><td className="num">–</td><td className="num">–</td></tr>
            <tr><td>the filter alone · the conformal bound</td><td className="num">–</td>
              <td className="num">{Math.round(st.filter_all_parts_per_order_us)} µs · {st.conformal_bound_us} µs</td><td className="num">–</td><td className="num">–</td></tr>
          </tbody>
        </table>
        <p className="hl-cap">p50 latency on this machine's CPU (not a RevPi). An order takes about 15 minutes.</p>
      </section>
      {b && <BrowserCard b={b} gflop={gflop} mac={d.work.tcn_mac} nin={4 + st.parts} />}
      {tpu && <TpuCard tpu={tpu} />}
    </>
  );
}

function BrowserCard({ b, gflop, mac, nin }: { b: BenchResult; gflop: (wps: number) => number; mac: number; nin: number }) {
  const bytes = nin * 48 * 4 + 16;                                     // one window in, four numbers out
  const stream = 32 * 3 * (nin + 3 * 32) + 64 * 64 + 64 * 4;            // the newest column of each layer
  const [live, setLive] = useState<BenchResult | null>(null);
  const [step, setStep] = useState<string | null>(null);
  const run = async () => {
    setStep("loading");
    try {
      const [{ bench }, W, M] = await Promise.all([import("../edge/bench"),
        fetch(`${import.meta.env.BASE_URL}ml/weights.json`).then((r) => r.json() as Promise<Weights>),
        fetch(`${import.meta.env.BASE_URL}ml/month_inputs.json`).then((r) => r.json() as Promise<{ x: number[][] }>)]);
      setLive(await bench(W, M.x, { n: 120, tiles: [1, 8], onStep: setStep }));
    } catch (e) { setStep(String(e)); return; }
    setStep(null);
  };
  const g = b.gpu ?? [];
  const best = g.length ? g[g.length - 1] : null;
  return (
    <>
      <section className="db-card">
        <h3>In the browser · a WebGPU kernel</h3>
        <Plot h={220} xTitle="output channels per thread (tile)" yTitle="windows per second" xMin={0} xMax={9} yMin={0}
          yFmt={(v) => `${Math.round(v / 1000)}k`}
          hlines={[{ y: b.ts.windows_per_s, color: "#e0a02a", label: "TypeScript" }]}
          series={[{ name: "WebGPU, whole replay", x: g.map((r) => r.tile), y: g.map((r) => r.windows_per_s), color: "#5b8cff", width: 2, kind: "line",
            fmt: (v) => `${Math.round(v).toLocaleString()} /s · ${gflop(v).toFixed(0)} GFLOP/s` }]} />
        <p className="hl-cap">{b.windows.toLocaleString()} windows in {best ? `${best.month_ms} ms` : "–"} ({b.adapter ?? "no GPU"}).</p>
        <p className="hl-cap">Same answers as TypeScript to {best?.max_abs_rul_diff ?? "–"} orders.</p>
      </section>
      <section className="db-card">
        <h3>One order vs the whole replay</h3>
        <table className="db-table">
          <thead><tr><td>{live ? "this browser" : "published run"}</td><td className="num">one window</td><td className="num">one order</td></tr></thead>
          <tbody>{[live ?? b].flatMap((r) => [
            <tr key="ts"><td>TypeScript</td><td className="num">{us(r.ts.window)}</td><td className="num">{us(r.ts.order)}</td></tr>,
            ...(r.gpu ?? []).map((x) => (
              <tr key={x.tile} className="hl"><td>GPU, tile {x.tile}</td><td className="num">{us(x.window)}</td><td className="num">{us(x.order)}</td></tr>))])}</tbody>
        </table>
        <p className="hl-cap">{live?.gpu_error ?? (live ? `Measured just now on ${live.adapter ?? "this device"}.` : "A dispatch and a read-back cost the GPU ~0.5 ms.")}</p>
        <button className="ui-btn" disabled={!!step} onClick={run}>{step ? `${step}…` : "Measure on this device"}</button>
      </section>
      <section className="db-card">
        <h3>Why not faster · the roofline</h3>
        <table className="db-table">
          <tbody>
            <tr><td>work per window</td><td className="num">{(2 * mac / 1e6).toFixed(2)} MFLOP</td></tr>
            <tr><td>from memory per window</td><td className="num">{(bytes / 1024).toFixed(1)} kB</td></tr>
            <tr><td>arithmetic intensity</td><td className="num">{Math.round((2 * mac) / bytes)} FLOP/B</td></tr>
            <tr><td>reached, tile 1 → {best?.tile ?? "–"}</td><td className="num">{g.length ? `${gflop(g[0].windows_per_s).toFixed(0)} → ${gflop(best!.windows_per_s).toFixed(0)} GFLOP/s` : "–"}</td></tr>
            <tr><td>memory traffic at that rate</td><td className="num">{best ? `${((best.windows_per_s * bytes) / 1e9).toFixed(2)} GB/s` : "–"}</td></tr>
            <tr className="hl"><td>a streaming TCN, per order</td><td className="num">{Math.round(mac / stream)}× less work</td></tr>
          </tbody>
        </table>
        <p className="hl-cap">Memory is not the limit; loads per multiply-add are.</p>
        <p className="hl-cap">Streaming reuses the 47 orders windows share.</p>
      </section>
    </>
  );
}

function TpuCard({ tpu }: { tpu: Tpu }) {
  return (
    <section className="db-card wide">
      <h3>Ready for a Coral · compiled for the Edge TPU, not run on one</h3>
      <table className="db-table">
        <thead><tr><td>model</td><td className="num">int8 TFLite</td><td className="num">compiled</td><td>operators</td></tr></thead>
        <tbody>{(["tcn", "cnn"] as const).map((k) => {
          const e = tpu[k].edgetpu;
          return (
            <tr key={k}><td>{k === "tcn" ? "remaining-life TCN" : "inspection CNN"}</td><td className="num">{kb(tpu[k].tflite_bytes)}</td>
              <td className={`num ${e.ok ? "ok" : "fail"}`}>{e.ok ? kb(e.bytes) : "failed"}</td>
              <td>{e.ops.map((o) => `${o.op} ×${o.count}${/Mapped to Edge TPU/i.test(o.status) ? "" : " (CPU)"}`).join(", ") || "–"}</td></tr>);
        })}</tbody>
      </table>
      <p className="hl-cap">{tpu.tcn.edgetpu.version} · TensorFlow {tpu.tf} · every operator on the accelerator, one subgraph each.</p>
      <p className="hl-cap">The int8 answers above are the TFLite interpreter's, the same int8 graph; the speed needs the device.</p>
    </section>
  );
}
