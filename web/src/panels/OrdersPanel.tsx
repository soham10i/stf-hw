// Orders: the customer's view of the cell. The cell holds exactly 12 cookies, one per slot,
// raw or baked. Pick a flavour and a quantity, place the order, and the 3D twin bakes exactly
// that: one cycle per cookie, each brought back into the slot it came from. When an order is
// completed its cookies are all in the rack. "Deliver" hands the baked cookies over and
// refills their moulds with fresh dough, so the count stays 12. The rack and the orders are kept
// in this browser across reloads (scene/engine/persistence.ts) until "Reset rack" starts afresh.
//
// It reads the cell from the store (scene/store/useCellStore.ts), re-rendering when an order
// moves on and a few times a second while a cookie is under way; its buttons are the store's
// actions, which the coordinator carries out in step with the machine.
//
// The physics kernel's manual crane commands are in the Telemetry panel, beside the kernel.

import { useEffect, useState } from "react";
import { DEFECTS, useCell, type Defect, type OrderLine } from "../scene/store/useCellStore";
import { useCadDoc } from "../shared/model";
import { ago, fetchRecords, type TwinRecords } from "../shared/records";
import { HAS_API } from "../shared/mode";
import { CameraView } from "../twin/CameraView";
import { SAMPLE } from "../twin/livePublish";
import { Icon } from "../shared/icons";
import { liveLink } from "../shared/liveLink";

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const clock = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
/** The step text without the "VGR:" prefix and the oven's side note. */
const plain = (s: string) => cap(s.split("   ·   ")[0].replace(/^VGR: /, "Robot arm: ").replace(/—/g, "–"));

export function OrdersPanel({ slots }: { slots?: string[] }) {
  const { doc } = useCadDoc();
  const flavours = doc ? doc.pipeline.flavours : {};
  const names = Object.keys(flavours);
  const [flavour, setFlavour] = useState("chocolate");
  const [qty, setQty] = useState(3);
  const [msg, setMsg] = useState<{ text: string; tone: "ok" | "bad" } | null>(null);
  // a broken cookie in the order: the inspection must catch it (the camera, the CNN, the line)
  const [broken, setBroken] = useState(false);
  const store = useCell((s) => s);
  const m = store.model;
  const rack = m.rack, raw = m.rawColour, cyc = m.cycle;
  const all = slots ?? Object.keys(rack);
  const busy = !m.idle;
  const colour = (f: string) => flavours[f]?.colour ?? raw;
  const flavourOf = (c: string | null | undefined) => names.find((f) => flavours[f].colour.toLowerCase() === c?.toLowerCase());
  const queue = m.queue;
  const ins = m.inspect;
  const free = store.free();
  const current = queue.find((o) => o.started > o.done);

  // this session's stored past (shared/records.ts): refreshed on mount, when the twin
  // finishes something, and every half minute; hidden without the API
  const [hist, setHist] = useState<TwinRecords | null>(null);
  useEffect(() => {
    if (!HAS_API) return;
    let live = true;
    const load = () => { void fetchRecords().then((r) => { if (live) setHist(r); }); };
    load();
    const off = store.onRecord(load);
    const timer = window.setInterval(load, 30_000);
    return () => { live = false; off(); window.clearInterval(timer); };
  }, [store]);

  // the twelve cookies, by state
  const inOven = busy ? cyc.from : null;
  const counts = { raw: 0, oven: inOven ? 1 : 0 } as Record<string, number>;
  for (const q of all) {
    if (q === inOven) continue;
    const f = flavourOf(rack[q]);
    const k = rack[q] === null ? "empty" : f ?? "raw";
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
    if (queue.length >= 12) {
      setMsg({ tone: "bad", text: "The order book is full (12 orders). Wait until one is finished, or reset the rack to clear the list." });
      return;
    }
    const wasIdle = m.idle && !queue.some((o) => o.done < o.qty);
    if (broken) store.injectDefect("cracked");
    store.place(flavour, qty);
    setMsg({ tone: "ok", text: `Order placed: ${qty} × ${flavour}${broken ? ", the first one broken" : ""}. ${wasIdle ? "The cell starts now." : "Queued."}` });
  };
  /** One cookie of each flavour: the quickest way to watch the whole line work. */
  const sample = () => {
    if (free < SAMPLE.length) { setMsg({ tone: "bad", text: "Not enough raw dough: deliver the baked cookies first." }); return; }
    if (broken) store.injectDefect("cracked");
    SAMPLE.forEach((f) => store.place(f, 1));
    setMsg({ tone: "ok", text: `Sample order: one of each flavour${broken ? ", the first one broken" : ""}.` });
  };
  const reset = () => {
    if (!window.confirm("Reset the rack? Every slot gets fresh dough and the order list is cleared.")) return;
    store.reset();
    setMsg({ tone: "ok", text: "The rack is reset: 12 raw cookies, no orders." });
  };
  const deliver = () => {
    store.deliver();
    setMsg({ tone: "ok", text: `${baked} baked cookie${baked === 1 ? "" : "s"} delivered; their moulds are refilled with fresh dough.` });
  };
  const cancelOrder = (id: number) => {
    const ok = store.cancel(id);
    if (ok) {
      setMsg({ tone: "ok", text: `Order #${id} deleted from queue.` });
      try {
        liveLink("dashboard").send({ type: "cancel_order", id });
      } catch {
        // liveLink fallback
      }
    } else {
      setMsg({ tone: "bad", text: `Order #${id} is currently in production or completed and cannot be cancelled.` });
    }
  };

  return (
    <div className="panel orders ord">
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
        <button className={`ord-broken ${broken ? "on" : ""}`} aria-pressed={broken} onClick={() => setBroken(!broken)}
          title="The first cookie of the order comes out broken (cracked): watch the camera find it and the line hold it back">
          <span className="ord-broken-ico" aria-hidden>{broken ? "✕" : ""}</span>
          <span><b>Broken cookie</b><small>{broken ? "the first cookie is cracked" : "every cookie baked right"}</small></span>
        </button>
        <div className="ord-go">
          <button className="op cycle ord-place" onClick={place} disabled={!free}>
            Place order · {qty} × {cap(flavour)}
          </button>
          <button className="op ord-sample" onClick={sample} disabled={free < SAMPLE.length}
            title="One chocolate, one vanilla, one strawberry">Sample order</button>
        </div>
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
            <div className="ord-now-foot"><span>{plain(m.step)}</span><b>{clock(Math.max(0, cyc.total - cyc.t))} left</b></div>
          </div>
        ) : (
          <p className="ord-hint">{queue.length ? "Every order is done." : "The cell is waiting."} Place an order above to start it.</p>
        )}
      </section>

      {/* ---------------------------------------------------------------- inspection */}
      <section className="ord-card">
        <div className="ord-head"><h3>Quality inspection</h3>
          <span className="ord-total">{ins.passed} passed · {ins.rejected} rejected</span></div>
        <CameraView size={220} />
        <label className="ord-auto">
          <input type="checkbox" checked={ins.auto} onChange={(e) => store.autoDefects(e.target.checked)} />
          <span><b>QC testing</b>: one cookie in every 12, drawn at random, gets a random fault</span>
        </label>
        <div className="ord-label">Next cookie</div>
        <div className="ui-seg ord-defects" role="radiogroup" aria-label="Fault for the next cookie">
          {([null, ...DEFECTS] as (Defect | null)[]).map((d) => (
            <button key={d ?? "ok"} role="radio" aria-checked={ins.next === d} className={ins.next === d ? "on" : ""}
              onClick={() => store.injectDefect(d)} title={d ? `The simulation makes the next cookie ${d}` : "A good cookie"}>{d ? cap(d) : "Good"}</button>
          ))}
        </div>
        {ins.recent.length > 0 && (
          <ol className="ord-ins">
            {ins.recent.slice(0, 4).map((r) => {
              const pass = r.verdict === "pass", ok = r.truth === "ok";
              const call = pass === ok ? (pass ? "right" : "caught") : pass ? "escape" : "false reject";
              return (
                <li key={r.n} className={call.replace(" ", "-")}>
                  <i className="slot-dot" style={{ background: colour(r.cookieFlavour) }} />
                  <span><b>#{r.n} {r.truth === "ok" ? "good" : r.truth}</b><small>CNN: {r.condition} {Math.round(r.p * 100)} % · autoencoder {r.ae.toFixed(2)}×</small></span>
                  <em className={pass ? "pass" : "reject"}>{pass ? "pass" : r.verdict === "check" ? "to a person" : "reject"}</em>
                  <small className="ord-call">{call}</small>
                </li>
              );
            })}
          </ol>
        )}
      </section>

      {/* ---------------------------------------------------------------- orders */}
      <section className="ord-card">
        <div className="ord-head"><h3>Orders</h3><span className="ord-total">{queue.filter((o) => o.done >= o.qty).length} of {queue.length} completed</span></div>
        {queue.length === 0 && <p className="ord-hint">No orders yet.</p>}
        <ol className="ord-list">
          {[...queue].reverse().slice(0, 8).map((o: OrderLine) => {
            const st = o.done >= o.qty ? "done" : o.started > 0 ? "run" : "wait";
            const canCancel = st === "wait";
            return (
              <li key={o.id} className={st}>
                <i className="slot-dot" style={{ background: colour(o.flavour) }} />
                <div>
                  <b>{o.qty} × {cap(o.flavour)}</b>
                  <small>#{o.id}</small>
                </div>
                <div className="ord-line-actions">
                  <span className={`ord-pill ${st}`}>{st === "done" ? "Completed" : st === "run" ? `${o.done} of ${o.qty}` : "Queued"}</span>
                  {canCancel ? (
                    <button
                      type="button"
                      className="ord-cancel-btn"
                      onClick={() => cancelOrder(o.id)}
                      title={`Cancel and delete queued order #${o.id}`}
                      aria-label={`Cancel order #${o.id}`}
                    >
                      <Icon name="close" size={11} />
                      <span>Delete</span>
                    </button>
                  ) : (
                    <span
                      className="ord-locked-badge"
                      title={st === "run" ? "In production: cannot be cancelled" : "Completed order"}
                    >
                      <Icon name="shieldlock" size={11} />
                      <small>{st === "run" ? "In production" : "Done"}</small>
                    </span>
                  )}
                </div>
                <div className="ord-bar"><i style={{ width: `${(100 * o.done) / o.qty}%`, background: colour(o.flavour) }} /></div>
              </li>
            );
          })}
        </ol>
      </section>

      {/* ---------------------------------------------------------------- rack */}
      <section className="ord-card">
        <div className="ord-head"><h3>Warehouse rack</h3><span className="ord-total">{total} cookies, always</span></div>
        <p className="ord-sum">{counts.raw ?? 0} raw{names.map((f) => counts[f] ? ` · ${counts[f]} ${f}` : "").join("")}{counts.oven ? ` · ${counts.oven} in the oven line` : ""}{counts.empty ? ` · ${counts.empty} empty (rejected)` : ""}</p>
        {/* as the rack stands: the top shelf (row C) first, row A at the bottom */}
        <div className="ord-rack">
          {[...all].sort((a, b) => b[0].localeCompare(a[0]) || Number(a.slice(1)) - Number(b.slice(1))).map((s) => {
            const out = s === inOven, f = flavourOf(rack[s]), empty = rack[s] === null;
            return (
              <div key={s} className={`ord-cell ${out ? "out" : empty ? "empty" : f ? "baked" : "raw"}`}
                title={out ? `${s}: in the oven line` : empty ? `${s}: an empty mould - its cookie was rejected by the inspection` : f ? `${s}: ${f}, baked` : `${s}: raw dough`}>
                <i style={{ background: out || empty ? "transparent" : rack[s] ?? "transparent" }} />
                <b>{s}</b>
                <small>{out ? "in oven" : empty ? "empty" : f ?? "raw"}</small>
              </div>
            );
          })}
        </div>
        <button className="op ord-reset" onClick={reset} title="Fresh dough in every slot and an empty order list; also forgets what this browser saved">
          Reset rack
        </button>
      </section>

      {/* ------------------------------------------------- this session's stored past */}
      {hist && (hist.orders.length > 0 || hist.inspections.length > 0) && (
        <section className="ord-card">
          <div className="ord-head"><h3>Session history</h3>
            <span className="ord-total">{hist.orders.length} order{hist.orders.length === 1 ? "" : "s"} · {hist.inspections.length} cookie{hist.inspections.length === 1 ? "" : "s"}</span></div>
          <p className="ord-hint">Kept on the server under this session's id ({hist.database}) — another visitor sees none of it.</p>
          {hist.orders.length > 0 && (
            <ol className="ord-list ord-hist">
              {hist.orders.slice(0, 10).map((o, i) => (
                <li key={`${o.t}-${i}`}>
                  <i className="slot-dot" style={{ background: colour(o.flavour) }} />
                  <div><b>{o.qty} × {cap(o.flavour)}</b><small>{o.good} good{o.scrap ? ` · ${o.scrap} scrap` : ""}</small></div>
                  <span className="ord-hist-t" title={new Date(o.t).toLocaleString()}>{ago(o.t)}</span>
                </li>
              ))}
            </ol>
          )}
          {hist.inspections.length > 0 && (
            <ol className="ord-ins ord-hist-cookies">
              {hist.inspections.slice(0, 6).map((c, i) => {
                const pass = c.verdict === "pass";
                return (
                  <li key={`${c.t}-${i}`}>
                    <i className="slot-dot" style={{ background: colour(c.flavour) }} />
                    <span><b>#{c.n} {c.truth === "ok" ? "good" : c.truth}</b><small>{c.condition} · {ago(c.t)}</small></span>
                    <em className={pass ? "pass" : "reject"}>{pass ? "pass" : "reject"}</em>
                  </li>
                );
              })}
            </ol>
          )}
        </section>
      )}

    </div>
  );
}
