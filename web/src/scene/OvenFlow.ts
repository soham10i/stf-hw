// The workpiece's journey from the oven tray to its Lagerstelle - ONE cookie,
// one continuous path, no teleporting.
//
// Order and I/O are the booklet's (536634 p.30 / p.36); every position comes
// from the exported geometry (oven.flow, sorting.handovers, the part table):
//
//   Ofenschieber in -> Ofentuer shut -> bake (Q9) -> door open -> slider out
//   -> the station's own Sauger lifts it (Q12 down, Q11 vacuum) -> carries it
//   to the Drehtisch -> Drehtisch to the Saege (I4), saw dwell (Q4) -> to the
//   Foerderband (I2) -> Auswerfer (Q14) pushes it onto the belt -> the belt
//   ends against the sorting belt's rail and hands it across the corner
//   -> Farbsensor A4 -> I1 pulses counted -> its ejector fires -> the cookie
//   slides down its Lagerstelle to the end stop (its light barrier), the very
//   point the VGR's cup comes down on.
//
// The timeline is a list of steps, each easing some joints to a target while
// the cookie is held by ONE thing (its `mode`). The cookie's position is then
// derived from the joints of whatever holds it, so it can never drift away
// from the machine that is carrying it.

import * as THREE from "three";
import type { CadDoc } from "../shared/model";

export type Mode = "tray" | "cup" | "disc" | "line" | "eject" | "slide" | "bay";

export interface FlowState {
  slider: number; door: number; turn: number; sauger: number; lower: number; push: number;
  lamp: number; saw: number; vac: number; baked: number;
  ly: number;       // distance travelled along the belt path (oven belt -> sorting belt)
  eject: number;    // the firing ejector's stroke
  chute: number;    // how far it has slid down the Lagerstelle past the ejector's reach
}

interface Step { d: number; say: string; to: Partial<FlowState>; mode: Mode }

/** One sample of the flow, written in place by Flow.sample (no allocation per frame). */
export interface FlowSample { s: FlowState; mode: Mode; say: string; pos: [number, number, number] }
export const FLOW_KEYS = ["slider", "door", "turn", "sauger", "lower", "push", "lamp", "saw", "vac", "baked", "ly", "eject", "chute"] as const;
export function newSample(): FlowSample {
  const s = {} as FlowState;
  for (const k of FLOW_KEYS) s[k] = 0;
  return { s, mode: "tray", say: "", pos: [0, 0, 0] };
}

export interface Flow {
  steps: (Step & { t0: number; from: FlowState })[];
  total: number;
  arrive: number;           // time the cookie enters its Lagerstelle
  /** the end of the colour reading: up to here the pass and reject journeys are the same, so the
      inspection's verdict must be in by then (the coordinator holds the belt until it is) */
  decide: number;
  bin: string;
  binIndex: number;
  /** The joints, the holder, the caption and the cookie's position at time t, written into
      `out` - the 60 fps path: nothing is allocated. */
  sample: (t: number, out: FlowSample) => FlowSample;
  at: (t: number) => { s: FlowState; mode: Mode; say: string };
  /** belt surface travel for each belt, from the path distance */
  belts: (ly: number) => { oven: number; sort: number };
  beltOven: (ly: number) => number;
  beltSort: (ly: number) => number;
  pos: (s: FlowState, mode: Mode) => [number, number, number];
}

const BELT = 60; // mm/s of playback on the belts - slowed so the hand-over reads

/** The cookie's journey. `reject`: the inspection rejected it - no ejector fires, and the belt
    carries it past the Lagerstellen to the end of the line, where it is held for the operator.
    Up to the end of the colour reading (`decide`) both journeys are the same, at the same speed:
    the coordinator commits a cookie to one of them there, never later. */
export function buildFlow(doc: CadDoc, flavour: string, bakeExtra = 0, reject = false): Flow {
  const J = doc.oven.joints, F = doc.oven.flow;
  // the oven is placed rotated +90 about Z: module (x, y) -> (-y + tx, x + ty)
  const [ox, oy] = doc.factory.oven_placement.translate;
  const fromOven = (x: number, y: number): [number, number] => [-y + ox, x + oy];
  const [stx, sty] = doc.factory.sort_placement.translate;
  const bin = doc.pipeline.flavours[flavour]?.bin ?? doc.sorting.colours[0];
  const binIndex = Math.max(0, doc.sorting.colours.indexOf(bin));
  const mV = doc.pipeline.flavours[flavour]?.mV;

  // sorting line, in its own frame (x along the belt, y toward the bays)
  const sp = (n: string) => doc.sorting.parts.find((p) => p.n === n);
  const web = sp("belt_web")!;
  const beltC = web.p[1] + (web.s[1] as number) / 2;
  const sensor = sp("A4_colour_sensor");
  const sensorX = sensor ? sensor.p[0] + (sensor.s[0] as number) / 2 : 120;
  const [ejX, bayY] = doc.sorting.handovers[bin];
  const pusher = sp(`pusher_${bin}`);
  // the ejectors push toward the Lagerstellen: -Y in the sorting frame
  const dir = Math.sign(bayY - beltC) || 1;
  const gap = !pusher ? 0 : dir < 0
    ? pusher.p[1] - (beltC + F.wp_d / 2)
    : beltC - F.wp_d / 2 - (pusher.p[1] + (pusher.s[1] as number));
  const ejMax = doc.sorting.joints.push.limits[1];
  const bayEj = Math.min(Math.abs(bayY - beltC), ejMax - gap);
  // the ejector's stroke ends short of the Lagerstelle's end stop: the cookie slides the rest
  // of the way (the bay floor is level with the belt) and rests where the VGR picks it up
  const chute = Math.abs(bayY - beltC) - bayEj;
  // sorting (x, y) -> factory: rotated +90 about Z, then translated
  const fromSort = (x: number, y: number): [number, number] => [-y + stx, x + sty];

  const [ttx, tty] = F.tt;
  const nest = (turn: number): [number, number] => {
    const t = THREE.MathUtils.degToRad(turn);
    const dx = 0, dy = -F.tt_r;
    return [ttx + dx * Math.cos(t) - dy * Math.sin(t), tty + dx * Math.sin(t) + dy * Math.cos(t)];
  };
  // The belt path, in the factory frame: pushed off the disc, along the oven
  // belt to its end, across onto the sorting belt's centre line (the oven belt
  // ends against the sorting belt's rail, both at the same height), then along
  // the sorting belt to the ejector of the cookie's bin.
  const bandM = nest(F.stations.band)[1];
  const V2 = (p: [number, number]) => new THREE.Vector2(p[0], p[1]);
  const P0 = V2(fromOven(F.x_line, bandM));
  const P1 = V2(fromOven(F.x_line, bandM + F.push));
  const P2 = V2(fromOven(F.x_line, F.belt[1]));
  // the nose ends above the sorting belt's centre line: the cookie drops 15 mm
  // onto it here, then rides along it
  const P3 = new THREE.Vector2(fromSort(0, beltC)[0] - 0.5, P2.y);
  const sortZ = web.p[2] + (web.s[2] as number);
  const P4 = V2(fromSort(sensorX, beltC));
  // a rejected cookie rides to the end of the belt, short of its drive drum
  const endX = web.p[0] + (web.s[0] as number) - F.wp_d / 2 - 8;
  const P5 = V2(fromSort(reject ? endX : ejX, beltC));
  const path = [P0, P1, P2, P3, P4, P5];
  const cum = path.map((_, i) => path.slice(1, i + 1).reduce((a, p, j) => a + p.distanceTo(path[j]), 0));
  const bandY = 0;
  const pushedY = cum[1];
  const handY = cum[3];
  const sensorLy = cum[4];
  const ejectLy = cum[5];

  const S = J.slider.stops, D = J.door.stops, SA = J.sauger.stops, T = J.turn.stops;
  const steps: Step[] = [
    { d: 2, mode: "tray", say: "Oven Q5: the Ofenschieber carries the cookie into the chamber (I6)", to: { slider: S.innen } },
    { d: 1, mode: "tray", say: "Oven Q13: the Ofentür shuts", to: { door: D.shut } },
    { d: 4 + bakeExtra, mode: "tray", say: "Oven Q9 lamp on: baking, the dough takes its flavour colour", to: { lamp: 1, baked: 1 } },
    { d: 1, mode: "tray", say: "Oven Q13: the door opens", to: { lamp: 0, door: D.open } },
    { d: 2, mode: "tray", say: "Oven Q6: the Ofenschieber extends onto the flow line (I7)", to: { slider: S.aussen } },
    { d: 1.6, mode: "tray", say: "Oven Q7: the station's own Sauger runs to the oven (I8)", to: { sauger: SA.oven } },
    { d: 1, mode: "tray", say: "Oven Q12: one pneumatic stroke puts the cup on the cookie's top face", to: { lower: F.stroke } },
    { d: 0.6, mode: "tray", say: "Oven Q11: vacuum on", to: { vac: 1 } },
    { d: 1, mode: "cup", say: "Oven Q12 vents: the cup rises with the cookie", to: { lower: 0 } },
    { d: 1.6, mode: "cup", say: "Oven Q8: the Sauger carries it to the Drehtisch (I5)", to: { sauger: SA.turntable } },
    { d: 1, mode: "cup", say: "Oven Q12: the same stroke sets it in the disc nest", to: { lower: F.stroke } },
    { d: 0.6, mode: "disc", say: "Oven Q11 off: released onto the Drehtisch", to: { vac: 0 } },
    { d: 1, mode: "disc", say: "Oven: the cup rises clear", to: { lower: 0 } },
    { d: 2, mode: "disc", say: "Oven Q1: the Drehtisch turns it under the Säge (I4)", to: { turn: T.saege } },
    { d: 3, mode: "disc", say: "Oven Q4: the Säge runs - the processing dwell", to: { saw: 90 } },
    { d: 2, mode: "disc", say: "Oven Q1: the Drehtisch turns it to the Förderband (I2)", to: { turn: T.band } },
    { d: 1, mode: "line", say: "Oven Q14: the Auswerfer pushes it off the disc onto the belt", to: { push: F.push, ly: pushedY } },
    { d: 0.8, mode: "line", say: "Oven Q3: the belt runs, the Auswerfer returns", to: { push: 0, ly: pushedY + 20 } },
    { d: (cum[2] - pushedY - 20) / BELT, mode: "line", say: "Oven belt: through I3 at its end; I3 sends the Drehtisch home", to: { ly: cum[2], turn: T.sauger } },
    { d: 0.8, mode: "line", say: "Hand-over: over the nose roller, the cookie drops onto the Sortierstrecke's belt (I2), Q1 on", to: { ly: handY + 10 } },
    { d: (sensorLy - handY - 10) / BELT, mode: "line", say: "Sortierstrecke belt: into the darkened colour lock", to: { ly: sensorLy } },
    { d: 1.4, mode: "line", say: `Farbsensor A4 reads ~${mV ?? "?"} mV -> ${flavour} -> Lagerstelle ${bin}`, to: { ly: sensorLy + 12 } },
    ...(reject ? [
      { d: (ejectLy - sensorLy - 12) / BELT, mode: "line" as Mode, say: "Inspection: REJECTED - no ejector fires; the cookie rides on past the Lagerstellen", to: { ly: ejectLy } },
      { d: 1.5, mode: "line" as Mode, say: "Held at the end of the line for the operator: the inspection rejected it", to: {} },
    ] : [
      { d: (ejectLy - sensorLy - 12) / BELT, mode: "line" as Mode, say: `I3 passed; the I1 Impulstaster counts belt pulses to the ${bin} ejector`, to: { ly: ejectLy } },
      { d: 1, mode: "eject" as Mode, say: `Q${3 + binIndex}: the ${bin} ejector pushes it off the belt into its Lagerstelle`, to: { eject: bayEj + gap } },
      { d: 0.4 + chute / 120, mode: "slide" as Mode, say: `It slides down the ${bin} Lagerstelle to the end stop (I${5 + binIndex}); the ejector returns`, to: { eject: 0, chute } },
      { d: 0.8, mode: "bay" as Mode, say: `The baked cookie rests in the ${bin} Lagerstelle, where the VGR collects from`, to: {} },
    ]),
  ];

  const s0: FlowState = {
    slider: S.aussen, door: D.open, turn: T.sauger, sauger: SA.turntable, lower: 0, push: 0,
    lamp: 0, saw: 0, vac: 0, baked: 0, ly: bandY, eject: 0, chute: 0,
  };
  let t0 = 0;
  let cur = { ...s0 };
  const timed = steps.map((st) => {
    const from = { ...cur };
    cur = { ...cur, ...st.to };
    const r = { ...st, t0, from };
    t0 += st.d;
    return r;
  });
  const total = t0;
  // the cookie has arrived once it has come to rest at the Lagerstelle's end stop
  const slid = timed.find((st) => st.mode === "slide");
  const arrive = slid ? slid.t0 + slid.d : total;
  const last: Mode = reject ? "line" : "bay";
  const read = timed.find((st) => st.say.startsWith("Farbsensor"));
  const decide = read ? read.t0 + read.d : total;

  // the sorting frame -> factory frame, and the oven frame -> factory frame, into `out`
  const sortTo = (x: number, y: number, z: number, out: [number, number, number]) => {
    out[0] = -y + stx; out[1] = x + sty; out[2] = z;
  };
  const ovenTo = (x: number, y: number, z: number, out: [number, number, number]) => {
    out[0] = -y + ox; out[1] = x + oy; out[2] = z;
  };
  const posInto = (s: FlowState, mode: Mode, out: [number, number, number]) => {
    switch (mode) {
      case "tray": ovenTo(s.slider + F.tray_w / 2, F.tray_y, F.z_w, out); return;
      case "cup": ovenTo(F.x_line, s.sauger, F.cup_up - s.lower - F.wp_h, out); return;
      case "disc": {
        const t = THREE.MathUtils.degToRad(s.turn);
        // the nest sits at (0, -tt_r) from the disc's centre, turned by `turn`
        ovenTo(ttx + F.tt_r * Math.sin(t), tty - F.tt_r * Math.cos(t), F.z_w, out);
        return;
      }
      case "line": {
        // along the polyline P0..P5 by distance ly
        const d = s.ly;
        let i = 1;
        while (i < path.length - 1 && d > cum[i]) i++;
        const span = cum[i] - cum[i - 1] || 1;
        const u = Math.min(1, Math.max(0, (d - cum[i - 1]) / span));
        const a = path[i - 1], b = path[i];
        // off the nose: falls from the oven belt (z_w) onto the sorting belt
        const fall = Math.min(1, Math.max(0, (d - cum[2] + 12) / 12));
        out[0] = a.x + (b.x - a.x) * u; out[1] = a.y + (b.y - a.y) * u; out[2] = F.z_w + (sortZ - F.z_w) * fall * fall;
        return;
      }
      case "eject": sortTo(ejX, beltC + dir * Math.max(0, Math.min(bayEj, s.eject - gap)), sortZ, out); return;
      case "slide": {
        // decelerating as it runs out against the end stop
        const u = chute > 0 ? s.chute / chute : 1;
        sortTo(ejX, beltC + dir * (bayEj + chute * (1 - (1 - u) * (1 - u))), sortZ, out);
        return;
      }
      case "bay": sortTo(ejX, bayY, sortZ, out); return;
    }
  };

  const sample = (t: number, out: FlowSample) => {
    const o = out.s;
    if (t <= 0) {
      for (const k of FLOW_KEYS) o[k] = s0[k];
      out.mode = "tray"; out.say = "";
    } else {
      let hit = -1;
      for (let i = 0; i < timed.length; i++) if (t < timed[i].t0 + timed[i].d) { hit = i; break; }
      if (hit < 0) {
        for (const k of FLOW_KEYS) o[k] = cur[k];
        out.mode = last; out.say = "";
      } else {
        const st = timed[hit];
        const u = THREE.MathUtils.smoothstep((t - st.t0) / st.d, 0, 1);
        for (const k of FLOW_KEYS) {
          const to = st.to[k];
          o[k] = to === undefined ? st.from[k] : st.from[k] + (to - st.from[k]) * u;
        }
        out.mode = st.mode; out.say = st.say;
      }
    }
    posInto(o, out.mode, out.pos);
    return out;
  };
  const at = (t: number) => {
    const r = sample(t, newSample());
    return { s: r.s, mode: r.mode, say: r.say };
  };
  const pos = (s: FlowState, mode: Mode): [number, number, number] => {
    const out: [number, number, number] = [0, 0, 0];
    posInto(s, mode, out);
    return out;
  };
  const beltOven = (ly: number) => Math.min(ly, cum[2]);
  const beltSort = (ly: number) => Math.max(0, ly - cum[2]);
  const belts = (ly: number) => ({ oven: beltOven(ly), sort: beltSort(ly) });
  return { steps: timed, total, arrive, decide, bin, binIndex, sample, at, pos, belts, beltOven, beltSort };
}
