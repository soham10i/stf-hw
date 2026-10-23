// The physics of the precision engine, independent of any thread (Deliverable 2). physics.worker.ts
// runs it in a worker at a fixed 100 Hz; the tests run it directly. One call to `stepOnce()` is
// one 10 ms step, and nothing in it reads a clock: given the same world and the same commands at
// the same steps, two runs end in bit-identical states (Rapier's deterministic build; our own
// arithmetic is float64 in a fixed order).
//
// Units are the factory's: millimetres, the z axis up, mass in kg (the schema's grams / 1000).
// Rapier works in those units directly (lengthUnit = 1000 per metre).
//
// What moves what:
// - fixed parts stay where they are placed;
// - kinematic parts follow their joints - planned tracks in SIMULATION_MODE, the live factory's
//   joint_angles in LIVE_TELEMETRY_MODE - composed along their parent chain in float64, and that
//   float64 pose is what is published (Rapier gets it too, as float32, to push what they touch);
// - dynamic parts (cookies, boxes) are Rapier's: gravity, contacts, friction;
// - a conveyor carries what lies on it: each step, a body touching its top has its velocity
//   relative to the belt reduced by at most mu * g * dt (Coulomb friction, the belt never slips
//   faster than friction allows), and the belt's collider itself has no friction, so this model
//   is the only one acting along the belt;
// - a sensor volume (light barrier) drives its pin high while a dynamic body is inside it; in
//   live mode the factory's sensor_states drive the pins instead.
import type RAPIER_NS from "@dimforge/rapier3d-deterministic-compat";

import { applyFaults, NetlistSolver, type Contact, type Diagnostic } from "../circuit/NetlistSolver";
import { compose, invert, IDENTITY, lerp, qaxis, rotate, type Pose } from "../core/math64";
import {
  parseProjectState, pinIndex, pinTable, type PartDefinition, type PinRow, type PlacedPart, type Quat, type Vec3, type WireNet,
} from "../core/schema";
import {
  FLAG_RUNNING, FLAG_TELEMETRY_STALE, H, MODE_LIVE_TELEMETRY, MODE_SIMULATION, PIN_FORCED, PIN_HIGH,
  PIN_TELEMETRY, S, TRANSFORM_STRIDE, type BridgeWriter,
} from "../core/SimulationBridge";
import { planMove, sampleMove, type SMove } from "./scurve";
import type { AxisCommand, AxisMotor, AxisSwitch, BodyRole, JointBinding, JointDrive, JointTrack, Mode, TelemetrySample, WorldInit } from "./protocol";
import { FT_ENCODER_MOTOR, newMotor, scan, stepMotor, switchState, TAU, type MotorSpec, type MotorState, type Task } from "./motors";
import { AX, AXIS_STRIDE, TASKS } from "../core/SimulationBridge";

type Rapier = typeof RAPIER_NS;
type World = InstanceType<Rapier["World"]>;
type RigidBody = ReturnType<World["createRigidBody"]>;
type Collider = ReturnType<World["createCollider"]>;

export const FIXED_DT = 0.01;
export const GRAVITY_MM_S2: Vec3 = [0, 0, -9810];
const DEFAULT_PLAYOUT_MS = 100;
const DEFAULT_SENSOR_VOLTS = 24;
const MAX_TELEMETRY = 4096; // samples kept

export class WorldError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "WorldError";
  }
}

interface Entry {
  inst: PlacedPart;
  def: PartDefinition;
  role: BodyRole;
  body: RigidBody;
  collider: Collider;
  base: Pose; // where it is placed
  pose: Pose; // the master pose, float64
  speed: number; // conveyors: the belt speed now, mm/s
}

/** Commands are queued and applied at the start of the next step, in the order they came, so a
    run is reproduced by the same commands at the same steps. */
export type Command =
  | { type: "mode"; mode: Mode }
  | { type: "telemetry"; samples: TelemetrySample[] }
  | { type: "spawn"; part: PlacedPart; role: BodyRole }
  | { type: "remove"; instance_id: string }
  | { type: "conveyor"; instance_id: string; speed_mm_s: number }
  | { type: "input"; pin: number; volts: number | null }
  | { type: "nets"; wire_nets: WireNet[] }
  | { type: "contact"; contact: Contact }
  | { type: "target"; joint: number; value: number }
  | { type: "pulse"; joint: number; value: number; hold_s: number }
  | { type: "axis"; id: string; command: AxisCommand };

/** A motor axis at run time. */
interface AxisRun {
  cfg: AxisMotor;
  spec: MotorSpec;
  motor: MotorState;
  task: Task;
  /** switch pins: [reference, ...switches]; -1 where there is none */
  pins: number[];
  closed: boolean[];
  zero: number; // the raw count at the reference (the count reads 0 there)
  homed: boolean;
  lastError: number; // the last move's final error, in the joint's unit (NaN: none yet)
  crashes: number;
  steps: number;
  /** the switch an "until" task drives to: its index in [reference, ...switches] */
  untilSwitch: number;
}

/** A driven joint's state: where it is, how fast, where it is going, and a stroke in progress. */
interface DriveState {
  cfg: JointDrive;
  pos: number;
  vel: number;
  /** acceleration (S-curve drives; 0 on a trapezoid) */
  acc: number;
  target: number;
  /** the S-curve move under way, and the time into it */
  move: SMove | null;
  moveT: number;
  pulse: { home: number; holdSteps: number; phase: "out" | "hold" | "back" } | null;
}

/** One fixed step of a trapezoidal move: accelerate at most `amax`, never faster than `vmax`, and
    never faster than lets it brake to a stop on the target - which it then lands on exactly. */
export function driveStep(pos: number, vel: number, target: number, vmax: number, amax: number, dt: number): [number, number] {
  const dx = target - pos;
  if (dx === 0 && vel === 0) return [pos, 0];
  const dir = Math.sign(dx);
  // the fastest speed from which the remaining distance still brakes to zero, a step at a time:
  // braking from k * amax * dt covers amax * dt^2 * k (k + 1) / 2, solved for k
  const a = amax * dt;
  const vStop = a * (Math.sqrt(0.25 + (2 * Math.abs(dx)) / (a * dt)) - 0.5);
  const want = dir * Math.min(vmax, vStop);
  const dv = Math.max(-amax * dt, Math.min(amax * dt, want - vel));
  const v = vel + dv;
  const next = pos + v * dt;
  // arrived, or would pass it: stop on the target
  if ((target - next) * dir <= 0 || Math.abs(target - next) < 1e-9) return [target, 0];
  return [next, v];
}

const SAMPLE: [number, number, number] = [0, 0, 0];
/** One fixed step of an S-curve drive: a move is planned when the drive is at rest away from its
    target, then followed to its end, landing exactly on it; a target changed meanwhile is the
    next move's (buffered). */
export function sCurveStep(d: { pos: number; vel: number; acc: number; target: number; move: SMove | null; moveT: number;
  cfg: { vmax: number; amax: number; jmax?: number } }, dt: number): void {
  if (!d.move) {
    if (d.pos === d.target) { d.vel = 0; d.acc = 0; return; }
    d.move = planMove(d.pos, d.target, d.cfg.vmax, d.cfg.amax, d.cfg.jmax!);
    d.moveT = 0;
  }
  d.moveT += dt;
  sampleMove(d.move, d.moveT, SAMPLE);
  [d.pos, d.vel, d.acc] = SAMPLE;
  if (d.moveT >= d.move.T) d.move = null;
}

const posePlaced = (p: PlacedPart): Pose => ({ p: [...p.world_position_mm] as Vec3, q: [...p.world_quaternion] as Quat });
const toRapierV = (v: Vec3) => ({ x: v[0], y: v[1], z: v[2] });
const toRapierQ = (q: Quat) => ({ x: q[0], y: q[1], z: q[2], w: q[3] });
/** a switch on an axis (one with `at` and `toward`) as motors.ts reads it */
const limitSwitch = (s: AxisSwitch) => ({ at: s.at!, toward: s.toward!, hysteresis: s.hysteresis ?? 0.5 });

/** Validates a sample from the outside world (the WebSocket): finite numbers, nothing else. */
export function parseTelemetrySample(x: unknown): TelemetrySample {
  if (typeof x !== "object" || x === null) throw new WorldError("a telemetry sample must be an object");
  const o = x as Record<string, unknown>;
  for (const k of Object.keys(o)) if (!["timestamp", "joint_angles", "sensor_states"].includes(k)) throw new WorldError(`telemetry: unknown field "${k}"`);
  const num = (v: unknown, what: string) => {
    if (typeof v !== "number" || !Number.isFinite(v)) throw new WorldError(`telemetry: ${what} must be a finite number`);
    return v;
  };
  const arr = (v: unknown, what: string) => {
    if (!Array.isArray(v)) throw new WorldError(`telemetry: ${what} must be an array`);
    return v.map((e, i) => num(e, `${what}[${i}]`));
  };
  return { timestamp: num(o.timestamp, "timestamp"), joint_angles: arr(o.joint_angles, "joint_angles"), sensor_states: arr(o.sensor_states, "sensor_states") };
}

/** A track's value at time t: linear between keys, held before the first and after the last. */
export function trackValue(track: JointTrack, t: number): number {
  const { times_s: ts, values: vs } = track;
  if (t <= ts[0]) return vs[0];
  const n = ts.length - 1;
  if (t >= ts[n]) return vs[n];
  let lo = 0;
  let hi = n;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (ts[mid] <= t) lo = mid;
    else hi = mid;
  }
  return lerp(vs[lo], vs[hi], (t - ts[lo]) / (ts[hi] - ts[lo]));
}

/** A pin reads high: 24 V digital pins by IEC 61131-2 type 1 (ON from 15 V); lower-voltage pins
    from half their maximum. */
export function logicHigh(volts: number, limits: [number, number]): boolean {
  return limits[1] >= 24 ? volts >= 15 : volts >= limits[1] / 2;
}

export class PhysicsCore {
  readonly world: World;
  readonly pins: PinRow[];
  readonly pinVolts: Float64Array;
  readonly pinFlags: Int32Array;
  readonly partCapacity: number;
  mode: Mode = "SIMULATION_MODE";
  step = 0;
  running = false;
  rate = 1;

  private readonly R: Rapier;
  private readonly catalogue: Map<string, PartDefinition>;
  private entries: Entry[] = [];
  private readonly byId = new Map<string, Entry>();
  private readonly byCollider = new Map<number, Entry>();
  private readonly bindings: JointBinding[];
  private readonly tracks = new Map<number, JointTrack>();
  private readonly chainRel = new Map<string, Pose>(); // base of child relative to base of parent
  private readonly order: string[]; // bound instances, parents first
  private readonly sensorPins = new Map<Entry, number>();
  private readonly telemetryPins: number[];
  private readonly forced = new Map<number, number>();
  private readonly playoutMs: number;
  private readonly g: number; // |gravity|, mm/s^2
  private readonly bindingsOf = new Map<string, JointBinding[]>();
  private playoutT: number | null = null; // the factory time (ms) the current step plays
  private telemetry: TelemetrySample[] = [];
  private playoutT0: number | null = null; // the factory time (ms) at liveStartStep
  private liveStartStep = 0;
  private telemetryStale = false;
  private joints: Float64Array;
  private queue: Command[] = [];
  private partsChanged = false;
  private readonly drives = new Map<number, DriveState>();
  private readonly axes: AxisRun[] = [];
  /** the live netlist, checked after every step (circuit/NetlistSolver.ts) */
  readonly circuit: NetlistSolver;
  private readonly placedAtStart: PlacedPart[];
  diagnostics: Diagnostic[] = [];
  private circuitKey = "";
  private circuitChanged = false;

  private constructor(R: Rapier, init: WorldInit) {
    this.R = R;
    this.catalogue = new Map(init.parts.map((p) => [p.part_id, p]));
    const gravity = init.gravity_mm_s2 ?? GRAVITY_MM_S2;
    this.g = Math.hypot(...gravity);
    this.world = new R.World(toRapierV(gravity));
    this.world.lengthUnit = 1000; // millimetres
    this.world.timestep = FIXED_DT;
    this.playoutMs = init.playout_delay_ms ?? DEFAULT_PLAYOUT_MS;
    this.partCapacity = init.project.placed_parts.length + (init.extra_part_capacity ?? 64);

    this.pins = pinTable(init.project, this.catalogue);
    this.pinVolts = new Float64Array(this.pins.length);
    this.pinFlags = new Int32Array(this.pins.length);
    this.circuit = new NetlistSolver(init.project, this.catalogue, init.supplies ?? [], init.contacts ?? []);
    this.placedAtStart = init.project.placed_parts;

    for (const inst of init.project.placed_parts) {
      const role = init.roles[inst.instance_id];
      if (!role) throw new WorldError(`"${inst.instance_id}" has no physics role`);
      this.add(inst, role);
    }

    // joints: each bound part must be kinematic; parents resolve before children
    this.bindings = [...(init.bindings ?? [])];
    for (const b of this.bindings) {
      const e = this.byId.get(b.instance_id);
      if (!e) throw new WorldError(`joint ${b.joint}: "${b.instance_id}" is not placed`);
      if (e.role.kind !== "kinematic") throw new WorldError(`joint ${b.joint}: "${b.instance_id}" must be kinematic to follow a joint`);
      if (b.parent) {
        const p = this.byId.get(b.parent);
        if (!p) throw new WorldError(`joint ${b.joint}: parent "${b.parent}" is not placed`);
        if (p.role.kind !== "kinematic") throw new WorldError(`joint ${b.joint}: parent "${b.parent}" must be kinematic`);
        this.chainRel.set(b.instance_id, compose(invert(p.base), e.base));
      }
      if (b.type === "rigid" && !b.parent) throw new WorldError(`"${b.instance_id}": a rigid binding rides on a parent`);
      if (Math.abs(Math.hypot(...b.axis_local) - 1) > 1e-9) throw new WorldError(`joint ${b.joint}: axis_local must have length 1`);
      if (b.type === "prismatic" && b.unit !== "mm") throw new WorldError(`prismatic joint ${b.joint} must be in mm`);
      if (b.type === "revolute" && b.unit === "mm") throw new WorldError(`revolute joint ${b.joint} must be in deg or rad`);
      this.bindingsOf.set(b.instance_id, [...(this.bindingsOf.get(b.instance_id) ?? []), b]);
    }
    this.order = this.chainOrder();
    const nJoints = this.bindings.reduce((m, b) => Math.max(m, b.joint + 1), 0);
    this.joints = new Float64Array(nJoints);
    for (const t of init.tracks ?? []) {
      if (t.times_s.length === 0 || t.times_s.length !== t.values.length) throw new WorldError(`track ${t.joint}: times and values must be non-empty and equal in length`);
      for (let i = 1; i < t.times_s.length; i++) if (!(t.times_s[i] > t.times_s[i - 1])) throw new WorldError(`track ${t.joint}: times must increase`);
      this.tracks.set(t.joint, t);
    }
    for (const d of init.drives ?? []) {
      if (d.joint < 0 || d.joint >= nJoints) throw new WorldError(`drive on joint ${d.joint}: no part is bound to it`);
      if (!(d.vmax > 0 && d.amax > 0)) throw new WorldError(`drive on joint ${d.joint}: vmax and amax must be greater than 0`);
      if (d.jmax !== undefined && !(d.jmax >= 0)) throw new WorldError(`drive on joint ${d.joint}: jmax must be 0 or more`);
      if (this.drives.has(d.joint)) throw new WorldError(`joint ${d.joint} has two drives`);
      const start = d.start ?? 0;
      this.drives.set(d.joint, { cfg: d, pos: start, vel: 0, acc: 0, target: start, move: null, moveT: 0, pulse: null });
      this.joints[d.joint] = start;
    }
    for (const a of init.axes ?? []) {
      if (a.belt !== undefined) {
        const e = this.byId.get(a.belt);
        if (!e || e.role.kind !== "conveyor") throw new WorldError(`axis "${a.id}": "${a.belt}" is not a conveyor`);
        if (a.joint !== -1) throw new WorldError(`axis "${a.id}" drives a belt: its joint must be -1`);
        if (this.axes.some((x) => x.cfg.belt === a.belt)) throw new WorldError(`belt "${a.belt}" has two motors`);
        if (a.reference) throw new WorldError(`axis "${a.id}" drives a belt: a belt has no reference to home to`);
      } else {
        if (a.joint < 0 || a.joint >= nJoints) throw new WorldError(`axis "${a.id}": no part is bound to joint ${a.joint}`);
        if (this.drives.has(a.joint) || this.axes.some((x) => x.cfg.joint === a.joint)) throw new WorldError(`joint ${a.joint} has two drives`);
      }
      if (!(a.perRev > 0)) throw new WorldError(`axis "${a.id}": perRev must be greater than 0`);
      const sw = [a.reference, ...(a.switches ?? [])];
      const pins = sw.map((s, i) => {
        if (!s) return -1;
        const k = pinIndex(this.pins, s.pin.part_instance, s.pin.pin_label);
        if (k < 0) throw new WorldError(`axis "${a.id}" switch ${i}: no pin "${s.pin.pin_label}" on "${s.pin.part_instance}"`);
        if ((s.at === undefined) !== (s.toward === undefined)) throw new WorldError(`axis "${a.id}" switch ${i}: give both "at" and "toward", or neither (a sensor)`);
        if (i === 0 && s.at === undefined) throw new WorldError(`axis "${a.id}": its reference must be a switch on the axis, not a sensor`);
        return k;
      });
      this.axes.push({
        cfg: a, spec: a.motor ?? FT_ENCODER_MOTOR, motor: newMotor(), task: { kind: "idle" }, pins,
        closed: sw.map((s) => !!s && s.at !== undefined && switchState(limitSwitch(s), a.start, false)),
        zero: 0, homed: false, lastError: Number.NaN, crashes: 0, steps: 0, untilSwitch: 0,
      });
      if (a.belt === undefined) this.joints[a.joint] = a.start;
    }
    this.telemetryPins = (init.telemetry_sensors ?? []).map((r, i) => {
      const k = pinIndex(this.pins, r.part_instance, r.pin_label);
      if (k < 0) throw new WorldError(`telemetry sensor ${i}: no pin "${r.pin_label}" on "${r.part_instance}"`);
      return k;
    });
    this.updateKinematics(); // the first published state is the placed one, with joints at t = 0
    this.checkCircuit();
  }

  /** Builds the world. `R` must already be initialised (`await R.init()`). */
  static create(R: Rapier, init: WorldInit): PhysicsCore {
    return new PhysicsCore(R, init);
  }

  // ---------------------------------------------------------------- building
  private add(inst: PlacedPart, role: BodyRole): Entry {
    if (this.byId.has(inst.instance_id)) throw new WorldError(`"${inst.instance_id}" is placed twice`);
    if (this.entries.length >= this.partCapacity) throw new WorldError(`no room for "${inst.instance_id}": ${this.partCapacity} parts`);
    const def = this.catalogue.get(inst.part_id);
    if (!def) throw new WorldError(`"${inst.part_id}" is not in the catalogue`);
    const R = this.R;
    const base = posePlaced(inst);
    const desc =
      role.kind === "dynamic" ? R.RigidBodyDesc.dynamic().setCcdEnabled(true)
        : role.kind === "kinematic" ? R.RigidBodyDesc.kinematicPositionBased()
          : R.RigidBodyDesc.fixed();
    desc.setTranslation(base.p[0], base.p[1], base.p[2]).setRotation(toRapierQ(base.q));
    const body = this.world.createRigidBody(desc);
    const { x, y, z } = def.dimensions_mm;
    const cd = R.ColliderDesc.cuboid(x / 2, y / 2, z / 2).setContactSkin(def.mesh_data.collision_margin_mm);
    if (role.kind === "dynamic") {
      cd.setMass(def.mass_g / 1000).setFriction(role.friction ?? 0.5).setRestitution(role.restitution ?? 0.1);
    } else if (role.kind === "fixed" && role.friction !== undefined) {
      // a ceiling on the contact's friction: the lower of the two surfaces' values counts
      cd.setFriction(role.friction).setFrictionCombineRule(R.CoefficientCombineRule.Min);
    } else if (role.kind === "conveyor") {
      // the belt's carrying force is modelled in stepConveyors; the collider only supports
      cd.setFriction(0).setFrictionCombineRule(R.CoefficientCombineRule.Min);
    } else if (role.kind === "sensor") {
      cd.setSensor(true).setActiveCollisionTypes(R.ActiveCollisionTypes.DEFAULT | R.ActiveCollisionTypes.KINEMATIC_FIXED);
    }
    const collider = this.world.createCollider(cd, body);
    const e: Entry = { inst, def, role, body, collider, base, pose: { p: [...base.p] as Vec3, q: [...base.q] as Quat }, speed: role.kind === "conveyor" ? role.speed_mm_s : 0 };
    this.entries.push(e);
    this.byId.set(inst.instance_id, e);
    this.byCollider.set(collider.handle, e);
    if (role.kind === "sensor") {
      const k = pinIndex(this.pins, role.pin.part_instance, role.pin.pin_label);
      if (k < 0) throw new WorldError(`sensor "${inst.instance_id}": no pin "${role.pin.pin_label}" on "${role.pin.part_instance}"`);
      this.sensorPins.set(e, k);
    }
    this.partsChanged = true;
    return e;
  }

  private remove(id: string): void {
    const e = this.byId.get(id);
    if (!e) return;
    if (e.role.kind !== "dynamic") throw new WorldError(`only spawned (dynamic) parts can be removed, not "${id}"`);
    this.world.removeRigidBody(e.body);
    this.byId.delete(id);
    this.byCollider.delete(e.collider.handle);
    this.entries = this.entries.filter((x) => x !== e);
    this.partsChanged = true;
  }

  /** The bound instances, every parent before its children; a cycle is an error. */
  private chainOrder(): string[] {
    const parentOf = new Map<string, string | undefined>();
    for (const b of this.bindings) {
      const prev = parentOf.get(b.instance_id);
      if (prev !== undefined && b.parent !== undefined && prev !== b.parent) throw new WorldError(`"${b.instance_id}" has two parents`);
      parentOf.set(b.instance_id, b.parent ?? prev);
    }
    const out: string[] = [];
    const state = new Map<string, 1 | 2>();
    const visit = (id: string) => {
      if (state.get(id) === 2) return;
      if (state.get(id) === 1) throw new WorldError(`joint chain through "${id}" is a cycle`);
      state.set(id, 1);
      const p = parentOf.get(id);
      if (p !== undefined && parentOf.has(p)) visit(p);
      state.set(id, 2);
      out.push(id);
    };
    for (const id of parentOf.keys()) visit(id);
    return out;
  }

  // ---------------------------------------------------------------- commands
  enqueue(cmd: Command): void {
    this.queue.push(cmd);
  }

  private apply(cmd: Command): void {
    switch (cmd.type) {
      case "mode":
        if (cmd.mode === this.mode) return;
        this.mode = cmd.mode;
        if (cmd.mode === "LIVE_TELEMETRY_MODE") {
          this.liveStartStep = this.step;
          this.playoutT0 = null;
        }
        return;
      case "telemetry":
        for (const s of cmd.samples) this.telemetry.push(s);
        this.telemetry.sort((a, b) => a.timestamp - b.timestamp);
        if (this.telemetry.length > MAX_TELEMETRY) this.telemetry.splice(0, this.telemetry.length - MAX_TELEMETRY);
        return;
      case "spawn":
        if (cmd.role.kind !== "dynamic") throw new WorldError("only dynamic parts can be spawned");
        if (this.catalogue.get(cmd.part.part_id)?.electrical_pins.length) throw new WorldError(`"${cmd.part.part_id}" has pins: spawned parts cannot carry pins`);
        this.add(cmd.part, cmd.role);
        return;
      case "remove":
        this.remove(cmd.instance_id);
        return;
      case "conveyor": {
        const e = this.byId.get(cmd.instance_id);
        if (!e || e.role.kind !== "conveyor") throw new WorldError(`"${cmd.instance_id}" is not a conveyor`);
        const motor = this.axes.find((a) => a.cfg.belt === cmd.instance_id);
        if (motor) throw new WorldError(`"${cmd.instance_id}" is driven by its motor: command axis "${motor.cfg.id}"`);
        if (!Number.isFinite(cmd.speed_mm_s)) throw new WorldError("a belt speed must be finite");
        e.speed = cmd.speed_mm_s;
        return;
      }
      case "input":
        if (cmd.pin < 0 || cmd.pin >= this.pins.length) throw new WorldError(`input pin ${cmd.pin} does not exist`);
        if (cmd.volts === null) this.forced.delete(cmd.pin);
        else this.forced.set(cmd.pin, cmd.volts);
        return;
      case "nets":
        // checked like the project itself: every net names pins its parts have
        this.circuit.setNets(parseProjectState({ placed_parts: this.placedAtStart, wire_nets: cmd.wire_nets }, this.catalogue).wire_nets);
        return;
      case "contact":
        this.circuit.setContact(cmd.contact);
        return;
      case "axis":
        this.commandAxis(cmd.id, cmd.command);
        return;
      case "target":
      case "pulse": {
        const d = this.drives.get(cmd.joint);
        if (!d) throw new WorldError(`joint ${cmd.joint} has no drive`);
        if (!Number.isFinite(cmd.value)) throw new WorldError("a target must be finite");
        const lim = d.cfg.limits;
        const value = lim ? Math.min(lim[1], Math.max(lim[0], cmd.value)) : cmd.value;
        if (cmd.type === "target") {
          d.target = value;
          d.pulse = null;
        } else {
          if (!(cmd.hold_s >= 0)) throw new WorldError("a stroke's hold must be 0 s or more");
          d.pulse = { home: d.pulse ? d.pulse.home : d.target, holdSteps: Math.round(cmd.hold_s / FIXED_DT), phase: "out" };
          d.target = value;
        }
        return;
      }
    }
  }

  // ---------------------------------------------------------------- one step
  get simTime(): number {
    return this.step * FIXED_DT; // from the integer step: no accumulated rounding
  }

  /** Applies the queued commands now, without stepping (a paused world still takes a spawn or a
      belt speed); a running world applies them at the start of its next step. Either way they
      fall between the same two steps. */
  flush(): void {
    const q = this.queue;
    this.queue = [];
    // every command is tried; one that is refused (an axis not homed yet) is reported after the
    // rest are applied, and leaves the world running
    let refused: unknown = null;
    for (const c of q) {
      try {
        this.apply(c);
      } catch (e) {
        refused ??= e;
      }
    }
    if (q.some((c) => c.type === "input" || c.type === "nets" || c.type === "contact")) this.updatePins();
    if (refused) throw refused;
  }

  /** One fixed 10 ms step. */
  stepOnce(): void {
    this.flush();

    this.updateJointValues();
    this.updateKinematics();
    this.stepConveyors();
    this.world.step();
    this.step += 1;
    this.readDynamics();
    this.updatePins();
  }

  /** The joint values for the coming step: the plan, or the live factory. */
  private updateJointValues(): void {
    const t = (this.step + 1) * FIXED_DT; // the time the step ends at: where kinematic bodies arrive
    if (this.mode === "SIMULATION_MODE") {
      for (const [j, track] of this.tracks) if (j < this.joints.length && !this.drives.has(j)) this.joints[j] = trackValue(track, t);
      for (const [j, d] of this.drives) {
        if (d.cfg.jmax) sCurveStep(d, FIXED_DT);
        else [d.pos, d.vel] = driveStep(d.pos, d.vel, d.target, d.cfg.vmax, d.cfg.amax, FIXED_DT);
        const p = d.pulse;
        if (p && d.pos === d.target && d.vel === 0) {
          if (p.phase === "out") p.phase = "hold";
          if (p.phase === "hold") {
            if (p.holdSteps > 0) p.holdSteps--;
            else {
              p.phase = "back";
              d.target = p.home;
            }
          } else if (p.phase === "back") d.pulse = null;
        }
        this.joints[j] = d.pos;
      }
      for (const a of this.axes) this.stepAxis(a);
      this.telemetryStale = false;
      return;
    }
    const s = this.telemetry;
    if (s.length === 0) {
      this.telemetryStale = true;
      this.playoutT = null;
      return;
    }
    const newest = s[s.length - 1].timestamp;
    // the playout clock starts one delay behind the newest sample, then advances with the steps;
    // if the factory runs ahead by more than two delays (a stall), it jumps to catch up
    if (this.playoutT0 === null) this.playoutT0 = newest - this.playoutMs;
    let T = this.playoutT0 + (this.step + 1 - this.liveStartStep) * FIXED_DT * 1000;
    if (newest - T > 2 * this.playoutMs) {
      this.playoutT0 += newest - this.playoutMs - T;
      T = newest - this.playoutMs;
    }
    this.playoutT = T;
    let i = s.length - 1;
    while (i > 0 && s[i].timestamp > T) i--;
    const a = s[i];
    const b = s[Math.min(i + 1, s.length - 1)];
    this.telemetryStale = T > newest || T < s[0].timestamp;
    const k = b.timestamp > a.timestamp ? Math.min(1, Math.max(0, (T - a.timestamp) / (b.timestamp - a.timestamp))) : 0;
    for (let j = 0; j < this.joints.length; j++) {
      const va = a.joint_angles[j];
      const vb = b.joint_angles[j];
      if (va === undefined) continue;
      this.joints[j] = vb === undefined ? va : lerp(va, vb, k);
    }
    // samples before the bracket are no longer needed
    if (i > 1) this.telemetry.splice(0, i - 1);
  }

  // ---------------------------------------------------------------- motor axes
  private axisValue(a: AxisRun): number {
    return a.cfg.start + (a.motor.angle / TAU) * a.cfg.perRev;
  }

  private rawCount(a: AxisRun): number {
    return a.cfg.pulsesPerRev ? Math.floor((a.motor.angle / TAU) * a.cfg.pulsesPerRev) : 0;
  }

  /** The count the PLC reads: whole pulses since the reference. */
  private count(a: AxisRun): number {
    return this.rawCount(a) - a.zero;
  }

  private commandAxis(id: string, c: AxisCommand): void {
    const a = this.axes.find((x) => x.cfg.id === id);
    if (!a) throw new WorldError(`no axis "${id}"`);
    switch (c.kind) {
      case "stop":
        a.task = { kind: "idle" };
        return;
      case "jog":
        a.task = { kind: "jog", dir: c.dir };
        return;
      case "home": {
        const ref = a.cfg.reference;
        if (!ref) throw new WorldError(`axis "${id}" has no reference switch`);
        a.task = { kind: "home", dir: ref.toward === "up" ? 1 : -1, leave: a.closed[0], creep: a.cfg.homeCreepV !== undefined };
        return;
      }
      case "until": {
        if (!a.cfg.switches?.[c.switch]) throw new WorldError(`axis "${id}" has no switch ${c.switch}`);
        a.task = { kind: "until", dir: c.dir };
        a.untilSwitch = c.switch + 1;
        return;
      }
      case "move": {
        const ref = a.cfg.reference;
        const ppr = a.cfg.pulsesPerRev;
        if (!ref || !ppr) throw new WorldError(`axis "${id}" has no encoder and reference to position by`);
        if (!a.homed) throw new WorldError(`axis "${id}" is not homed: home it first`);
        if (!Number.isFinite(c.target)) throw new WorldError("a target must be finite");
        // the PLC's calibration: the count is 0 at the reference switch's point
        const target = Math.round(((c.target - ref.at!) * ppr) / a.cfg.perRev); // a reference always has `at` (checked at build)
        a.task = { kind: "move", target, lead: a.cfg.brakeLeadCounts ?? 1 };
        a.steps = 0;
        return;
      }
    }
  }

  /** One scan of the axis's positioning block, then one step of its motor. */
  private stepAxis(a: AxisRun): void {
    // the sensors it waits on read as their pins do (a light barrier: high while cut)
    const sw = [a.cfg.reference, ...(a.cfg.switches ?? [])];
    sw.forEach((s, i) => {
      if (s && s.at === undefined) a.closed[i] = logicHigh(this.pinVolts[a.pins[i]], this.pins[a.pins[i]].voltage_limits);
    });
    const sensed = a.task.kind === "until" ? a.closed[a.untilSwitch] : a.closed[0];
    const before = a.task.kind;
    const { dir, next, slow } = scan(a.task, this.count(a), sensed, a.steps);
    a.task = next;
    a.steps++;
    if (before === "home" && next.kind === "done") {
      a.zero = this.rawCount(a); // the count reads 0 where the reference switch closed
      a.homed = true;
    }
    const volts = dir * (slow ? a.cfg.homeCreepV! : a.spec.ratedV);
    const hs = a.cfg.hardStop;
    const stop: [number, number] | undefined = hs && [((hs[0] - a.cfg.start) / a.cfg.perRev) * TAU, ((hs[1] - a.cfg.start) / a.cfg.perRev) * TAU];
    if (stepMotor(a.motor, a.spec, volts, FIXED_DT, stop).crashed) {
      a.crashes++;
      if (a.task.kind !== "idle" && a.task.kind !== "done") a.task = { kind: "idle" }; // a crash stops the block
    }
    // a finished move: its error once the axis is at rest
    if (a.task.kind === "done" && a.task.target !== null && a.motor.speed === 0 && Number.isNaN(a.task.error ?? Number.NaN)) {
      const errCounts = this.count(a) - a.task.target;
      a.task = { ...a.task, error: errCounts };
      a.lastError = (errCounts * a.cfg.perRev) / (a.cfg.pulsesPerRev ?? 1);
    }
    const v = this.axisValue(a);
    if (a.cfg.belt !== undefined) {
      // the belt's surface moves as the drum turns
      this.byId.get(a.cfg.belt)!.speed = (a.motor.speed / TAU) * a.cfg.perRev;
    } else this.joints[a.cfg.joint] = v;
    sw.forEach((s, i) => {
      if (s && s.at !== undefined) a.closed[i] = switchState(limitSwitch(s), v, a.closed[i]);
    });
  }

  /** An axis's state: position, speed, current, count, task, last error. */
  axis(id: string) {
    const a = this.axes.find((x) => x.cfg.id === id);
    if (!a) return undefined;
    return {
      position: this.axisValue(a), rpm: (a.motor.speed * 60) / TAU, current: a.motor.current, volts: a.motor.volts,
      count: this.count(a), homed: a.homed, task: a.task, lastError: a.lastError, crashes: a.crashes, closed: [...a.closed],
    };
  }

  get axisCount(): number {
    return this.axes.length;
  }

  /** Every bound part's world pose from its joints, in float64, parents first. */
  private updateKinematics(): void {
    const world = new Map<string, Pose>();
    for (const id of this.order) {
      const e = this.byId.get(id)!;
      const bs = this.bindingsOf.get(id)!;
      const parent = bs.find((b) => b.parent)?.parent;
      let pose = parent ? compose(world.get(parent) ?? this.byId.get(parent)!.pose, this.chainRel.get(id)!) : e.base;
      for (const b of bs) {
        if (b.type === "rigid") continue;
        const v = (this.joints[b.joint] ?? 0) + (b.offset ?? 0);
        const motion: Pose =
          b.type === "prismatic"
            ? { p: [b.axis_local[0] * v, b.axis_local[1] * v, b.axis_local[2] * v], q: IDENTITY.q }
            : { p: [0, 0, 0], q: qaxis(b.axis_local, b.unit === "deg" ? (v * Math.PI) / 180 : v) };
        pose = compose(pose, motion);
      }
      world.set(id, pose);
      e.pose = pose;
      e.body.setNextKinematicTranslation(toRapierV(pose.p));
      e.body.setNextKinematicRotation(toRapierQ(pose.q));
    }
  }

  /** Belts carry what lies on them, limited by friction. */
  private stepConveyors(): void {
    const g = this.g;
    for (const belt of this.entries) {
      if (belt.role.kind !== "conveyor") continue;
      const role = belt.role;
      const dir = rotate(belt.pose.q, role.direction_local);
      const n = rotate(belt.pose.q, [0, 0, 1]);
      const vb: Vec3 = [dir[0] * belt.speed, dir[1] * belt.speed, dir[2] * belt.speed];
      const mu = role.friction ?? 0.6;
      const maxDv = mu * g * FIXED_DT;
      this.world.contactPairsWith(belt.collider, (other) => {
        const e = this.byCollider.get(other.handle);
        if (!e || e.role.kind !== "dynamic") return;
        // lying on the belt: the solver is using a contact between them (a distance cut-off is
        // not enough - at mm scale Rapier rests bodies a fixed fraction of a mm apart)
        let touching = false;
        this.world.contactPair(belt.collider, other, (m) => {
          if (m.numSolverContacts() > 0) touching = true;
        });
        if (!touching) return;
        const v = e.body.linvel();
        // the relative velocity in the belt's plane
        const rx = v.x - vb[0];
        const ry = v.y - vb[1];
        const rz = v.z - vb[2];
        const dn = rx * n[0] + ry * n[1] + rz * n[2];
        const tx = rx - dn * n[0];
        const ty = ry - dn * n[1];
        const tz = rz - dn * n[2];
        const mag = Math.hypot(tx, ty, tz);
        if (mag === 0) return;
        const k = Math.min(1, maxDv / mag);
        e.body.setLinvel({ x: v.x - tx * k, y: v.y - ty * k, z: v.z - tz * k }, true);
      });
    }
  }

  /** Dynamic bodies' poses from Rapier (float32 widened to float64). */
  private readDynamics(): void {
    for (const e of this.entries) {
      if (e.role.kind !== "dynamic") continue;
      const t = e.body.translation();
      const r = e.body.rotation();
      e.pose = { p: [t.x, t.y, t.z], q: [r.x, r.y, r.z, r.w] };
    }
  }

  /** Sensors, the live factory and forced inputs set the pins, in that order of precedence. */
  private updatePins(): void {
    this.pinVolts.fill(0);
    this.pinFlags.fill(0);
    if (this.mode === "SIMULATION_MODE") {
      for (const [e, k] of this.sensorPins) {
        let occupied = false;
        this.world.intersectionPairsWith(e.collider, (other) => {
          if (this.byCollider.get(other.handle)?.role.kind === "dynamic") occupied = true;
        });
        const hi = e.role.kind === "sensor" ? (e.role.high_volts ?? DEFAULT_SENSOR_VOLTS) : DEFAULT_SENSOR_VOLTS;
        this.setPin(k, occupied ? hi : 0, 0);
      }
    } else {
      const s = this.telemetry;
      const T = this.playoutT;
      if (s.length && T !== null) {
        let i = s.length - 1;
        while (i > 0 && s[i].timestamp > T) i--;
        const states = s[i].sensor_states;
        this.telemetryPins.forEach((k, j) => {
          const v = states[j];
          if (v === undefined) return;
          const row = this.pins[k];
          // digital pins carry logic levels (0/1), analogue pins volts; a 24 V input reads 24 V
          const high = row.voltage_limits[1] >= 24 ? 24 : row.voltage_limits[1];
          const volts = row.electrical_type === "analog_in" ? v : v ? high : 0;
          this.setPin(k, volts, PIN_TELEMETRY);
        });
      }
    }
    // an axis drives its own switches' pins; the sensors it reads are driven by their volumes
    for (const a of this.axes) {
      const sw = [a.cfg.reference, ...(a.cfg.switches ?? [])];
      a.pins.forEach((k, i) => { if (k >= 0 && sw[i]!.at !== undefined) this.setPin(k, a.closed[i] ? 24 : 0, 0); });
    }
    for (const [k, v] of this.forced) this.setPin(k, v, PIN_FORCED);
    this.checkCircuit();
  }

  /** The circuit checks on this step's pins; the faulted pins are flagged for the renderer. A
      change of any status is noted for the worker to send (a status, not every step's volts). */
  private checkCircuit(): void {
    const ev = this.circuit.evaluate(this.pinVolts, this.pinFlags);
    applyFaults(this.pinFlags, ev.faultPins);
    const key = JSON.stringify(ev.diagnostics.map((d) => [d.status, d.netId, d.affectedInstances]));
    if (key !== this.circuitKey) {
      this.circuitKey = key;
      this.circuitChanged = true;
    }
    this.diagnostics = ev.diagnostics;
  }

  /** True once after a circuit status changed. */
  takeCircuitChanged(): boolean {
    const c = this.circuitChanged;
    this.circuitChanged = false;
    return c;
  }

  private setPin(k: number, volts: number, flags: number): void {
    this.pinVolts[k] = volts;
    this.pinFlags[k] = flags | (logicHigh(volts, this.pins[k].voltage_limits) ? PIN_HIGH : 0);
  }

  // ---------------------------------------------------------------- reading out
  /** The instance ids in bridge order (the renderer's index into the transforms). */
  partOrder(): string[] {
    return this.entries.map((e) => e.inst.instance_id);
  }

  /** True once after the part list changed (spawn, remove). */
  takePartsChanged(): boolean {
    const c = this.partsChanged;
    this.partsChanged = false;
    return c;
  }

  pose(id: string): Pose | undefined {
    return this.byId.get(id)?.pose;
  }

  /** A driven joint's position and velocity, or undefined. */
  drive(joint: number): { pos: number; vel: number; target: number } | undefined {
    const d = this.drives.get(joint);
    return d && { pos: d.pos, vel: d.vel, target: d.target };
  }

  /** Writes the state to the bridge under its seqlock. */
  publish(w: BridgeWriter): void {
    w.publish((v) => {
      const n = this.entries.length;
      w.setCounts(n, this.pins.length, this.axes.length);
      this.axes.forEach((a, i) => {
        const k = i * AXIS_STRIDE;
        v.axes[k + AX.POSITION] = this.axisValue(a);
        v.axes[k + AX.RPM] = (a.motor.speed * 60) / TAU;
        v.axes[k + AX.CURRENT] = a.motor.current;
        v.axes[k + AX.VOLTS] = a.motor.volts;
        v.axes[k + AX.COUNT] = this.count(a);
        v.axes[k + AX.TASK] = TASKS.indexOf(a.task.kind);
        v.axes[k + AX.ERROR] = a.lastError;
        v.axes[k + AX.CRASHES] = a.crashes;
        v.axes[k + AX.HOMED] = a.homed ? 1 : 0;
      });
      for (let i = 0; i < n; i++) {
        const { p, q } = this.entries[i].pose;
        const k = i * TRANSFORM_STRIDE;
        v.transforms[k] = p[0];
        v.transforms[k + 1] = p[1];
        v.transforms[k + 2] = p[2];
        v.transforms[k + 3] = q[0];
        v.transforms[k + 4] = q[1];
        v.transforms[k + 5] = q[2];
        v.transforms[k + 6] = q[3];
      }
      v.pinVolts.set(this.pinVolts);
      v.pinFlags.set(this.pinFlags);
      v.header[H.MODE] = this.mode === "SIMULATION_MODE" ? MODE_SIMULATION : MODE_LIVE_TELEMETRY;
      v.header[H.FLAGS] = (this.running ? FLAG_RUNNING : 0) | (this.mode === "LIVE_TELEMETRY_MODE" && this.telemetryStale ? FLAG_TELEMETRY_STALE : 0);
      w.setStep(this.step);
      v.scalars[S.SIM_TIME] = this.simTime;
      v.scalars[S.DT] = FIXED_DT;
      v.scalars[S.RATE] = this.rate;
    });
  }

  /** A fingerprint of the state (FNV-1a over the float64 bytes of every pose and pin): two runs
      are the same run when their fingerprints are equal at every step. */
  stateHash(): string {
    const f = new Float64Array(this.entries.length * TRANSFORM_STRIDE + this.pinVolts.length + 1);
    let k = 0;
    for (const e of this.entries) {
      for (const x of e.pose.p) f[k++] = x;
      for (const x of e.pose.q) f[k++] = x;
    }
    f.set(this.pinVolts, k);
    f[f.length - 1] = this.step;
    const bytes = new Uint8Array(f.buffer);
    let h1 = 0x811c9dc5;
    let h2 = 0x01000193;
    for (let i = 0; i < bytes.length; i++) {
      h1 = Math.imul(h1 ^ bytes[i], 0x01000193);
      h2 = Math.imul(h2 ^ bytes[bytes.length - 1 - i], 0x01000193);
    }
    return (h1 >>> 0).toString(16).padStart(8, "0") + (h2 >>> 0).toString(16).padStart(8, "0");
  }

  dispose(): void {
    this.world.free();
  }
}
