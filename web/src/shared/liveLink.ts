// The live link between the 3D twin and the dashboard (services/api/livehub.py).
//
// The simulation runs in the twin. While it runs, the twin publishes what the cell is doing -
// every unit's state and step, the order, each inspected cookie, the inspection camera - and
// every dashboard the visitor has open draws it as it happens. Dashboards talk back on the
// same link: simulate an order, break the next cookie, "I am watching the camera".
//
// Transport: the API's WebSocket /twin/live (one room per guest, so a dashboard in another
// browser or on another device sees the same twin). Without the API (the standalone Pages
// build) or while the socket is down, a BroadcastChannel carries the same messages between
// tabs of one browser. Every message carries its sender and a sequence number, so one that
// arrives both ways is taken once.
import { HAS_API } from "./mode";
import { fetchGuest } from "./session";
import { apiWs } from "./api";

export type Role = "twin" | "dashboard";
export type Msg = { type: string; src?: string; seq?: number; [k: string]: unknown };

/** The cell's units as the PLC names them (control.py UNITS), in line order. */
export const UNITS = ["crane", "belt", "arm", "door", "sauger", "turntable", "ovenbelt", "line"] as const;
export type UnitId = (typeof UNITS)[number];
/** A unit's state machine: IDLE (no order), READY (waiting its turn), RUN (moving), HELD
    (holding a part while another unit works), DONE (its part of the order finished). */
export type UnitState = "IDLE" | "READY" | "RUN" | "HELD";
export type LiveUnit = { state: UnitState; step: string };
/** Where the cookie being made is on its way through the cell. */
export const STAGES = ["rack", "belt", "arm", "oven", "turntable", "sorting", "camera", "bin"] as const;
export type Stage = (typeof STAGES)[number];

export type LiveInspection = { n: number; flavour: string; truth: string; verdict: string; condition: string; p: number; unusual: boolean };
export type LiveState = {
  type: "state"; t: number; running: boolean; step: string;
  order: { id: number; flavour: string; qty: number; started: number; done: number; rejected: number }[];
  delivered: number;
  cookie: { flavour: string; pct: number; from: string; to: string; stage: Stage; defect: string | null } | null;
  units: Record<UnitId, LiveUnit>;
  oven: { C: number; heating: boolean };
  inspect: { passed: number; rejected: number; next: string | null; recent: LiveInspection[] };
};

const CHANNEL = "stf-live";
const id = () => Math.random().toString(36).slice(2, 10);

export class LiveLink {
  readonly src = id();
  private seq = 0;
  private ws: WebSocket | null = null;
  private bc: BroadcastChannel | null = null;
  private backoff = 500;
  private closed = false;
  private seen = new Map<string, number>();
  private listeners = new Set<(m: Msg) => void>();
  /** the hub's count of the other side: twins (for a dashboard) or dashboards (for a twin) */
  peers = { twins: 0, dashboards: 0 };

  constructor(readonly role: Role) {
    try { this.bc = new BroadcastChannel(CHANNEL); this.bc.onmessage = (e) => this.take(e.data as Msg, false); } catch { /* none */ }
    if (HAS_API) this.open();
  }

  get socket(): boolean { return this.ws?.readyState === WebSocket.OPEN; }

  private open() {
    if (this.closed) return;
    // the hub keys rooms by the signed guest cookie and refuses a socket without one: make sure
    // GET /guest has issued it (once per page; cached) before connecting
    void fetchGuest().then(() => this.connect());
  }

  private connect() {
    if (this.closed) return;
    let ws: WebSocket;
    try { ws = new WebSocket(apiWs(`/twin/live?role=${this.role}`)); } catch { return; }
    this.ws = ws;
    ws.onopen = () => { this.backoff = 500; this.emit({ type: "link", up: true }); };
    ws.onmessage = (e) => { try { this.take(JSON.parse(e.data as string) as Msg, true); } catch { /* not JSON */ } };
    ws.onclose = () => {
      this.ws = null;
      this.emit({ type: "link", up: false });
      if (this.closed) return;
      window.setTimeout(() => this.open(), this.backoff);
      this.backoff = Math.min(this.backoff * 2, 10000);
    };
    ws.onerror = () => ws.close();
  }

  private take(m: Msg, fromSocket: boolean) {
    if (!m || typeof m.type !== "string") return;
    if (m.type === "peers") { this.peers = { twins: Number(m.twins) || 0, dashboards: Number(m.dashboards) || 0 }; this.emit(m); return; }
    // the channel also carries this tab's own messages to other tabs' links: only the other side's
    if (!fromSocket && (m.src === this.src || (m as { role?: string }).role === this.role)) return;
    if (m.src && typeof m.seq === "number") {
      if ((this.seen.get(m.src) ?? -1) >= m.seq) return;  // already had it the other way
      this.seen.set(m.src, m.seq);
    }
    this.emit(m);
  }

  private emit(m: Msg) { this.listeners.forEach((f) => f(m)); }

  /** Send to the other side: over the socket when it is open, else to this browser's tabs. */
  send(m: Msg) {
    const out = { ...m, src: this.src, seq: this.seq++, role: this.role };
    if (this.socket) {
      try { this.ws!.send(JSON.stringify(out)); return; } catch { /* fall through */ }
    }
    try { this.bc?.postMessage(out); } catch { /* none */ }
  }

  on(f: (m: Msg) => void) { this.listeners.add(f); return () => { this.listeners.delete(f); }; }

  close() {
    this.closed = true;
    this.ws?.close();
    this.bc?.close();
  }
}

const shared: Partial<Record<Role, LiveLink>> = {};
/** One link per role per tab, shared by everything on the page that uses it. */
export function liveLink(role: Role): LiveLink {
  return (shared[role] ??= new LiveLink(role));
}

/** A Blob as base64 (the link carries JSON), and back. */
export async function toB64(b: Blob): Promise<string> {
  const bytes = new Uint8Array(await b.arrayBuffer());
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}
export function fromB64(s: string, type = "image/jpeg"): Blob {
  const bin = atob(s), out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return new Blob([out], { type });
}
