// The HBW's scripted cycle: the keyframes of one cookie's journey and the playback speeds.















import type { CadDoc, PlanKey } from "../shared/model";








// --- the cycle -----------------------------------------------------------------
// One timeline drives the whole table:
//   crane lifts the mould (raw cookie) out of B2 -> hands it to the belt -> belt
//   carries it to the VGR point -> the VGR plays its PROVEN tour
//   (stf-cad/hbw/vgr_path.py: belt -> oven -> rot Lagerstelle -> belt, every leg
//   swept against every module). Once the VGR has lifted the raw cookie off,
//   the belt returns the EMPTY mould and the crane stores it back in its own
//   slot, so it does not stand on the belt through the whole bake. While the
//   cookie bakes, the crane fetches the mould again and the belt brings it to
//   the VGR point, where the VGR sets the BAKED cookie into it -> the belt
//   brings it back to the crane -> the crane stows it in the slot it came from.
// The VGR waypoints are the exported plan, not typed in here: if the geometry
// changes, the planner re-plans and this view follows.
type Held = "shelf" | "fork" | "belt";
type Key = {
  t: number; l: number; f: number; b: number;
  held: Held; slot: string; cookie: boolean; cc: string;
  vs: number; vr: number; vp: number; vc: number; cup: boolean; carry: string | null;
  taken: string | null; ovenIn: boolean; ovenGo: boolean;
  /** the first step toward the Lagerstelle: the VGR waits before it until the cookie has arrived */
  bayGo?: boolean;
  say: string;
};

/** The flavour colour of a Lagerstelle's cookies: every Lagerstelle holds one flavour. */
export function binColour(doc: CadDoc, bin: string | null) {
  const fl = Object.values(doc.pipeline.flavours).find((f) => f.bin === bin);
  return fl?.colour ?? doc.pipeline.raw_colour;
}

/** One cycle's choreography. `plan` is the VGR's tour (vgr_tours.json: belt -> oven, then the
    oldest finished cookie's Lagerstelle -> belt, or nothing); `collect` is that Lagerstelle.
    `rest` (a rack slot) short-circuits the park detour: after the empty mould is stowed the
    crane travels straight to that slot's bay and rests there, because the next order's pick is
    known — the shortest path between jobs, and the next cycle then starts `fromRest` (already at
    its pick bay, so its head skips the park-and-travel keys). */
export function script(doc: CadDoc, FROM: string, free: string, plan: PlanKey[], collect: string | null,
                       rest: string | null = null, fromRest = false): Key[] {
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
  type VV = { vs: number; vr: number; vp: number; vc: number; cup: boolean; carry: string | null };
  const V0: VV = { vs: home.sw, vr: home.rr, vp: home.pz, vc: 0, cup: false, carry: null };
  const st = { cookie: true, cc: RAW, taken: null as string | null, ovenIn: false, ovenGo: false };
  const out: Key[] = [];
  const k = (
    t: number, l: number, f: number, b: number, held: Held, slot: string,
    vv: VV,
    say: string,
  ) => out.push({ t, l, f, b, held, slot, cookie: st.cookie, cc: st.cc, ...vv,
                  taken: st.taken, ovenIn: st.ovenIn, ovenGo: st.ovenGo, say });

  // ---- warehouse -> belt -> VGR point (raw cookie) ----
  if (fromRest) {
    // the previous cycle stowed the empty mould and came straight here to rest: the pick starts
    // at once, no park detour
    k(TF, L.transit, F.retracted, hb, "shelf", FROM, V0, `resting at ${FROM} — the next order's pick, brought here by the last job`);
  } else {
    k(T.conveyor, L.transit, F.retracted, hb, "shelf", FROM, V0, "park at the conveyor");
    k(TF, L.transit, F.retracted, hb, "shelf", FROM, V0, `travel to bay column ${fc}`);
  }
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

  // ---- the empty mould: back into its slot, and out again for the baked cookie ----
  // The VGR holds its pose (vv) while the crane works; nothing else moves.
  const stowEmpty = (vv: VV, rest: string | null) => {
    k(T.conveyor, L.transit, F.retracted, hb, "belt", FROM, vv, "Q2 belt reverse — the empty mould rides back to the crane");
    k(T.conveyor, L.belt_under, F.retracted, hb, "belt", FROM, vv, "descend below the empty mould");
    k(T.conveyor, L.belt_under, F.conveyor, hb, "belt", FROM, vv, "Ausleger under the empty mould");
    k(T.conveyor, L.belt_lift, F.conveyor, hb, "fork", FROM, vv, "lift — the empty mould off the belt");
    k(T.conveyor, L.belt_lift, F.retracted, hb, "fork", FROM, vv, "retract");
    k(T.conveyor, L.transit, F.retracted, hb, "fork", FROM, vv, "raise to transit");
    k(TF, L.transit, F.retracted, hb, "fork", FROM, vv, `travel to bay column ${fc} — the mould goes home to ${FROM}`);
    k(TF, LFl, F.retracted, hb, "fork", FROM, vv, `descend to shelf ${fr}`);
    k(TF, LFl, F.bay, hb, "fork", FROM, vv, "Ausleger into its own bay");
    k(TF, LFu, F.bay, hb, "shelf", FROM, vv, `lower — the empty mould waits in ${FROM} while the cookie bakes`);
    k(TF, LFu, F.retracted, hb, "shelf", FROM, vv, "retract");
    k(TF, L.transit, F.retracted, hb, "shelf", FROM, vv, "raise to transit");
    if (rest) {
      // the next order's pick is known: go straight to its bay and rest there — the shortest
      // path between jobs, no detour to the conveyor
      const rc = rest.slice(1), TRr = T[`bay${rc}`];
      k(TRr, L.transit, F.retracted, hb, "shelf", FROM, vv, `next order waiting: rest at ${rest} — the crane's next pick, on the shortest path`);
    } else {
      k(T.conveyor, L.transit, F.retracted, hb, "shelf", FROM, vv, "return to park");
    }
  };
  const fetchEmpty = (vv: VV) => {
    k(TF, L.transit, F.retracted, hb, "shelf", FROM, vv, `travel to bay column ${fc} — fetch the empty mould for the baked cookie`);
    k(TF, LFu, F.retracted, hb, "shelf", FROM, vv, `drop 10 mm below shelf ${fr}`);
    k(TF, LFu, F.bay, hb, "shelf", FROM, vv, `Ausleger into ${FROM}, under the empty mould`);
    k(TF, LFl, F.bay, hb, "fork", FROM, vv, "lift 10 mm — the mould off the brackets");
    k(TF, LFl, F.retracted, hb, "fork", FROM, vv, "retract clear of the rack face");
    k(TF, L.transit, F.retracted, hb, "fork", FROM, vv, "raise to transit");
    k(T.conveyor, L.transit, F.retracted, hb, "fork", FROM, vv, "travel to the conveyor");
    k(T.conveyor, L.belt_lift, F.retracted, hb, "fork", FROM, vv, "descend to the hand-over height");
    k(T.conveyor, L.belt_lift, F.conveyor, hb, "fork", FROM, vv, "Ausleger out over the belt (I2)");
    k(T.conveyor, L.belt_under, F.conveyor, hb, "belt", FROM, vv, "table through the belt gap — mould released");
    k(T.conveyor, L.belt_under, F.retracted, hb, "belt", FROM, vv, "retract");
    k(T.conveyor, L.transit, F.retracted, hb, "belt", FROM, vv, "raise clear");
    k(T.conveyor, L.transit, F.retracted, vg, "belt", FROM, vv, "Q1 belt forward — the empty mould waits at the VGR point (I3)");
  };

  // ---- the VGR's proven tour ----
  let stowed = false, fetched = false, toBay = false;
  for (let i = 1; i < plan.length; i++) {
    const p = plan[i], q = plan[i - 1];
    const picked = !q.carry && !!p.carry, placed = !!q.carry && !p.carry;
    const vq = { vs: q.sw, vr: q.rr, vp: q.pz, vc: q.compress, cup: q.cup, carry: q.carry };
    // the VGR has left the belt with the raw cookie: the empty mould goes home
    if (!stowed && !st.cookie && p.station !== "belt") { stowEmpty(vq, collect ? rest : null); stowed = true; }
    // the cookie is baking and the VGR is clear of the oven: the crane brings the mould back
    if (collect && stowed && !fetched && st.ovenGo && p.station !== "oven") { fetchEmpty(vq); fetched = true; }
    if (p.station === "belt" && picked) st.cookie = false;
    if (p.station === "belt" && placed) { st.cookie = true; st.cc = colourOf(q.carry); }
    if (p.station?.startsWith("bay_") && picked) st.taken = p.station.slice(4);
    if (p.station === "oven" && placed) st.ovenIn = true;
    // the bake starts once the arm is clear of the oven: back at transit height (the original
    // path), or on its way to the next station (Upgrade 10's blended path never climbs to transit)
    if (st.ovenIn && !st.ovenGo && (p.station !== "oven" || p.pz >= doc.vgr.plan.transit - 0.5))
      st.ovenGo = true;
    // the crane and the belt stay where the last step left them (the mould on the belt, or home)
    const h = out[out.length - 1];
    k(h.t, h.l, h.f, h.b, h.held, h.slot,
      { vs: p.sw, vr: p.rr, vp: p.pz, vc: p.compress, cup: p.cup, carry: p.carry }, `VGR: ${p.say}`);
    if (!toBay && p.station?.startsWith("bay_")) { out[out.length - 1].bayGo = true; toBay = true; }
  }
  // no cookie comes back (no order): the empty mould is already home
  if (!collect) {
    if (!stowed) stowEmpty(V0, null);
    return out;
  }

  // ---- the BAKED cookie goes back into the rack in its mould ----
  const back = "the finished cookie";
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
export const PLAYBACK = Math.max(0.1, Math.min(50, Number(new URLSearchParams(typeof window === "undefined" ? "" : window.location.search).get("speed")) || 1));
/** Fast-forward, set live by the control in the twin's chrome: the clock runs PLAYBACK × this
    faster, so 2×/4×/8× watch a whole order without waiting on every motion. */
export const FF = { value: 1 };
