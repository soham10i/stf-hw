// Poses in float64: a position (mm) and a unit quaternion (x, y, z, w). Kinematic chains are
// composed here, in double precision, so a link's pose never passes through the physics engine's
// float32 storage before it is published.
import type { Quat, Vec3 } from "./schema";

export interface Pose {
  p: Vec3;
  q: Quat;
}

export const IDENTITY: Pose = { p: [0, 0, 0], q: [0, 0, 0, 1] };

export function qmul(a: Quat, b: Quat): Quat {
  const [ax, ay, az, aw] = a;
  const [bx, by, bz, bw] = b;
  return [
    aw * bx + ax * bw + ay * bz - az * by,
    aw * by - ax * bz + ay * bw + az * bx,
    aw * bz + ax * by - ay * bx + az * bw,
    aw * bw - ax * bx - ay * by - az * bz,
  ];
}

export const qconj = (q: Quat): Quat => [-q[0], -q[1], -q[2], q[3]];

export function qnormalize(q: Quat): Quat {
  const n = Math.hypot(q[0], q[1], q[2], q[3]);
  if (n === 0) throw new RangeError("a zero quaternion has no rotation");
  return [q[0] / n, q[1] / n, q[2] / n, q[3] / n];
}

/** The rotation of `angle` radians about the unit `axis`. */
export function qaxis(axis: Vec3, angle: number): Quat {
  const s = Math.sin(angle / 2);
  return [axis[0] * s, axis[1] * s, axis[2] * s, Math.cos(angle / 2)];
}

/** `v` rotated by the unit quaternion `q`. */
export function rotate(q: Quat, v: Vec3): Vec3 {
  const [x, y, z, w] = q;
  // t = 2 * cross(q.xyz, v); v' = v + w * t + cross(q.xyz, t)
  const tx = 2 * (y * v[2] - z * v[1]);
  const ty = 2 * (z * v[0] - x * v[2]);
  const tz = 2 * (x * v[1] - y * v[0]);
  return [
    v[0] + w * tx + (y * tz - z * ty),
    v[1] + w * ty + (z * tx - x * tz),
    v[2] + w * tz + (x * ty - y * tx),
  ];
}

/** a then b: the pose of b's frame placed in a's frame. */
export function compose(a: Pose, b: Pose): Pose {
  const r = rotate(a.q, b.p);
  return { p: [a.p[0] + r[0], a.p[1] + r[1], a.p[2] + r[2]], q: qnormalize(qmul(a.q, b.q)) };
}

export function invert(a: Pose): Pose {
  const qi = qconj(a.q);
  const p = rotate(qi, a.p);
  return { p: [-p[0], -p[1], -p[2]], q: qi };
}

/** Spherical interpolation between unit quaternions (the short way round). */
export function slerp(a: Quat, b: Quat, t: number): Quat {
  let [bx, by, bz, bw] = b;
  let d = a[0] * bx + a[1] * by + a[2] * bz + a[3] * bw;
  if (d < 0) { d = -d; bx = -bx; by = -by; bz = -bz; bw = -bw; }
  if (d > 0.9995) {
    return qnormalize([a[0] + t * (bx - a[0]), a[1] + t * (by - a[1]), a[2] + t * (bz - a[2]), a[3] + t * (bw - a[3])]);
  }
  const th = Math.acos(d);
  const s = Math.sin(th);
  const ka = Math.sin((1 - t) * th) / s;
  const kb = Math.sin(t * th) / s;
  return [ka * a[0] + kb * bx, ka * a[1] + kb * by, ka * a[2] + kb * bz, ka * a[3] + kb * bw];
}

export const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
