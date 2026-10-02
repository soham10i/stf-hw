// Upgrade 13: the PLC program running live. The same WebAssembly the proof ran
// (MatIEC -> C -> plc.wasm) is scanned here against the plant, in the browser.
import { useEffect, useMemo, useRef, useState } from "react";
import { loadJson, useJson } from "../shared/data";
import { Icon } from "../shared/icons";
import { Sil, type JobEvent, type PlcMeta } from "../sil/sim";
import type { PlantParams } from "../sil/plant";
import { Empty, Stat } from "./kit";

const BASE = import.meta.env.BASE_URL;
const SPEEDS = [1, 4, 16, 64];
const PHASE = ["Homing", "Running the order", "Order complete"];

type Proof = {
  compiler: string; wasm_sha: string; st_lines: number; decisions: number; jobs: number; order_s: number; model_s: number;
  u4: { accepted: boolean; errors: number; first: string };
  findings: { id: string; kind: string; text: string }[];
  mutants?: { id: string; what: string; caught: boolean }[];
  checks: Record<string, boolean>;
};

/** state code -> its comment, per function block, read from the program source. */
function stateNames(st: string) {
  const out: Record<string, Record<number, string>> = {};
  let fb = "";
  for (const line of st.split("\n")) {
    const f = line.match(/^FUNCTION_BLOCK FB_(\w+)/);
    if (f) { fb = f[1].toLowerCase(); out[fb] = {}; continue; }
    const s = line.match(/^ {2}(\d+): \(\* (.*?) \*\)/);
    if (s && fb) out[fb][Number(s[1])] = s[2];
  }
  return out;
}

type Live = { t: number; phase: number; units: { u: string; sn: number }[]; on: Set<string>; events: JobEvent[]; log: string[]; flags: string[] };

export function useSil() {
  const [err, setErr] = useState<string | null>(null);
  const [sim, setSim] = useState<Sil | null>(null);
  const [names, setNames] = useState<Record<string, Record<number, string>>>({});
  const [gen, setGen] = useState(0);
  const parts = useRef<{ wasm: WebAssembly.Module; meta: PlcMeta; params: PlantParams } | null>(null);
  useEffect(() => {
    let live = true;
    (async () => {
      try {
        if (!parts.current) {
          const [bytes, meta, params, st] = await Promise.all([
            fetch(`${BASE}sil/plc.wasm`).then((r) => { if (!r.ok) throw new Error(`plc.wasm: HTTP ${r.status}`); return r.arrayBuffer(); }),
            loadJson<PlcMeta>("sil/plc.json"), loadJson<PlantParams>("sil/plant.json"),
            fetch(`${BASE}sil/stf_plc.st`).then((r) => r.text()),
          ]);
          parts.current = { wasm: await WebAssembly.compile(bytes), meta, params };
          if (live) setNames(stateNames(st));
        }
        const p = parts.current;
        if (live) setSim(new Sil(p.wasm, p.meta, structuredClone(p.params)));
      } catch (e) { if (live) setErr((e as Error).message); }
    })();
    return () => { live = false; };
  }, [gen]);
  return { sim, names, err, restart: () => setGen((g) => g + 1) };
}

export function PlcPanel() {
  const { sim, names, err, restart } = useSil();
  const { data: proof } = useJson<Proof>("sil/sil.json");
  const [run, setRun] = useState(true);
  const [speed, setSpeed] = useState(4);
  const [live, setLive] = useState<Live | null>(null);

  // the scan loop: speed x real time, capped per frame; React sees a snapshot 8 times a second
  useEffect(() => {
    if (!sim) return;
    let last = performance.now(), acc = 0, raf = 0, shown = 0;
    const frame = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      if (run && sim.phase !== 2 && !sim.faults.length) {
        acc += dt * speed;
        let n = Math.floor(acc / sim.dt);
        acc -= n * sim.dt;
        n = Math.min(n, 4000);
        for (let k = 0; k < n; k++) sim.tick();
      }
      if (now - shown > 120) {
        shown = now;
        const on = new Set<string>();
        sim.meta.io.qx.forEach((e) => { if (sim.qx[e.bit!]) on.add(e.name); });
        sim.meta.io.ix.forEach((e) => { if (sim.ix[e.bit!]) on.add(e.name); });
        setLive({
          t: sim.t, phase: sim.phase, on,
          units: sim.meta.units.map((u, i) => ({ u, sn: sim.unitState(i) })),
          events: sim.events.slice(-6).reverse(),
          log: sim.plant.events.slice(-4).reverse().map((e) => `${e.t.toFixed(1)} s · ${e.text}`),
          flags: sim.plant.flags,
        });
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [sim, run, speed]);

  const modules = useMemo(() => {
    if (!sim) return [];
    const by: Record<string, { ins: string[]; outs: string[] }> = {};
    for (const e of sim.meta.io.ix) { const m = e.name.split("_")[0]; (by[m] ??= { ins: [], outs: [] }).ins.push(e.name); }
    for (const e of sim.meta.io.qx) { const m = e.name.split("_")[0]; (by[m] ??= { ins: [], outs: [] }).outs.push(e.name); }
    return Object.entries(by).filter(([m]) => m !== "cell");
  }, [sim]);

  if (err) return <Empty text={`The PLC program could not load (${err}). Run sil/run.py.`} />;
  if (!sim || !live) return <Empty text="Compiling the PLC program…" />;
  const fmt = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
  const caught = proof?.mutants?.filter((m) => m.caught).length ?? 0;

  return (
    <div className="np plc">
      <div className="np-head">
        <div><b>PLC program, live</b><span>IEC 61131-3, compiled by MatIEC, running in your browser</span></div>
        <a className="ui-btn" href={`${BASE}sil/stf_plc.st`} target="_blank" rel="noopener noreferrer">Source <Icon name="external" size={13} /></a>
      </div>

      <div className="plc-bar">
        <button className="ui-btn icon" onClick={() => setRun(!run)} aria-label={run ? "Pause" : "Run"}><Icon name={run ? "pause" : "play"} size={15} /></button>
        <div className="plc-speed" role="group" aria-label="Speed">
          {SPEEDS.map((s) => <button key={s} className={s === speed ? "on" : ""} onClick={() => setSpeed(s)}>{s}×</button>)}
        </div>
        <button className="ui-btn" onClick={restart}>Restart</button>
        <span className={`tag ${live.phase === 2 ? "run" : "idle"}`}>{PHASE[live.phase] ?? "?"} · {fmt(live.t)}</span>
      </div>

      {proof && (
        <div className="np-stats">
          <Stat label="Decisions = proven model" value={`${proof.decisions}/${proof.decisions}`} sub="every job start, replayed in control.py" tone={proof.checks.decisions ? "ok" : "bad"} />
          <Stat label="Mutants caught" value={`${caught}/${proof.mutants?.length ?? 0}`} sub="the proof can fail" tone={caught === proof.mutants?.length ? "ok" : "bad"} />
          <Stat label="Order time" value={`${Math.round(proof.order_s)} s`} sub={`model ${Math.round(proof.model_s)} s`} tone={proof.checks.timing ? "ok" : "warn"} />
          <Stat label="U4's program" value={proof.u4.accepted ? "compiled" : "rejected"} sub={`${proof.u4.errors} MatIEC errors`} tone="warn" />
        </div>
      )}

      <h4 className="np-h">Units</h4>
      <div className="plc-units">
        {live.units.map(({ u, sn }) => {
          const say = names[u]?.[sn] ?? "";
          const cls = sn === 910 ? "bad" : sn >= 1000 ? "busy" : sn === 100 ? "ready" : "";
          return (
            <div key={u} className={`plc-unit ${cls}`} title={say}>
              <b>{u}</b><code>{sn}</code><span>{sn === 100 ? "ready" : say.replace(/^\S+ /, "")}</span>
            </div>
          );
        })}
      </div>

      <h4 className="np-h">I/O image</h4>
      <div className="plc-io">
        {modules.map(([m, { ins, outs }]) => (
          <div key={m}><b>{m}</b>
            <span>{ins.map((n) => <i key={n} className={live.on.has(n) ? "on in" : "in"} title={n}>{n.slice(m.length + 1).replace("_Valid", "")}</i>)}</span>
            <span>{outs.map((n) => <i key={n} className={live.on.has(n) ? "on out" : "out"} title={n}>{n.slice(m.length + 1)}</i>)}</span>
          </div>
        ))}
      </div>

      <h4 className="np-h">Jobs</h4>
      <div className="plc-log">
        {live.events.map((e, i) => (
          <div key={i}><em>{e.t.toFixed(1)}</em><b className={e.kind}>{e.kind}</b><span>{e.job.replace(/_/g, " ")}</span><i>{e.unit}</i></div>
        ))}
        {live.log.map((l, i) => <p key={`l${i}`}>{l}</p>)}
        {live.flags.map((f) => <p key={f} className="bad">{f}</p>)}
      </div>

      {proof && (
        <details className="plc-find">
          <summary>{proof.findings.length} findings: what running the program exposed</summary>
          {proof.findings.map((f) => <p key={f.id}><b>{f.id}</b> {f.text}</p>)}
        </details>
      )}
      <p className="np-foot">{proof ? `${proof.st_lines} lines of Structured Text · ${proof.compiler} · wasm ${proof.wasm_sha}. ` : ""}
        The plant sees only the program's outputs; light barriers, the vacuum switch, RFID and the colour sensor report what is physically there.</p>
    </div>
  );
}
