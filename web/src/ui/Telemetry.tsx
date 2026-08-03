// Live readouts for the side panel. These DO go through React state, but sampled
// at 8 Hz rather than the 30 Hz frame rate - the 3D view reads `hot` directly and
// must never be gated on React, whereas a numeric panel updating 8 times a second
// is smooth enough and costs almost nothing.

import { useEffect, useState } from "react";
import { hot } from "../store";
import type { SceneDescriptor } from "../types";

interface Snapshot {
  t: number;
  busy: boolean;
  joints: Record<string, number>;
  err: Record<string, number>;
  motors: Record<string, { amps: number; health: number; phase: string }>;
  sensors: Record<string, boolean>;
}

function snap(): Snapshot {
  return {
    t: hot.t,
    busy: hot.busy,
    joints: hot.joints,
    err: hot.tracking_error,
    motors: hot.motors,
    sensors: hot.sensors,
  };
}

export function Telemetry({ scene }: { scene: SceneDescriptor }) {
  const [s, setS] = useState<Snapshot>(snap);

  useEffect(() => {
    const id = setInterval(() => setS(snap()), 125); // 8 Hz
    return () => clearInterval(id);
  }, []);

  return (
    <div className="panel">
      <h2>
        Telemetry <span className={s.busy ? "tag run" : "tag idle"}>{s.busy ? "RUNNING" : "IDLE"}</span>
      </h2>
      <p className="clock">t = {s.t.toFixed(1)} s</p>

      <table className="tbl">
        <thead>
          <tr>
            <th>joint</th>
            <th>pos</th>
            <th>err</th>
          </tr>
        </thead>
        <tbody>
          {scene.joint_refs.map((ref) => {
            const unit = scene.devices[ref.split(".")[0]].joints[ref.split(".")[1]].kind === "revolute" ? "°" : "mm";
            const err = s.err[ref] ?? 0;
            return (
              <tr key={ref}>
                <td>{ref}</td>
                <td className="num">
                  {(s.joints[ref] ?? 0).toFixed(1)}
                  {unit}
                </td>
                <td className={"num " + (Math.abs(err) > 1 ? "warn" : "")}>{err.toFixed(2)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h3>Motors</h3>
      <table className="tbl">
        <tbody>
          {Object.entries(s.motors).map(([id, m]) => (
            <tr key={id}>
              <td>{id}</td>
              <td className="num">{m.amps.toFixed(2)} A</td>
              <td className="num">
                <span className="health" style={{ opacity: 0.4 + m.health * 0.6 }}>
                  {(m.health * 100).toFixed(1)}%
                </span>
              </td>
              <td className="phase">{m.phase}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Sensors</h3>
      <div className="sensors">
        {Object.entries(s.sensors).map(([name, on]) => (
          <span key={name} className={on ? "led on" : "led"}>
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}
