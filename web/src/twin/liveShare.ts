// The twin's live state for the dashboard's chat: while the 3D twin is open (and the API is
// there), a small snapshot of what the cell is doing goes to POST /twin/state every few
// seconds, so the copilot can answer "is the oven hot right now?" from the running twin.
// Read from the cell store (scene/store/useCellStore.ts), never React; nothing is sent without
// the API. The send is a heartbeat to the server, not a redraw, so it keeps its own timer.
import { useEffect } from "react";
import { cellStore, type CellStore } from "../scene/store/useCellStore";
import { HAS_API } from "../shared/mode";
import { api } from "../shared/api";

const EVERY_MS = 3000;
const NAMES: Record<string, string> = { "#5C3A1E": "chocolate", "#F4A6BF": "strawberry", "#FBF8F1": "vanilla" };
const flavourOf = (c: string | null | undefined) => (c ? NAMES[c.toUpperCase()] ?? NAMES[c] ?? "baked" : "empty");

export function snapshot(store: CellStore = cellStore) {
  const m = store.model, J = store.joints, q = m.queue, cyc = m.cycle;
  const rack: Record<string, string> = {};
  for (const [slot, c] of Object.entries(m.rack)) {
    rack[slot] = c === null ? "empty mould" : c.toLowerCase() === m.rawColour.toLowerCase() ? "raw dough" : flavourOf(c);
  }
  return {
    running: !m.idle && q.some((o) => o.done < o.qty),
    step: m.step || "waiting for an order",
    current_cookie: cyc.total > 0 ? `${cyc.flavour || "?"}, from ${cyc.from} to ${cyc.to}, ${Math.round((100 * cyc.t) / cyc.total)} % of its cycle` : "none",
    orders: q.map((o) => `${o.qty} x ${o.flavour}: ${o.done} done`),
    raw_cookies_free: store.free(),
    oven_temperature_C: Math.round(J.oven.chamberC),
    oven_heating: J.oven.element > 0.5,
    oven_at_temperature: J.oven.chamberC >= 170,
    robot_vacuum_pct: Math.round(J.vgr.seal * 100),
    robot_carrying: J.vgr.carry ?? "nothing",
    light_barriers_broken: Object.entries(J.beams).filter(([, b]) => b).map(([k]) => k),
    rack,
  };
}

/** Post the snapshot every few seconds while mounted (the machine view is open). */
export function useLiveShare(on: boolean) {
  useEffect(() => {
    if (!on || !HAS_API) return;
    const send = () => {
      if (document.hidden) return;
      fetch(api("/twin/state"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(snapshot()) })
        .catch(() => { /* the API is optional */ });
    };
    send();
    const id = window.setInterval(send, EVERY_MS);
    return () => window.clearInterval(id);
  }, [on]);
}
