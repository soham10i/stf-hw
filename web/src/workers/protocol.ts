// The messages between the main thread and the physics worker (physics.worker.ts). The state
// itself never travels as a message when the bridge is shared: only commands go to the worker,
// and only status (and, in the transfer fallback, the published buffer) comes back.
import type { PartDefinition, PinRef, ProjectState, Vec3, WireNet } from "../core/schema";
import type { Contact, Diagnostic, Supply } from "../circuit/NetlistSolver";
import type { MotorSpec } from "./motors";

export type Mode = "SIMULATION_MODE" | "LIVE_TELEMETRY_MODE";

/** What a placed part is to the physics: the schema says what a part IS, this says how it moves. */
export type BodyRole =
  /** `friction`: the most friction a contact with it has (whatever touches it): 0 is a smooth guide
      (a side rail) that supports without dragging; a low value a slick plastic chute */
  | { kind: "fixed"; friction?: number }
  | { kind: "dynamic"; friction?: number; restitution?: number }
  | { kind: "kinematic" }
  /** a belt: its top surface carries what lies on it along `direction_local` at `speed_mm_s` */
  | { kind: "conveyor"; direction_local: Vec3; speed_mm_s: number; friction?: number }
  /** a light barrier or proximity switch: its volume senses any dynamic body and drives a pin */
  | { kind: "sensor"; pin: PinRef; high_volts?: number };

/** One joint moving one kinematic part: a slide along, or a turn about, an axis of the part's own
    frame, measured from where it is placed. `parent` makes it ride on another kinematic part (a
    lift on a travel axis, a gripper on a lift). */
export interface JointBinding {
  joint: number; // index into joint_angles[] and the tracks (-1 for "rigid")
  instance_id: string;
  /** "rigid": no motion of its own - it rides on its parent (a switch on a carriage) */
  type: "prismatic" | "revolute" | "rigid";
  axis_local: Vec3;
  unit: "mm" | "deg" | "rad";
  offset?: number; // added to the joint value, in its unit
  parent?: string;
}

/** A joint's planned motion for SIMULATION_MODE: values at times, linear between, held at the ends. */
export interface JointTrack {
  joint: number;
  times_s: number[];
  values: number[];
}

/** An actuator on a joint: it moves toward its target with a trapezoidal profile - accelerating at
    `amax`, cruising at most at `vmax`, braking to stop exactly on the target - instead of jumping.
    A pneumatic cylinder is fast and stiff (high vmax and amax); an encoder motor is slow. Units:
    the joint's (mm or deg) per second, and per second squared. A driven joint ignores its track. */
export interface JointDrive {
  joint: number;
  vmax: number;
  amax: number;
  /** jerk limit (unit/s^3). Above 0 the drive runs seven-segment S-curves (workers/scurve.ts), as
      PLCopen MC_MoveAbsolute with a jerk does, and a new target given during a move is taken up
      when that move has stopped (BufferMode "Buffered"); 0 or absent: the trapezoid, which
      re-plans at once. A pneumatic cylinder has no profile to limit - leave it 0. */
  jmax?: number;
  /** the joint's travel; targets are clamped into it */
  limits?: [number, number];
  /** where it starts (default 0) */
  start?: number;
}

/** A switch on a motor axis (a reference switch, an end-position switch): it closes as the axis
    passes `at` (in the joint's unit) moving `toward` it, and drives its pin to 24 V while closed.
    Without `at` it is a sensor the axis waits on (a light barrier over a belt): its state is its
    pin's level, which a sensor volume drives, and the axis only reads it. */
export interface AxisSwitch {
  pin: PinRef;
  at?: number;
  toward?: "up" | "down";
  hysteresis?: number; // the switch's differential travel; default 0.5
}

/** An axis driven by a DC encoder motor (workers/motors.ts): the motor turns the joint by `perRev`
    per output revolution (a 4 mm spindle: 4 mm), its encoder counts `pulsesPerRev` (none: the axis
    is positioned by its switches only). The PLC's positioning block drives it (command "axis").
    With `belt` the motor drives a conveyor instead of a joint (`joint` -1): `perRev` is the belt
    travel per output revolution, and the belt's surface speed follows the motor's. */
export interface AxisMotor {
  id: string;
  joint: number;
  belt?: string;
  motor?: MotorSpec; // default: the ft 24 V encoder motor on a spindle
  perRev: number;
  pulsesPerRev?: number;
  /** the joint value at power-up (anywhere: the axis is homed before it positions) */
  start: number;
  /** the mechanism's ends, in the joint's unit: driving into one is a crash */
  hardStop?: [number, number];
  /** the reference switch: homing drives to it and zeroes the count where it closes */
  reference?: AxisSwitch;
  /** further switches on the axis (an end position) */
  switches?: AxisSwitch[];
  /** homing comes onto the reference a second time at this voltage (PWM), for a fast axis whose
      one scan of travel would otherwise be its homing error; none: one approach at full speed */
  homeCreepV?: number;
  /** encoder counts before the target at which the block switches the motor off */
  brakeLeadCounts?: number;
}

/** What the PLC's positioning block is told to do with an axis. */
export type AxisCommand =
  | { kind: "jog"; dir: 1 | -1 }
  | { kind: "move"; target: number } // in the joint's unit, from the calibrated zero
  | { kind: "home" }
  | { kind: "until"; dir: 1 | -1; switch: number } // to switches[switch] (an axis without encoder)
  | { kind: "stop" };

/** One sample from the live factory (WebSocket / MQTT bridge). `timestamp` in ms. */
export interface TelemetrySample {
  timestamp: number;
  joint_angles: number[];
  sensor_states: number[];
}

export interface WorldInit {
  parts: PartDefinition[];
  project: ProjectState;
  roles: Record<string, BodyRole>;
  bindings?: JointBinding[];
  tracks?: JointTrack[];
  /** sensor_states[i] drives this pin */
  telemetry_sensors?: PinRef[];
  /** default [0, 0, -9810]: the factory frame is z-up, in mm */
  gravity_mm_s2?: Vec3;
  /** how far behind the newest sample live mode plays, so two samples bracket every step */
  playout_delay_ms?: number;
  /** room for parts spawned later (cookies); default 64 */
  extra_part_capacity?: number;
  /** the circuit's sources: a positive terminal at a voltage and its ground */
  supplies?: Supply[];
  /** contacts inside parts (switches, relay contacts, jumpers): edges while closed */
  contacts?: Contact[];
  /** actuators on joints (SIMULATION_MODE) */
  drives?: JointDrive[];
  /** joints driven by DC encoder motors (SIMULATION_MODE) */
  axes?: AxisMotor[];
}

export type ToWorker =
  | { type: "init"; world: WorldInit; bridge: SharedArrayBuffer | null }
  | { type: "mode"; mode: Mode }
  | { type: "run"; running: boolean; rate?: number }
  | { type: "step"; steps: number }
  | { type: "telemetry"; samples: TelemetrySample[] }
  | { type: "connect"; url: string }
  | { type: "disconnect" }
  | { type: "spawn"; part: ProjectState["placed_parts"][number]; role: BodyRole }
  | { type: "remove"; instance_id: string }
  | { type: "conveyor"; instance_id: string; speed_mm_s: number }
  | { type: "inputs"; inputs: [number, number | null][] }
  | { type: "nets"; wire_nets: WireNet[] }
  | { type: "contact"; contact: Contact }
  /** move a driven joint to a value */
  | { type: "target"; joint: number; value: number }
  /** a stroke: out to `value`, hold `hold_s`, back to where it started (an ejector firing) */
  | { type: "pulse"; joint: number; value: number; hold_s: number }
  | { type: "axis"; id: string; command: AxisCommand }
  | { type: "dispose" };

export interface WorkerStats {
  stepsPerSecond: number;
  overruns: number; // ticks that had to drop time to stay real-time
  stepMsMean: number;
  bodies: number;
}

export type FromWorker =
  | { type: "ready"; rapier: string; shared: boolean; partCount: number; pinCount: number; partOrder: string[] }
  | { type: "frame"; buffer: ArrayBuffer }
  | { type: "stats"; stats: WorkerStats }
  | { type: "parts"; partOrder: string[] }
  | { type: "telemetry-status"; connected: boolean; lastTimestamp: number | null; error?: string }
  /** the circuit checks, sent when a status changes (not every step) */
  | { type: "circuit"; diagnostics: Diagnostic[] }
  | { type: "error"; message: string };
