// The precision engine's data schemas (docs/architecture/simulation-engine.md): a part's
// definition (its size, mass, mating connectors and electrical pins), and a project (the parts
// placed and the nets that wire them). Every value that enters the engine passes a parser here,
// which rejects anything the schema does not allow - unknown keys, non-finite numbers,
// non-unit normals and quaternions, a net naming a pin its part does not have - with the path of
// the offending value. All lengths are millimetres, as float64 (JavaScript numbers).

export type Vec3 = [number, number, number];
export type Quat = [number, number, number, number]; // x, y, z, w

export const PRECISION_GRID_MM = 0.1;
export const UNIT_TOLERANCE = 1e-6; // |n| and |q| must be within this of 1

export type MatingType = "DIN_35mm" | "M3_screw";
export type PinType = "power_input" | "digital_io" | "analog_in";
const MATING_TYPES: readonly MatingType[] = ["DIN_35mm", "M3_screw"];
const PIN_TYPES: readonly PinType[] = ["power_input", "digital_io", "analog_in"];

export interface SystemContext {
  target: string;
  precision_grid_mm: number;
  electrical_netlist_type: "nodal_adjacency_matrix";
}
export interface MatingConnector {
  node_id: string;
  local_position_mm: Vec3;
  normal_vector: Vec3;
  allowed_mating_type: MatingType;
}
export interface ElectricalPin {
  pin_number: number;
  label: string;
  local_position_mm: Vec3;
  electrical_type: PinType;
  voltage_limits: [number, number];
}
export interface PartDefinition {
  part_id: string;
  dimensions_mm: { x: number; y: number; z: number };
  mass_g: number;
  bounding_box_type: "OBB";
  mesh_data: { glb_url: string; collision_margin_mm: number };
  mating_connectors: MatingConnector[];
  electrical_pins: ElectricalPin[];
}
export interface PlacedPart {
  instance_id: string;
  part_id: string;
  world_position_mm: Vec3;
  world_quaternion: Quat;
}
export interface PinRef {
  part_instance: string;
  pin_label: string;
}
export interface WireNet {
  net_id: string;
  connections: PinRef[];
}
export interface ProjectState {
  placed_parts: PlacedPart[];
  wire_nets: WireNet[];
}

export class SchemaError extends Error {
  constructor(public readonly path: string, message: string) {
    super(`${path}: ${message}`);
    this.name = "SchemaError";
  }
}

// ------------------------------------------------------------------ primitives
type Obj = Record<string, unknown>;

function record(x: unknown, path: string, keys: readonly string[]): Obj {
  if (typeof x !== "object" || x === null || Array.isArray(x)) throw new SchemaError(path, "must be an object");
  const o = x as Obj;
  for (const k of Object.keys(o)) if (!keys.includes(k)) throw new SchemaError(`${path}.${k}`, "is not in the schema");
  for (const k of keys) if (!(k in o)) throw new SchemaError(`${path}.${k}`, "is required");
  return o;
}

function finite(x: unknown, path: string): number {
  if (typeof x !== "number" || !Number.isFinite(x)) throw new SchemaError(path, "must be a finite number");
  return x;
}

function positive(x: unknown, path: string): number {
  const n = finite(x, path);
  if (n <= 0) throw new SchemaError(path, "must be greater than 0");
  return n;
}

function text(x: unknown, path: string): string {
  if (typeof x !== "string" || x.trim() === "") throw new SchemaError(path, "must be a non-empty string");
  return x;
}

function oneOf<T extends string>(x: unknown, path: string, allowed: readonly T[]): T {
  if (typeof x !== "string" || !allowed.includes(x as T)) {
    throw new SchemaError(path, `must be one of ${allowed.join(", ")}`);
  }
  return x as T;
}

function tuple(x: unknown, path: string, n: number): number[] {
  if (!Array.isArray(x) || x.length !== n) throw new SchemaError(path, `must be an array of ${n} numbers`);
  return x.map((v, i) => finite(v, `${path}[${i}]`));
}

function list(x: unknown, path: string): unknown[] {
  if (!Array.isArray(x)) throw new SchemaError(path, "must be an array");
  return x;
}

const norm = (v: number[]) => Math.hypot(...v);

function unit(v: number[], path: string): void {
  if (Math.abs(norm(v) - 1) > UNIT_TOLERANCE) throw new SchemaError(path, "must have length 1");
}

function unique(values: string[], path: string, what: string): void {
  const seen = new Set<string>();
  for (const v of values) {
    if (seen.has(v)) throw new SchemaError(path, `${what} "${v}" appears twice`);
    seen.add(v);
  }
}

// ------------------------------------------------------------------ parsers
export function parseSystemContext(x: unknown, path = "system_context"): SystemContext {
  const o = record(x, path, ["target", "precision_grid_mm", "electrical_netlist_type"]);
  return {
    target: text(o.target, `${path}.target`),
    precision_grid_mm: positive(o.precision_grid_mm, `${path}.precision_grid_mm`),
    electrical_netlist_type: oneOf(o.electrical_netlist_type, `${path}.electrical_netlist_type`, ["nodal_adjacency_matrix"] as const),
  };
}

function parseConnector(x: unknown, path: string): MatingConnector {
  const o = record(x, path, ["node_id", "local_position_mm", "normal_vector", "allowed_mating_type"]);
  const normal = tuple(o.normal_vector, `${path}.normal_vector`, 3);
  unit(normal, `${path}.normal_vector`);
  return {
    node_id: text(o.node_id, `${path}.node_id`),
    local_position_mm: tuple(o.local_position_mm, `${path}.local_position_mm`, 3) as Vec3,
    normal_vector: normal as Vec3,
    allowed_mating_type: oneOf(o.allowed_mating_type, `${path}.allowed_mating_type`, MATING_TYPES),
  };
}

function parsePin(x: unknown, path: string): ElectricalPin {
  const o = record(x, path, ["pin_number", "label", "local_position_mm", "electrical_type", "voltage_limits"]);
  const n = finite(o.pin_number, `${path}.pin_number`);
  if (!Number.isInteger(n) || n < 1) throw new SchemaError(`${path}.pin_number`, "must be a whole number from 1");
  const limits = tuple(o.voltage_limits, `${path}.voltage_limits`, 2);
  if (limits[0] > limits[1]) throw new SchemaError(`${path}.voltage_limits`, "must be [min, max] with min <= max");
  return {
    pin_number: n,
    label: text(o.label, `${path}.label`),
    local_position_mm: tuple(o.local_position_mm, `${path}.local_position_mm`, 3) as Vec3,
    electrical_type: oneOf(o.electrical_type, `${path}.electrical_type`, PIN_TYPES),
    voltage_limits: limits as [number, number],
  };
}

export function parsePartDefinition(x: unknown, path = "part"): PartDefinition {
  const o = record(x, path, [
    "part_id", "dimensions_mm", "mass_g", "bounding_box_type", "mesh_data", "mating_connectors", "electrical_pins",
  ]);
  const d = record(o.dimensions_mm, `${path}.dimensions_mm`, ["x", "y", "z"]);
  const m = record(o.mesh_data, `${path}.mesh_data`, ["glb_url", "collision_margin_mm"]);
  const margin = finite(m.collision_margin_mm, `${path}.mesh_data.collision_margin_mm`);
  if (margin < 0) throw new SchemaError(`${path}.mesh_data.collision_margin_mm`, "must not be negative");
  const connectors = list(o.mating_connectors, `${path}.mating_connectors`).map((c, i) => parseConnector(c, `${path}.mating_connectors[${i}]`));
  const pins = list(o.electrical_pins, `${path}.electrical_pins`).map((p, i) => parsePin(p, `${path}.electrical_pins[${i}]`));
  unique(connectors.map((c) => c.node_id), `${path}.mating_connectors`, "node_id");
  unique(pins.map((p) => String(p.pin_number)), `${path}.electrical_pins`, "pin_number");
  unique(pins.map((p) => p.label), `${path}.electrical_pins`, "label");
  return {
    part_id: text(o.part_id, `${path}.part_id`),
    dimensions_mm: { x: positive(d.x, `${path}.dimensions_mm.x`), y: positive(d.y, `${path}.dimensions_mm.y`), z: positive(d.z, `${path}.dimensions_mm.z`) },
    mass_g: positive(o.mass_g, `${path}.mass_g`),
    bounding_box_type: oneOf(o.bounding_box_type, `${path}.bounding_box_type`, ["OBB"] as const),
    mesh_data: { glb_url: text(m.glb_url, `${path}.mesh_data.glb_url`), collision_margin_mm: margin },
    mating_connectors: connectors,
    electrical_pins: pins,
  };
}

/** A catalogue of part definitions, keyed by part_id (each id once). */
export function parseCatalogue(x: unknown, path = "parts"): Map<string, PartDefinition> {
  const parts = list(x, path).map((p, i) => parsePartDefinition(p, `${path}[${i}]`));
  unique(parts.map((p) => p.part_id), path, "part_id");
  return new Map(parts.map((p) => [p.part_id, p]));
}

export function parsePlacedPart(x: unknown, catalogue: Map<string, PartDefinition>, path = "placed_part"): PlacedPart {
  const o = record(x, path, ["instance_id", "part_id", "world_position_mm", "world_quaternion"]);
  const partId = text(o.part_id, `${path}.part_id`);
  if (!catalogue.has(partId)) throw new SchemaError(`${path}.part_id`, `"${partId}" is not in the part catalogue`);
  const q = tuple(o.world_quaternion, `${path}.world_quaternion`, 4);
  unit(q, `${path}.world_quaternion`);
  return {
    instance_id: text(o.instance_id, `${path}.instance_id`),
    part_id: partId,
    world_position_mm: tuple(o.world_position_mm, `${path}.world_position_mm`, 3) as Vec3,
    world_quaternion: q as Quat,
  };
}

/** A project, checked against the catalogue: every part known, every instance once, and every
    net naming pins that exist on the instances it connects. */
export function parseProjectState(x: unknown, catalogue: Map<string, PartDefinition>, path = "project_state"): ProjectState {
  const o = record(x, path, ["placed_parts", "wire_nets"]);
  const placed = list(o.placed_parts, `${path}.placed_parts`).map((p, i) => parsePlacedPart(p, catalogue, `${path}.placed_parts[${i}]`));
  unique(placed.map((p) => p.instance_id), `${path}.placed_parts`, "instance_id");
  const byId = new Map(placed.map((p) => [p.instance_id, p]));
  const nets = list(o.wire_nets, `${path}.wire_nets`).map((n, i) => {
    const np = `${path}.wire_nets[${i}]`;
    const no = record(n, np, ["net_id", "connections"]);
    const connections = list(no.connections, `${np}.connections`).map((c, j) => {
      const cp = `${np}.connections[${j}]`;
      const co = record(c, cp, ["part_instance", "pin_label"]);
      const inst = text(co.part_instance, `${cp}.part_instance`);
      const label = text(co.pin_label, `${cp}.pin_label`);
      const placedPart = byId.get(inst);
      if (!placedPart) throw new SchemaError(`${cp}.part_instance`, `"${inst}" is not a placed part`);
      const def = catalogue.get(placedPart.part_id)!;
      if (!def.electrical_pins.some((p) => p.label === label)) {
        throw new SchemaError(`${cp}.pin_label`, `"${inst}" (${def.part_id}) has no pin "${label}"`);
      }
      return { part_instance: inst, pin_label: label };
    });
    if (connections.length < 2) throw new SchemaError(`${np}.connections`, "a net connects at least two pins");
    return { net_id: text(no.net_id, `${np}.net_id`), connections };
  });
  unique(nets.map((n) => n.net_id), `${path}.wire_nets`, "net_id");
  return { placed_parts: placed, wire_nets: nets };
}

// ------------------------------------------------------------------ the pin table
/** One row per electrical pin of every placed part, in a fixed order (parts as placed, pins as
    defined): a pin's row is its index in the simulation bridge's pin arrays. */
export interface PinRow {
  index: number;
  instance_id: string;
  pin_number: number;
  label: string;
  electrical_type: PinType;
  voltage_limits: [number, number];
}

export function pinTable(project: ProjectState, catalogue: Map<string, PartDefinition>): PinRow[] {
  const rows: PinRow[] = [];
  for (const p of project.placed_parts) {
    for (const pin of catalogue.get(p.part_id)!.electrical_pins) {
      rows.push({
        index: rows.length, instance_id: p.instance_id, pin_number: pin.pin_number, label: pin.label,
        electrical_type: pin.electrical_type, voltage_limits: pin.voltage_limits,
      });
    }
  }
  return rows;
}

/** The row of a pin, by its instance and label; -1 when there is none. */
export function pinIndex(rows: PinRow[], instance: string, label: string): number {
  const r = rows.find((x) => x.instance_id === instance && x.label === label);
  return r ? r.index : -1;
}
