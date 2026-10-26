// The twin's end of the live link (shared/liveLink.ts): what the cell is doing, published as it
// happens, and the dashboard's commands carried out.
//
// Published: a state message 4 times a second while an order runs (once a second at rest) -
// every unit's state machine and step, the order's lines, the cookie on its way and where it
// is, the oven, the inspection's counts; each inspected cookie and each finished order line
// as they happen. A unit's state is read from the machine itself: RUN while its axes move,
// HELD while it holds a part and waits, READY while an order runs and it waits its turn, IDLE
// with no order.
//
// Commands: "simulate" (a sample order, optionally with a broken cookie), "defect" (the fault
// for the next cookie), "watch" (stream the inspection camera for the next 5 s).
import { useEffect } from "react";
import { cellStore, DEFECTS, type CellStore, type Defect } from "../scene/store/useCellStore";
import { liveLink, UNITS, type LiveState, type LiveUnit, type Stage, type UnitId } from "../shared/liveLink";
import { cameraWatch } from "../vision/photo";

const RUN_MS = 250, IDLE_MS = 1000;
/** the sample order the dashboard's "Simulate order" places: one cookie of each flavour */
export const SAMPLE = ["chocolate", "vanilla", "strawberry"];

type Axes = Record<UnitId, number[]>;
function axes(s: CellStore): Axes {
  const J = s.joints, o = J.oven;
  return {
    crane: [J.hbw.travel, J.hbw.lift, J.hbw.fork],
    belt: [J.hbw.belt],
    arm: [J.vgr.swivel, J.vgr.reach, J.vgr.plunge],
    door: [o.door, o.slider],
    sauger: [o.sauger, o.lower, o.vac],
    turntable: [o.turn, o.saw, o.push],
    ovenbelt: [o.beltOven],
    line: [o.beltSort, o.eject, o.chute],
  };
}
const moved = (a: number[], b: number[]) => a.some((x, i) => Math.abs(x - b[i]) > 1e-3);
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** What each unit does when it runs, in a few words (the flow's own caption where it has one). */
const DOING: Record<UnitId, string> = {
  crane: "moves the mould", belt: "carries the mould", arm: "carries the cookie", door: "opens the oven",
  sauger: "lifts the cookie", turntable: "turns and pushes", ovenbelt: "carries the cookie", line: "sorts the cookie",
};

export class Publisher {
  private prev: Axes | null = null;
  private last: Record<UnitId, number> = Object.fromEntries(UNITS.map((u) => [u, -1e9])) as Record<UnitId, number>;

  constructor(private store: CellStore) {}

  state(now = performance.now()): LiveState {
    const s = this.store, m = s.model, J = s.joints, o = J.oven;
    const ax = axes(s);
    const running = !m.idle;
    for (const u of UNITS) if (this.prev && moved(ax[u], this.prev[u])) this.last[u] = now;
    this.prev = ax;
    // a unit counts as running for a moment after its last move, so a pause between two legs
    // does not flicker it to READY
    const recent = (u: UnitId) => now - this.last[u] < 400;
    const [armSay, flowSay] = (m.step || "").split("   ·   ");
    const held: Partial<Record<UnitId, boolean>> = {
      crane: J.load.held === "fork", arm: !!J.vgr.carry, door: o.lamp > 0.5,
    };
    const units = {} as Record<UnitId, LiveUnit>;
    for (const u of UNITS) {
      let state: LiveUnit["state"] = !running ? "IDLE" : recent(u) ? "RUN" : held[u] ? "HELD" : "READY";
      if (u === "door" && running && o.lamp > 0.5) state = "RUN";  // baking: the oven works with its door shut
      let step = "";
      if (state === "RUN") {
        if (u === "arm" && armSay?.startsWith("VGR")) step = cap(armSay.replace(/^VGR: /, ""));
        else if (u === "door" && o.lamp > 0.5) step = `Bakes at ${Math.round(o.chamberC)} °C`;
        else if (["door", "sauger", "turntable", "ovenbelt", "line"].includes(u) && flowSay) step = cap(flowSay);
        else step = cap(DOING[u]);
      } else if (state === "HELD") step = u === "arm" ? "Holds the cookie" : u === "crane" ? "Holds the mould" : "Waits";
      units[u] = { state, step };
    }
    const cyc = m.cycle;
    const stage = (): Stage => {
      if (J.camera.lit > 0.1) return "camera";
      if (o.eject > 0.1 || o.chute > 0.1) return "bin";
      if (recent("line")) return "sorting";
      if (recent("turntable") || recent("sauger") || recent("ovenbelt")) return "turntable";
      if (o.lamp > 0.5 || (J.workpiece.visible && recent("door"))) return "oven";
      if (J.vgr.carry) return "arm";
      if (J.load.held === "belt" || recent("belt")) return "belt";
      return "rack";
    };
    return {
      type: "state", t: Date.now(), running, step: m.step || "",
      order: m.queue.slice(-8).map((q) => ({ id: q.id, flavour: q.flavour, qty: q.qty, started: q.started, done: q.done, rejected: q.rejected ?? 0 })),
      delivered: m.delivered,
      cookie: running && cyc.total > 0 ? {
        flavour: cyc.flavour, pct: Math.min(1, cyc.t / Math.max(1, cyc.total)), from: cyc.from, to: cyc.collect || cyc.to,
        stage: stage(), defect: J.workpiece.defect ?? null,
      } : null,
      units,
      oven: { C: Math.round(o.chamberC), heating: o.element > 0.5 },
      inspect: {
        passed: m.inspect.passed, rejected: m.inspect.rejected, next: m.inspect.next,
        recent: m.inspect.recent.slice(0, 6).map((r) => ({ n: r.n, flavour: r.cookieFlavour, truth: r.truth, verdict: r.verdict,
          condition: r.condition, p: r.p, unusual: r.anomaly })),
      },
    };
  }

  /** Carry out a dashboard's command. Returns what happened, in a few words. */
  command(msg: { type: string; [k: string]: unknown }): string {
    const s = this.store;
    if (msg.type === "watch") { cameraWatch.until = Date.now() + 5000; return ""; }
    const defect = (d: unknown): Defect | null => (DEFECTS.includes(d as Defect) ? (d as Defect) : null);
    if (msg.type === "defect") { s.injectDefect(defect(msg.defect)); return msg.defect ? `next cookie: ${msg.defect}` : "next cookie: good"; }
    if (msg.type === "simulate") {
      const flavours = typeof msg.flavour === "string" ? [msg.flavour] : SAMPLE;
      const qty = Math.max(1, Math.min(12, Number(msg.qty) || 1));
      const need = flavours.length * qty;
      const go = () => {
        if (msg.broken) s.injectDefect(defect(msg.broken) ?? "cracked");
        const ok = flavours.every((f) => s.place(f, qty));
        return ok ? `order placed: ${flavours.map((f) => `${qty} × ${f}`).join(", ")}` : "the rack has too little dough";
      };
      if (s.free() >= need) return go();
      // not enough raw dough: hand the baked cookies over (the moulds are refilled), then place
      if (s.model.idle) { s.deliver(); window.setTimeout(go, 800); return "refilling the rack, then the order starts"; }
      return "busy: the order is queued after the current one";
    }
    if (msg.type === "cancel_order") {
      const id = typeof msg.id === "number" ? msg.id : undefined;
      const flavour = typeof msg.flavour === "string" ? msg.flavour : undefined;
      const ok = s.cancel(id, flavour);
      return ok ? (id ? `Order #${id} deleted from queue` : "Queued order deleted") : "Cannot cancel: order is already in production or completed";
    }
    return "";
  }
}

/** Publish the cell on the live link while the twin is open, and take the dashboard's commands. */
export function useLivePublish(on: boolean, store: CellStore = cellStore) {
  useEffect(() => {
    if (!on) return;
    const link = liveLink("twin"), pub = new Publisher(store);
    let timer = 0;
    const send = () => {
      link.send(pub.state());
      timer = window.setTimeout(send, store.model.idle ? IDLE_MS : RUN_MS);
    };
    link.send({ type: "hello" });
    send();
    const off = link.on((m) => {
      if (m.type === "link" && m.up) link.send(pub.state());       // a socket came up: draw at once
      if (["watch", "simulate", "defect", "cancel_order"].includes(m.type)) {
        const said = pub.command(m);
        if (said) link.send({ type: "notice", text: said });
        if (m.type !== "watch") link.send(pub.state());
      }
    });
    const offRec = store.onRecord((r) => {
      if (r.kind === "inspection") link.send({ type: "inspection", n: r.n, flavour: r.flavour, truth: r.truth, verdict: r.verdict,
        condition: r.condition, p: r.p, unusual: r.unusual });
      else link.send({ type: "order_done", flavour: r.flavour, qty: r.qty, good: r.good, scrap: r.scrap, qc_fault: r.qc_fault });
    });
    // opened by the dashboard's "Simulate order" (?simulate=sample or =broken): once the cell
    // has its rack, the order starts here, and the URL forgets it (a reload does not repeat it)
    const q = new URLSearchParams(location.search), ask = q.get("simulate");
    let wait = 0;
    if (ask) {
      const t0 = Date.now();
      const tryStart = () => {
        if (Object.keys(store.model.rack).length && store.free() > 0) {
          const said = pub.command({ type: "simulate", broken: ask === "broken" ? "cracked" : undefined });
          link.send({ type: "notice", text: said });
          q.delete("simulate");
          history.replaceState(null, "", `${location.pathname}${q.size ? `?${q}` : ""}${location.hash}`);
        } else if (Date.now() - t0 < 60000) wait = window.setTimeout(tryStart, 500);
      };
      wait = window.setTimeout(tryStart, 1500);
    }
    return () => { window.clearTimeout(timer); window.clearTimeout(wait); off(); offRec(); };
  }, [on, store]);
}
