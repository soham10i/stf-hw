// Mating and precision snapping (Deliverable 3): where a part lands when it is dragged near another.
//
// Each part carries mating connectors (a DIN-rail latch, an M3 mount): a point and an outward
// normal in the part's own frame. When a connector of the dragged part comes within the snap
// threshold of a free connector of the same mating type on another part, the dragged part is
// turned so its connector's normal points straight into the target's (normals opposite, dot -1)
// and moved so the two points meet. Otherwise it only snaps to the grid.
//
// The arithmetic is float64 throughout. The final position is locked to the precision grid
// (0.1 mm). A mate between two parts placed on the grid lands on the grid exactly; when it would
// not, the result says by how much the grid moved the connectors apart (`residualMm`, at most half
// a grid step per axis), rather than silently leaving a part off the grid.
import { compose, qaxis, qmul, qnormalize, rotate, type Pose } from "../core/math64";
import { PRECISION_GRID_MM, type MatingConnector, type PartDefinition, type PlacedPart, type Quat, type Vec3 } from "../core/schema";

export interface SnapPart {
  instance: PlacedPart;
  definition: PartDefinition;
}

export interface SnapOptions {
  /** also round the turn about the mating axis to this step (BenchTwin's "Turn 15°"); off by default */
  twistStepDeg?: number;
  /** connectors already in use: "instance_id/node_id" - they take no second mate */
  occupied?: ReadonlySet<string>;
}

export interface Mate {
  activeNode: string;
  targetInstance: string;
  targetNode: string;
  matingType: MatingConnector["allowed_mating_type"];
  /** connector to connector before the snap, mm */
  distanceMm: number;
  /** the normals' dot product after the snap: -1 when they face each other */
  normalDot: number;
  /** connector to connector after the grid lock, mm (0 when the mate lies on the grid) */
  residualMm: number;
}

export interface SnapResult {
  snapped: boolean;
  position_mm: Vec3;
  quaternion: Quat;
  mate: Mate | null;
}

/** A connector in world coordinates. */
export interface WorldConnector {
  instance: string;
  node: MatingConnector;
  position: Vec3;
  normal: Vec3;
}

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const len = (a: Vec3) => Math.hypot(a[0], a[1], a[2]);
const scale = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k];
const unitV = (a: Vec3): Vec3 => scale(a, 1 / len(a));

const poseOf = (p: PlacedPart): Pose => ({ p: p.world_position_mm, q: p.world_quaternion });

/** Every connector of a placed part, in world coordinates. */
export function connectorsWorld(part: SnapPart): WorldConnector[] {
  const pose = poseOf(part.instance);
  return part.definition.mating_connectors.map((node) => {
    const at = compose(pose, { p: node.local_position_mm, q: [0, 0, 0, 1] });
    return { instance: part.instance.instance_id, node, position: at.p, normal: rotate(pose.q, node.normal_vector) };
  });
}

/** The decimal places a grid step needs (0.1 -> 1, 0.25 -> 2, 5 -> 0). */
function decimals(step: number): number {
  const s = step.toString();
  if (s.includes("e-")) return Number(s.split("e-")[1]);
  return s.includes(".") ? s.split(".")[1].length : 0;
}

/** A coordinate on the grid, exactly as the grid's decimal (0.3, not 0.30000000000000004). */
export function snapToGrid(v: number, step = PRECISION_GRID_MM): number {
  if (!(step > 0)) throw new RangeError("the grid step must be greater than 0");
  const k = Math.round(v / step);
  const out = Number((k * step).toFixed(decimals(step)));
  return out === 0 ? 0 : out; // no -0
}

/** The shortest rotation that turns unit vector `u` onto unit vector `v`. Opposite vectors turn
    half a revolution about an axis perpendicular to `u` (the same axis every time). */
export function rotationBetween(u: Vec3, v: Vec3): Quat {
  const d = dot(u, v);
  if (d >= 1 - 1e-15) return [0, 0, 0, 1];
  if (d <= -1 + 1e-15) {
    // perpendicular: cross u with the basis axis it is least aligned with
    const ax = Math.abs(u[0]) <= Math.abs(u[1]) && Math.abs(u[0]) <= Math.abs(u[2]) ? [1, 0, 0] : Math.abs(u[1]) <= Math.abs(u[2]) ? [0, 1, 0] : [0, 0, 1];
    const p = unitV(cross(u, ax as Vec3));
    return [p[0], p[1], p[2], 0];
  }
  const c = cross(u, v);
  return qnormalize([c[0], c[1], c[2], 1 + d]);
}

/** A unit vector perpendicular to `n`, from the basis axis least aligned with it: a part's
    reference direction for measuring its turn about a mating axis. */
function perpendicular(n: Vec3): Vec3 {
  const ax: Vec3 = Math.abs(n[0]) <= Math.abs(n[1]) && Math.abs(n[0]) <= Math.abs(n[2]) ? [1, 0, 0] : Math.abs(n[1]) <= Math.abs(n[2]) ? [0, 1, 0] : [0, 0, 1];
  const p = sub(ax, scale(n, dot(ax, n)));
  return unitV(p);
}

/** The turn (radians) about axis `n` that takes `a` onto `b`, both perpendicular to `n`. */
const turnAbout = (n: Vec3, a: Vec3, b: Vec3) => Math.atan2(dot(n, cross(a, b)), dot(a, b));

/** Where the dragged part lands.
 *
 * Every connector of `activePart` is tried against every free connector of the same mating type
 * on the candidates; the nearest pair within `snapThresholdMm` wins (ties: the first by instance,
 * then node id, so the result never depends on the candidates' order). No pair in range: the part
 * keeps its turn and only its position snaps to the grid.
 */
export function calculateSnapTransform(
  activePart: SnapPart,
  candidateParts: readonly SnapPart[],
  snapThresholdMm = 5.0,
  gridSnapMm = PRECISION_GRID_MM,
  options: SnapOptions = {},
): SnapResult {
  if (!(snapThresholdMm >= 0)) throw new RangeError("the snap threshold must be 0 or more");
  const active = activePart.instance;
  const mine = connectorsWorld(activePart);
  const occupied = options.occupied ?? new Set<string>();
  const reach = snapThresholdMm + halfDiagonal(activePart.definition);

  let best: { a: WorldConnector; b: WorldConnector; d: number } | null = null;
  for (const cand of candidateParts) {
    if (cand.instance.instance_id === active.instance_id) continue;
    // a part whose box is out of reach cannot hold a connector in range
    const gap = len(sub(cand.instance.world_position_mm, active.world_position_mm));
    if (gap > reach + halfDiagonal(cand.definition)) continue;
    for (const b of connectorsWorld(cand)) {
      if (occupied.has(`${b.instance}/${b.node.node_id}`)) continue;
      for (const a of mine) {
        if (a.node.allowed_mating_type !== b.node.allowed_mating_type) continue;
        if (occupied.has(`${active.instance_id}/${a.node.node_id}`)) continue;
        const d = len(sub(a.position, b.position));
        if (d > snapThresholdMm) continue;
        if (!best || d < best.d - 1e-12 || (Math.abs(d - best.d) <= 1e-12 && order(a, b) < order(best.a, best.b))) best = { a, b, d };
      }
    }
  }

  const grid = (p: Vec3): Vec3 => [snapToGrid(p[0], gridSnapMm), snapToGrid(p[1], gridSnapMm), snapToGrid(p[2], gridSnapMm)];
  if (!best) {
    return { snapped: false, position_mm: grid(active.world_position_mm), quaternion: active.world_quaternion, mate: null };
  }

  // turn: the active normal onto the reverse of the target's
  const { a, b } = best;
  const into = scale(b.normal, -1);
  let q = qnormalize(qmul(rotationBetween(a.normal, into), active.world_quaternion));
  if (options.twistStepDeg && options.twistStepDeg > 0) {
    // the turn about the mating axis, measured against the target part's own reference, rounded
    const target = candidateParts.find((c) => c.instance.instance_id === b.instance)!;
    const refTarget = rotate(target.instance.world_quaternion, perpendicular(b.node.normal_vector));
    const refMine = rotate(q, perpendicular(a.node.normal_vector));
    const now = turnAbout(into, refTarget, refMine);
    const step = (options.twistStepDeg * Math.PI) / 180;
    q = qnormalize(qmul(qaxis(into, Math.round(now / step) * step - now), q));
  }
  // move: the active connector onto the target's
  const exact = sub(b.position, rotate(q, a.node.local_position_mm));
  const position = grid(exact);
  const landed = compose({ p: position, q }, { p: a.node.local_position_mm, q: [0, 0, 0, 1] }).p;
  return {
    snapped: true,
    position_mm: position,
    quaternion: q,
    mate: {
      activeNode: a.node.node_id,
      targetInstance: b.instance,
      targetNode: b.node.node_id,
      matingType: a.node.allowed_mating_type,
      distanceMm: best.d,
      normalDot: dot(rotate(q, a.node.normal_vector), b.normal),
      residualMm: len(sub(landed, b.position)),
    },
  };
}

function halfDiagonal(def: PartDefinition): number {
  const { x, y, z } = def.dimensions_mm;
  return Math.hypot(x, y, z) / 2;
}

const order = (a: WorldConnector, b: WorldConnector) => `${b.instance}\u0000${b.node.node_id}\u0000${a.node.node_id}`;
