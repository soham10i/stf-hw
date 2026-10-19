# PLC traceability

Every cookie travels in a tagged mould (Werkstuecktraeger). The belt's two RFID read points
read the tag; the sorting line's colour sensor confirms the flavour before the cookie is
ejected into its bin; the program writes one trace record per cookie.

## Moulds

| Slot | Mould |
|---|---|
| A1 | M01 |
| A2 | M02 |
| A3 | M03 |
| A4 | M04 |
| B1 | M05 |
| B2 | M06 |
| B3 | M07 |
| B4 | M08 |
| C1 | M09 |
| C2 | M10 |
| C3 | M11 |
| C4 | M12 |

## RFID read points

| Point | Where |
|---|---|
| RF1 | RFID read point RP1: belt, crane end (IO-Link port 1) |
| RF2 | RFID read point RP2: belt, VGR hand-over (IO-Link port 2) |

Geometry: {"y": [440.0, 580.0], "pick_hbw": 325.0, "pick_vgr": 580.0, "reach_y": 405.0, "belt_speed": 50.0} (mm, mm/s).

## Colour bands (sensor A4, mV)

| Bin | From (mV) | To (mV) |
|---|---|---|
| blau | 0 | 645 |
| rot | 645 | 1305 |
| weiss | 1305 | 5000 |

## A trace record

```json
{
 "id": "c00",
 "flavour": "chocolate",
 "kind": "production",
 "mould": "M01",
 "slot_from": "A1",
 "slot_to": null,
 "reads": [
  [
   "RP1",
   "M01",
   17.7
  ],
  [
   "RP2",
   "M01",
   20.8
  ]
 ],
 "t": {
  "retrieved": 15.4,
  "off_mould": 26.08,
  "bake_start": 31.95,
  "bake_end": 39.95,
  "sorted": 75.95
 },
 "colour_mV": 340,
 "class": "blau",
 "bin": "blau",
 "verified": true,
 "bake_s": 2.0
}
```

Assumed values: speeds as motion.py (HBW 150 mm/s, VGR 60 deg/s, 120 mm/s); belts 50 mm/s; RFID read 0.3 s; vacuum 0.5 s; the booklet's 2 s demo bake; reference-switch directions.

<!-- Sources: `web/public/hbw_parts_up12.json (control.moulds, control.read_points, control.rfid, control.bands, control.trace)`. -->

<!-- Generated from the twin's exports by `docs/gen/plc_docs.py`; do not edit. -->
