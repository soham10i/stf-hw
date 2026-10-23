// Clicking a part in the 3D twin opens its electrical sheet (twin/ElectricCard.tsx).
//
// The electrical export (public/electrical.json, the upgraded variant: the factory the twin
// draws) records, for every electrical part, the CAD part it was placed from ("hbw/M2_travel_motor",
// "plc/psu_wdr120", "io3/io_hbw_DI1"). The renderers wrap each CAD part in <Pickable cad=...>: a
// part that is in the index becomes clickable, every other part is drawn as before.
import { useSyncExternalStore, type ReactNode } from "react";

import type { ElectricalDoc } from "../circuit/factoryCircuit";
import { loadJson } from "../shared/data";

let index = new Map<string, string>(); // CAD key -> electrical instance
let doc: ElectricalDoc | null = null;
let picked: string | null = null;
let hover: string | null = null;
let version = 0;
const listeners = new Set<() => void>();
const emit = () => { version++; listeners.forEach((l) => l()); };
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

let loading: Promise<void> | null = null;
/** Loads the export once and indexes its placements. */
export function loadElectrical(): Promise<void> {
  loading ??= loadJson<ElectricalDoc>("electrical.json").then((d) => {
    doc = d;
    const up = d.variants.upgraded;
    const ix = new Map<string, string>();
    for (const [inst, where] of Object.entries(up.placement)) if (where && !ix.has(where.cad)) ix.set(where.cad, inst);
    index = ix;
    emit();
  }).catch(() => { /* the twin works without it: nothing is clickable */ });
  return loading;
}

export const electricalDoc = () => doc;
export function pickPart(inst: string | null): void {
  picked = inst;
  emit();
}
export function usePicked(): string | null {
  return useSyncExternalStore(subscribe, () => picked);
}
export function useHovered(): string | null {
  return useSyncExternalStore(subscribe, () => hover);
}

/** Makes a CAD part clickable when it is an electrical part. */
export function Pickable({ cad, children }: { cad: string; children: ReactNode }) {
  useSyncExternalStore(subscribe, () => version);
  const inst = index.get(cad);
  if (!inst) return <>{children}</>;
  return (
    <group
      onClick={(e) => { e.stopPropagation(); pickPart(inst); }}
      onPointerOver={(e) => { e.stopPropagation(); hover = inst; document.body.style.cursor = "pointer"; emit(); }}
      onPointerOut={() => { if (hover === inst) { hover = null; document.body.style.cursor = ""; emit(); } }}
    >
      {children}
    </group>
  );
}
