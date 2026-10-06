// DT-2: the twin's player rules in JavaScript (three.js math) - the SAME rules as twin/playback.py and the FreeCAD
// player (motion/motion_player.py). No DOM: the browser viewer (viewer.js) and the Node check (check_player.mjs) both
// run this file, so the gate tests the code the browser runs.
//
// Units mm, the model frame (Z up). A part node's local matrix (inside the GLB's root, which scales mm -> m and turns
// Z-up into Y-up) is:
//   rigid track     M(t, q) * T(offset)         v = [tx, ty, tz, qx, qy, qz, qw, vis]
//   follower        M(t, q of its body) * T(offset)
//   reshaped track  the part is hidden; a unit cylinder (base at 0, axis +z, diameter 1, height 1) gets
//                   T(c) * R(axis) * S(dia, dia, max(len, 0.01))           v = {c, ax, dia, len, col?, vis?}
//   spawned         a unit cylinder: M(t, q) * [cylinder of spawn p, s]
//   glow            the element's colour: bits[k] ? on : off
import { Matrix4, Quaternion, Vector3 } from "three";

export function rigidMatrix(v) {
  return new Matrix4().compose(new Vector3(v[0], v[1], v[2]), new Quaternion(v[3], v[4], v[5], v[6]), new Vector3(1, 1, 1));
}

export function cylinderMatrix(c, ax, dia, len) {
  const r = new Matrix4();
  if (ax === "x") r.set(0, 0, 1, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 0, 1);       // +z -> +x
  else if (ax === "y") r.set(1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1);  // +z -> +y
  const s = new Matrix4().makeScale(dia, dia, Math.max(len, 0.01));
  return new Matrix4().makeTranslation(c[0], c[1], c[2]).multiply(r).multiply(s);
}

export function offsetMatrix(o) {
  return new Matrix4().makeTranslation(o[0], o[1], o[2]);
}

export class Timeline {
  constructor(tl) {
    this.raw = tl;
    this.dt = tl.dt;
    this.n = tl.frames;
    this.track = tl.track;
    this.follow = tl.follow || {};
    this.glow = tl.glow || {};
    this.spawn = Object.fromEntries((tl.spawn || []).map((s) => [s.name, s]));
    this.reshaped = new Set(Object.keys(tl.track).filter((n) => !Array.isArray(tl.track[n][0])));
    this.spawnBase = {};
    for (const [n, s] of Object.entries(this.spawn)) this.spawnBase[n] = cylinderMatrix(s.p, s.s[0], s.s[2], s.s[1]);
  }

  bodyOf(name) {   // a follower's moving body: screws by their F####_ prefix, brackets by label
    const key = name.startsWith("F") && /^\d{4}$/.test(name.slice(1, 5)) ? name.slice(0, 6) : name;
    const b = this.follow[key];
    return b && this.track[b] ? b : null;
  }

  // {name: {kind: 'rigid' | 'cyl', m: Matrix4, vis, col}} for frame k
  frame(k) {
    k = Math.max(0, Math.min(this.n - 1, Math.floor(k)));
    const out = {};
    for (const [n, tr] of Object.entries(this.track)) {
      const v = tr[k];
      if (Array.isArray(v)) out[n] = { kind: "rigid", m: rigidMatrix(v), vis: !!v[7], col: null };
      else out[n] = { kind: "cyl", m: cylinderMatrix(v.c, v.ax, v.dia, v.len), vis: v.vis === undefined ? true : !!v.vis, col: v.col || null };
    }
    for (const [n, g] of Object.entries(this.glow)) {
      const f = out[n] || { kind: "rigid", m: new Matrix4(), vis: true };
      out[n] = { ...f, col: g.bits[k] === "1" ? g.on : g.off };
    }
    return out;
  }

  // the matrix a drawn cylinder gets (reshaped or spawned), or null if `name` is a CAD part moved rigidly
  cylinderOf(name, f) {
    const e = f[name];
    if (!e) return null;
    if (e.kind === "cyl") return e.m;
    if (this.spawn[name]) return e.m.clone().multiply(this.spawnBase[name]);
    return null;
  }

  followerMatrix(name, f) {
    const b = this.bodyOf(name);
    return b && f[b].kind === "rigid" ? f[b].m : null;
  }
}
