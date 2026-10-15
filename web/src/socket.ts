// WebSocket client. Pushes every frame into the mutable `hot` object (no React
// involvement) and reflects only connection state and the layout fingerprint
// into the discrete store. Reconnects with backoff; on reconnect it resyncs by
// simply receiving the next pushed frame.

import { applyFrame, store } from "./store";
import type { Frame } from "./types";

let ws: WebSocket | null = null;
let backoff = 500;

export function connect(): void {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${location.host}/ws`;
  store.set({ conn: "connecting" });

  ws = new WebSocket(url);

  ws.onopen = () => {
    backoff = 500;
    store.set({ conn: "open" });
  };

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.type === "hello") {
      store.set({ layoutFingerprint: msg.layout });
      return;
    }
    if (msg.type === "frame") {
      applyFrame(msg as Frame);
    }
  };

  ws.onclose = () => {
    store.set({ conn: "closed" });
    setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, 8000);
  };

  ws.onerror = () => ws?.close();
}

export async function sendCommand(op: string, slot: string | null): Promise<void> {
  const res = await fetch("/command", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ op, slot }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error ?? `command failed (${res.status})`);
  }
}
