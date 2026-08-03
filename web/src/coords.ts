// Coordinate mapping between the factory frame and three.js.
//
// The layout frame is millimetres, right-handed, +Z up (see factory.layout.yaml).
// three.js is +Y up. So a factory point (x, y, z) maps to three (x, z, y): the
// factory's vertical Z becomes three's vertical Y, and the factory's depth Y
// becomes three's depth Z. VIEW scales mm to a comfortable on-screen size; it is
// presentation only and never touches the physics.

import * as THREE from "three";

export const VIEW = 0.01; // 1 mm -> 0.01 scene units (a 400 mm axis -> 4 units)

/** Factory (x, y, z) in mm -> three.js Vector3. */
export function v3(x: number, y: number, z: number): THREE.Vector3 {
  return new THREE.Vector3(x * VIEW, z * VIEW, y * VIEW);
}

export function v3a(p: [number, number, number]): THREE.Vector3 {
  return v3(p[0], p[1], p[2]);
}

/** Each crane joint maps cleanly to one three.js axis under the mapping above. */
export const AXIS3 = {
  travel: "x", // factory +X
  lift: "y", // factory +Z (up)
  fork: "z", // factory +Y (depth, into the rack)
  reach: "z", // factory +Y
  plunge: "y", // factory +Z (up)
} as const;
