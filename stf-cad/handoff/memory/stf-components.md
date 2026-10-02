---
name: stf-components
description: The four ft electrical components (144643/37783/36134/128599) as one tagged parameter table -> FreeCAD, web tabs, AI prompt
metadata:
  type: project
---
`stf-cad/hbw/components.py` (2026-09-27) is the single table for the encoder motor
144643, mini switch 37783, phototransistor 36134, colour sensor 128599. Every dim is
tagged datasheet / photo / ft-std / assumed - the datasheets only fix envelopes,
shaft (D4, L7.5, two 0.7 flats -> AF 2.6) and plug D2.5; groove profile, socket
positions, button size are NOT documented (user wants 0.1 mm; only datasheet values
can honestly claim it).

`components_cad.py` (freecadcmd) builds B-rep, refuses unless each housing's
optimalBoundingBox equals the datasheet to 0.01 mm -> stf-factory/cad/components/
<id>.FCStd/.step + stf-hw/web/public/components/<id>.glb + components.json.
`components_prompt.py` -> FREECAD_AI_PROMPTS.md (for Gemini in FreeCAD).
Web: stf-hw App.tsx tab bar (Complete setup + 4 components, `?tab=<id>`),
`scene/ComponentView.tsx` (MeshPhysicalMaterial per CAD material tag, Lightformer
studio env - no network HDRI, dimension overlay, accuracy panel).

Which factory parts ARE which component is decided by the Belegungsplan
(parts_table._kind): encoder motor only where B.. encoder channels are wired (5:
HBW travel+lift, VGR x3); light-barrier tx = LED 162135, only rx = 36134.
Official uni repo is ~/stf (git.oth-aw.de, Prof. Wiehl) - docs only, no part CAD.

**2026-09-27: now NINE components.** Added the booklet's (536634 p.8-11) S-Motor 24V, Kompressor,
Pneumatikzylinder, IR-Spursensor 128598, 3/2-Wege-Magnetventil. The booklet gives ratings but
NO dimensions and there is no datasheet for them in ~/stf/docs/hw, so their sizes are tagged
"assumed" (measure). New source tag "booklet". Each has a `motion` table (spin/reciprocate/
slide/squash) the viewer animates, plus X-ray for compressor/valve/S-motor. parts_table._kind
maps them: non-encoder motors = S-Motor, *valve*, *compressor*, pneumatic *cylinder*, HBW A1/A2
= ONE IR track sensor with two channels (the HBW model draws two parts - a modelling finding).
Web view selection is now ONE dropdown (App.tsx .viewbar), not a tab row.
