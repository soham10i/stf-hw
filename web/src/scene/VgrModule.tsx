// The vacuum gripper robot (VGR): swivel, reach and plunge, the spring stem and the suction cup.


import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";






import { DragChain } from "./DragChain";



import { type CadPart, type CadDoc, cylSpec } from "../shared/model";
import { Drive, vgrHot } from "./hot";
import { MM, v, Solid, Cookie } from "./parts";
import { RunningGear, VGR } from "./RunningGear";






/** Compression spring round the stem: a real helix whose pitch closes up as the
    carriage over-travels past the cookie's top face. */
function Coil({ h, r }: { h: number; r: number }) {
  const geo = useMemo(() => {
    const turns = 7, n = 160;
    const pts = Array.from({ length: n + 1 }, (_, i) => {
      const t = i / n, a = t * turns * Math.PI * 2;
      return new THREE.Vector3(Math.cos(a) * r, t * h, Math.sin(a) * r);
    });
    return new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), n, 0.9 * MM, 6, false);
  }, [h, r]);
  return (
    <mesh geometry={geo} castShadow>
      <meshStandardMaterial color="#c9ced3" metalness={0.8} roughness={0.3} />
    </mesh>
  );
}

/** The VGR: cylindrical R-P-P, so the first joint is a ROTATION.
    world -> swivel(Rz about the tower axis) -> plunge(+Z) -> reach(-Y). Both
    linear axes are spindles (4 mm lead) that turn with the axis they drive. The
    cup rides a spring stem: at contact the carriage over-travels, the spring
    closes, the cup stays on the cookie's top face and flattens as it seals. */
export function VgrModule({ doc, drive }: { doc: CadDoc; drive: React.MutableRefObject<Drive> }) {
  const gSwivel = useRef<THREE.Group>(null);
  const gPlunge = useRef<THREE.Group>(null);
  const gReach = useRef<THREE.Group>(null);
  const gCup = useRef<THREE.Group>(null);
  const gCupBody = useRef<THREE.Group>(null);
  const gCoil = useRef<THREE.Group>(null);
  const onCup = useRef<THREE.Group>(null);
  const [cx, cy] = doc.vgr.centre;
  const A = doc.vgr.authoring;
  const over = doc.vgr.plan.overtravel;
  const byFrame = useMemo(() => {
    const m: Record<string, CadPart[]> = { world: [], swivel: [], plunge: [], reach: [] };
    for (const p of doc.vgr.parts) {
      if (p.n === "suction_cup" || p.n === "suction_stem") continue; // drawn below
      m[p.f].push(p);
    }
    return m;
  }, [doc]);
  const cup = doc.vgr.parts.find((p) => p.n === "suction_cup")!;
  const stem = doc.vgr.parts.find((p) => p.n === "suction_stem")!;
  const [, cupH, cupD] = cylSpec(cup);
  const [, stemL] = cylSpec(stem);
  const cupZ = cup.p[2];                 // cup underside, authoring pose
  const cupTop = cupZ + cupH;
  const headZ = stem.p[2] + stemL;       // underside of the suction head
  const coilL = headZ - cupTop;
  const tex = useMemo(() => new THREE.Texture(), []);

  useFrame(() => {
    if (gSwivel.current) gSwivel.current.rotation.y = -THREE.MathUtils.degToRad(vgrHot.swivel);
    // parts are emitted at doc.vgr.authoring; the groups carry only the DELTA
    if (gPlunge.current) gPlunge.current.position.y = (vgrHot.plunge - A.plunge) * MM;
    if (gReach.current) gReach.current.position.z = -(vgrHot.reach - A.reach) * MM;
    drive.current.plunge = vgrHot.plunge;
    drive.current.reach = vgrHot.reach;
    drive.current.swivel = vgrHot.swivel;
    const c = vgrHot.compress;
    if (gCup.current) gCup.current.position.y = c * MM;
    if (gCoil.current) {
      gCoil.current.position.y = c * MM;
      gCoil.current.scale.y = (coilL - c) / coilL;
    }
    // the rubber cup flattens while it is sucked onto the cookie
    const seal = vgrHot.seal * Math.min(1, c / over);
    if (gCupBody.current) gCupBody.current.scale.y = 1 - 0.3 * seal;
    if (onCup.current) onCup.current.visible = vgrHot.carry !== null;
  });

  const P = (p: CadPart) => <Solid key={p.n} part={p} drive={drive} pitch={doc.vgr.pitch_mm} tex={tex} />;
  const back = v(-cx, -cy, 0);
  const [px, py] = [cup.p[0], cup.p[1]];
  const R = (cupD / 2) * MM;
  return (
    <group>
      {byFrame.world.map(P)}
      <RunningGear all={doc.vgr.parts} frame="world" axes={VGR} />
      <group position={v(cx, cy, 0)}>
        <group ref={gSwivel}>
          <group position={back}>
            {byFrame.swivel.map(P)}
            <RunningGear all={doc.vgr.parts} frame="swivel" axes={VGR} />
            {doc.chains?.chains["vgr:plunge"] && (
              <DragChain spec={doc.chains.chains["vgr:plunge"]}
                joint={() => vgrHot.plunge + doc.chains!.chains["vgr:plunge"].M[2]} />
            )}
            <group ref={gPlunge}>
              {byFrame.plunge.map(P)}
              <RunningGear all={doc.vgr.parts} frame="plunge" axes={VGR} />
              {doc.chains?.chains["vgr:reach"] && (
                <DragChain spec={doc.chains.chains["vgr:reach"]} zBase={A.plunge}
                  joint={() => doc.chains!.chains["vgr:reach"].M[1] - vgrHot.reach} />
              )}
              <group ref={gReach}>
                {byFrame.reach.map(P)}
                <RunningGear all={doc.vgr.parts} frame="reach" axes={VGR} />
                {/* spring: from the cup's top up to the underside of the head */}
                <group position={v(px, py, cupTop)}>
                  <group ref={gCoil}>
                    <Coil h={coilL * MM} r={7 * MM} />
                  </group>
                </group>
                <group ref={gCup}>
                  {/* guide rod: rides with the cup and slides up into the head */}
                  <mesh position={v(px, py, cupTop + (coilL + 4) / 2)} castShadow>
                    <cylinderGeometry args={[2.6 * MM, 2.6 * MM, (coilL + 4) * MM, 12]} />
                    <meshStandardMaterial color="#aeb4b8" metalness={0.8} roughness={0.3} />
                  </mesh>
                  {/* the rubber cup - pivots at its lip so it squashes onto the cookie */}
                  <group ref={gCupBody} position={v(px, py, cupZ)}>
                    <mesh position={[0, (cupH / 2) * MM, 0]} castShadow>
                      <cylinderGeometry args={[R * 0.45, R, cupH * MM, 28, 1, true]} />
                      <meshStandardMaterial color="#1c1d20" roughness={0.85} side={THREE.DoubleSide} />
                    </mesh>
                    <mesh position={[0, cupH * MM, 0]}>
                      <cylinderGeometry args={[R * 0.45, R * 0.45, 2 * MM, 20]} />
                      <meshStandardMaterial color="#1c1d20" roughness={0.85} />
                    </mesh>
                  </group>
                  {/* held cookie: its top face on the cup lip */}
                  <group ref={onCup}>
                    <Cookie x={px} y={py} z={cupZ - 20} dynamic />
                  </group>
                </group>
              </group>
            </group>
          </group>
        </group>
      </group>
    </group>
  );
}
