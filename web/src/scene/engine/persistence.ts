// The cell's material state across reloads: the rack (which slot holds raw dough, which a baked
// cookie of which flavour) and the orders. The coordinator saves through a CellPersistence when
// the material state changes - never from the frame loop - and restores it when it starts.
//
// localPersistence keeps it in this browser (localStorage) until the visitor resets the rack.
// Storage can be missing or throw (private mode, blocked site data): the cell then starts fresh.
// memoryPersistence is the same contract in memory, for tests.
import type { OrderLine, Rack } from "../store/useCellStore";

export type Saved = { rack: Rack; queue: OrderLine[]; seq: number; delivered: number };

export interface CellPersistence {
  load(slots: string[]): Saved | null;
  save(s: Saved): void;
  clear(): void;
}

const KEY = "stf.cell.v1";

const isLine = (o: unknown): o is OrderLine => {
  const l = o as OrderLine;
  return !!l && typeof l.id === "number" && typeof l.flavour === "string"
    && [l.qty, l.started, l.done].every((n) => Number.isInteger(n) && n >= 0) && l.done <= l.qty;
};

/** The saved state, if it fits this machine (the same slots) and is well formed. */
export function parseSaved(raw: string | null, slots: string[]): Saved | null {
  try {
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

const encode = (s: Saved) => JSON.stringify({ ...s, queue: s.queue.slice(-200) });

export function localPersistence(key = KEY): CellPersistence {
  let last = "";
  return {
    load: (slots) => {
      try { return parseSaved(localStorage.getItem(key), slots); } catch { return null; }
    },
    save: (s) => {
      const raw = encode(s);
      if (raw === last) return;
      last = raw;
      try { localStorage.setItem(key, raw); } catch { /* not persisted */ }
    },
    clear: () => {
      last = "";
      try { localStorage.removeItem(key); } catch { /* nothing to clear */ }
    },
  };
}

export function memoryPersistence(initial: string | null = null): CellPersistence & { raw: string | null; saves: number } {
  const p = {
    raw: initial,
    saves: 0,
    load: (slots: string[]) => parseSaved(p.raw, slots),
    save: (s: Saved) => { p.raw = encode(s); p.saves++; },
    clear: () => { p.raw = null; },
  };
  return p;
}
