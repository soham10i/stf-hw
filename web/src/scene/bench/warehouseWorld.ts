// The high-bay warehouse's axes as a physics world (the Test bench): three motor-driven axes in
// nested frames, built from the CAD export - travel along the rail, the lift up the mast, the fork
// in and out of the shelves - each with its DC encoder motor, and their reference switches.
//
//   travel  M2 on a 4 mm spindle, encoder 75 pulses/rev (B1/B2), reference I1 at the conveyor end
//   lift    M3 on a 4 mm spindle up the mast, encoder (B3/B4), reference I4 at the top; it
//           lifts the carriage against gravity (the spindle holds it when the motor is off)
//   fork    M4 on the Ausleger spindle, no encoder: positioned by its switches, I6 back, I5 front
//   belt    M1, an S-Motor on the belt's 20 mm drum, no encoder: it runs until a light barrier -
//           I2 inside (at the crane's hand-over), I3 outside (at the gripper's end) - is cut
//
// The CAD export places each frame's parts relative to the frame's origin (travel: along x by
// the travel value; lift: up by the lift value; fork: across by the fork value), so a moving part
// is placed where it is at joint 0 and its binding moves it by the joint's value - parents first.
//
// Where the switches close: the CAD boxes of the switches are estimates from photos (the carriage
// would stop 10 mm short of I1), so each closes at its axis's documented end (doc.joints limits,
// the positions the PLC program uses), with the Mini-Taster's 0.5 mm differential travel. The hard
// stops - where the mechanism ends - are [assumed] 3 mm beyond.
//
// The belt: one conveyor body over both of the CAD's belt strips (a mould spans the 40 mm gap
// between them), the side rails as smooth guides, each light barrier a thin beam from its
// transmitter to its receiver. "Forward" is out of the warehouse, toward the gripper (+y).
// Its speed: the project's [assumed] 50 mm/s for every belt (docs/UPGRADE_PLAN.md) sets the
// load the motor turns against, as the lab's 214 rpm sets the spindles'.
import { compose, qaxis, type Pose } from "../../core/math64";
import type { PartDefinition, PlacedPart, Vec3 } from "../../core/schema";
import type { CadDoc, CadPart } from "../../shared/model";
import { FT_ENCODER_MOTOR, loadedTo, S_MOTOR_24V, TAU } from "../../workers/motors";
import type { AxisMotor, BodyRole, JointBinding, WorldInit } from "../../workers/protocol";

export const AXES = ["travel", "lift", "fork", "belt"] as const;
export type AxisId = (typeof AXES)[number];
export type CraneAxis = Exclude<AxisId, "belt">;
export const SPINDLE_LEAD_MM = 4;
export const PULSES_PER_REV = 75;
const OVERTRAVEL_MM = 3; // [assumed] from the switch's point to the mechanism's end
/** encoder counts before the target the PLC switches the motor off: the axis coasts about two
    counts after it. A 10 ms scan is 2.7 counts of travel at full speed, so where the motor is
    switched off spreads over that: measured on this model over 24 targets, a lead of 2 stops
    every move within two counts and most within one (1 and 4 reach three) */
export const BRAKE_LEAD = 2;
/** [assumed] the lift carriage, fork and table the lift spindle carries */
export const LIFT_MASS_KG = 0.25;
/** the belt drum's diameter (doc.belt.pulley_d, the CAD's cv_drum parts) */
export const DRUM_D_MM = 20;
/** [assumed] the speed every belt of the project runs at */
export const BELT_MM_S = 50;
/** [assumed] a mould (workpiece carrier) with its cookie */
const MOULD_MASS_G = 40;
const BEAM_MM = 3;

export interface WarehouseWorld {
  init: WorldInit;
  placement: Pose;
  /** where each axis starts at power-up (anywhere: it is homed first) */
  powerUp: Record<CraneAxis, number>;
  /** the named positions of each axis (the PLC program's stops) */
  stops: Record<CraneAxis, Record<string, number>>;
  limits: Record<CraneAxis, [number, number]>;
  switchPin: Record<"I1" | "I4" | "I5" | "I6" | "I2" | "I3", number>;
  /** where a mould is set on the belt: the crane's hand-over, factory mm (its centre) */
  handover: Vec3;
  mouldSize: Vec3;
}

const box = (p: CadPart): [Vec3, Vec3] => {
  if (p.k !== "box") throw new Error(`${p.n} is not a box`);
  const s = p.s as Vec3;
  return [p.p, [p.p[0] + s[0], p.p[1] + s[1], p.p[2] + s[2]]];
};

const definition = (part_id: string, size: Vec3, mass_g: number, pins: PartDefinition["electrical_pins"] = []): PartDefinition => ({
  part_id, dimensions_mm: { x: size[0], y: size[1], z: size[2] }, mass_g, bounding_box_type: "OBB",
  mesh_data: { glb_url: "precise_up7.glb", collision_margin_mm: 0.05 }, mating_connectors: [], electrical_pins: pins,
});

export function warehouseWorld(doc: CadDoc, powerUp: Partial<Record<CraneAxis, number>> = {}): WarehouseWorld {
  const parts = doc.parts as unknown as CadPart[];
  const need = (n: string) => {
    const p = parts.find((x) => x.n === n);
    if (!p) throw new Error(`the CAD export has no warehouse part "${n}"`);
    return p;
  };
  const pl = doc.factory.placement;
  const placement: Pose = { p: [pl.translate[0], pl.translate[1], 0], q: qaxis([0, 0, 1], (pl.rotate_deg * Math.PI) / 180) };
  const toFactory = (local: Vec3) => compose(placement, { p: local, q: [0, 0, 0, 1] }).p;

  const defs: PartDefinition[] = [];
  const placed: PlacedPart[] = [];
  const roles: Record<string, BodyRole> = {};
  const bindings: JointBinding[] = [];
  /** a CAD box, placed where it is with every joint at 0 (frame-local coordinates are then the
      warehouse's own: the frames' origins sit at the joint values) */
  const addBox = (id: string, lo: Vec3, hi: Vec3, role: BodyRole, pins?: PartDefinition["electrical_pins"]) => {
    const size: Vec3 = [hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]];
    defs.push(definition(id, size, 100, pins));
    placed.push({ instance_id: id, part_id: id, world_position_mm: toFactory([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2]), world_quaternion: [...placement.q] });
    roles[id] = role;
  };
  const add = (id: string, p: CadPart, role: BodyRole, pins?: PartDefinition["electrical_pins"]) => addBox(id, ...box(p), role, pins);
  const out = (): PartDefinition["electrical_pins"] => [
    { pin_number: 1, label: "OUT", local_position_mm: [0, 0, 0], electrical_type: "digital_io", voltage_limits: [0, 28.8] },
  ];

  // the moving frames, each a kinematic part on its axis, nested
  add("hbw_travel", need("travel_carriage"), { kind: "kinematic" });
  add("hbw_lift", need("lift_carriage_yoke"), { kind: "kinematic" });
  add("hbw_fork", need("fork_table"), { kind: "kinematic" });
  bindings.push(
    { joint: 0, instance_id: "hbw_travel", type: "prismatic", axis_local: [1, 0, 0], unit: "mm" },
    { joint: 1, instance_id: "hbw_lift", type: "prismatic", axis_local: [0, 0, 1], unit: "mm", parent: "hbw_travel" },
    { joint: 2, instance_id: "hbw_fork", type: "prismatic", axis_local: [0, 1, 0], unit: "mm", parent: "hbw_lift" },
  );
  // the switches, each on the frame that carries it: I1 on the rail, I4 on the mast, I5/I6 on the lift
  add("I1", need("I1_ref_horizontal"), { kind: "fixed" }, out());
  add("I4", need("I4_ref_vertical"), { kind: "kinematic" }, out());
  add("I5", need("I5_ref_ausleger_front"), { kind: "kinematic" }, out());
  add("I6", need("I6_ref_ausleger_back"), { kind: "kinematic" }, out());
  bindings.push(
    { joint: -1, instance_id: "I4", type: "rigid", axis_local: [1, 0, 0], unit: "mm", parent: "hbw_travel" },
    { joint: -1, instance_id: "I5", type: "rigid", axis_local: [1, 0, 0], unit: "mm", parent: "hbw_lift" },
    { joint: -1, instance_id: "I6", type: "rigid", axis_local: [1, 0, 0], unit: "mm", parent: "hbw_lift" },
  );

  // the belt, its guides and its light barriers
  const [bl] = box(need("cv_belt_L"));
  const [, bh] = box(need("cv_belt_R"));
  addBox("hbw_belt", bl, bh, { kind: "conveyor", direction_local: [0, 1, 0], speed_mm_s: 0, friction: 0.6 });
  add("hbw_rail_L", need("cv_side_rail_L"), { kind: "fixed", friction: 0 });
  add("hbw_rail_R", need("cv_side_rail_R"), { kind: "fixed", friction: 0 });
  for (const tag of ["I2", "I3"] as const) {
    const [rx, tx] = parts.filter((p) => p.tag === tag && p.g === "conveyor");
    if (!rx || !tx) throw new Error(`light barrier ${tag} needs its transmitter and receiver in the CAD export`);
    const [rlo, rhi] = box(rx);
    const [tlo, thi] = box(tx);
    // across the belt (x): from the receiver's face to the transmitter's, through their middle
    const mid = (rlo[1] + rhi[1]) / 2;
    addBox(tag, [Math.min(rhi[0], thi[0]), mid - BEAM_MM / 2, rlo[2] + 1], [Math.max(rlo[0], tlo[0]), mid + BEAM_MM / 2, rhi[2] - 1],
      { kind: "sensor", pin: { part_instance: tag, pin_label: "OUT" } }, out());
  }
  const [mw, md, mb] = doc.moulds.size as unknown as Vec3;
  const mouldSize: Vec3 = [mw, md, mb + doc.moulds.rim_h];
  defs.push({ ...definition("mould", mouldSize, MOULD_MASS_G), mesh_data: { glb_url: "mould", collision_margin_mm: 0.05 } });
  const B = doc.belt as unknown as { x: number; surface: number; handover: number };
  const handover = toFactory([B.x, B.handover, B.surface + mouldSize[2] / 2 + 0.5]);

  const J = doc.joints as unknown as Record<CraneAxis, { limits: [number, number]; stops: Record<string, number> }>;
  const limits = { travel: J.travel.limits, lift: J.lift.limits, fork: J.fork.limits } as Record<CraneAxis, [number, number]>;
  const start = {
    travel: powerUp.travel ?? (limits.travel[0] + limits.travel[1]) / 2,
    lift: powerUp.lift ?? (limits.lift[0] + limits.lift[1]) / 2,
    fork: powerUp.fork ?? 0,
  };
  const hard = (a: CraneAxis): [number, number] => [limits[a][0] - OVERTRAVEL_MM, limits[a][1] + OVERTRAVEL_MM];
  const pin = (id: string) => ({ part_instance: id, pin_label: "OUT" });
  const axes: AxisMotor[] = [
    {
      id: "travel", joint: 0, perRev: SPINDLE_LEAD_MM, pulsesPerRev: PULSES_PER_REV, start: start.travel, hardStop: hard("travel"),
      reference: { pin: pin("I1"), at: limits.travel[1], toward: "up" }, brakeLeadCounts: BRAKE_LEAD,
    },
    {
      id: "lift", joint: 1, perRev: SPINDLE_LEAD_MM, pulsesPerRev: PULSES_PER_REV, start: start.lift, hardStop: hard("lift"),
      // the carriage's weight on the spindle, as a torque at the motor's output
      motor: { ...FT_ENCODER_MOTOR, loadNm: (LIFT_MASS_KG * 9.81 * SPINDLE_LEAD_MM * 1e-3) / TAU },
      reference: { pin: pin("I4"), at: limits.lift[1], toward: "up" }, brakeLeadCounts: BRAKE_LEAD,
    },
    {
      id: "fork", joint: 2, perRev: SPINDLE_LEAD_MM, start: start.fork, hardStop: hard("fork"),
      switches: [
        { pin: pin("I6"), at: limits.fork[0], toward: "down" },
        { pin: pin("I5"), at: limits.fork[1], toward: "up" },
      ],
    },
    {
      // M1: the belt's travel, mm, from power-up; it waits on its light barriers
      id: "belt", joint: -1, belt: "hbw_belt", perRev: Math.PI * DRUM_D_MM, start: 0,
      motor: loadedTo(S_MOTOR_24V, (BELT_MM_S / (Math.PI * DRUM_D_MM)) * 60),
      switches: [{ pin: pin("I2") }, { pin: pin("I3") }],
    },
  ];

  return {
    init: { parts: defs, project: { placed_parts: placed, wire_nets: [] }, roles, bindings, axes, extra_part_capacity: 8 },
    placement,
    powerUp: start,
    stops: { travel: J.travel.stops, lift: J.lift.stops, fork: J.fork.stops },
    limits,
    switchPin: { I1: 0, I4: 1, I5: 2, I6: 3, I2: 4, I3: 5 },
    handover,
    mouldSize,
  };
}

/** A mould set on the belt at the crane's hand-over (instance ids must be unique: pass a counter). */
export function mouldAt(world: WarehouseWorld, n: number): PlacedPart {
  return { instance_id: `mould_${n}`, part_id: "mould", world_position_mm: [...world.handover], world_quaternion: [...world.placement.q] };
}
