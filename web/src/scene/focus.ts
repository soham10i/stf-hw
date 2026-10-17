// What the 3D camera frames: the whole table, or one module. The view's control bar sets it and
// the stage's camera rig flies to it; both read it from here, outside the Canvas' reconciler.
import { useSyncExternalStore } from "react";

export type FocusId = "overview" | "hbw" | "vgr" | "oven" | "sort" | "plc";

/** The presets, in the order the machine works: each module is framed by its rect on the table. */
export const FOCUS: { id: FocusId; label: string; rect?: string }[] = [
  { id: "overview", label: "Whole machine" },
  { id: "hbw", label: "Warehouse", rect: "hbw_rect" },
  { id: "vgr", label: "Robot arm", rect: "vgr_rect" },
  { id: "oven", label: "Oven", rect: "oven_rect" },
  { id: "sort", label: "Sorting line", rect: "sort_rect" },
  { id: "plc", label: "Control cabinet", rect: "plc_rect" },
];

let current: FocusId = "overview";
/** bumped on every request, so asking for the same module again flies back to it */
let seq = 0;
const listeners = new Set<() => void>();

export function setFocus(id: FocusId) {
  current = id;
  seq++;
  listeners.forEach((l) => l());
}
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

/** The current focus and its request number. */
export function useFocus(): [FocusId, number] {
  const n = useSyncExternalStore(subscribe, () => seq);
  return [current, n];
}

/** How much of the view the floating chrome covers, in CSS px from the left (rail, an unpinned
    panel) and the top (the top bar and the control bar): the camera centres on the rest. */
let inset = { left: 0, top: 0 };
const insetListeners = new Set<() => void>();
export function setViewInset(left: number, top: number) {
  if (left === inset.left && top === inset.top) return;
  inset = { left, top };
  insetListeners.forEach((l) => l());
}
export const getViewInset = () => inset;
