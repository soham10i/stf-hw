// Whether the 3D stage has its precise meshes in: the twin's loading screen waits for it, so the
// machine appears once, finished, instead of in primitives first.
import { useSyncExternalStore } from "react";

let ready = false;
const listeners = new Set<() => void>();

export function markStageReady() {
  if (ready) return;
  ready = true;
  listeners.forEach((l) => l());
}
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };
export const useStageReady = () => useSyncExternalStore(subscribe, () => ready);
