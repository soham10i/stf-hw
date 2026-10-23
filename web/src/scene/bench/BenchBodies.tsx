// The Test bench in the scene: what the physics worker publishes, drawn each frame from the shared
// bridge - the cookies and moulds (as many as are on the bench, at their float64 poses), the
// warehouse's and the arm's axis positions for their renderers, and for the sorting
// line's own renderer the pushers' strokes, the belt's travel and the barriers' states (benchStore
// `live`). This reads; it never steps physics. Rendered inside the scene's factory group (the
// factory's mm frame mapped to three.js as in parts.tsx `v`).
import { useFrame } from "@react-three/fiber";
import { useMemo, useRef, useState } from "react";
import * as THREE from "three";

import type { Snapshot } from "../../core/SimulationBridge";
import { SnapshotInterpolator } from "../../core/SnapshotInterpolator";
import { Cookie, MM } from "../parts";
import { AXIS_STRIDE } from "../../core/SimulationBridge";
import { benchActive, live, useBench } from "./benchStore";
import { BARRIERS, COLOURS, COOKIE } from "./sortingWorld";

export function BenchBodies() {
  const b = useBench();
  if (!benchActive() || !live.client) return null;
  return <Bodies beltSpeed={b.beltSpeed} />;
}

function Bodies({ beltSpeed }: { beltSpeed: number }) {
  // the newest state as read, and the one drawn: interpolated between physics steps so motion is
  // smooth at any display rate (core/SnapshotInterpolator.ts)
  const raw = useMemo<Snapshot>(() => live.client!.snapshot(), []);
  const snap = useMemo<Snapshot>(() => live.client!.snapshot(), []);
  const interp = useMemo(() => new SnapshotInterpolator(live.client!.layout), []);
  const groups = useRef(new Map<string, THREE.Group>());
  const [ids, setIds] = useState<string[]>([]);
  const lastSim = useRef<number | null>(null);
  useFrame((_, delta) => {
    const c = live.client;
    if (!c || !c.read(raw)) return;
    interp.push(raw);
    if (!interp.sample(delta, c.rate, c.running, snap)) return;
    if (live.module !== "sorting") {
      // the axes: where each really is, for the crane's and the arm's renderers
      if (live.axes.length !== snap.axisCount * AXIS_STRIDE) live.axes = new Float64Array(snap.axisCount * AXIS_STRIDE);
      live.axes.set(snap.axes.subarray(0, snap.axisCount * AXIS_STRIDE));
      const ax = (i: number) => snap.axes[i * AXIS_STRIDE];
      if (live.module === "warehouse") live.hbw = { travel: ax(0), lift: ax(1), fork: ax(2), belt: ax(3) };
      else live.vgr = { swivel: ax(0), plunge: ax(1), reach: ax(2) };
    }
    const w = live.world;
    const order = c.partOrder;
    const t = snap.transforms;
    const cookies: string[] = [];
    const xy: [number, number][] = [];
    for (let i = 0; i < snap.partCount; i++) {
      const id = order[i];
      const k = i * 7;
      if (id?.startsWith("cookie_") || id?.startsWith("mould_")) {
        cookies.push(id);
        xy.push([t[k], t[k + 1]]);
        const g = groups.current.get(id);
        if (g) {
          // factory (x, y, z) mm -> three (x, z, y); the y/z swap mirrors, so the turn reverses
          g.position.set(t[k] * MM, t[k + 2] * MM, t[k + 1] * MM);
          g.quaternion.set(-t[k + 3], -t[k + 5], -t[k + 4], t[k + 6]);
        }
      } else if (w && id?.startsWith("pusher_")) {
        const j = COLOURS.indexOf(id.slice(7) as (typeof COLOURS)[number]);
        const base = w.pusherBase[COLOURS[j]];
        // the stroke: how far the pusher has moved along its own axis
        live.pusherMm[j] = (t[k] - base.at[0]) * base.axis[0] + (t[k + 1] - base.at[1]) * base.axis[1] + (t[k + 2] - base.at[2]) * base.axis[2];
      }
    }
    if (cookies.length !== ids.length || cookies.some((id, i) => id !== ids[i])) setIds(cookies);
    if (!w) return;
    live.cookieXY = xy;
    BARRIERS.forEach((tag, i) => { live.pins[i] = snap.pinVolts[w.barrierPin[tag]]; });
    if (lastSim.current !== null) live.beltTravel += (snap.simTime - lastSim.current) * beltSpeed;
    lastSim.current = snap.simTime;
  });
  return (
    <>
      {ids.map((id) => (
        <group key={id} ref={(g) => { if (g) groups.current.set(id, g); else groups.current.delete(id); }}>
          {id.startsWith("mould_") ? <MouldBody /> : (
            // the physics pose is the cookie's centre; the mesh stands on its underside
            <group position={[0, (-COOKIE.h / 2) * MM, 0]}>
              <Cookie x={0} y={0} z={0} colour={live.world?.tint[live.colours.get(id) ?? "weiss"] ?? "#D8B98C"} />
            </group>
          )}
        </group>
      ))}
    </>
  );
}

/** A mould as the physics sees it: a tray of the CAD's size, its pose at its centre. */
function MouldBody() {
  const size = live.warehouse?.mouldSize ?? [60, 64, 20];
  // factory (x, y, z) -> three (x, z, y)
  return (
    <mesh castShadow receiveShadow>
      <boxGeometry args={[size[0] * MM, size[2] * MM, size[1] * MM]} />
      <meshStandardMaterial color="#9aa3ac" metalness={0.5} roughness={0.42} />
    </mesh>
  );
}
