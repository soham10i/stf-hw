# Viewing the STF-2 twin (DT-2): Blender and the browser

Both views play `motion/timeline.json`, the 40 s reference run that `motion.py` derives from the model and sweeps
for collisions. Both are proven to draw every moving part where the FreeCAD player puts it (`twin/playback_check.py`:
19,907 part-frames, worst 0.097 mm). Build them first:

```bash
cd ~/workspace/stf-hw-stf2/stf-cad/line2
twin/export_scene.sh      # DT-1: the scene (USD / GLB), ~40 s
twin/playback.sh          # DT-2: FreeCAD reference, Blender keyframes, the gate, ~25 s
```

## Blender

```bash
open -a Blender twin/out/stf2_anim.blend
```

- **Play:** press **Space** (or use the play button in the Timeline at the bottom). It runs at 10 fps, so 401 frames are the 40 s. Frame *n* is t = (n − 1) × 0.1 s.
- **Navigate:** middle-drag to orbit, Shift + middle-drag to pan, wheel to zoom. Press numpad `.` (or View → Frame Selected) on a selected object.
- **Look inside:** in the Outliner (top right), the hierarchy is `STF2 › M1_loop … M10_safety › group › part`. Click the eye icon on `M10_safety` to hide the guards and enclosure. Every part Empty carries `stf_name`, `stf_module` and `stf_tag` (Object Properties → Custom Properties).
- **What moves:**
  - the chain and its pucks;
  - the band rows: the cookies spread and brown in the oven;
  - the three deltas;
  - the depositor wire;
  - the kicker, sealers and stackers;
  - the airlock exchange of lane *weiss*;
  - the 9 oven elements glow while their SSR conducts.
- **Look:** use the shading buttons at the top right of the 3D view: *Material Preview* for colours, *Rendered* for EEVEE with lighting.
- **Render a frame:** set the frame, then F12. A video: Output Properties → File Format FFmpeg, then Render → Render Animation.
- **Rebuild from scratch:**
  - with the GUI: `blender -P twin/blender_anim.py` (builds, saves and leaves it open);
  - headless: `blender -b -P twin/blender_anim.py -- --render 150 frame.png` renders frame 150.

To use the scene without the animation (renders, DT-7), load it with
`blender -b -P twin/blender_load.py -- [--module M3_oven] [--render out.png]`. It keeps the part names, which
Blender's default USD import loses, and restores the guards' transparency, which the importer drops.

## Browser (three.js)

```bash
cd ~/workspace/stf-hw-stf2/stf-cad/line2 && python3 -m http.server 8300 --bind 127.0.0.1
open http://localhost:8300/twin/web/
```

- **Controls:** drag to orbit, right-drag to pan, wheel to zoom.
- **Bottom bar:** play/pause, the time slider (scrub any frame), the speed (0.25-4×) and the airlock phase.
- **Left panel:** the guards start hidden (tick to show), plus one checkbox per module. Click any part to see its name, module, group, tag and hardware.
- **Right panel:** oven power, elements on, L1/L2/L3 current, duty and TC reading per zone. In DT-2 these come from the timeline; in DT-3 they come from the live plant.

### How the web simulation works

1. **Scene.** `twin/out/stf2.glb` (from DT-1) is one glTF file. Each part is a node with its CAD name, and `extras`
   holds `stf:module`, `stf:tag`, `stf:hw`, `stf:moving`. The root node turns the model's mm / Z-up into glTF's m / Y-up,
   so everything inside it stays in the model's own coordinates.
2. **Rules.** `twin/web/player.js` applies the FreeCAD player's rules to a frame:
   - a rigid part's node matrix = M(t, q) × T(offset);
   - screws and brackets take their body's M;
   - a reshaped part (a spreading cookie, an extending rod) is drawn as that frame's cylinder;
   - an oven element takes its on / off colour.
   It has no DOM code, so Node runs the same file for the gate (`twin/web/check_player.mjs`).
3. **Loop.** `twin/web/viewer.js` advances a clock with `requestAnimationFrame`, asks `player.js` for frame
   k = floor(t / 0.1 s) and copies the matrices into the three.js nodes (`matrixAutoUpdate = false`). three.js renders
   with WebGL on the Mac's GPU.
4. **What changes in DT-3.** The recorded timeline is replaced by a WebSocket from the live plant + PLC simulation,
   sending the same per-part transforms (see `DATA_CONTRACT.md` §3.2). The viewer keeps its scene and its matrix
   code; only the source of the frames changes. Later the operations dashboard (DT-8) moves into the existing React
   web app on `main`, like cell 1's twin.

## Which one for what

| Need | Use |
|---|---|
| look around, scrub time, click parts, show someone | browser |
| beauty renders, videos, camera moves, synthetic training images (DT-7) | Blender |
| engineering checks against the B-rep (exact solids, collisions) | FreeCAD: `STF2_Precise.FCStd` + `play_motion.FCMacro` |
| Omniverse / Isaac Sim | the same `stf2.usda` on a cloud RTX machine (DT-9) |
