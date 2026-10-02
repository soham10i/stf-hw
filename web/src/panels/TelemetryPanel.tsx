// Live readouts for the side panel, sampled at 8 Hz: the 3D loop runs at the frame
// rate and must never wait on React, while a table of numbers updating 8 times a
// second is smooth enough and costs almost nothing.
//
// Two sources. The TWIN is the machine the 3D view animates - every axis, the
// vacuum, the oven and the light barriers - and needs no server. The physics
// KERNEL (services/api) streams its own simulation when the live API is there.

import { useEffect, useState } from "react";
import { hbwHot, ovenHot, twinOrders, vgrHot } from "../scene/HbwCad";
import { hot } from "../store";
import type { SceneDescriptor } from "../types";

type Row = [label: string, value: string, warn?: boolean];

const mm = (v: number) => `${v.toFixed(1)} mm`;
const pct = (v: number) => `${Math.round(v * 100)} %`;

function twinRows(): { crane: Row[]; vgr: Row[]; oven: Row[]; sensors: [string, boolean][]; cycle: string } {
  const a = hbwHot.axes, s = ovenHot.s, c = twinOrders.cycle;
  const crane: Row[] = [["travel", mm(a.travel)], ["lift", mm(a.lift)], ["fork", mm(a.fork)], ["belt", mm(a.belt)]];
  const vgr: Row[] = [
    ["swivel", `${vgrHot.swivel.toFixed(1)}°`], ["reach", mm(vgrHot.reach)], ["plunge", mm(vgrHot.plunge)],
    ["vacuum", pct(vgrHot.seal)], ["carrying", vgrHot.carry ?? "—"],
  ];
  const oven: Row[] = s
    ? [["oven slider", mm(s.slider)], ["oven door", mm(s.door)], ["oven sauger", mm(s.sauger)],
       ["turntable", `${s.turn.toFixed(1)}°`], ["baked", pct(s.baked)], ["belt path", mm(s.ly)]]
    : [];
  const sensors: [string, boolean][] = [
    ...Object.entries(hbwHot.blocked).map(([k, v]) => [`${k} light barrier`, v] as [string, boolean]),
    ["VGR vacuum", vgrHot.seal > 0.5],
    ["oven lamp", !!s && s.lamp > 0.5],
    ["sorting vacuum", !!s && s.vac > 0.5],
  ];
  const cycle = c.total > 0 ? `${c.from} → ${c.to} · ${Math.round((100 * c.t) / c.total)} %` : "starting";
  return { crane, vgr, oven, sensors, cycle };
}

function Table({ title, rows }: { title: string; rows: Row[] }) {
  if (!rows.length) return null;
  return (
    <>
      <h3>{title}</h3>
      <table className="tbl">
        <tbody>
          {rows.map(([k, v, w]) => (
            <tr key={k}><td>{k}</td><td className={"num " + (w ? "warn" : "")}>{v}</td></tr>
          ))}
        </tbody>
      </table>
    </>
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
  const sample = () => ({ twin: twinRows(), kernel: scene ? kernelRows(scene) : [], busy: hot.busy, t: hot.t });
  const [s, setS] = useState(sample);
  useEffect(() => {
    const id = window.setInterval(() => setS(sample()), 125); // 8 Hz
    return () => window.clearInterval(id);
  }, [scene]);

  return (
    <div className="panel">
      <h2>Telemetry <span className="tag run">{s.twin.cycle}</span></h2>

      <Table title="Warehouse crane" rows={s.twin.crane} />
      <Table title="Vacuum gripper robot" rows={s.twin.vgr} />
      <Table title="Oven & sorting line" rows={s.twin.oven} />

      <h3>Sensors</h3>
      <div className="sensors">
        {s.twin.sensors.map(([name, on]) => <span key={name} className={on ? "led on" : "led"}>{name}</span>)}
      </div>

      {scene && (
        <>
          <h3>Physics kernel <span className={s.busy ? "tag run" : "tag idle"}>{s.busy ? "RUNNING" : "IDLE"}</span></h3>
          <p className="clock">t = {s.t.toFixed(1)} s</p>
          <table className="tbl">
            <tbody>
              {s.kernel.map(([k, v, w]) => <tr key={k}><td>{k}</td><td className={"num " + (w ? "warn" : "")}>{v}</td></tr>)}
              {Object.entries(hot.motors).map(([id, m]) => (
                <tr key={id}><td>{id}</td><td className="num">{m.amps.toFixed(2)} A · {(m.health * 100).toFixed(1)} % · {m.phase}</td></tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
