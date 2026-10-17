// The cell's material state across reloads: the rack (which slot holds raw dough, which a baked
// cookie of which flavour) and the orders, kept in this browser (localStorage) until the visitor
// resets the rack in the Orders panel. A cookie that was in the oven line when the page closed
// is raw dough again in its slot and is baked again - the order resumes where it was.
// Storage can be missing or throw (private mode, blocked site data): the cell then starts fresh.
import type { OrderLine } from "./hot";

const KEY = "stf.cell.v1";

export type Saved = { rack: Record<string, string | null>; queue: OrderLine[]; seq: number; delivered: number };

const isLine = (o: unknown): o is OrderLine => {
  const l = o as OrderLine;
  return !!l && typeof l.id === "number" && typeof l.flavour === "string"
    && [l.qty, l.started, l.done].every((n) => Number.isInteger(n) && n >= 0) && l.done <= l.qty;
};

/** The saved state, if it fits this machine (the same slots) and is well formed. */
export function loadCell(slots: string[]): Saved | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Saved;
    const keys = Object.keys(s?.rack ?? {});
    if (keys.length !== slots.length || !slots.every((q) => keys.includes(q))) return null;
    if (!Object.values(s.rack).every((c) => c === null || (typeof c === "string" && /^#[0-9a-f]{6}$/i.test(c)))) return null;
    if (!Array.isArray(s.queue) || !s.queue.every(isLine)) return null;
    return { rack: s.rack, queue: s.queue.slice(-200), seq: Number(s.seq) || 0, delivered: Number(s.delivered) || 0 };
  } catch {
    return null;
  }
}

let last = "";
/** Save when something changed; cheap enough to call every second. */
export function saveCell(s: Saved) {
  const raw = JSON.stringify({ ...s, queue: s.queue.slice(-200) });
  if (raw === last) return;
  last = raw;
  try { localStorage.setItem(KEY, raw); } catch { /* not persisted */ }
}

export function clearCell() {
  last = "";
  try { localStorage.removeItem(KEY); } catch { /* nothing to clear */ }
}
