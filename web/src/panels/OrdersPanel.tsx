// Orders: the customer's view of the cell. Pick a flavour and a quantity (1-12), place the
// order, and the 3D twin bakes exactly that: one cycle per cookie, each sorted into its
// flavour's Lagerstelle; the VGR returns finished cookies to the warehouse. With nothing
// ordered the cell idles. The order queue and the material state live in twinOrders
// (scene/HbwCad), which the 3D loop works through.
//
// With the live API (scene !== null) the physics kernel's manual commands are under
// "Manual crane commands"; it still models the original 3x3 rack.

import { useEffect, useState } from "react";
import { twinOrders } from "../scene/HbwCad";
import { sendCommand } from "../socket";
import type { SceneDescriptor } from "../types";
import { useCadDoc } from "../shared/model";

const BINS: Record<string, string> = { blau: "blue", rot: "red", weiss: "white" };

export function OrdersPanel({ scene, slots }: { scene: SceneDescriptor | null; slots?: string[] }) {
  const { doc } = useCadDoc();
  const flavours = doc ? doc.pipeline.flavours : {};
  const names = Object.keys(flavours);
  const [flavour, setFlavour] = useState("chocolate");
  const [qty, setQty] = useState(3);
  const [msg, setMsg] = useState<string | null>(null);
  // the queue and the cell move in the 3D loop; sample them twice a second
  const [, tick] = useState(0);
  useEffect(() => { const id = window.setInterval(() => tick((x) => x + 1), 500); return () => window.clearInterval(id); }, []);

  const rack = twinOrders.rack, raw = twinOrders.rawColour, cyc = twinOrders.cycle;
  const all = slots ?? Object.keys(rack);
  const state = (q: string) => (!(q in rack) ? "none" : rack[q] === null ? "empty" : rack[q] === raw ? "raw" : "baked");
  const count = (k: string) => all.filter((q) => state(q) === k).length;
  const colour = (f: string) => flavours[f]?.colour ?? raw;
  const binFlavour = (bin: string) => names.find((f) => flavours[f].bin === bin) ?? "";
  const queue = twinOrders.queue;
  const open = queue.filter((o) => o.done < o.qty);
  const left = Math.max(0, cyc.total - cyc.t);
  const busy = !twinOrders.idle;

  const place = () => {
    twinOrders.place(flavour, qty);
    setMsg(`Order placed: ${qty} × ${flavour}. ${open.length ? "It joins the queue." : "The cell starts now."}`);
  };
  const manual = async (op: string, slot: string | null) => {
    try { await sendCommand(op, slot); setMsg(`queued ${op}${slot ? " " + slot : ""} on the physics kernel`); }
    catch (e) { setMsg((e as Error).message); }
  };

  return (
    <div className="panel orders">
      <h2>Place an order</h2>
      <div className="ord-form">
        <div className="ord-flavours" role="radiogroup" aria-label="Flavour">
          {names.map((f) => (
            <button key={f} role="radio" aria-checked={f === flavour} className={`slot ${f === flavour ? "active" : ""}`}
              onClick={() => setFlavour(f)}>
              <i className="slot-dot raw" style={{ background: colour(f) }} />{f}
            </button>
          ))}
        </div>
        <div className="ord-qty">
          <span>Quantity</span>
          <button className="slot" onClick={() => setQty(Math.max(1, qty - 1))} aria-label="Fewer">−</button>
          <input type="number" min={1} max={12} value={qty} aria-label="Quantity"
            onChange={(e) => setQty(Math.max(1, Math.min(12, Number(e.target.value) || 1)))} />
          <button className="slot" onClick={() => setQty(Math.min(12, qty + 1))} aria-label="More">+</button>
          <em>1–12</em>
        </div>
        <button className="op cycle" onClick={place}>Place order: {qty} × {flavour}</button>
      </div>
      {msg && <p className="msg">{msg}</p>}

      <h3>Orders</h3>
      <div className="ord-queue">
        {queue.length === 0 && <p className="muted small">No orders yet.</p>}
        {[...queue].reverse().slice(0, 6).map((o) => {
          const st = o.done >= o.qty ? "done" : o.started > o.done || (o.started > 0 && busy) ? "baking" : "queued";
          return (
            <div key={o.id} className={`ord-line ${st}`}>
              <i className="slot-dot raw" style={{ background: colour(o.flavour) }} />
              <b>{o.qty} × {o.flavour}{o.demo ? " (demo)" : ""}</b>
              <span>{st === "done" ? "done" : st === "baking" ? `baking ${o.done + 1} of ${o.qty}` : "queued"}</span>
              <em><i style={{ width: `${(100 * o.done) / o.qty}%`, background: colour(o.flavour) }} /></em>
            </div>
          );
        })}
      </div>

      <div className="rack-next">
        {busy ? (
          <>
            <div>Baking <b>{cyc.flavour}</b> (dough from <b>{cyc.from}</b>) · cycle ends in {Math.floor(left / 60)}:{String(Math.floor(left % 60)).padStart(2, "0")}, then slot <b>{cyc.to}</b> is filled</div>
            <i><em style={{ width: `${Math.min(100, (cyc.t / Math.max(1, cyc.total)) * 100)}%` }} /></i>
            <p>{cyc.collect
              ? `The VGR also brings the oldest finished cookie (${binFlavour(cyc.collect)}, ${BINS[cyc.collect]} bay) back to the warehouse.`
              : "No finished cookie is waiting: an empty mould goes back to the warehouse."}</p>
          </>
        ) : <div><b>Idle</b> · every order is done. Place an order to start the cell.</div>}
      </div>

      <h3>Sorting bays</h3>
      <div className="ord-bays">
        {Object.entries(twinOrders.bays).map(([bin, list]) => (
          <div key={bin}><span>{BINS[bin] ?? bin}</span>
            <b>{list.length ? list.map((f, i) => <i key={i} className="slot-dot raw" style={{ background: colour(f) }} title={f} />) : <em>empty</em>}</b>
          </div>
        ))}
      </div>

      <h3>Warehouse rack</h3>
      <div className="slot-grid" style={{ gridTemplateColumns: "repeat(4, 1fr)" }}>
        {all.map((s) => (
          <span key={s} className="slot static">
            <i className={`slot-dot ${state(s)}`} style={state(s) === "raw" || state(s) === "baked" ? { background: rack[s]! } : undefined} />
            {s}
          </span>
        ))}
      </div>
      <div className="rack-legend">
        <span><i className="slot-dot raw" style={{ background: raw }} />{count("raw")} raw</span>
        <span><i className="slot-dot baked" />{count("baked")} finished</span>
        <span><i className="slot-dot empty" />{count("empty")} empty mould</span>
        <span><i className="slot-dot none" />{count("none")} free</span>
      </div>

      {scene && (
        <details className="ord-manual">
          <summary>Manual crane commands (physics kernel, 3×3 rack)</summary>
          <div className="op-actions">
            <div className="btn-row">
              <button className="op retrieve" onClick={() => manual("retrieve", "B2")}>Retrieve B2</button>
              <button className="op store" onClick={() => manual("store", "B2")}>Store B2</button>
            </div>
            <button className="op home" onClick={() => manual("home", null)}>Home crane</button>
          </div>
        </details>
      )}
    </div>
  );
}
