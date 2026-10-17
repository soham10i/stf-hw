// The joints the twin draws trimmed (joints.ts), found in the exported machine.
import { describe, expect, it } from "vitest";
import { jointTrims } from "./joints";
import machine from "../../public/hbw_parts_up12.json";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const doc = machine as any;

describe("joints", () => {
  it("trims a rack's shelf support at the face of the post it is slotted into", () => {
    const t = jointTrims(doc.parts);
    // shelf_A1_L spans x 70..100, rack_post_1 x 45..75: drawn from x = 75 on
    expect(t.get("shelf_A1_L")).toEqual([{ axis: 0, at: 75, keep: 1 }]);
    // shelf_A1_R spans x 140..170, rack_post_2 x 165..195: drawn up to x = 165
    expect(t.get("shelf_A1_R")).toEqual([{ axis: 0, at: 165, keep: -1 }]);
    expect(t.has("rack_post_1")).toBe(false);          // the host is drawn whole
  });

  it("trims a guard post at both frame rails it runs between", () => {
    const t = jointTrims(doc.safety.parts).get("guard_post_2") ?? [];
    expect(t).toContainEqual({ axis: 2, at: 0, keep: 1 });
    expect(t).toContainEqual({ axis: 2, at: 900, keep: -1 });
  });

  it("leaves parts that move alone: their joints change as they move", () => {
    const moving = doc.parts.filter((p: { f?: string }) => (p.f ?? "world") !== "world").map((p: { n: string }) => p.n);
    const t = jointTrims(doc.parts);
    expect(moving.length).toBeGreaterThan(0);
    expect(moving.some((n: string) => t.has(n))).toBe(false);
  });
});
