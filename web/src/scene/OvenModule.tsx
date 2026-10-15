// The oven station and the one travelling cookie of the oven/sorting flow (OvenFlow.ts).


import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";










import { type CadPart, type CadDoc, boxSize, cylSpec } from "../shared/model";
import { twinOrders, Drive, sortHot, ovenHot } from "./hot";
import { MM, v, centreOf, Solid, Cookie, useBeltTexture } from "./parts";





/** The oven station, rebuilt to Abb. 9: Ofenschieber (+X), Ofentuer (+Z),
    the station's own Sauger (+Y) with its one-stroke lowering cylinder (-Z),
    the Drehtisch (Rz), the Saege and the Auswerfer (+Y). Every joint is read
    from ovenHot, which the one shared timeline writes. The cookie itself is
    drawn once, at factory level (FlowCookie), not per holder. */
export function OvenModule({ doc }: { doc: CadDoc }) {
  const g = {
    slider: useRef<THREE.Group>(null), door: useRef<THREE.Group>(null),
    turn: useRef<THREE.Group>(null), sauger: useRef<THREE.Group>(null),
    lower: useRef<THREE.Group>(null), push: useRef<THREE.Group>(null),
  };
  const lamp = useRef<THREE.MeshStandardMaterial>(null);
  const lampLight = useRef<THREE.PointLight>(null);
  const cup = useRef<THREE.MeshStandardMaterial>(null);
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

  useFrame(() => {
    const s = ovenHot.s;
    if (!s) return;
    // module frame = factory axes: +X -> three x, +Y -> three z, +Z -> three y
    if (g.slider.current) g.slider.current.position.x = (s.slider - A.slider) * MM;
    if (g.door.current) g.door.current.position.y = (s.door - A.door) * MM;
    if (g.turn.current) g.turn.current.rotation.y = -THREE.MathUtils.degToRad(s.turn - A.turn);
    if (g.sauger.current) g.sauger.current.position.z = (s.sauger - A.sauger) * MM;
    if (g.lower.current) g.lower.current.position.y = -(s.lower - A.lower) * MM;
    if (g.push.current) g.push.current.position.z = (s.push - A.push) * MM;
    if (lamp.current) {
      lamp.current.emissiveIntensity = 0.05 + 4 * s.lamp;
      lamp.current.color.set(s.lamp > 0.5 ? "#ffb13b" : "#6f6a5e");
    }
    if (lampLight.current) lampLight.current.intensity = 3 * s.lamp;
    if (cup.current) cup.current.emissiveIntensity = 0.6 * s.vac;
    beltDrive.current.belt = ovenHot.belts.oven;
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

/** The one travelling cookie, in FACTORY coordinates: wherever the flow says it
    is, in whatever colour the bake has given it. */
export function FlowCookie() {
  const grp = useRef<THREE.Group>(null);
  const hot = useMemo(() => ({ colour: "#D8B98C" }), []);
  useFrame(() => {
    if (!grp.current) return;
    grp.current.visible = ovenHot.visible;
    const [x, y, z] = ovenHot.pos;
    grp.current.position.set(x * MM, z * MM, y * MM);
    hot.colour = ovenHot.colour;
  });
  return (
    <group ref={grp}>
      <Cookie x={0} y={0} z={0} hot={hot} />
    </group>
  );
}

/** Light barriers on the oven and the sorting line: a beam from each LED to
    its phototransistor; when the travelling cookie (or a cookie resting in a
    Lagerstelle) cuts it, the beam flickers and the receiver blinks red. */
export function FlowBarriers({ doc }: { doc: CadDoc }) {
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
  const stock = useMemo(() => {
    const [stx, sty] = doc.factory.sort_placement.translate;
    return Object.fromEntries(
      Object.entries(doc.sorting.handovers).map(([c, h]) => [c, [-h[1] + stx, h[0] + sty] as [number, number]]),
    );
  }, [doc]);
  const beams = useRef<(THREE.Mesh | null)[]>([]);
  const leds = useRef<(THREE.MeshStandardMaterial | null)[]>([]);
  useFrame(({ clock }) => {
    const on = Math.floor(clock.getElapsedTime() * 8) % 2 === 0;
    const cookies: [number, number][] = [];
    if (ovenHot.visible) cookies.push([ovenHot.pos[0], ovenHot.pos[1]]);
    for (const [c, xy] of Object.entries(stock)) {
      if ((twinOrders.bays[c] ?? []).length - (sortHot.taken === c ? 1 : 0) > 0) cookies.push(xy);
    }
    pairs.forEach((pr, i) => {
      // where along the beam (0 = receiver, 1 = LED) a cookie blocks it: the
      // light from the LED stops at the cookie's near face, it never passes through
      let stop = 0;
      const ab = new THREE.Vector2(pr.b.x - pr.a.x, pr.b.y - pr.a.y);
      const L = ab.length();
      for (const [cx, cy] of cookies) {
        const ac = new THREE.Vector2(cx - pr.a.x, cy - pr.a.y);
        const u = ac.dot(ab) / (L * L);
        const d = ac.clone().sub(ab.clone().multiplyScalar(u)).length();
        if (u < 0 || u > 1 || d >= 22.5 || !(pr.a.z > 55 && pr.a.z < 85)) continue;
        stop = Math.max(stop, u + Math.sqrt(22.5 * 22.5 - d * d) / L);
      }
      const hit = stop > 0;
      const m = beams.current[i], l = leds.current[i];
      if (m) {
        const keep = Math.max(0.001, 1 - Math.min(1, stop));
        m.scale.set(1, keep, 1);
        const p = pr.b.clone().lerp(pr.a, keep / 2);
        m.position.copy(v(p.x, p.y, p.z));
      }
      if (l) {
        l.color.set(hit ? "#ff3b30" : "#39d353");
        l.emissive.set(hit ? "#ff3b30" : "#39d353");
        l.emissiveIntensity = hit ? (on ? 3 : 0.2) : 0.9;
      }
    });
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
