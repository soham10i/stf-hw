// The sorting line as a physics world (the Test bench): built from the CAD export, part by part,
// in the factory frame, so what the physics simulates is the machine as it is drawn.
//
//   belt_web               a conveyor: carries what lies on it along the line (+x of the line)
//   belt_rail_F / _B       fixed: the side rails that keep a cookie on the belt
//   bay_*_floor / _wall_*  fixed: the three Lagerstellen a cookie is pushed into
//   sorting_plate          fixed: the base plate (a cookie that runs off the end lands on it)
//   pusher_*               kinematic, on a driven prismatic joint (-y of the line, 0-90 mm):
//                          pneumatic ejectors, fast and stiff
//   I2, I3, I5, I6, I7     sensors: each light barrier's beam, from its transmitter to its
//                          receiver, drives its OUT pin
//   cookies                dynamic, spawned at the inlet: 45 mm across, 20 mm tall
//
// Each CAD box is a corner and a size in the line's own frame; a physics part is placed at its
// centre, and the line's placement (a turn about z and a shift) takes it to the factory frame,
// in float64.
import { compose, qaxis, type Pose } from "../../core/math64";
import type { PartDefinition, PlacedPart, Vec3 } from "../../core/schema";
import type { CadDoc, CadPart } from "../../shared/model";
import type { BodyRole, JointBinding, JointDrive, WorldInit } from "../../workers/protocol";

export const COLOURS = ["weiss", "rot", "blau"] as const;
export type Colour = (typeof COLOURS)[number];
export const COOKIE = { d: 45, h: 20, mass_g: 25 };
/** the ejectors: a pneumatic cylinder's stroke in tenths of a second */
export const PUSHER = { stroke_mm: 90, vmax: 900, amax: 15000 };
export const BARRIERS = ["I2", "I3", "I5", "I6", "I7"] as const;
const BEAM_MM = 3; // a light barrier's beam, as thick as the physics sees it
export const BAY_FRICTION = 0.15; // smooth plastic

export interface SortingWorld {
  init: WorldInit;
  /** the line's placement: line frame -> factory frame */
  placement: Pose;
  /** the joint that drives each colour's pusher */
  pusherJoint: Record<Colour, number>;
  /** each barrier's pin row in the bridge (its index in the pin table) */
  barrierPin: Record<(typeof BARRIERS)[number], number>;
  /** where a new cookie starts, factory frame */
  inlet: Vec3;
  /** the belt's direction of travel, factory frame */
  beltAxis: Vec3;
  /** each flavour's colour, from its bay's sample in the CAD export */
  tint: Record<Colour, string>;
  /** each pusher's placed position and its direction of travel, factory frame */
  pusherBase: Record<Colour, { at: Vec3; axis: Vec3 }>;
}

const box = (p: CadPart) => {
  if (p.k !== "box") throw new Error(`${p.n} is not a box`);
  return p.s as [number, number, number];
};

const definition = (part_id: string, size: Vec3, mass_g: number, pins: PartDefinition["electrical_pins"] = []): PartDefinition => ({
  part_id, dimensions_mm: { x: size[0], y: size[1], z: size[2] }, mass_g, bounding_box_type: "OBB",
  mesh_data: { glb_url: "precise_up7.glb", collision_margin_mm: 0.05 }, mating_connectors: [], electrical_pins: pins,
});

/** Builds the sorting line's world from the CAD export. Throws if a part it needs is missing. */
export function sortingWorld(doc: CadDoc): SortingWorld {
  const parts = doc.sorting.parts as unknown as CadPart[];
  const byName = new Map(parts.map((p) => [p.n, p]));
  const need = (n: string) => {
    const p = byName.get(n);
    if (!p) throw new Error(`the CAD export has no sorting part "${n}"`);
    return p;
  };
  const sp = doc.factory.sort_placement;
  const placement: Pose = { p: [sp.translate[0], sp.translate[1], 0], q: qaxis([0, 0, 1], (sp.rotate_deg * Math.PI) / 180) };
  const toFactory = (local: Vec3): PlacedPart["world_position_mm"] => compose(placement, { p: local, q: [0, 0, 0, 1] }).p;

  const defs: PartDefinition[] = [];
  const placed: PlacedPart[] = [];
  const roles: Record<string, BodyRole> = {};
  /** a CAD box as a physics part, centred, in the factory frame */
  const add = (id: string, corner: Vec3, size: Vec3, role: BodyRole, mass_g = 100, pins?: PartDefinition["electrical_pins"]) => {
    defs.push(definition(id, size, mass_g, pins));
    placed.push({
      instance_id: id, part_id: id,
      world_position_mm: toFactory([corner[0] + size[0] / 2, corner[1] + size[1] / 2, corner[2] + size[2] / 2]),
      world_quaternion: [...placement.q],
    });
    roles[id] = role;
  };
  const addBox = (p: CadPart, role: BodyRole) => add(p.n, p.p, box(p), role);

  // the belt and what keeps a cookie on it
  addBox(need("belt_web"), { kind: "conveyor", direction_local: [1, 0, 0], speed_mm_s: 0, friction: 0.6 });
  // the side rails are smooth guides: flush with the belt's top in the CAD, a cookie (45 mm, on a
  // 40 mm web) rests on their edges too, and only the belt may drive it
  addBox(need("belt_rail_F"), { kind: "fixed", friction: 0 });
  addBox(need("belt_rail_B"), { kind: "fixed", friction: 0 });
  addBox(need("sorting_plate"), { kind: "fixed" });
  // the bays are smooth plastic: a pushed cookie runs on to the back wall, where its barrier and
  // the twin's hand-over point are (the CAD floors are flat, so the friction carries this)
  for (const c of COLOURS) {
    addBox(need(`bay_${c}_floor`), { kind: "fixed", friction: BAY_FRICTION });
    for (const w of ["wall_B", "wall_L", "wall_R"]) addBox(need(`bay_${c}_${w}`), { kind: "fixed" });
  }

  // the ejectors on their joints
  const bindings: JointBinding[] = [];
  const drives: JointDrive[] = [];
  const pusherJoint = {} as Record<Colour, number>;
  COLOURS.forEach((c, j) => {
    addBox(need(`pusher_${c}`), { kind: "kinematic" });
    bindings.push({ joint: j, instance_id: `pusher_${c}`, type: "prismatic", axis_local: [0, -1, 0], unit: "mm" });
    drives.push({ joint: j, vmax: PUSHER.vmax, amax: PUSHER.amax, limits: [0, PUSHER.stroke_mm] });
    pusherJoint[c] = j;
  });

  // the light barriers: a thin volume from the transmitter's face to the receiver's
  const out = (): PartDefinition["electrical_pins"] => [
    { pin_number: 1, label: "OUT", local_position_mm: [0, 0, 0], electrical_type: "digital_io", voltage_limits: [0, 28.8] },
  ];
  for (const tag of BARRIERS) {
    const [rx, tx] = parts.filter((p) => p.tag === tag && p.g === "sense");
    if (!rx || !tx) throw new Error(`light barrier ${tag} needs its transmitter and receiver in the CAD export`);
    const a = rx.p, as = box(rx), b = tx.p, bs = box(tx);
    const alongY = Math.abs(a[1] - b[1]) > Math.abs(a[0] - b[0]);
    const lo: Vec3 = alongY ? [a[0], Math.min(a[1] + as[1], b[1] + bs[1]), a[2]] : [Math.min(a[0] + as[0], b[0] + bs[0]), a[1], a[2]];
    const hi: Vec3 = alongY ? [a[0] + as[0], Math.max(a[1], b[1]), a[2] + as[2]] : [Math.max(a[0], b[0]), a[1] + as[1], a[2] + as[2]];
    // the beam runs through the middle of the emitter's face, BEAM_MM across
    const mid = alongY ? (lo[0] + hi[0]) / 2 : (lo[1] + hi[1]) / 2;
    const corner: Vec3 = alongY ? [mid - BEAM_MM / 2, lo[1], lo[2] + 1] : [lo[0], mid - BEAM_MM / 2, lo[2] + 1];
    const size: Vec3 = alongY ? [BEAM_MM, hi[1] - lo[1], hi[2] - lo[2] - 2] : [hi[0] - lo[0], BEAM_MM, hi[2] - lo[2] - 2];
    add(tag, corner, size, { kind: "sensor", pin: { part_instance: tag, pin_label: "OUT" } }, 1, out());
  }

  // the cookie, for spawning
  defs.push(definition("cookie", [COOKIE.d, COOKIE.d, COOKIE.h], COOKIE.mass_g));

  const web = need("belt_web");
  const top = web.p[2] + box(web)[2];
  const inlet = toFactory([web.p[0] + 30, web.p[1] + box(web)[1] / 2, top + COOKIE.h / 2 + 0.5]);
  const beltAxis = compose(placement, { p: [1, 0, 0], q: [0, 0, 0, 1] }).p.map((x, i) => x - placement.p[i]) as Vec3;

  // pin rows: the parts with pins are the barriers, in the order added, one pin each
  const barrierPin = Object.fromEntries(BARRIERS.map((t, i) => [t, i])) as SortingWorld["barrierPin"];

  const dirOf = (local: Vec3) => compose(placement, { p: local, q: [0, 0, 0, 1] }).p.map((x, i) => x - placement.p[i]) as Vec3;
  const tint = Object.fromEntries(COLOURS.map((c) => [c, byName.get(`wp_${c}_lid`)?.c ?? "#D8B98C"])) as Record<Colour, string>;
  const pusherBase = Object.fromEntries(COLOURS.map((c) => {
    const at = placed.find((p) => p.instance_id === `pusher_${c}`)!.world_position_mm;
    return [c, { at, axis: dirOf([0, -1, 0]) }];
  })) as SortingWorld["pusherBase"];

  return {
    tint,
    pusherBase,
    init: {
      parts: defs,
      project: { placed_parts: placed, wire_nets: [] },
      roles,
      bindings,
      drives,
      extra_part_capacity: 48,
    },
    placement,
    pusherJoint,
    barrierPin,
    inlet,
    beltAxis,
  };
}

/** A new cookie at the inlet (instance ids must be unique: pass a counter). */
export function cookieAt(world: SortingWorld, n: number, colour: Colour): { part: PlacedPart; colour: Colour } {
  const jitter = ((n * 7) % 5) - 2; // a millimetre or two off the centre line, like a real hand-over
  const p: Vec3 = [world.inlet[0], world.inlet[1], world.inlet[2]];
  // across the belt is the line's y, which the placement turned
  const across = compose(world.placement, { p: [0, 1, 0], q: [0, 0, 0, 1] }).p.map((x, i) => x - world.placement.p[i]);
  return {
    part: {
      instance_id: `cookie_${n}`, part_id: "cookie",
      world_position_mm: [p[0] + across[0] * jitter, p[1] + across[1] * jitter, p[2]],
      world_quaternion: [...world.placement.q],
    },
    colour,
  };
}
