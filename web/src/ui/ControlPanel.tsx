// Order controls: pick a slot, fire a retrieve or store, home the crane. Talks
// to the API over REST; results appear as motion streamed back over the socket.

import { useState } from "react";
import { sendCommand } from "../socket";
import type { SceneDescriptor } from "../types";

export function ControlPanel({ scene }: { scene: SceneDescriptor }) {
  const slots = Object.keys(scene.rack.slots);
  const [slot, setSlot] = useState(slots[4] ?? slots[0]);
  const [msg, setMsg] = useState<string | null>(null);

  const fire = async (op: string, withSlot: boolean) => {
    try {
      await sendCommand(op, withSlot ? slot : null);
      setMsg(`queued ${op}${withSlot ? " " + slot : ""}`);
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  return (
    <div className="panel">
      <h2>Orders</h2>

      <div className="slot-grid">
        {slots.map((s) => (
          <button
            key={s}
            className={s === slot ? "slot active" : "slot"}
            onClick={() => setSlot(s)}
          >
            {s}
          </button>
        ))}
      </div>

      <div className="btn-row">
        <button className="op retrieve" onClick={() => fire("retrieve", true)}>
          Retrieve {slot}
        </button>
        <button className="op store" onClick={() => fire("store", true)}>
          Store {slot}
        </button>
      </div>
      <button className="op cycle" onClick={() => fire("cycle", true)}>
        Run full cycle from {slot}
      </button>
      <button className="op home" onClick={() => fire("home", false)}>
        Home crane
      </button>

      {msg && <p className="msg">{msg}</p>}
    </div>
  );
}
