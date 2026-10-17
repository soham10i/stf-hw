// The oven station and the one travelling cookie of the oven/sorting flow (OvenFlow.ts).


import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";










import { type CadPart, type CadDoc, boxSize, cylSpec } from "../shared/model";
import type { CellJoints, Drive } from "./store/useCellStore";
import { AIM, MM, v, centreOf, Solid, Cookie, useBeltTexture } from "./parts";
import { subjects } from "../vision/photo";





const LAMP_ON = new THREE.Color("#ffb13b"), LAMP_OFF = new THREE.Color("#6f6a5e");
const LED_OK = new THREE.Color("#39d353"), LED_HIT = new THREE.Color("#ff3b30");

/** The oven station, rebuilt to Abb. 9: Ofenschieber (+X), Ofentuer (+Z),
    the station's own Sauger (+Y) with its one-stroke lowering cylinder (-Z),
    the Drehtisch (Rz), the Saege and the Auswerfer (+Y). Every joint, and the
    heating's glow and chamber temperature, is read from `joints`, which the
    coordinator writes. The cookie itself is drawn once, at factory level
    (FlowCookie), not per holder. */
export function OvenModule({ doc, joints }: { doc: CadDoc; joints: CellJoints["oven"] }) {
  const g = {
    slider: useRef<THREE.Group>(null), door: useRef<THREE.Group>(null),
    turn: useRef<THREE.Group>(null), sauger: useRef<THREE.Group>(null),
    lower: useRef<THREE.Group>(null), push: useRef<THREE.Group>(null),
  };
  const lamp = useRef<THREE.MeshStandardMaterial>(null);
  const lampLight = useRef<THREE.PointLight>(null);
  const cup = useRef<THREE.MeshStandardMaterial>(null);
  // the heating: one material for every element, its glow following the element temperature
  const heaterMat = useMemo(() => new THREE.MeshStandardMaterial({
    color: "#6f7175", metalness: 0.75, roughness: 0.42, emissive: new THREE.Color("#ff4a0a"), emissiveIntensity: 0, toneMapped: false,
  }), []);
  const display = useReadout();
  const heatLed = useRef<THREE.MeshStandardMaterial>(null);
  const beltDrive = useRef<Drive>({ travel: 0, lift: 0, fork: 0, belt: 0, plunge: 0, reach: 0, swivel: 0 });
  const sawDrive = useRef<Drive>({ travel: 0, lift: 0, fork: 0, belt: 0, plunge: 0, reach: 0, swivel: 0 });
  const [tx, ty] = doc.oven.turntable;
  const A = doc.oven.authoring;
  const byFrame = useMemo(() => {
    const m: Record<string, CadPart[]> = {
      world: [], slider: [], door: [], turn: [], sauger: [], lower: [], push: [],
    };
    for (const p of doc.oven.parts) if (p.n !== "Q9_oven_lamp") (m[p.f] ??= []).push(p);
    return m;
  }, [doc]);
  const lampPart = doc.oven.parts.find((p) => p.n === "Q9_oven_lamp");
  const tex = useBeltTexture();

  const shown = useRef(NaN);
  useFrame(() => {
    const s = joints;
    const on = s.lamp > 0.5, el = s.element;
    heaterMat.emissiveIntensity = 2.6 * el * el;
    heaterMat.color.setRGB(0.44 + 0.3 * el, 0.44 - 0.12 * el, 0.46 - 0.2 * el);
    // the display redraws (and builds its string) only when the reading changes
    const deg = Math.round(s.chamberC);
    if (deg !== shown.current) { shown.current = deg; display.show(`${deg} °C`); }
    if (heatLed.current) heatLed.current.emissiveIntensity = on ? 3 : 0.15;
    // module frame = factory axes: +X -> three x, +Y -> three z, +Z -> three y
    if (g.slider.current) g.slider.current.position.x = (s.slider - A.slider) * MM;
    if (g.door.current) g.door.current.position.y = (s.door - A.door) * MM;
    if (g.turn.current) g.turn.current.rotation.y = -THREE.MathUtils.degToRad(s.turn - A.turn);
    if (g.sauger.current) g.sauger.current.position.z = (s.sauger - A.sauger) * MM;
    if (g.lower.current) g.lower.current.position.y = -(s.lower - A.lower) * MM;
    if (g.push.current) g.push.current.position.z = (s.push - A.push) * MM;
    if (lamp.current) {
      lamp.current.emissiveIntensity = 0.05 + 4 * s.lamp;
      lamp.current.color.copy(s.lamp > 0.5 ? LAMP_ON : LAMP_OFF);
    }
    if (lampLight.current) lampLight.current.intensity = 1.2 * s.lamp + 4 * el;
    if (cup.current) cup.current.emissiveIntensity = 0.6 * s.vac;
    beltDrive.current.belt = s.beltOven;
    sawDrive.current.belt = s.saw * 20;
  });

  const P = (p: CadPart) => {
    const drive = p.mech === "spin:saw" ? sawDrive : beltDrive;
    // the disc turns with its group; drawn as a plain solid, not a belt roller
    const part = p.mech === "spin:turn" ? { ...p, mech: "" } : p;
    if (p.n === "Q11_suction_cup") {
      const [, len, dia] = cylSpec(p);
      return (
        <mesh key={p.n} position={centreOf(p)} castShadow>
          <cylinderGeometry args={[(dia / 2) * MM * 0.55, (dia / 2) * MM, len * MM, 24]} />
          <meshStandardMaterial ref={cup} color={p.c} roughness={0.8} emissive="#3aa0ff" emissiveIntensity={0} />
        </mesh>
      );
    }
    if (/^heater_(top|bot)_\d(_\d)?(_bend)?$|^heater_top_bend$/.test(p.n) && p.k === "cyl") {
      const [ax, len, dia] = cylSpec(p);
      return (
        <mesh key={p.n} position={centreOf(p)} rotation={AIM[ax]} material={heaterMat} castShadow>
          <cylinderGeometry args={[(dia / 2) * MM, (dia / 2) * MM, len * MM, 20]} />
        </mesh>
      );
    }
    if (CASING[p.n]) {
      const [dx, dy, dz] = boxSize(p);
      return (
        <mesh key={p.n} position={centreOf(p)} castShadow receiveShadow>
          <boxGeometry args={[dx * MM, dz * MM, dy * MM]} />
          <meshStandardMaterial {...CASING[p.n]} />
        </mesh>
      );
    }
    if (p.n === "Q13_oven_door") return <WindowDoor key={p.n} part={p} />;
    if (p.n === "drehtisch_nest") {
      // the nest's top is the disc's top (both z = Z_W): drawn coplanar they z-fight into a
      // flickering black pattern as the disc turns. Drawn as the locating ring it is, a hair
      // proud of the disc and depth-biased toward the camera.
      const [, len, dia] = cylSpec(p);
      return (
        <mesh key={p.n} position={v(p.p[0], p.p[1], p.p[2] + len + 0.3)} rotation={[-Math.PI / 2, 0, 0]} renderOrder={1}>
          <ringGeometry args={[(dia / 2 - 3) * MM, (dia / 2) * MM, 48]} />
          <meshStandardMaterial color="#2b2b2f" roughness={0.7} polygonOffset polygonOffsetFactor={-2} polygonOffsetUnits={-2} side={THREE.DoubleSide} />
        </mesh>
      );
    }
    if (p.n === "oven_control_panel") return <ControlPanel key={p.n} part={p} display={display} led={heatLed} />;
    return <Solid key={p.n} part={part} drive={drive} pitch={4} tex={tex} />;
  };
  return (
    <group>
      {byFrame.world.map(P)}
      {lampPart && (() => {
        // Q9 "Leuchte Ofen": a lamp on the roof you can see from anywhere -
        // dark when idle, glowing amber (and lighting the chamber) while baking
        const [dx, dy, dz] = boxSize(lampPart);
        const [px, py, pz] = lampPart.p;
        return (
          <group>
            <mesh position={centreOf(lampPart)} castShadow>
              <boxGeometry args={[dx * MM, dz * MM, dy * MM]} />
              <meshStandardMaterial color="#2a2b2e" roughness={0.6} />
            </mesh>
            <mesh position={v(px + dx / 2, py + dy / 2, pz + dz + 7)}>
              <sphereGeometry args={[8 * MM, 20, 16]} />
              <meshStandardMaterial ref={lamp} color="#6f6a5e" emissive="#ff7a00" emissiveIntensity={0.05} toneMapped={false}
                transparent opacity={0.92} />
            </mesh>
            <pointLight ref={lampLight} position={v(200, 100, 150)} color="#ff9a3c" intensity={0} distance={4} decay={2} />
          </group>
        );
      })()}
      <group ref={g.slider}>{byFrame.slider.map(P)}</group>
      <group ref={g.door}>{byFrame.door.map(P)}</group>
      <group ref={g.push}>{byFrame.push.map(P)}</group>
      <group ref={g.sauger}>
        {byFrame.sauger.map(P)}
        <group ref={g.lower}>{byFrame.lower.map(P)}</group>
      </group>
      <group position={v(tx, ty, 0)}>
        <group ref={g.turn}>
          <group position={v(-tx, -ty, 0)}>{byFrame.turn.map(P)}</group>
        </group>
      </group>
    </group>
  );
}

// The oven's casing, as a real deck oven is built: brushed stainless walls over ceramic-fibre
// insulation, a stainless floor, a black enamelled top. Drawn here rather than from the ft
// detail meshes, which show the plastic model's red plates.
// metalness kept moderate: a fully metallic surface only mirrors the dark studio and reads black
const STAINLESS = { color: "#d4d9de", metalness: 0.55, roughness: 0.3 };
const CASING: Record<string, object> = {
  oven_wall_back: STAINLESS, oven_wall_L: STAINLESS, oven_wall_R: STAINLESS, oven_front_lintel: STAINLESS,
  oven_floor: { color: "#b9bfc5", metalness: 0.55, roughness: 0.38 },
  oven_roof: { color: "#2a2d31", metalness: 0.35, roughness: 0.5 },
  oven_pedestal: { color: "#2f3236", metalness: 0.3, roughness: 0.6 },
};

/** The oven door: a stainless frame round a tinted, triple-glazed window, so the glowing
    elements and the cookie on its tray can be watched while it bakes. Inside the door's
    proven envelope (factory axes: x through the door, y across, z up). */
function WindowDoor({ part }: { part: CadPart }) {
  const [dx, dy, dz] = boxSize(part);
  const [x, y, z] = part.p, f = 16;
  const bar = (yy: number, zz: number, w: number, h: number, k: string) => (
    <mesh key={k} position={v(x + dx / 2, yy + w / 2, zz + h / 2)} castShadow>
      <boxGeometry args={[dx * MM, h * MM, w * MM]} /><meshStandardMaterial {...STAINLESS} />
    </mesh>
  );
  return (
    <group>
      {bar(y, z, f, dz, "l")}{bar(y + dy - f, z, f, dz, "r")}
      {bar(y + f, z, dy - 2 * f, f, "b")}{bar(y + f, z + dz - f, dy - 2 * f, f, "t")}
      <mesh position={v(x + dx / 2, y + dy / 2, z + dz / 2)} renderOrder={2}>
        <boxGeometry args={[(dx - 2) * MM, (dz - 2 * f) * MM, (dy - 2 * f) * MM]} />
        <meshPhysicalMaterial color="#2a1a10" transparent opacity={0.28} roughness={0.04} metalness={0}
          clearcoat={1} clearcoatRoughness={0.03} depthWrite={false} />
      </mesh>
      {/* the gasket where the frame meets the glass */}
      <mesh position={v(x + dx + 0.3, y + dy / 2, z + dz - f / 2)}>
        <boxGeometry args={[0.6 * MM, 3 * MM, (dy - 2 * f) * MM]} /><meshStandardMaterial color="#111" roughness={0.9} />
      </mesh>
    </group>
  );
}

/** The control panel on the oven's side: the controller's display (chamber temperature from
    the thermocouple), the set-point and timer knobs and the heating lamp. Its face is +Y. */
/** A seven-segment-style readout drawn into a canvas texture; `show` redraws it only when the
    text changes. */
export function useReadout(w = 256, h = 96) {
  return useMemo(() => {
    const canvas = document.createElement("canvas");
    canvas.width = w; canvas.height = h;
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    // the stage is drawn inside one mirror (Stage.tsx: scale z -1), which mirrors the readout
    // too: read the canvas right to left so the digits come out the right way round
    tex.repeat.x = -1; tex.offset.x = 1;
    let last = "";
    const show = (text: string) => {
      if (text === last) return;
      last = text;
      const g = canvas.getContext("2d")!;
      g.fillStyle = "#0b0907"; g.fillRect(0, 0, w, h);
      g.font = `700 ${Math.round(h * 0.62)}px ui-monospace, Menlo, monospace`;
      g.textAlign = "center"; g.textBaseline = "middle";
      g.shadowColor = "rgba(255,110,40,.8)"; g.shadowBlur = 10;
      g.fillStyle = "#ff7a2e"; g.fillText(text, w / 2, h / 2 + 2);
      tex.needsUpdate = true;
    };
    show("25 °C");
    return { tex, show };
  }, [w, h]);
}

function ControlPanel({ part, display, led }: {
  part: CadPart; display: { tex: THREE.Texture }; led: React.RefObject<THREE.MeshStandardMaterial>;
}) {
  const [dx, dy, dz] = boxSize(part);
  const [x, y, z] = part.p, face = y + dy;
  return (
    <group>
      <mesh position={centreOf(part)} castShadow><boxGeometry args={[dx * MM, dz * MM, dy * MM]} /><meshStandardMaterial {...STAINLESS} /></mesh>
      {/* black glass fascia */}
      <mesh position={v(x + dx / 2, face + 0.5, z + dz / 2)}>
        <boxGeometry args={[(dx - 16) * MM, (dz - 16) * MM, 1 * MM]} /><meshStandardMaterial color="#121418" metalness={0.2} roughness={0.15} />
      </mesh>
      {/* the controller's display: a texture on the fascia, so the oven hides it like any face */}
      <mesh position={v(x + dx / 2, face + 1.2, z + dz - 34)} rotation={[0, 0, 0]}>
        <planeGeometry args={[64 * MM, 24 * MM]} />
        <meshBasicMaterial map={display.tex} toneMapped={false} />
      </mesh>
      {[x + dx * 0.32, x + dx * 0.68].map((kx, i) => (
        <group key={i} position={v(kx, face + 4, z + 42)}>
          <mesh rotation={[Math.PI / 2, 0, 0]} castShadow><cylinderGeometry args={[11 * MM, 12 * MM, 8 * MM, 28]} />
            <meshStandardMaterial color="#1b1d21" roughness={0.45} metalness={0.3} /></mesh>
          <mesh position={[0, 6 * MM, 4.2 * MM]}><boxGeometry args={[2 * MM, 8 * MM, 0.6 * MM]} /><meshStandardMaterial color="#d9dde2" /></mesh>
        </group>
      ))}
      <mesh position={v(x + dx / 2, face + 1.5, z + 70)}>
        <sphereGeometry args={[3.5 * MM, 16, 12]} />
        <meshStandardMaterial ref={led} color="#ff8a2a" emissive="#ff6a00" emissiveIntensity={0.15} toneMapped={false} />
      </mesh>
    </group>
  );
}

/** The one travelling cookie, in FACTORY coordinates: wherever the flow says it
    is, in whatever colour the bake has given it. */
export function FlowCookie({ workpiece }: { workpiece: CellJoints["workpiece"] }) {
  const grp = useRef<THREE.Group>(null);
  // the inspection camera in the colour hood sees the cookie (vision/photo.ts)
  useEffect(() => {
    const g = grp.current;
    if (!g) return;
    subjects.add(g);
    return () => { subjects.delete(g); };
  }, []);
  useFrame(() => {
    if (!grp.current) return;
    grp.current.visible = workpiece.visible;
    const p = workpiece.pos;
    grp.current.position.set(p[0] * MM, p[2] * MM, p[1] * MM);
  });
  return (
    <group ref={grp}>
      <Cookie x={0} y={0} z={0} tint={workpiece.tint} />
    </group>
  );
}

/** Light barriers on the oven and the sorting line: a beam from each LED to
    its phototransistor; when the travelling cookie (also while it rests in a
    Lagerstelle) cuts it, the beam flickers and the receiver blinks red. */
export function FlowBarriers({ doc, workpiece }: { doc: CadDoc; workpiece: CellJoints["workpiece"] }) {
  const pairs = useMemo(() => {
    const [ox, oy] = doc.factory.oven_placement.translate;
    const [stx, sty] = doc.factory.sort_placement.translate;
    const out: { tag: string; a: THREE.Vector3; b: THREE.Vector3; bin?: string }[] = [];
    const centre = (p: CadPart): [number, number, number] => {
      const [dx, dy, dz] = boxSize(p);
      return [p.p[0] + dx / 2, p.p[1] + dy / 2, p.p[2] + dz / 2];
    };
    const add = (parts: CadPart[], tf: (x: number, y: number) => [number, number]) => {
      // a barrier is a TAGGED rx/tx pair - the posts they stand on are named
      // *_post_rx / *_post_tx too, and were drawn as a beam under the tray
      for (const rx of parts.filter((p) => p.n.endsWith("_rx") && p.k === "box" && p.tag)) {
        const tx = parts.find((p) => p.n === rx.n.replace(/_rx$/, "_tx"));
        if (!tx) continue;
        const [ax, ay, az] = centre(rx), [bx, by, bz] = centre(tx);
        const [fax, fay] = tf(ax, ay), [fbx, fby] = tf(bx, by);
        const bin = doc.sorting.colours.find((c) => rx.n.includes(`bay_${c}`));
        out.push({ tag: rx.tag, a: new THREE.Vector3(fax, fay, az), b: new THREE.Vector3(fbx, fby, bz), bin });
      }
    };
    add(doc.oven.parts, (x, y) => [-y + ox, x + oy]);
    add(doc.sorting.parts, (x, y) => [-y + stx, x + sty]);
    return out;
  }, [doc]);
  const beams = useRef<(THREE.Mesh | null)[]>([]);
  const leds = useRef<(THREE.MeshStandardMaterial | null)[]>([]);
  useFrame(({ clock }) => {
    const on = Math.floor(clock.getElapsedTime() * 8) % 2 === 0;
    const cx = workpiece.pos[0], cy = workpiece.pos[1];
    for (let i = 0; i < pairs.length; i++) {
      const pr = pairs[i];
      // where along the beam (0 = receiver, 1 = LED) the cookie blocks it: the light from
      // the LED stops at the cookie's near face, it never passes through
      let stop = 0;
      if (workpiece.visible && pr.a.z > 55 && pr.a.z < 85) {
        const abx = pr.b.x - pr.a.x, aby = pr.b.y - pr.a.y, L = Math.hypot(abx, aby);
        const acx = cx - pr.a.x, acy = cy - pr.a.y;
        const u = (acx * abx + acy * aby) / (L * L);
        const d = Math.hypot(acx - abx * u, acy - aby * u);
        if (u >= 0 && u <= 1 && d < 22.5) stop = u + Math.sqrt(22.5 * 22.5 - d * d) / L;
      }
      const hit = stop > 0;
      const m = beams.current[i], l = leds.current[i];
      if (m) {
        const keep = Math.max(0.001, 1 - Math.min(1, stop));
        m.scale.set(1, keep, 1);
        // the beam's centre: from the LED (b) toward the receiver (a) by keep / 2; factory -> three
        const k = keep / 2;
        const x = pr.b.x + (pr.a.x - pr.b.x) * k, y = pr.b.y + (pr.a.y - pr.b.y) * k, z = pr.b.z + (pr.a.z - pr.b.z) * k;
        m.position.set(x * MM, z * MM, y * MM);
      }
      if (l) {
        l.color.copy(hit ? LED_HIT : LED_OK);
        l.emissive.copy(hit ? LED_HIT : LED_OK);
        l.emissiveIntensity = hit ? (on ? 3 : 0.2) : 0.9;
      }
    }
  });
  return (
    <group>
      {pairs.map((pr, i) => {
        const mid = pr.a.clone().add(pr.b).multiplyScalar(0.5);
        const len = pr.a.distanceTo(pr.b);
        const ang = Math.atan2(pr.b.y - pr.a.y, pr.b.x - pr.a.x);
        return (
          <group key={i}>
            <mesh ref={(m) => { beams.current[i] = m; }} position={v(mid.x, mid.y, mid.z)}
                  rotation={[0, -ang, Math.PI / 2]}>
              <cylinderGeometry args={[0.9 * MM, 0.9 * MM, len * MM, 8]} />
              <meshBasicMaterial color="#ff5a3c" transparent opacity={0.85} />
            </mesh>
            <mesh position={v(pr.a.x, pr.a.y, pr.a.z + 10)}>
              <sphereGeometry args={[2.6 * MM, 12, 12]} />
              <meshStandardMaterial ref={(m) => { leds.current[i] = m; }} color="#39d353" emissive="#39d353" emissiveIntensity={0.9} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
}
