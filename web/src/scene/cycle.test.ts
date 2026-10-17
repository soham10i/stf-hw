// The order cycle's choreography (timeline.ts, OvenFlow.ts), checked on the exported machine:
// the empty mould goes home while the cookie bakes and is back on the belt for the baked
// cookie, and the sorted cookie comes to rest exactly where the VGR's cup comes down.
import { describe, expect, it } from "vitest";
import { script } from "./timeline";
import { buildFlow } from "./OvenFlow";
import machine from "../../public/hbw_parts_up12.json";
import tours from "../../public/vgr_tours.json";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const doc = machine as any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const T = (tours as any).tours;

describe("the empty mould during the bake", () => {
  for (const [flavour, f] of Object.entries(doc.pipeline.flavours) as [string, { bin: string }][]) {
    it(`${flavour}: stored in its own slot while the cookie bakes, back on the belt for the baked cookie`, () => {
      const keys = script(doc, "C1", "C1", T[f.bin], f.bin);
      const rawPick = keys.findIndex((k) => k.carry === "raw");
      const ovenIn = keys.findIndex((k) => k.ovenIn);
      const bakedPlace = keys.findIndex((k, i) => i > 0 && keys[i - 1].carry === "baked" && !k.carry);
      expect(rawPick).toBeGreaterThan(0);
      expect(bakedPlace).toBeGreaterThan(ovenIn);
      // between the raw pick and the oven, the empty mould is stowed in C1
      const home = keys.slice(rawPick, ovenIn + 1).filter((k) => k.held === "shelf");
      expect(home.length).toBeGreaterThan(0);
      expect(home.every((k) => k.slot === "C1" && !k.cookie)).toBe(true);
      // when the VGR sets the baked cookie down, the mould waits on the belt at the VGR point
      const at = keys[bakedPlace];
      expect(at.held).toBe("belt");
      expect(at.b).toBe(doc.stations.vgr_pick[1]);
      expect(at.cookie).toBe(true);
      // ...and the cycle ends with the baked cookie stored back in C1
      const end = keys[keys.length - 1];
      expect([end.held, end.slot, end.cookie]).toEqual(["shelf", "C1", true]);
    });
  }
  it("no empty mould stands on the belt while the VGR is at the oven or a Lagerstelle", () => {
    const keys = script(doc, "B2", "B2", T.blau, "blau");
    const away = keys.filter((k) => k.say.startsWith("VGR:") && k.ovenIn && !k.cookie);
    expect(away.filter((k) => k.held === "belt" && k.b !== doc.stations.vgr_pick[1])).toEqual([]);
  });
});

describe("the sorted cookie", () => {
  for (const [flavour, f] of Object.entries(doc.pipeline.flavours) as [string, { bin: string }][]) {
    it(`${flavour}: slides to the end of its Lagerstelle, where the VGR picks it up, with no jump`, () => {
      const flow = buildFlow(doc, flavour);
      const end = flow.at(flow.total + 1);
      const [x, y] = flow.pos(end.s, end.mode);
      // the VGR's pick point at the Lagerstelle (sorting frame -> factory frame)
      const [hx, hy] = doc.sorting.handovers[f.bin];
      const [tx, ty] = doc.factory.sort_placement.translate;
      expect(Math.hypot(x - (-hy + tx), y - (hx + ty))).toBeLessThan(0.5);
      // the path is continuous: no frame-to-frame step of more than 15 mm at 60 fps
      let prev: number[] | null = null, worst = 0;
      for (let t = 0; t <= flow.total; t += 1 / 60) {
        const st = flow.at(t);
        const p = flow.pos(st.s, st.mode);
        if (prev) worst = Math.max(worst, Math.hypot(p[0] - prev[0], p[1] - prev[1], p[2] - prev[2]));
        prev = p;
      }
      expect(worst).toBeLessThan(15);
      // it has come to rest when the VGR is allowed to collect it
      const r = flow.at(flow.arrive);
      const pr = flow.pos(r.s, r.mode);
      expect(Math.hypot(pr[0] - x, pr[1] - y)).toBeLessThan(0.5);
    });
  }
});
