// The HBW's scripted cycle: the keyframes of one cookie's journey and the playback speeds.















import type { CadDoc, PlanKey } from "../shared/model";








// --- the cycle -----------------------------------------------------------------
// One timeline drives the whole table:
//   crane lifts the mould (raw cookie) out of B2 -> hands it to the belt -> belt
//   carries it to the VGR point -> the VGR plays its PROVEN tour
//   (stf-cad/hbw/vgr_path.py: belt -> oven -> rot Lagerstelle -> belt, every leg
//   swept against every module) -> the belt brings the mould, now holding a
//   BAKED cookie, back to the crane -> the crane stows it in C4.
// The VGR waypoints are the exported plan, not typed in here: if the geometry
// changes, the planner re-plans and this view follows.
type Held = "shelf" | "fork" | "belt";
type Key = {
  t: number; l: number; f: number; b: number;
  held: Held; slot: string; cookie: boolean; cc: string;
  vs: number; vr: number; vp: number; vc: number; cup: boolean; carry: string | null;
  taken: string | null; ovenIn: boolean; ovenGo: boolean;
  say: string;
};

/** The flavour colour of a Lagerstelle's cookies: every Lagerstelle holds one flavour. */
export function binColour(doc: CadDoc, bin: string | null) {
  const fl = Object.values(doc.pipeline.flavours).find((f) => f.bin === bin);
  return fl?.colour ?? doc.pipeline.raw_colour;
}

/** One cycle's choreography. `plan` is the VGR's tour (vgr_tours.json: belt -> oven, then the
    oldest finished cookie's Lagerstelle -> belt, or nothing); `collect` is that Lagerstelle. */
export function script(doc: CadDoc, FROM: string, free: string, plan: PlanKey[], collect: string | null): Key[] {
  const T = doc.joints.travel.stops, L = doc.joints.lift.stops, F = doc.joints.fork.stops;
  const hb = doc.stations.hbw_pick[1], vg = doc.stations.vgr_pick[1];
  const RAW = doc.pipeline.raw_colour;
  const BAKED = binColour(doc, collect);
  const colourOf = (c: string | null) => (c === "baked" ? BAKED : RAW);
  // "B2" = shelf row B, bay column 2; every crane stop comes from the export
  const fr = FROM[0], fc = FROM.slice(1), tr = free[0], tcol = free.slice(1);
  const TF = T[`bay${fc}`], TT = T[`bay${tcol}`];
  const LFu = L[`row${fr}_under`], LFl = L[`row${fr}_lift`];
  const LTu = L[`row${tr}_under`], LTl = L[`row${tr}_lift`];

  const home = plan[0];
  const V0 = { vs: home.sw, vr: home.rr, vp: home.pz, vc: 0, cup: false, carry: null };
  const st = { cookie: true, cc: RAW, taken: null as string | null, ovenIn: false, ovenGo: false };
  const out: Key[] = [];
  const k = (
    t: number, l: number, f: number, b: number, held: Held, slot: string,
    vv: { vs: number; vr: number; vp: number; vc: number; cup: boolean; carry: string | null },
    say: string,
  ) => out.push({ t, l, f, b, held, slot, cookie: st.cookie, cc: st.cc, ...vv,
                  taken: st.taken, ovenIn: st.ovenIn, ovenGo: st.ovenGo, say });

  // ---- warehouse -> belt -> VGR point (raw cookie) ----
  k(T.conveyor, L.transit, F.retracted, hb, "shelf", FROM, V0, "park at the conveyor");
  k(TF, L.transit, F.retracted, hb, "shelf", FROM, V0, `travel to bay column ${fc}`);
  k(TF, LFu, F.retracted, hb, "shelf", FROM, V0, `lift spindle: drop 10 mm below shelf ${fr}`);
  k(TF, LFu, F.bay, hb, "shelf", FROM, V0, `Ausleger into ${FROM}, under the mould`);
  k(TF, LFl, F.bay, hb, "fork", FROM, V0, "lift 10 mm — mould off the brackets");
  k(TF, LFl, F.retracted, hb, "fork", FROM, V0, "retract clear of the rack face");
  k(TF, L.transit, F.retracted, hb, "fork", FROM, V0, "raise to transit");
  k(T.conveyor, L.transit, F.retracted, hb, "fork", FROM, V0, "travel to the conveyor");
  k(T.conveyor, L.belt_lift, F.retracted, hb, "fork", FROM, V0, "descend to the hand-over height");
  k(T.conveyor, L.belt_lift, F.conveyor, hb, "fork", FROM, V0, "Ausleger out over the belt — the mould breaks light barrier I2");
  k(T.conveyor, L.belt_under, F.conveyor, hb, "belt", FROM, V0, "table through the belt gap — mould released");
  k(T.conveyor, L.belt_under, F.retracted, hb, "belt", FROM, V0, "retract");
  k(T.conveyor, L.transit, F.retracted, hb, "belt", FROM, V0, "raise clear");
  k(T.conveyor, L.transit, F.retracted, vg, "belt", FROM, V0, "Q1 belt forward — through the hood to I3 at the VGR point");

  // ---- the VGR's proven tour ----
  for (let i = 1; i < plan.length; i++) {
    const p = plan[i], q = plan[i - 1];
    const picked = !q.carry && !!p.carry, placed = !!q.carry && !p.carry;
    if (p.station === "belt" && picked) st.cookie = false;
    if (p.station === "belt" && placed) { st.cookie = true; st.cc = colourOf(q.carry); }
    if (p.station?.startsWith("bay_") && picked) st.taken = p.station.slice(4);
    if (p.station === "oven" && placed) st.ovenIn = true;
    // the bake starts once the arm is clear of the oven: back at transit height (the original
    // path), or on its way to the next station (Upgrade 10's blended path never climbs to transit)
    if (st.ovenIn && !st.ovenGo && (p.station !== "oven" || p.pz >= doc.vgr.plan.transit - 0.5))
      st.ovenGo = true;
    k(T.conveyor, L.transit, F.retracted, vg, "belt", FROM,
      { vs: p.sw, vr: p.rr, vp: p.pz, vc: p.compress, cup: p.cup, carry: p.carry }, `VGR: ${p.say}`);
  }

  // ---- the BAKED cookie goes back into the rack in its mould ----
  const back = collect ? "the finished cookie" : "the empty mould";
  k(T.conveyor, L.transit, F.retracted, hb, "belt", FROM, V0, `Q2 belt reverse — ${back} rides back to the crane`);
  k(T.conveyor, L.belt_under, F.retracted, hb, "belt", FROM, V0, "descend below the mould");
  k(T.conveyor, L.belt_under, F.conveyor, hb, "belt", FROM, V0, "Ausleger under the mould");
  k(T.conveyor, L.belt_lift, F.conveyor, hb, "fork", FROM, V0, `lift — ${back} off the belt`);
  k(T.conveyor, L.belt_lift, F.retracted, hb, "fork", FROM, V0, "retract");
  k(T.conveyor, L.transit, F.retracted, hb, "fork", FROM, V0, "raise to transit");
  k(TT, L.transit, F.retracted, hb, "fork", FROM, V0, `travel to bay column ${tcol} — ${free} is free`);
  k(TT, LTl, F.retracted, hb, "fork", FROM, V0, `descend to shelf ${tr}`);
  k(TT, LTl, F.bay, hb, "fork", FROM, V0, "Ausleger into the empty bay");
  k(TT, LTu, F.bay, hb, "shelf", free, V0, `lower — ${back} is stored in ${free}`);
  k(TT, LTu, F.retracted, hb, "shelf", free, V0, "retract");
  k(TT, L.transit, F.retracted, hb, "shelf", free, V0, "raise to transit");
  k(T.conveyor, L.transit, F.retracted, hb, "shelf", free, V0, "return to park — cycle complete");
  return out;
}

export const SPEED = 14.27; // mm/s, the real encoder-motor rate
export const BELT_SPEED = 25; // mm/s - slowed so the hand-over reads clearly
export const RATE = 4; // playback speedup
/** Review aid: ?speed=N plays the cell N times faster still (e.g. to watch a whole order). */
export const PLAYBACK = Math.max(0.1, Math.min(50, Number(new URLSearchParams(window.location.search).get("speed")) || 1));
