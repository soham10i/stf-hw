// Live readouts for the side panel, at the store's telemetry rate (8 Hz): the 3D loop runs at
// the frame rate and must never wait on React, while a table of numbers updating 8 times a
// second is smooth enough and costs almost nothing. The store tells the panel when to redraw
// (scene/store/useCellStore.ts); nothing polls.
//
// Two sources. The TWIN is the machine the 3D view animates - every axis, the
// vacuum, the oven and the light barriers - and needs no server. The physics
// KERNEL (services/api) streams its own simulation when the live API is there.

import { useState } from "react";
import { useCell, type CellStore } from "../scene/store/useCellStore";
import { hot } from "../store";
import type { SceneDescriptor } from "../types";
import { sendCommand } from "../socket";

type Row = [label: string, value: string, warn?: boolean];

const mm = (v: number) => `${v.toFixed(1)} mm`;
const pct = (v: number) => `${Math.round(v * 100)} %`;

function twinRows(store: CellStore): { crane: Row[]; vgr: Row[]; oven: Row[]; sensors: [string, boolean][]; cycle: string } {
  const J = store.joints, a = J.hbw, s = J.oven, c = store.model.cycle, vg = J.vgr;
  const crane: Row[] = [["travel", mm(a.travel)], ["lift", mm(a.lift)], ["fork", mm(a.fork)], ["belt", mm(a.belt)]];
  const vgr: Row[] = [
    ["swivel", `${vg.swivel.toFixed(1)}°`], ["reach", mm(vg.reach)], ["plunge", mm(vg.plunge)],
    ["vacuum", pct(vg.seal)], ["carrying", vg.carry ?? "—"],
  ];
  const oven: Row[] = [
    ["chamber temp", `${Math.round(s.chamberC)} °C`, s.chamberC > 240],
    ["elements", s.element > 0.5 ? "heating" : "off"],
    ["oven slider", mm(s.slider)], ["oven door", mm(s.door)], ["oven sauger", mm(s.sauger)],
    ["turntable", `${s.turn.toFixed(1)}°`], ["baked", pct(s.baked)], ["belt path", mm(s.ly)],
  ];
  const sensors: [string, boolean][] = [
    ...Object.entries(J.beams).map(([k, v]) => [`${k} light barrier`, v] as [string, boolean]),
    ["VGR vacuum", vg.seal > 0.5],
    ["oven heating", s.lamp > 0.5],
    ["oven at temperature", s.chamberC >= 170],
    ["sorting vacuum", s.vac > 0.5],
  ];
  const cycle = c.total > 0 ? `${c.from} → ${c.to} · ${Math.round((100 * c.t) / c.total)} %` : "starting";
  return { crane, vgr, oven, sensors, cycle };
}

/** One machine's live values as a compact card. */
function Card({ title, rows, wide }: { title: string; rows: Row[]; wide?: boolean }) {
  if (!rows.length) return null;
  return (
    <div className={`tm-card ${wide ? "wide" : ""}`}>
      <b>{title}</b>
      <dl>{rows.map(([k, v, w]) => <div key={k}><dt>{k}</dt><dd className={w ? "warn" : ""}>{v}</dd></div>)}</dl>
    </div>
  );
}

function kernelRows(scene: SceneDescriptor): Row[] {
  return scene.joint_refs.map((ref) => {
    const [dev, j] = ref.split(".");
    const unit = scene.devices[dev].joints[j].kind === "revolute" ? "°" : "mm";
    const err = hot.tracking_error[ref] ?? 0;
    return [ref, `${(hot.joints[ref] ?? 0).toFixed(1)}${unit}  ·  err ${err.toFixed(2)}`, Math.abs(err) > 1];
  });
}

export function TelemetryPanel({ scene }: { scene: SceneDescriptor | null }) {
  // re-read at the store's telemetry rate; the kernel's values (socket.ts) are read alongside
  const twin = useCell(twinRows);
  const s = { twin, kernel: scene ? kernelRows(scene) : [], busy: hot.busy, t: hot.t };

  return (
    <div className="panel">
      <h2>Telemetry <span className="tag run">{s.twin.cycle}</span></h2>
      <div className="sensors tm-sensors">
        {s.twin.sensors.map(([name, on]) => <span key={name} className={on ? "led on" : "led"}>{name}</span>)}
      </div>
      <div className="tm-grid">
        <Card title="Crane" rows={s.twin.crane} />
        <Card title="Robot arm" rows={s.twin.vgr} />
        <Card title="Oven & sorting" rows={s.twin.oven} wide />
      </div>

      {scene && (
        <details className="tm-kernel">
          <summary>Physics kernel <span className={s.busy ? "tag run" : "tag idle"}>{s.busy ? "RUNNING" : "IDLE"}</span>
            <em>live API · the original 3×3 machine</em></summary>
          <p className="clock">t = {s.t.toFixed(1)} s</p>
          <table className="tbl">
            <tbody>
              {s.kernel.map(([k, v, w]) => <tr key={k}><td>{k}</td><td className={"num " + (w ? "warn" : "")}>{v}</td></tr>)}
              {Object.entries(hot.motors).map(([id, m]) => (
                <tr key={id}><td>{id}</td><td className="num">{m.amps.toFixed(2)} A · {(m.health * 100).toFixed(1)} % · {m.phase}</td></tr>
              ))}
            </tbody>
          </table>
          <KernelCommands />
        </details>
      )}
    </div>
  );
}

/** Manual commands to the physics kernel (the live API's crane, which still models the original
    3x3 rack): retrieve or store slot B2, or home the crane. */
function KernelCommands() {
  const [msg, setMsg] = useState<string | null>(null);
  const run = async (op: string, slot: string | null) => {
    try { await sendCommand(op, slot); setMsg(`Queued ${op}${slot ? " " + slot : ""} on the physics kernel.`); }
    catch (e) { setMsg((e as Error).message); }
  };
  return (
    <div className="tm-cmds">
      <b>Manual crane commands</b>
      <div className="op-actions">
        <div className="btn-row">
          <button className="op retrieve" onClick={() => run("retrieve", "B2")}>Retrieve B2</button>
          <button className="op store" onClick={() => run("store", "B2")}>Store B2</button>
        </div>
        <button className="op home" onClick={() => run("home", null)}>Home crane</button>
        {msg && <p className="ord-msg ok" role="status">{msg}</p>}
      </div>
    </div>
  );
}
