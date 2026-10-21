// The dashboard's end of the live link (shared/liveLink.ts): the 3D twin's cell as it runs -
// one store for the whole page, so every card that shows the live cell reads the same socket.
import { useSyncExternalStore } from "react";
import { liveLink, type LiveInspection, type LiveState, type Msg } from "../shared/liveLink";


const BASE = import.meta.env.BASE_URL;
/** a state older than this means the twin has stopped publishing (closed, or its tab hidden) */
const STALE_MS = 4000;

type Live = {
  state: LiveState | null;
  /** the twin's last word on a command ("order placed: ...") and when */
  notice: { text: string; t: number } | null;
  inspections: LiveInspection[];
  socket: boolean;
  version: number;
};
const live: Live = { state: null, notice: null, inspections: [], socket: false, version: 0 };
const subs = new Set<() => void>();
const bump = () => { live.version++; subs.forEach((f) => f()); };
let started = false;

function start() {
  if (started) return;
  started = true;
  const link = liveLink("dashboard");
  link.on((m: Msg) => {
    if (m.type === "state") live.state = m as unknown as LiveState;
    else if (m.type === "notice") live.notice = { text: String(m.text ?? ""), t: Date.now() };
    else if (m.type === "inspection") live.inspections = [m as unknown as LiveInspection, ...live.inspections].slice(0, 24);
    else if (m.type === "link") live.socket = !!m.up;
    else if (m.type !== "peers") return;
    bump();
  });
  // the twin stopping shows within a second
  window.setInterval(() => { if (live.state && Date.now() - live.state.t > STALE_MS) bump(); }, 1000);
}

export function useLive() {
  start();
  useSyncExternalStore((f) => { subs.add(f); return () => { subs.delete(f); }; }, () => live.version);
  const connected = !!live.state && Date.now() - live.state.t < STALE_MS;
  return {
    state: connected ? live.state : null,
    connected,
    socket: live.socket,
    notice: live.notice && Date.now() - live.notice.t < 8000 ? live.notice.text : null,
    inspections: live.inspections,
  };
}

/** Simulate an order: on the open twin over the link, or - with none open - open the twin with
    the order in its address, and it starts there once the machine has loaded. */
export function simulate(connected: boolean, broken: boolean) {
  if (connected) liveLink("dashboard").send({ type: "simulate", broken: broken ? "cracked" : undefined });
  else window.open(`${BASE}?simulate=${broken ? "broken" : "sample"}`, "stf-twin");
}

/** While an order runs: the next cookie broken (cracked), or a good one again. */
export function breakNext(on: boolean) {
  liveLink("dashboard").send({ type: "defect", defect: on ? "cracked" : null });
}

/** The order in progress: its lines from the oldest unfinished one on (finished orders before
    it are history). Nothing while the cell rests. */
export function currentOrder(state: LiveState | null) {
  const lines = state?.order ?? [];
  const first = lines.find((o) => o.done < o.qty);
  const cur = first ? lines.filter((o) => o.id >= first.id) : [];
  return { lines: cur, total: cur.reduce((a, o) => a + o.qty, 0), done: cur.reduce((a, o) => a + o.done, 0) };
}
