// Orders: the customer's view of the cell. The cell holds exactly 12 cookies, one per slot,
// raw or baked. Pick a flavour and a quantity, place the order, and the 3D twin bakes exactly
// that: one cycle per cookie, each brought back into the slot it came from. When an order is
// completed its cookies are all in the rack. "Deliver" hands the baked cookies over and
// refills their moulds with fresh dough, so the count stays 12.
//
// With the live API (scene !== null) the physics kernel's manual commands are under
// "Manual crane commands"; it still models the original 3x3 rack.

import { useEffect, useState } from "react";
import { twinOrders, type OrderLine } from "../scene/HbwCad";
import { sendCommand } from "../socket";
import type { SceneDescriptor } from "../types";
import { useCadDoc } from "../shared/model";

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const clock = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
/** The step text without the "VGR:" prefix and the oven's side note. */
const plain = (s: string) => cap(s.split("   ·   ")[0].replace(/^VGR: /, "Robot arm: ").replace(/—/g, "–"));

export function OrdersPanel({ scene, slots }: { scene: SceneDescriptor | null; slots?: string[] }) {
  const { doc } = useCadDoc();
  const flavours = doc ? doc.pipeline.flavours : {};
  const names = Object.keys(flavours);
  const [flavour, setFlavour] = useState("chocolate");
  const [qty, setQty] = useState(3);
  const [msg, setMsg] = useState<{ text: string; tone: "ok" | "bad" } | null>(null);
  // the queue and the cell move in the 3D loop; sample them a few times a second
  const [, tick] = useState(0);
  useEffect(() => { const id = window.setInterval(() => tick((x) => x + 1), 400); return () => window.clearInterval(id); }, []);

  const rack = twinOrders.rack, raw = twinOrders.rawColour, cyc = twinOrders.cycle;
  const all = slots ?? Object.keys(rack);
  const busy = !twinOrders.idle;
  const colour = (f: string) => flavours[f]?.colour ?? raw;
  const flavourOf = (c: string | null | undefined) => names.find((f) => flavours[f].colour.toLowerCase() === c?.toLowerCase());
  const queue = twinOrders.queue;
  const free = twinOrders.free();
  const current = queue.find((o) => o.started > o.done);

  // the twelve cookies, by state
  const inOven = busy ? cyc.from : null;
  const counts = { raw: 0, oven: inOven ? 1 : 0 } as Record<string, number>;
  for (const q of all) {
    if (q === inOven) continue;
    const f = flavourOf(rack[q]);
    const k = f ?? "raw";
    counts[k] = (counts[k] ?? 0) + 1;
  }
  const baked = names.reduce((n, f) => n + (counts[f] ?? 0), 0);
  const total = all.length;

  const place = () => {
    if (qty > free) {
      setMsg({ tone: "bad", text: free
        ? `Only ${free} raw cookie${free === 1 ? "" : "s"} left. Lower the quantity, or deliver the baked cookies to refill the rack.`
        : "No raw dough left. Deliver the baked cookies to refill the rack." });
      return;
    }
    const wasIdle = twinOrders.idle && !queue.some((o) => o.done < o.qty);
    twinOrders.place(flavour, qty);
    setMsg({ tone: "ok", text: `Order placed: ${qty} × ${flavour}. ${wasIdle ? "The cell starts now." : "It is queued after the current order."}` });
  };
  const deliver = () => {
    twinOrders.restock = true;
    setMsg({ tone: "ok", text: `${baked} baked cookie${baked === 1 ? "" : "s"} delivered; their moulds are refilled with fresh dough.` });
  };
  const manual = async (op: string, slot: string | null) => {
    try { await sendCommand(op, slot); setMsg({ tone: "ok", text: `Queued ${op}${slot ? " " + slot : ""} on the physics kernel.` }); }
    catch (e) { setMsg({ tone: "bad", text: (e as Error).message }); }
  };

  return (
    <div className="panel orders ord">
      {/* ---------------------------------------------------------------- stock */}
      <section className="ord-card">
        <div className="ord-head"><h3>Cookies in the cell</h3><span className="ord-total">{total} cookies, always</span></div>
        <div className="ord-stockbar" aria-hidden>
          {names.map((f) => counts[f] ? <i key={f} style={{ flex: counts[f], background: colour(f) }} /> : null)}
          {counts.oven ? <i className="oven" style={{ flex: 1 }} /> : null}
          {counts.raw ? <i style={{ flex: counts.raw, background: raw }} /> : null}
        </div>
        <ul className="ord-stock">
          <li><i style={{ background: raw }} /><span>Raw dough</span><b>{counts.raw}</b></li>
          {names.map((f) => <li key={f}><i style={{ background: colour(f) }} /><span>{cap(f)}, baked</span><b>{counts[f] ?? 0}</b></li>)}
          <li><i className="oven" /><span>In the oven line</span><b>{counts.oven}</b></li>
        </ul>
      </section>

      {/* ---------------------------------------------------------------- new order */}
      <section className="ord-card">
        <div className="ord-head"><h3>New order</h3><span className={`ord-avail ${free ? "" : "none"}`}>{free} raw available</span></div>
        <div className="ord-label">Flavour</div>
        <div className="ord-flavours" role="radiogroup" aria-label="Flavour">
          {names.map((f) => (
            <button key={f} role="radio" aria-checked={f === flavour} className={`slot ${f === flavour ? "active" : ""}`}
              onClick={() => setFlavour(f)}>
              <i className="slot-dot" style={{ background: colour(f) }} />{f}
            </button>
          ))}
        </div>
        <div className="ord-label">Quantity</div>
        <div className="ord-qty">
          <button className="slot" onClick={() => setQty(Math.max(1, qty - 1))} aria-label="Fewer">−</button>
          <input type="number" min={1} max={12} value={qty} aria-label="Quantity"
            onChange={(e) => setQty(Math.max(1, Math.min(12, Number(e.target.value) || 1)))} />
          <button className="slot" onClick={() => setQty(Math.min(12, qty + 1))} aria-label="More">+</button>
          <em>1 to 12 cookies</em>
        </div>
        <button className="op cycle ord-place" onClick={place} disabled={!free}>
          Place order · {qty} × {cap(flavour)}
        </button>
        {msg && <p className={`ord-msg ${msg.tone}`} role="status">{msg.text}</p>}
        {baked > 0 && (
          <button className="op store ord-deliver" onClick={deliver} disabled={busy}
            title={busy ? "Wait until the cell is idle" : undefined}>
            Deliver {baked} baked cookie{baked === 1 ? "" : "s"} and refill with dough
          </button>
        )}
      </section>

      {/* ---------------------------------------------------------------- now */}
      <section className="ord-card">
        <div className="ord-head"><h3>Now</h3>{busy ? <span className="ord-pill run">Running</span> : <span className="ord-pill">Idle</span>}</div>
        {busy && current ? (
          <div className="ord-now">
            <div className="ord-now-head">
              <i className="slot-dot" style={{ background: colour(cyc.flavour) }} />
              <b>{cap(cyc.flavour)} cookie {current.done + 1} of {current.qty}</b>
              <span>from slot {cyc.from}</span>
            </div>
            <div className="ord-bar"><i style={{ width: `${Math.min(100, (cyc.t / Math.max(1, cyc.total)) * 100)}%`, background: colour(cyc.flavour) }} /></div>
            <div className="ord-now-foot"><span>{plain(twinOrders.step)}</span><b>{clock(Math.max(0, cyc.total - cyc.t))} left</b></div>
          </div>
        ) : (
          <p className="ord-hint">Every order is done. Place an order to start the cell.</p>
        )}
      </section>

      {/* ---------------------------------------------------------------- orders */}
      <section className="ord-card">
        <div className="ord-head"><h3>Orders</h3><span className="ord-total">{queue.filter((o) => o.done >= o.qty).length} of {queue.length} completed</span></div>
        {queue.length === 0 && <p className="ord-hint">No orders yet.</p>}
        <ol className="ord-list">
          {[...queue].reverse().slice(0, 8).map((o: OrderLine) => {
            const st = o.done >= o.qty ? "done" : o.started > 0 ? "run" : "wait";
            return (
              <li key={o.id} className={st}>
                <i className="slot-dot" style={{ background: colour(o.flavour) }} />
                <div>
                  <b>{o.qty} × {cap(o.flavour)}</b>
                  <small>#{o.id}{o.demo ? " · demo" : ""}</small>
                </div>
                <span className={`ord-pill ${st}`}>{st === "done" ? "Completed" : st === "run" ? `${o.done} of ${o.qty}` : "Queued"}</span>
                <div className="ord-bar"><i style={{ width: `${(100 * o.done) / o.qty}%`, background: colour(o.flavour) }} /></div>
              </li>
            );
          })}
        </ol>
      </section>

      {/* ---------------------------------------------------------------- rack */}
      <section className="ord-card">
        <div className="ord-head"><h3>Warehouse rack</h3><span className="ord-total">{baked} baked · {counts.raw} raw</span></div>
        <div className="ord-rack">
          {all.map((s) => {
            const out = s === inOven, f = flavourOf(rack[s]);
            return (
              <div key={s} className={`ord-cell ${out ? "out" : f ? "baked" : "raw"}`}
                title={out ? `${s}: in the oven line` : f ? `${s}: ${f}, baked` : `${s}: raw dough`}>
                <i style={{ background: out ? "transparent" : rack[s] ?? "transparent" }} />
                <b>{s}</b>
                <small>{out ? "in oven" : f ?? "raw"}</small>
              </div>
            );
          })}
        </div>
      </section>

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
