import { describe, expect, it } from "vitest";
import { _ridesOf, HBW, OVEN, VGR } from "./RunningGear";
import type { CadPart } from "../shared/model";
import machine from "../../public/hbw_parts_up12.json";


// eslint-disable-next-line @typescript-eslint/no-explicit-any
const doc = machine as any;
const list = (parts: CadPart[], axes: Record<string, "x" | "y" | "z">) => Array.from(new Set(parts.map((p) => p.f))).flatMap((f) =>
  _ridesOf(parts, f, axes).map((r) => `${f}: ${r.g.kind} ${r.g.part.n} ${Math.round(r.lo)}..${Math.round(r.hi)}`));

describe("running gear found from the parts", () => {
  it("puts bearings, nuts and shoes where carriages ride", () => {
    const all = { hbw: list(doc.parts, HBW), vgr: list(doc.vgr.parts, VGR), oven: list(doc.oven.parts, OVEN), sorting: list(doc.sorting.parts, {}) };
    // the crane's travel carriage on its rod and screw, the lift on four mast tubes and a screw
    expect(all.hbw).toEqual(expect.arrayContaining([expect.stringMatching(/^travel: rod guide_rod/), expect.stringMatching(/^travel: screw travel_spindle/),
      expect.stringMatching(/^lift: profile mast_tube_4/), expect.stringMatching(/^lift: screw lift_spindle/), expect.stringMatching(/^fork: screw ausleger_spindle/)]));
    // the robot's plunge carriage on its four columns and screw, the arm through it on two rails and a screw
    expect(all.vgr.filter((s) => s.startsWith("plunge: profile")).length).toBe(6);
    expect(all.vgr.filter((s) => s.startsWith("plunge: screw")).length).toBe(2);
    // a piston rod in its cylinder is not a bearing
    expect(all.oven).toEqual([]);
  });
});
