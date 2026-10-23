// The live netlist and its fault checks (Deliverable 4).
//
// Every electrical pin of every placed part is a vertex; a wire is a zero-impedance edge between
// two pins. The graph is kept as an n x n adjacency matrix (`adjacency[i * n + j]`, 1 = joined),
// built from the project's wire_nets and from the contacts that are closed right now (a switch,
// a relay contact, a jumper). Loads - a motor, an LED with its resistor, a sensor - are not edges:
// current through them is not a short. The matrix's connected components are the electrical
// nodes: every pin in one node is at one voltage.
//
// A node is checked each time the solver evaluates (the physics worker does at 100 Hz, after
// every step):
//   SHORT_CIRCUIT   a supply's positive terminal and a ground are in the same node: a path with
//                   no load between them; or two supplies at different voltages are joined
//   OVERVOLTAGE     the node's voltage is outside the voltage_limits of a pin on it
// The node's voltage comes from the supply terminals on it, else from the pins the simulation
// drives (a sensor output, a forced input); a node with neither floats and is not checked.
//
// The schema's pin types do not say which part is a source, so supplies are declared: a supply is
// a positive terminal at a voltage and its negative terminal (ground, 0 V).
import { pinIndex, pinTable, type PartDefinition, type PinRef, type PinRow, type ProjectState, type WireNet } from "../core/schema";
import { PIN_FAULT, PIN_FORCED, PIN_HIGH, PIN_TELEMETRY } from "../core/SimulationBridge";

export type DiagnosticStatus = "OK" | "SHORT_CIRCUIT" | "OVERVOLTAGE";

export interface Diagnostic {
  status: DiagnosticStatus;
  /** the parts on the faulted node (to highlight, or burn) */
  affectedInstances: string[];
  /** the wire net the diagnostic is about; "" for a node that no net names (a closed contact) */
  netId: string;
  /** the pins on the node, as "instance.label" */
  pins: string[];
  /** the node's voltage, null when it floats */
  volts: number | null;
  /** what is wrong, in plain words */
  message: string;
}

export interface Supply {
  id: string;
  positive: PinRef;
  negative: PinRef;
  volts: number;
}

/** A contact inside a part (a switch, a relay contact, a jumper): an edge only while closed. */
export interface Contact {
  id: string;
  a: PinRef;
  b: PinRef;
  closed: boolean;
}

export interface Evaluation {
  diagnostics: Diagnostic[];
  /** pin rows on a faulted node */
  faultPins: Set<number>;
  ok: boolean;
}

const DRIVEN = PIN_HIGH | PIN_FORCED | PIN_TELEMETRY;

export class NetlistError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NetlistError";
  }
}

export class NetlistSolver {
  readonly pins: PinRow[];
  readonly n: number;
  /** n x n, row-major: 1 where two pins are joined by a wire or a closed contact */
  readonly adjacency: Uint8Array;
  /** the node (connected component) of each pin */
  readonly node: Int32Array;
  private nets: WireNet[] = [];
  private readonly contacts = new Map<string, { a: number; b: number; closed: boolean }>();
  private readonly supplies: { id: string; pos: number; neg: number; volts: number }[];
  private dirty = true;

  constructor(project: ProjectState, catalogue: Map<string, PartDefinition>, supplies: Supply[] = [], contacts: Contact[] = []) {
    this.pins = pinTable(project, catalogue);
    this.n = this.pins.length;
    this.adjacency = new Uint8Array(this.n * this.n);
    this.node = new Int32Array(this.n);
    this.supplies = supplies.map((s) => {
      if (!(Number.isFinite(s.volts) && s.volts > 0)) throw new NetlistError(`supply "${s.id}": the voltage must be greater than 0`);
      return { id: s.id, pos: this.row(s.positive, `supply "${s.id}" +`), neg: this.row(s.negative, `supply "${s.id}" -`), volts: s.volts };
    });
    for (const c of contacts) this.setContact(c);
    this.setNets(project.wire_nets);
  }

  private row(r: PinRef, what: string): number {
    const k = pinIndex(this.pins, r.part_instance, r.pin_label);
    if (k < 0) throw new NetlistError(`${what}: no pin "${r.pin_label}" on "${r.part_instance}"`);
    return k;
  }

  // ---------------------------------------------------------------- the graph
  /** Replaces the wiring (a wire drawn or removed in the editor). */
  setNets(nets: WireNet[]): void {
    for (const net of nets) for (const c of net.connections) this.row(c, `net "${net.net_id}"`);
    this.nets = nets;
    this.dirty = true;
  }

  /** Adds, opens or closes a contact (a relay switching, a button pressed). */
  setContact(c: Contact): void {
    const a = this.row(c.a, `contact "${c.id}"`);
    const b = this.row(c.b, `contact "${c.id}"`);
    const prev = this.contacts.get(c.id);
    if (prev && prev.a === a && prev.b === b && prev.closed === c.closed) return;
    this.contacts.set(c.id, { a, b, closed: c.closed });
    this.dirty = true;
  }

  /** Rebuilds the matrix and its components, if the wiring or a contact changed since. */
  private rebuild(): void {
    if (!this.dirty) return;
    const { n, adjacency: m } = this;
    m.fill(0);
    const join = (i: number, j: number) => {
      if (i === j) return;
      m[i * n + j] = 1;
      m[j * n + i] = 1;
    };
    for (const net of this.nets) {
      // a net joins all its pins: a star from the first is enough for connectivity, but the matrix
      // holds every pair so a query of "are these two wired" is one lookup
      const rows = net.connections.map((c) => pinIndex(this.pins, c.part_instance, c.pin_label));
      for (let x = 0; x < rows.length; x++) for (let y = x + 1; y < rows.length; y++) join(rows[x], rows[y]);
    }
    for (const c of this.contacts.values()) if (c.closed) join(c.a, c.b);
    // components by breadth-first search over the matrix
    this.node.fill(-1);
    const queue = new Int32Array(n);
    let id = 0;
    for (let s = 0; s < n; s++) {
      if (this.node[s] !== -1) continue;
      let head = 0;
      let tail = 0;
      queue[tail++] = s;
      this.node[s] = id;
      while (head < tail) {
        const i = queue[head++];
        const row = i * n;
        for (let j = 0; j < n; j++) {
          if (m[row + j] && this.node[j] === -1) {
            this.node[j] = id;
            queue[tail++] = j;
          }
        }
      }
      id++;
    }
    this.dirty = false;
  }

  /** Whether two pins are on one node (joined by wires and closed contacts). */
  connected(a: PinRef, b: PinRef): boolean {
    this.rebuild();
    return this.node[this.row(a, "pin")] === this.node[this.row(b, "pin")];
  }

  // ---------------------------------------------------------------- the checks
  /**
   * Checks every node. `pinVolts` / `pinFlags` are the simulation's pin state (the bridge's
   * arrays, indexed like `pins`): a pin flagged high, forced or from telemetry drives its node.
   * One diagnostic per wire net (OK or its fault), plus one for any faulted node no net names.
   */
  evaluate(pinVolts?: ArrayLike<number>, pinFlags?: ArrayLike<number>): Evaluation {
    this.rebuild();
    const { n } = this;
    const count = n ? Math.max(...this.node) + 1 : 0;
    const label = (k: number) => `${this.pins[k].instance_id}.${this.pins[k].label}`;

    // each node's supplies and grounds
    const plus: { id: string; volts: number }[][] = Array.from({ length: count }, () => []);
    const ground = new Uint8Array(count);
    for (const s of this.supplies) {
      plus[this.node[s.pos]].push({ id: s.id, volts: s.volts });
      ground[this.node[s.neg]] = 1;
    }
    // each node's voltage: a supply's, 0 V on ground, else the highest driven pin
    const volts: (number | null)[] = new Array(count).fill(null);
    for (let c = 0; c < count; c++) {
      if (plus[c].length) volts[c] = Math.max(...plus[c].map((p) => p.volts));
      else if (ground[c]) volts[c] = 0;
    }
    if (pinVolts && pinFlags) {
      for (let k = 0; k < n; k++) {
        const c = this.node[k];
        if (plus[c].length || ground[c] || !(pinFlags[k] & DRIVEN)) continue;
        volts[c] = Math.max(volts[c] ?? 0, pinVolts[k]);
      }
    }

    const members: number[][] = Array.from({ length: count }, () => []);
    for (let k = 0; k < n; k++) members[this.node[k]].push(k);
    const fault: { status: DiagnosticStatus; message: string }[] = new Array(count).fill(null).map(() => ({ status: "OK" as DiagnosticStatus, message: "" }));
    for (let c = 0; c < count; c++) {
      const sources = plus[c];
      if (sources.length && ground[c]) {
        fault[c] = { status: "SHORT_CIRCUIT", message: `${sources.map((s) => s.id).join(" and ")} +${sources[0].volts} V is wired straight to ground, with no load between` };
        continue;
      }
      const levels = [...new Set(sources.map((s) => s.volts))];
      if (levels.length > 1) {
        fault[c] = { status: "SHORT_CIRCUIT", message: `supplies at ${levels.join(" V and ")} V are wired together` };
        continue;
      }
      const v = volts[c];
      if (v === null) continue;
      const over = members[c].filter((k) => v > this.pins[k].voltage_limits[1] || v < this.pins[k].voltage_limits[0]);
      if (over.length) {
        const k = over[0];
        fault[c] = {
          status: "OVERVOLTAGE",
          message: `${label(k)} takes ${this.pins[k].voltage_limits[0]} to ${this.pins[k].voltage_limits[1]} V but its node is at ${v} V`,
        };
      }
    }

    const diagnostics: Diagnostic[] = [];
    const faultPins = new Set<number>();
    const reported = new Set<number>();
    const describe = (c: number, netId: string): Diagnostic => ({
      status: fault[c].status,
      affectedInstances: fault[c].status === "OK" ? [] : [...new Set(members[c].map((k) => this.pins[k].instance_id))],
      netId,
      pins: members[c].map(label),
      volts: volts[c],
      message: fault[c].status === "OK" ? "" : fault[c].message,
    });
    for (const net of this.nets) {
      const c = this.node[pinIndex(this.pins, net.connections[0].part_instance, net.connections[0].pin_label)];
      diagnostics.push(describe(c, net.net_id));
      reported.add(c);
    }
    for (let c = 0; c < count; c++) {
      if (fault[c].status === "OK") continue;
      for (const k of members[c]) faultPins.add(k);
      if (!reported.has(c)) diagnostics.push(describe(c, ""));
    }
    return { diagnostics, faultPins, ok: faultPins.size === 0 };
  }
}

/** Marks the faulted pins in a bridge pin-flag array (the 3D view highlights or burns them). */
export function applyFaults(pinFlags: Int32Array, faultPins: Set<number>): void {
  for (let k = 0; k < pinFlags.length; k++) {
    if (faultPins.has(k)) pinFlags[k] |= PIN_FAULT;
    else pinFlags[k] &= ~PIN_FAULT;
  }
}
