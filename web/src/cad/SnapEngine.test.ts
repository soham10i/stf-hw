import { describe, expect, it } from "vitest";

import { qaxis, rotate } from "../core/math64";
import type { PartDefinition, Quat, Vec3 } from "../core/schema";
import { calculateSnapTransform, connectorsWorld, rotationBetween, snapToGrid, type SnapPart } from "./SnapEngine";

const def = (part_id: string, connectors: PartDefinition["mating_connectors"], size = 50): PartDefinition => ({
  part_id, dimensions_mm: { x: size, y: size, z: size }, mass_g: 100, bounding_box_type: "OBB",
  mesh_data: { glb_url: `${part_id}.glb`, collision_margin_mm: 0.05 }, mating_connectors: connectors, electrical_pins: [],
});
const RAIL = def("din_rail", [{ node_id: "rail_top", local_position_mm: [0, 0, 5], normal_vector: [0, 0, 1], allowed_mating_type: "DIN_35mm" }], 200);
const MODULE = def("plc", [
  { node_id: "din_rail_latch_1", local_position_mm: [0, 12.5, -5], normal_vector: [0, 0, -1], allowed_mating_type: "DIN_35mm" },
  { node_id: "m3_mount_a", local_position_mm: [20, 0, 0], normal_vector: [1, 0, 0], allowed_mating_type: "M3_screw" },
]);
const part = (id: string, d: PartDefinition, p: Vec3, q: Quat = [0, 0, 0, 1]): SnapPart =>
  ({ instance: { instance_id: id, part_id: d.part_id, world_position_mm: p, world_quaternion: q }, definition: d });

const close = (a: number[], b: number[], eps = 1e-12) => a.forEach((x, i) => expect(Math.abs(x - b[i])).toBeLessThan(eps));

describe("the grid", () => {
  it("lands on the grid's decimals exactly", () => {
    expect(snapToGrid(0.1 + 0.2)).toBe(0.3);
    expect(snapToGrid(12.34)).toBe(12.3);
    expect(snapToGrid(-0.04)).toBe(0);
    expect(Object.is(snapToGrid(-0.04), -0)).toBe(false);
    expect(snapToGrid(1.37, 0.25)).toBe(1.25);
    expect(snapToGrid(1234.56789, 1e-3)).toBe(1234.568);
    expect(() => snapToGrid(1, 0)).toThrow(RangeError);
  });
});

describe("rotations", () => {
  it("turn one direction onto another, the short way, opposite ones included", () => {
    close([...rotate(rotationBetween([1, 0, 0], [0, 1, 0]), [1, 0, 0])], [0, 1, 0]);
    close([...rotate(rotationBetween([0, 0, 1], [0, 0, -1]), [0, 0, 1])], [0, 0, -1]);
    expect(rotationBetween([0, 0, 1], [0, 0, 1])).toEqual([0, 0, 0, 1]);
    const u: Vec3 = [0.6, 0, 0.8];
    close([...rotate(rotationBetween(u, [-0.6, 0, -0.8]), u)], [-0.6, 0, -0.8]);
  });
});

describe("mating", () => {
  it("latches a tilted module onto the rail: normals opposite, points met, on the grid", () => {
    const rail = part("rail", RAIL, [0, 0, 0]);
    // the module's latch is ~3 mm from the rail's top, and the module leans 10 degrees
    const tilt = qaxis([1, 0, 0], (10 * Math.PI) / 180);
    const plc = part("plc1", MODULE, [1.2, -11.8, 9.4], tilt);
    const latch = connectorsWorld(plc)[0].position;
    expect(Math.hypot(latch[0], latch[1], latch[2] - 5)).toBeLessThan(5);
    const r = calculateSnapTransform(plc, [rail]);
    expect(r.snapped).toBe(true);
    expect(r.mate!.targetInstance).toBe("rail");
    expect(r.mate!.activeNode).toBe("din_rail_latch_1");
    expect(r.mate!.normalDot).toBeCloseTo(-1, 14);
    expect(r.position_mm).toEqual([0, -12.5, 10]);
    expect(r.mate!.residualMm).toBeLessThan(1e-12);
    close([...r.quaternion], [0, 0, 0, 1]); // the lean is gone
  });

  it("locks to the grid even when the mate is off it, and says how far that moved the connectors", () => {
    const rail = part("rail", RAIL, [0.03, 0, 0]);
    const r = calculateSnapTransform(part("plc1", MODULE, [1, -12, 10]), [rail]);
    expect(r.position_mm[0]).toBe(0);
    expect(r.mate!.residualMm).toBeCloseTo(0.03, 12);
  });

  it("only snaps within the threshold, between connectors of the same mating type", () => {
    const rail = part("rail", RAIL, [0, 0, 0]);
    const far = calculateSnapTransform(part("plc1", MODULE, [0, -12.5, 16.04]), [rail]); // 6.04 mm off
    expect(far.snapped).toBe(false);
    expect(far.position_mm).toEqual([0, -12.5, 16]);
    expect(calculateSnapTransform(part("plc1", MODULE, [0, -12.5, 16.04]), [rail], 7).snapped).toBe(true);
    const screwOnly = def("bracket", [{ node_id: "m3", local_position_mm: [0, 0, 5], normal_vector: [0, 0, 1], allowed_mating_type: "M3_screw" }]);
    expect(calculateSnapTransform(part("plc1", MODULE, [0, -12.5, 10]), [part("b", screwOnly, [0, 0, 0])]).snapped).toBe(false);
  });

  it("takes the nearest free connector, whatever order the candidates come in", () => {
    const a = part("rail_a", RAIL, [0, 0, 2]); // its top is 2 mm from the latch
    const b = part("rail_b", RAIL, [0, 0, -4]);
    const plc = part("plc1", MODULE, [0, -12.5, 10]);
    expect(calculateSnapTransform(plc, [a, b]).mate!.targetInstance).toBe("rail_a");
    expect(calculateSnapTransform(plc, [b, a]).mate!.targetInstance).toBe("rail_a");
    const tie = part("rail_0", RAIL, [0, 0, 2]); // same distance: decided by id, not order
    expect(calculateSnapTransform(plc, [a, tie]).mate!.targetInstance).toBe(calculateSnapTransform(plc, [tie, a]).mate!.targetInstance);
    const taken = calculateSnapTransform(plc, [a, b], 5, 0.1, { occupied: new Set(["rail_a/rail_top"]) });
    expect(taken.mate!.targetInstance).toBe("rail_b");
  });

  it("flips a part whose connector faces the same way as the target's", () => {
    const up = def("upside", [{ node_id: "c", local_position_mm: [0, 0, 0], normal_vector: [0, 0, 1], allowed_mating_type: "DIN_35mm" }]);
    const r = calculateSnapTransform(part("u", up, [0, 0, 6]), [part("rail", RAIL, [0, 0, 0])]);
    expect(r.mate!.normalDot).toBeCloseTo(-1, 14);
    expect(r.position_mm).toEqual([0, 0, 5]);
  });

  it("rounds the turn about the mating axis when asked (Turn 15 degrees)", () => {
    const rail = part("rail", RAIL, [0, 0, 0]);
    const turned = (deg: number) => part("plc1", MODULE, [0, 0, 10], qaxis([0, 0, 1], (deg * Math.PI) / 180));
    const angle = (q: Quat) => (Math.atan2(2 * q[3] * q[2], 1 - 2 * q[2] * q[2]) * 180) / Math.PI;
    expect(angle(calculateSnapTransform(turned(7), [rail], 15, 0.1, { twistStepDeg: 15 }).quaternion)).toBeCloseTo(0, 9);
    expect(angle(calculateSnapTransform(turned(10), [rail], 15, 0.1, { twistStepDeg: 15 }).quaternion)).toBeCloseTo(15, 9);
    expect(angle(calculateSnapTransform(turned(10), [rail], 15).quaternion)).toBeCloseTo(10, 9); // off: kept
  });
});
