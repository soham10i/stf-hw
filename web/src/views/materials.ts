// Physically based materials for the components' and the factory's meshes.




import * as THREE from "three";







// Physically based materials, chosen per sub-part from the CAD's own material tag.
/** `lite`: for the whole factory. Real transmission makes three.js render every opaque object a
    second time per frame (the transmission pass) - 22 small clear parts doubled the factory's draw
    calls - so there clear acrylic is drawn as plain see-through plastic instead. */
export function physical(material: string, colour: string, lite = false): THREE.Material {
  const c = new THREE.Color(colour);
  switch (material) {
    case "steel":
      return new THREE.MeshPhysicalMaterial({ color: c, metalness: 1, roughness: 0.26 });
    case "brass":
      return new THREE.MeshPhysicalMaterial({ color: c, metalness: 1, roughness: 0.32 });
    case "clear":
      if (lite) return new THREE.MeshPhysicalMaterial({
        color: c, metalness: 0, roughness: 0.05, clearcoat: 1, transparent: true, opacity: 0.35, depthWrite: false,
      });
      return new THREE.MeshPhysicalMaterial({
        color: c, metalness: 0, roughness: 0.05, transmission: 0.85, thickness: 0.6, ior: 1.49,
      });
    case "glass":
      return new THREE.MeshPhysicalMaterial({ color: c, metalness: 0, roughness: 0.08, clearcoat: 1 });
    case "pvc":
      return new THREE.MeshPhysicalMaterial({ color: c, metalness: 0, roughness: 0.55, sheen: 0.3 });
    case "paint":
      return new THREE.MeshPhysicalMaterial({ color: c, metalness: 0, roughness: 0.5 });
    default: // injection-moulded ABS: satin body with a thin glossy skin
      return new THREE.MeshPhysicalMaterial({
        color: c, metalness: 0, roughness: 0.42, clearcoat: 0.35, clearcoatRoughness: 0.4,
      });
  }
}
