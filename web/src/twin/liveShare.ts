// The twin's live state for the dashboard's chat: while the 3D twin is open (and the API is
// there), a small snapshot of what the cell is doing goes to POST /twin/state every few
// seconds, so the copilot can answer "is the oven hot right now?" from the running twin.
// Read imperatively from the hot state, never React; nothing is sent without the API.
import { useEffect } from "react";
import { hbwHot, ovenHot, twinOrders, vgrHot } from "../scene/hot";
import { HAS_API } from "../shared/mode";

const EVERY_MS = 3000;
const NAMES: Record<string, string> = { "#5C3A1E": "chocolate", "#F4A6BF": "strawberry", "#FBF8F1": "vanilla" };
const flavourOf = (c: string | null | undefined) => (c ? NAMES[c.toUpperCase()] ?? NAMES[c] ?? "baked" : "empty");

export function snapshot() {
  const q = twinOrders.queue, cyc = twinOrders.cycle;
  const rack: Record<string, string> = {};
  for (const [slot, c] of Object.entries(twinOrders.rack)) {
    rack[slot] = c === null ? "empty mould" : c.toLowerCase() === twinOrders.rawColour.toLowerCase() ? "raw dough" : flavourOf(c);
  }
  return {
    running: !twinOrders.idle && q.some((o) => o.done < o.qty),
    step: twinOrders.step || "waiting for an order",
    current_cookie: cyc.total > 0 ? `${cyc.flavour || "?"}, from ${cyc.from} to ${cyc.to}, ${Math.round((100 * cyc.t) / cyc.total)} % of its cycle` : "none",
    orders: q.map((o) => `${o.qty} x ${o.flavour}: ${o.done} done`),
    raw_cookies_free: twinOrders.free(),
    oven_temperature_C: Math.round(ovenHot.tempC),
    oven_heating: ovenHot.heat > 0.5,
    oven_at_temperature: ovenHot.tempC >= 170,
    robot_vacuum_pct: Math.round(vgrHot.seal * 100),
    robot_carrying: vgrHot.carry ?? "nothing",
    light_barriers_broken: Object.entries(hbwHot.blocked).filter(([, b]) => b).map(([k]) => k),
    bays: Object.fromEntries(Object.entries(twinOrders.bays).map(([b, cs]) => [b, cs.length])),
    rack,
  };
}

/** Post the snapshot every few seconds while mounted (the machine view is open). */
export function useLiveShare(on: boolean) {
  useEffect(() => {
    if (!on || !HAS_API) return;
    const send = () => {
      if (document.hidden) return;
      fetch("/twin/state", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(snapshot()) })
        .catch(() => { /* the API is optional */ });
    };
    send();
    const id = window.setInterval(send, EVERY_MS);
    return () => window.clearInterval(id);
  }, [on]);
}
