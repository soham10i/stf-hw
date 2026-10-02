// Order controls. The slot grid is the TWIN's rack - 12 slots (A1-C4), the same
// rack the 3D view draws - and "Run full cycle" tells the twin which raw cookie to
// bake next; that needs no server. With the live API (scene !== null) retrieve,
// store and home also go to the physics kernel, which still models the original
// 3x3 rack: for A4 / B4 / C4 it has no slot yet and says so.

import { useEffect, useState } from "react";
import { twinOrders } from "../scene/HbwCad";
import { sendCommand } from "../socket";
import type { SceneDescriptor } from "../types";

export function OrdersPanel({ scene, slots: twinSlots }: { scene: SceneDescriptor | null; slots?: string[] }) {
  const backend = new Set(Object.keys(scene?.rack.slots ?? {}));
  const slots = twinSlots?.length ? twinSlots : [...backend];
  const [slot, setSlot] = useState(slots.includes("B2") ? "B2" : slots[0]);
  const [msg, setMsg] = useState<string | null>(null);
  // the twin's rack and cycle live in the 3D loop; sample them twice a second
  const [, tick] = useState(0);
  useEffect(() => { const id = window.setInterval(() => tick((x) => x + 1), 500); return () => window.clearInterval(id); }, []);
  const rack = twinOrders.rack, raw = twinOrders.rawColour, cyc = twinOrders.cycle;
  const state = (q: string) => (!(q in rack) ? "none" : rack[q] === null ? "empty" : rack[q] === raw ? "raw" : "baked");
  const count = (k: string) => slots.filter((q) => state(q) === k).length;
  const left = Math.max(0, cyc.total - cyc.t);
  const bakedCol = Object.values(rack).find((c) => c && c !== raw) ?? "#F4A6BF";

  const fire = async (op: string, withSlot: boolean) => {
    if (op === "cycle") {
      const raw = twinOrders.raw;
      if (!raw.includes(slot)) {
        setMsg(`${slot} holds no raw dough right now (raw: ${raw.join(" ") || "none"})`);
        return;
      }
      twinOrders.next = slot;
      setMsg(`the twin's next cycle bakes the raw cookie from ${slot}`);
      if (!scene) return;
    }
    if (withSlot && !backend.has(slot)) {
      if (op !== "cycle") setMsg(`${slot}: twin rack only — the backend still models the 3×3 rack`);
      return;
    }
    try {
      await sendCommand(op, withSlot ? slot : null);
      if (op !== "cycle") setMsg(`queued ${op}${withSlot ? " " + slot : ""}`);
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  return (
    <div className="panel orders">
      <h2>Orders</h2>

      <div className="slot-grid" style={{ gridTemplateColumns: `repeat(${Math.max(3, new Set(slots.map((s) => s.slice(1))).size)}, 1fr)` }}>
        {slots.map((s) => (
          <button
            key={s}
            className={s === slot ? "slot active" : "slot"}
            onClick={() => setSlot(s)}
          >
            <i className={`slot-dot ${state(s)}`} style={state(s) === "raw" || state(s) === "baked" ? { background: rack[s]! } : undefined} />
            {s}
          </button>
        ))}
      </div>

      <div className="rack-legend">
        <span><i className="slot-dot raw" style={{ background: raw }} />{count("raw")} raw</span>
        <span><i className="slot-dot baked" style={{ background: bakedCol }} />{count("baked")} baked</span>
        <span><i className="slot-dot none" />{count("none") + count("empty")} free</span>
      </div>
      {cyc.total > 0 && (
        <div className="rack-next">
          <div><b>{cyc.from}</b> is being baked · a baked cookie goes into <b>{cyc.to}</b> in {Math.floor(left / 60)}:{String(Math.floor(left % 60)).padStart(2, "0")}</div>
          <i><em style={{ width: `${Math.min(100, (cyc.t / cyc.total) * 100)}%` }} /></i>
          <p>The cookie baked now goes to its colour bay at the sorting line; the rack gets back the one the VGR fetches from a bay.</p>
        </div>
      )}

      <div className="op-actions">
        <button className="op cycle" onClick={() => fire("cycle", true)}>
          Run full cycle from {slot}
        </button>
        {scene && (
          <>
            <div className="btn-row">
              <button className="op retrieve" onClick={() => fire("retrieve", true)}>Retrieve {slot}</button>
              <button className="op store" onClick={() => fire("store", true)}>Store {slot}</button>
            </div>
            <button className="op home" onClick={() => fire("home", false)}>Home crane</button>
          </>
        )}
      </div>

      {msg && <p className="msg">{msg}</p>}
    </div>
  );
}
