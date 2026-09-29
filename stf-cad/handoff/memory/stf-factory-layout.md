---
name: stf-factory-layout
description: Factory placement matched to the 536634 cover photo (2x2 block) and the web-view mirror bug; where the numbers come from
metadata:
  type: project
---
2026-09-27, stf-cad/hbw/factory_layout.py re-laid to the booklet cover photo: front row sorting
(left) + oven (right), back row VGR (left) + HBW (right). Factory frame: FRONT edge is x=0, "right"
seen from the front is -Y. HBW, oven and sorting all rotated +90 (module (x,y) -> (-y+TX, x+TY)).
Table 1360 x 1180.

- Oven rotated +90: Ofenschieber points back at the VGR, belt runs to the front and ENDS against the
  sorting belt's back rail (OVEN_TX solved = SORT_TX - 100 + 378); cookie crosses the corner.
- Sorting model was MIRRORED vs the real machine; fixed: ejectors behind the belt (front edge of
  the table), Lagerstellen in front (facing the VGR). EJECT_AXIS "-y". Bay barriers now actually
  cross a resting cookie (old ones missed it by 1 mm).
- Front row + VGR sit 250 mm left of the HBW's right edge: smallest 50 mm step at which the VGR's
  rear arm stops hitting the HBW cover while serving the bays (check_cross + vgr_path).
- Plate SIZES are still the models' own, not measured - the photo fixes arrangement only.

**Web mirror bug (fixed):** HbwCad's v(x,y,z)=(x,z,y) is a reflection, so the three.js twin drew
the MIRROR IMAGE of the CAD for its whole life. Fixed with one scale [1,1,-1] group around the
stage; world z = -factory y (camera/target/grid use -y). glTF/FreeCAD exports were always right.
See [[stf-oven-model]], [[stf-sorting-model]], [[stf-vgr-model]].

**2026-09-27 (later): 2x oven + sorting, PLC, precise parts, wiring.** Oven plate 660x760, sorting
1040x640 (structure/spacing doubled; ft parts + 45 mm workpiece stay real, sized to the precise
component envelopes). Layout: sorting front-left (650 deep), oven front-right set back (x 448..1208,
its belt still ends on the sorting rail), VGR behind sorting (plate enlarged to 495x740), HBW behind
the oven (TY=150 - smallest shift where the VGR's rear motor misses the waiting mould), PLC cabinet
(plc_model.py: WDR-120 PSU, RevPi Core + 3 DIO + AIO on DIN rail) in front of the oven. Table 1870x1510.
wiring.py: fit() lays each I/O part's precise glb in at real size (axis permutation, det +1);
wires() routes a cable per static I/O part to its module PCB + a 34-way ribbon PCB->PLC. Every module
now has a 160x100x22 adapter PCB. Web draws black ft base plates per module on a white table.
Wiring (2026-09-27, user: "lines, not coloured boxes"): every conductor is its own round tube
with a ROLE colour (wiring.ROLE: +24V red, 0V blue, PE green-yellow striped, mains L brown / N light
blue, DI white, DO orange, ENC yellow, AI violet, AIR = translucent PU hose). Cables carry the real
conductor set per part (sensor: +24V+DI, actuator: DO+0V, bidirectional motor: DO+DO); pneumatic
cylinders get HOSES from their valve, valves get wires. PCB->PLC = bundle of single wires (all ST3
signals + supply). Legend overlay in App.tsx (.wire-legend).
