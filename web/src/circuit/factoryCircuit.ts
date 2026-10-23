// The factory's electrics, pin by pin, as the netlist solver sees them: the parts, wires, supplies
// and relay/switch contacts that stf-cad/hbw/electrical.py exports (public/electrical.json) from
// the board's pinouts, the RevPi occupancy plans and the datasheets.
//
// The PLC drives it by its outputs: an output that coils a relay flips that relay's changeover
// contact (COM from NC - the motor lead on GND - to NO - on +24 V), so a motor's two leads are
// where its relay pair puts them; a reference switch closes its common-NO contact. Every change
// re-checks every node (shorts, overvoltage) through NetlistSolver.
import { parseCatalogue, parseProjectState, type PartDefinition, type PinRef, type ProjectState, type Vec3 } from "../core/schema";
import { NetlistSolver, type Contact, type Diagnostic, type Supply } from "./NetlistSolver";

export type Source = "datasheet" | "booklet" | "plan" | "board" | "derived" | "design" | "assumed";

/** A pin as the datasheet sheet shows it (the schema's ElectricalPin, with its provenance). */
export interface PinSheet {
  pin_number: number;
  label: string;
  function: string;
  electrical_type: "power_input" | "digital_io" | "analog_in";
  voltage_limits: [number, number];
  voltage_source: Source;
  colour?: string;
  max_mA?: number;
  current_source?: Source;
}

export interface PartSheet {
  part_id: string;
  name: string;
  ft: string;
  document: string;
  kind: "motor" | "switch" | "sensor" | "lamp" | "pneumatic" | "board" | "plc" | "power" | "safety";
  dimensions_mm: { x: number; y: number; z: number };
  dimensions_source: Source;
  mass_g: number;
  pins: PinSheet[];
  ratings: { label: string; value: string; source: string }[];
  glb: string | null;
}

export interface Check {
  check: string;
  ok: boolean;
  severity: "ok" | "warn" | "fail";
  detail: string;
  source: string;
}

/** Where a part is in the factory: the CAD export's part it was placed from, its box (factory mm,
    a moving frame at its zero pose) and the frame that carries it. */
export interface Placement {
  cad: string;
  box_mm: [number, number, number, number, number, number];
  frame: string;
}

export type Variant = "original" | "upgraded";

/** One variant's electrics: the original (the occupancy plans: a RevPi DIO per module) or the
    upgraded factory the 3D twin shows (remote I/O nodes, safety contactors, central air). */
export interface VariantDoc {
  project: ProjectState;
  modules: Record<string, string>;
  supplies: Supply[];
  contacts: Contact[];
  /** which PLC output closes which relay contact (and opens its partner) */
  controls: { output: string; closes: string; opens: string; motor: string }[];
  io: Record<string, { signal: string; terminal: number | null; revpi_terminal: number | null; channel: string; kind?: "IN" | "OUT" }[]>;
  checks: Check[];
  findings: string[];
  placement: Record<string, Placement | null>;
}

export interface ElectricalDoc {
  schema: "stf.electrical/2";
  parts: Record<string, PartSheet>;
  source_tags: Record<string, string>;
  variants: Record<Variant, VariantDoc>;
}

/** A sheet as the schema's strict PartDefinition (the solver and the physics take these). */
export function toDefinition(s: PartSheet): PartDefinition {
  return {
    part_id: s.part_id,
    dimensions_mm: s.dimensions_mm,
    mass_g: s.mass_g,
    bounding_box_type: "OBB",
    // a part with no model yet is drawn as its datasheet box
    mesh_data: { glb_url: s.glb ?? `box:${s.part_id}`, collision_margin_mm: 0.05 },
    mating_connectors: [],
    electrical_pins: s.pins.map((p) => ({
      pin_number: p.pin_number, label: p.label, local_position_mm: [0, 0, 0] as Vec3,
      electrical_type: p.electrical_type, voltage_limits: p.voltage_limits,
    })),
  };
}

export class FactoryCircuit {
  readonly solver: NetlistSolver;
  readonly catalogue: Map<string, PartDefinition>;
  readonly project: ProjectState;
  private readonly contacts = new Map<string, Contact>();
  private readonly outputs = new Map<string, boolean>();
  private last: Diagnostic[] | null = null;
  readonly doc: VariantDoc;

  constructor(readonly file: ElectricalDoc, readonly variant: Variant = "upgraded") {
    if (file.schema !== "stf.electrical/2") throw new Error(`not an electrical export: ${String(file.schema)}`);
    const doc = file.variants[variant];
    if (!doc) throw new Error(`no variant "${variant}"`);
    this.doc = doc;
    // through the strict parsers: every pin a wire names must exist on its part
    this.catalogue = parseCatalogue(Object.values(file.parts).map(toDefinition));
    this.project = parseProjectState(doc.project, this.catalogue);
    for (const c of doc.contacts) this.contacts.set(c.id, { ...c });
    this.solver = new NetlistSolver(this.project, this.catalogue, doc.supplies, [...this.contacts.values()]);
  }

  /** Switches a PLC output ("hbw.Q3"): a relay coil flips its changeover contact. */
  setOutput(output: string, on: boolean): void {
    const [module, signal] = output.split(".");
    if (!this.doc.io[module]?.some((r) => r.signal === signal && (r.channel.startsWith("OUT") || r.kind === "OUT"))) throw new Error(`no PLC output "${output}"`);
    const ctl = this.doc.controls.filter((c) => c.output === output);
    this.outputs.set(output, on);
    for (const c of ctl) {
      this.setContact(c.closes, on);
      this.setContact(c.opens, !on);
    }
  }

  /** A switch's contact by its part ("hbw.I1" pressed closes its common-NO contact). */
  press(instance: string, pressed: boolean): void {
    this.setContact(`${instance}.NO`, pressed);
  }

  setContact(id: string, closed: boolean): void {
    const c = this.contacts.get(id);
    if (!c) throw new Error(`no contact "${id}"`);
    c.closed = closed;
    this.solver.setContact(c);
    this.last = null;
  }

  /** Every net checked: one diagnostic per wire net, and any faulted node. */
  evaluate(): Diagnostic[] {
    this.last ??= this.solver.evaluate().diagnostics;
    return this.last;
  }

  faults(): Diagnostic[] {
    return this.evaluate().filter((d) => d.status !== "OK");
  }

  /** A pin's voltage now (null: it floats). */
  volts(ref: PinRef): number | null {
    const key = `${ref.part_instance}.${ref.pin_label}`;
    const d = this.evaluate().find((x) => x.pins.includes(key));
    if (!d) throw new Error(`pin ${key} is on no wire`);
    return d.volts;
  }

  /** The wiring changed (a wire drawn, removed or moved in the editor): re-checked. */
  rewire(nets: ProjectState["wire_nets"]): void {
    this.solver.setNets(parseProjectState({ placed_parts: this.project.placed_parts, wire_nets: nets }, this.catalogue).wire_nets);
    this.last = null;
  }
}
