// The vacuum gripper robot's axes as a physics world (the Test bench): cylindrical R-P-P, built
// from the CAD export's vgr block - the swivel turns everything above the Drehkranz about the
// tower, the plunge carriage runs up and down the tower, the arm reaches out under it - each on a
// DC encoder motor with its reference switch (docs/HARDWARE_MODEL.md, the VGR's Belegungsplan).
//
//   swivel  M3, Q5/Q6, encoder B5/B6, reference I3 - a cam on the ring closes it at 0 deg and
//           holds it closed above (so the PLC knows which side it is on; homing leaves it first).
//           Homing turns counter-clockwise (+), as the occupancy plan's homing output Q6 does
//   plunge  M1, Q1/Q2, encoder B1/B2, reference I1 at the top of the tower; a 4 mm spindle that
//           carries the carriage and the arm against gravity
//   reach   M2, Q3/Q4, encoder B3/B4, reference I2 with the arm drawn back; a 4 mm spindle
//
// The swivel's gearing is NOT in the documents. The CAD draws a 90 mm pinion on the 180 mm ring
// (2:1): at the motor's 214 rpm the arm would swing at 642 deg/s, and one encoder count would be
// 2.4 deg - 17 mm at the belt. That pinion is a placeholder, so the ratio here is [assumed] to
// give the kernel's 60 deg/s (control.py V_DEG): 16.8 deg per motor revolution, 0.224 deg a count.
//
// Frames, as the CAD export authors them: parts sit at doc.vgr.authoring (swivel 0, plunge 250,
// reach 0) in the VGR's own coordinates, and the VGR stands at doc.factory.vgr_at, unturned. The
// cup is at 168 mm from the tower axis along -y at reach 0; +swivel turns counter-clockwise seen
// from above (the solved stations: belt at 69.013 deg, 236.857 mm reach).
import { compose, IDENTITY, type Pose } from "../../core/math64";
import type { PartDefinition, PlacedPart, Vec3 } from "../../core/schema";
import type { CadDoc, CadPart } from "../../shared/model";
import { FT_ENCODER_MOTOR, TAU } from "../../workers/motors";
import type { AxisMotor, BodyRole, JointBinding, WorldInit } from "../../workers/protocol";

export const VGR_AXES = ["swivel", "plunge", "reach"] as const;
export type VgrAxis = (typeof VGR_AXES)[number];
export const SPINDLE_LEAD_MM = 4;
export const PULSES_PER_REV = 75;
/** [assumed] the swivel's output per motor revolution: the kernel's 60 deg/s at 214 rpm */
export const SWIVEL_DEG_PER_REV = 60 / (214 / 60);
/** [assumed] the carriage, arm and suction head the plunge spindle lifts */
export const PLUNGE_MASS_KG = 0.6;
/** [assumed] the swivel's mechanism ends past its limits, in degrees; the spindles' in mm */
const OVERTRAVEL_DEG = 3;
const OVERTRAVEL_MM = 3;
export const BRAKE_LEAD = 2;
/** the swivel homes a second time slowly: at full speed it turns 0.6 deg in one 10 ms scan, which
    would zero its count up to 0.6 deg late - 4 mm at the belt. At 15 V (PWM, [assumed] available
    on the controller's outputs) the motor turns ~49 rpm against its friction: 0.14 deg a scan,
    under one count. (Below ~12.3 V it does not start at all: the friction holds it.) */
export const SWIVEL_CREEP_V = 15;

export interface VgrWorld {
  init: WorldInit;
  placement: Pose;
  powerUp: Record<VgrAxis, number>;
  stops: Record<VgrAxis, Record<string, number>>;
  limits: Record<VgrAxis, [number, number]>;
  /** each axis's unit, as the panel shows it */
  unit: Record<VgrAxis, "deg" | "mm">;
  /** the solved stations: where the cup must be, factory mm, with the axis values that put it there */
  stations: Record<string, { target: [number, number]; swivel: number; reach: number }>;
  switchPin: Record<"I1" | "I2" | "I3", number>;
}

/** A CAD part's enclosing box in its own coordinates: boxes as they are, z cylinders round. */
function bounds(p: CadPart): [Vec3, Vec3] {
  if (p.k === "box") {
    const s = p.s as Vec3;
    return [p.p, [p.p[0] + s[0], p.p[1] + s[1], p.p[2] + s[2]]];
  }
  const [axis, h, d] = p.s as [string, number, number];
  if (p.k !== "cyl" || axis !== "z") throw new Error(`${p.n}: only boxes and upright cylinders are placed`);
  return [[p.p[0] - d / 2, p.p[1] - d / 2, p.p[2]], [p.p[0] + d / 2, p.p[1] + d / 2, p.p[2] + h]];
}

const definition = (part_id: string, size: Vec3, pins: PartDefinition["electrical_pins"] = []): PartDefinition => ({
  part_id, dimensions_mm: { x: size[0], y: size[1], z: size[2] }, mass_g: 100, bounding_box_type: "OBB",
  mesh_data: { glb_url: "precise_up7.glb", collision_margin_mm: 0.05 }, mating_connectors: [], electrical_pins: pins,
});

export function vgrWorld(doc: CadDoc, powerUp: Partial<Record<VgrAxis, number>> = {}): VgrWorld {
  const V = doc.vgr as unknown as {
    parts: CadPart[]; centre: [number, number]; authoring: Record<VgrAxis, number>;
    joints: Record<VgrAxis, { limits: [number, number]; stops: Record<string, number> }>;
  };
  const need = (n: string) => {
    const p = V.parts.find((x) => x.n === n);
    if (!p) throw new Error(`the CAD export has no gripper part "${n}"`);
    return p;
  };
  const [ax, ay] = doc.factory.vgr_at;
  const placement: Pose = { p: [ax, ay, 0], q: IDENTITY.q };
  const toFactory = (local: Vec3) => compose(placement, { p: local, q: [0, 0, 0, 1] }).p;

  const defs: PartDefinition[] = [];
  const placed: PlacedPart[] = [];
  const roles: Record<string, BodyRole> = {};
  const add = (id: string, lo: Vec3, hi: Vec3, role: BodyRole, pins?: PartDefinition["electrical_pins"]) => {
    defs.push(definition(id, [hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]], pins));
    placed.push({ instance_id: id, part_id: id, world_position_mm: toFactory([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2]), world_quaternion: [...placement.q] });
    roles[id] = role;
  };
  const out = (): PartDefinition["electrical_pins"] => [
    { pin_number: 1, label: "OUT", local_position_mm: [0, 0, 0], electrical_type: "digital_io", voltage_limits: [0, 28.8] },
  ];

  // the moving frames: the turntable turns about its own centre - the tower axis - and carries
  // the rest; the carriage and the arm slide; the cup rides on the arm
  const [tlo, thi] = bounds(need("turntable_disc"));
  const [cx, cy] = V.centre;
  if (Math.abs((tlo[0] + thi[0]) / 2 - cx) > 1e-9 || Math.abs((tlo[1] + thi[1]) / 2 - cy) > 1e-9) throw new Error("the turntable is not centred on the tower axis");
  add("vgr_turntable", tlo, thi, { kind: "kinematic" });
  add("vgr_carriage", ...bounds(need("plunge_carriage")), { kind: "kinematic" });
  // the arm: both rails and their end blocks as one body
  const arm = ["arm_rail_L", "arm_rail_R", "arm_end_F", "arm_end_B"].map((n) => bounds(need(n)));
  add("vgr_arm", [0, 1, 2].map((i) => Math.min(...arm.map((b) => b[0][i]))) as Vec3, [0, 1, 2].map((i) => Math.max(...arm.map((b) => b[1][i]))) as Vec3, { kind: "kinematic" });
  add("vgr_cup", ...bounds(need("suction_cup")), { kind: "kinematic" });
  const A = V.authoring;
  const bindings: JointBinding[] = [
    { joint: 0, instance_id: "vgr_turntable", type: "revolute", axis_local: [0, 0, 1], unit: "deg", offset: -A.swivel },
    { joint: 1, instance_id: "vgr_carriage", type: "prismatic", axis_local: [0, 0, 1], unit: "mm", offset: -A.plunge, parent: "vgr_turntable" },
    { joint: 2, instance_id: "vgr_arm", type: "prismatic", axis_local: [0, -1, 0], unit: "mm", offset: -A.reach, parent: "vgr_carriage" },
    { joint: -1, instance_id: "vgr_cup", type: "rigid", axis_local: [1, 0, 0], unit: "mm", parent: "vgr_arm" },
  ];
  // the switches, on what carries them: I3 on the base, I1 on the tower, I2 on the carriage
  add("I3", ...bounds(need("I3_ref_swivel")), { kind: "fixed" }, out());
  add("I1", ...bounds(need("I1_ref_plunge")), { kind: "kinematic" }, out());
  add("I2", ...bounds(need("I2_ref_reach")), { kind: "kinematic" }, out());
  bindings.push(
    { joint: -1, instance_id: "I1", type: "rigid", axis_local: [1, 0, 0], unit: "mm", parent: "vgr_turntable" },
    { joint: -1, instance_id: "I2", type: "rigid", axis_local: [1, 0, 0], unit: "mm", parent: "vgr_carriage" },
  );

  const J = V.joints;
  const limits = { swivel: J.swivel.limits, plunge: J.plunge.limits, reach: J.reach.limits };
  const start = { swivel: powerUp.swivel ?? 30, plunge: powerUp.plunge ?? 300, reach: powerUp.reach ?? 100 };
  const hard = (a: VgrAxis, over: number): [number, number] => [limits[a][0] - over, limits[a][1] + over];
  const pin = (id: string) => ({ part_instance: id, pin_label: "OUT" });
  const axes: AxisMotor[] = [
    {
      id: "swivel", joint: 0, perRev: SWIVEL_DEG_PER_REV, pulsesPerRev: PULSES_PER_REV, start: start.swivel, hardStop: hard("swivel", OVERTRAVEL_DEG),
      // the cam: closed at 0 deg and above - homing comes onto it counter-clockwise (Q6, the plan)
      reference: { pin: pin("I3"), at: 0, toward: "up" }, brakeLeadCounts: BRAKE_LEAD, homeCreepV: SWIVEL_CREEP_V,
    },
    {
      id: "plunge", joint: 1, perRev: SPINDLE_LEAD_MM, pulsesPerRev: PULSES_PER_REV, start: start.plunge, hardStop: hard("plunge", OVERTRAVEL_MM),
      motor: { ...FT_ENCODER_MOTOR, loadNm: (PLUNGE_MASS_KG * 9.81 * SPINDLE_LEAD_MM * 1e-3) / TAU },
      reference: { pin: pin("I1"), at: limits.plunge[1], toward: "up" }, brakeLeadCounts: BRAKE_LEAD,
    },
    {
      id: "reach", joint: 2, perRev: SPINDLE_LEAD_MM, pulsesPerRev: PULSES_PER_REV, start: start.reach, hardStop: hard("reach", OVERTRAVEL_MM),
      reference: { pin: pin("I2"), at: limits.reach[0], toward: "down" }, brakeLeadCounts: BRAKE_LEAD,
    },
  ];

  const S = doc.factory.stations as unknown as VgrWorld["stations"];
  return {
    init: { parts: defs, project: { placed_parts: placed, wire_nets: [] }, roles, bindings, axes, extra_part_capacity: 8 },
    placement,
    powerUp: start,
    stops: { swivel: J.swivel.stops, plunge: J.plunge.stops, reach: J.reach.stops },
    limits,
    unit: { swivel: "deg", plunge: "mm", reach: "mm" },
    stations: Object.fromEntries(Object.entries(S).map(([k, s]) => [k, { target: s.target, swivel: s.swivel, reach: s.reach }])),
    switchPin: { I3: 0, I1: 1, I2: 2 },
  };
}
