// The controller board's data (public/controller.json, from stf-cad/hbw/controller.py): modules,
// pin headers, relays, and the helpers that read a pin's signal.


import { useJson } from "../shared/data";



type Pin = { pin: number; terminal: string | null; signal: string | null; function: string };
export type Relay = { role: string; a: string; b: string; motor: string } | null;
interface Module {
  name: string; ft: string; short: string; pages: number[];
  req: {
    supply: string; page: number;
    digital_in: Record<string, string[]>; counter_in: Record<string, string[]>;
    analog_in: Record<string, string[]>; outputs: Record<string, string[]>;
  };
  st3: Record<string, string>;
  st1: Pin[]; st2: Pin[];
  relays: Record<string, Relay>;
  valves: Record<string, { role: string; q: string; terminal: string }>;
  encoders: Record<string, [string, string]>;
}
export interface ControllerDoc {
  source: string;
  board: { name: string; blocks: Record<string, string>; page: number };
  plc: {
    inputs: string; outputs: string; other_controllers: string[];
    power: Record<string, string>; rules: string[]; pages: number[];
  };
  factory: Record<string, number | string>;
  modules: Record<string, Module>;
  discrepancies: { what: string; a: string; b: string; impact: string }[];
  reconciliation: {
    modules: { module: string; plan_signals: string[]; missing_in_model: string[];
               extra_in_model: Record<string, string[]>; ok: boolean }[];
    totals: { what: string; doc_p2: number; sum_of_modules: number; ok: boolean }[];
  };
}

export function useController(): { doc: ControllerDoc | null; err: string | null } {
  const { data, error } = useJson<ControllerDoc>("controller.json", "controller.json missing - run controller.py in stf-cad/hbw");
  return { doc: data, err: error };
}

export const KIND = (s: string | null | undefined) =>
  !s ? "nc" : s.startsWith("Q") ? "out" : s.startsWith("B") ? "cnt" : s.startsWith("A") ? "ana"
    : s.startsWith("I") ? "in" : s === "GND" ? "gnd" : "pwr";

export const POWER: Record<number, string> = { 1: "+24V actuators", 2: "+24V sensors", 3: "GND", 4: "GND" };

// Relay geometry on the board, from the p.4 drawing (board-local units).
export const RELAY_X = [90, 130, 215, 265, 315, 360, 445, 495];

/** Everything known about one signal on the selected module. */
export function signalInfo(m: Module) {
  const info: Record<string, { terminal: string; function: string; header?: string; relay?: string; valve?: string }> = {};
  for (const [hdr, pins] of [["ST1", m.st1], ["ST2", m.st2]] as const) {
    for (const p of pins) {
      if (!p.signal || !/^[IQAB]\d+$/.test(p.signal)) continue;
      info[p.signal] = { terminal: p.terminal ?? "", function: p.function, header: `${hdr} pin ${p.pin}` };
    }
  }
  for (const [v, x] of Object.entries(m.valves))
    info[x.q] = { terminal: x.terminal, function: `valve: ${x.role}`, valve: v };
  Object.entries(m.relays).forEach(([pair, r]) => {
    if (!r) return;
    const [ra, rb] = pair.split("/");
    if (info[r.a]) info[r.a].relay = ra;
    if (info[r.b]) info[r.b].relay = rb;
  });
  return info;
}
