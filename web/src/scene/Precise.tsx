// Upgrade 1's precise geometry: the part meshes stf-cad/hbw/web_precise.py
// tessellates from the SAME FreeCAD functions that build STF_Factory_MCP.FCStd
// (guide pockets, T-slot profiles, threads, kiln seams, saw teeth ...). Each
// mesh is in millimetres in the part's own frame, so it drops in exactly where
// the part's proven box was - and every detail stays inside that box.

import { useGLTF } from "@react-three/drei";
import { createContext, useContext, useEffect, useMemo } from "react";
import * as THREE from "three";
import { VIEW as MM } from "../coords";

/** "<module>:<part>" -> its meshes (several for a multi-colour part). */
export type PreciseLib = Map<string, THREE.Mesh[]>;

export const PreciseLibCtx = createContext<PreciseLib | null>(null);
const ModuleCtx = createContext<string>("");

export function PreciseScope({ module, children }: { module: string; children: React.ReactNode }) {
  return <ModuleCtx.Provider value={module}>{children}</ModuleCtx.Provider>;
}

/** The precise meshes for a part in the current module, or undefined. */
export function usePrecise(part: string): THREE.Mesh[] | undefined {
  const lib = useContext(PreciseLibCtx);
  const module = useContext(ModuleCtx);
  return lib?.get(`${module}:${part}`);
}

export function PreciseLoader({ url, onLib }: { url: string; onLib: (l: PreciseLib) => void }) {
  const { scene } = useGLTF(url);
  useEffect(() => {
    const lib: PreciseLib = new Map();
    scene.traverse((o) => {
      const u = o.userData as { module?: string; part?: string };
      if ((o as THREE.Mesh).isMesh) {
        // the GLB's metal class (metalness 0.85) mirrors this stage's dark
        // surroundings and turns aluminium black; keep it bright, satin metal
        const m = (o as THREE.Mesh).material as THREE.MeshStandardMaterial;
        if (m.metalness > 0.5 && !m.userData.tuned) {
          m.metalness = 0.55;
          m.roughness = 0.38;
          m.userData.tuned = true;
        }
      }
      if ((o as THREE.Mesh).isMesh && u.module && u.part) {
        const k = `${u.module}:${u.part}`;
        if (!lib.has(k)) lib.set(k, []);
        lib.get(k)!.push(o as THREE.Mesh);
      }
    });
    onLib(lib);
  }, [scene, onLib]);
  return null;
}

/** factory millimetres (x, y, z) -> scene units (x, z, y): the stage's own
    mapping, so a precise mesh lands exactly on its box. */
export const MM_TO_SCENE = new THREE.Matrix4().set(
  MM, 0, 0, 0,
  0, 0, MM, 0,
  0, MM, 0, 0,
  0, 0, 0, 1,
);

export function PreciseMesh({ meshes, matrix = MM_TO_SCENE }: { meshes: THREE.Mesh[]; matrix?: THREE.Matrix4 }) {
  const objs = useMemo(() => meshes.map((m) => {
    const c = m.clone();
    c.castShadow = true;
    c.receiveShadow = true;
    return c;
  }), [meshes]);
  return (
    <group matrix={matrix} matrixAutoUpdate={false}>
      {objs.map((o, i) => <primitive key={i} object={o} />)}
    </group>
  );
}

/** Scope-local helper: the precise meshes of `part` in `module` from the lib. */
export function usePreciseIn(module: string, part: string) {
  const lib = useContext(PreciseLibCtx);
  return lib?.get(`${module}:${part}`);
}
