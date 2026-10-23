// Jerk-limited point-to-point moves: the seven-segment "S-curve" a servo drive or PLCopen's
// MC_MoveAbsolute runs when it is given a jerk limit (with jerk 0 it is a trapezoid: driveStep).
//
//   jerk:  +J | 0 | -J | 0 (cruise) | -J | 0 | +J
//
// A move is planned once, rest to rest, in closed form, then sampled at any time: the position is
// a piecewise cubic, the acceleration piecewise linear with slope at most J - so the jerk is
// bounded at every step, and the move ends exactly on the target at t = T. The peak velocity is
// vmax when the distance allows a cruise; otherwise the highest velocity whose acceleration and
// deceleration fit the distance.

export interface SMove {
  from: number;
  to: number;
  /** the move's duration (s) */
  T: number;
  /** segment durations, segment jerks (signed), and each segment's start state */
  dur: number[];
  jerk: number[];
  p: number[];
  v: number[];
  a: number[];
  /** the velocity it cruises at (or peaks at, with no cruise) */
  vpeak: number;
}

/** The acceleration phase to velocity v from rest: its time and distance. */
function ramp(v: number, amax: number, jmax: number) {
  const ap = Math.min(amax, Math.sqrt(v * jmax));
  const tj = ap / jmax;
  const tc = ap > 0 ? Math.max(0, v / ap - tj) : 0;
  const time = 2 * tj + tc;
  return { ap, tj, tc, time, dist: (v * time) / 2 };
}

/** Plan a rest-to-rest move from `from` to `to` under vmax, amax, jmax (all > 0). */
export function planMove(from: number, to: number, vmax: number, amax: number, jmax: number): SMove {
  const D = Math.abs(to - from);
  const dir = Math.sign(to - from) || 1;
  let v = vmax;
  let r = ramp(v, amax, jmax);
  let cruise = 0;
  if (2 * r.dist <= D) cruise = (D - 2 * r.dist) / v;
  else {
    // no room to reach vmax: the peak velocity whose two ramps cover D exactly (the ramp's
    // distance grows monotonically with v, so bisection converges)
    let lo = 0, hi = vmax;
    for (let i = 0; i < 80; i++) {
      const mid = (lo + hi) / 2;
      if (2 * ramp(mid, amax, jmax).dist > D) hi = mid; else lo = mid;
    }
    v = lo;
    r = ramp(v, amax, jmax);
  }
  const { tj, tc } = r;
  const J = dir * jmax;
  const dur = [tj, tc, tj, cruise, tj, tc, tj];
  const jerk = [J, 0, -J, 0, -J, 0, J];
  const p: number[] = [], vs: number[] = [], as: number[] = [];
  let P = from, V = 0, A = 0;
  for (let i = 0; i < 7; i++) {
    p.push(P); vs.push(V); as.push(A);
    const t = dur[i], j = jerk[i];
    P += V * t + (A * t * t) / 2 + (j * t * t * t) / 6;
    V += A * t + (j * t * t) / 2;
    A += j * t;
  }
  return { from, to, T: dur.reduce((s, d) => s + d, 0), dur, jerk, p, v: vs, a: as, vpeak: v };
}

/** The state at time t of the move, written into `out` as [pos, vel, acc]. */
export function sampleMove(m: SMove, t: number, out: [number, number, number]): [number, number, number] {
  if (t >= m.T) { out[0] = m.to; out[1] = 0; out[2] = 0; return out; }
  if (t <= 0) { out[0] = m.from; out[1] = 0; out[2] = 0; return out; }
  let i = 0, t0 = 0;
  while (i < 6 && t >= t0 + m.dur[i]) { t0 += m.dur[i]; i++; }
  const s = t - t0, j = m.jerk[i], A = m.a[i], V = m.v[i];
  out[0] = m.p[i] + V * s + (A * s * s) / 2 + (j * s * s * s) / 6;
  out[1] = V + A * s + (j * s * s) / 2;
  out[2] = A + j * s;
  return out;
}
