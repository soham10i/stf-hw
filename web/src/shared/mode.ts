// How this build is served. The twin itself (the 3D machine, its cycle, every panel
// built from the exports) needs no server. The live API adds the physics-kernel
// stream and the order queue; a static build (GitHub Pages) leaves it out entirely,
// so it never tries to reach a backend that is not there.
//
//   npm run build                 with the API (served by `make share` / vite preview)
//   npm run build:pages           standalone (VITE_LIVE_API=0), for any static host

export const HAS_API = import.meta.env.VITE_LIVE_API !== "0";
