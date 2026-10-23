# The control and power devices, as precise models

The fischertechnik components hang on six control and power devices, now built the same way as
the components:

- the RevPi DIO and the RevPi Core S;
- the Mean Well WDR-120-24 power supply;
- the 24 V adaptor PCB;
- the remote I/O bus coupler and an 8-channel slice.

Every device has a parameter table with a source for each value (`stf-cad/hbw/devices.py`) and
FreeCAD solids (`devices_cad.py`). It is checked and exported by `components_cad.py`:
`.FCStd`/`.step` in `stf-factory/cad/components`, `.glb` and `components.json` in
`web/public/components`.

```bash
/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd stf-cad/hbw/components_cad.py
```

## Where every value comes from

| Device | Envelope | Its source | What is assumed |
|---|---|---|---|
| RevPi DIO 100197 | 96 × 22.5 × 110.5 mm | `docs/Datenblatt_RevPi_DIO.pdf` | where the plugs and LEDs sit on the front |
| RevPi Core S 100359 | 96 × 22.5 × 110.5 mm | `docs/Datenblatt_RevPi_Cores.pdf` | where the jacks and LEDs sit |
| Mean Well WDR-120-24 | 40 × 125.2 × 113.5 mm (±1 mm) | Mean Well's WDR-120 spec sheet (case 992B) | the terminal pitch |
| Adaptor PCB 24V | 123.84 × 81.0 × 1.6 mm | scaled off the p.4 drawing of the 536634 extended description | the relays' height |
| Remote I/O coupler / slice | 100 × 51 × 72 / 100 × 12 × 68 mm | the upgrade design (`io_nodes.py`): no product chosen | all |

- **Counts and kinds come from the datasheets:**
  - the DIO's 2 × 14-pole spring plugs at 3.5 mm (a 49 mm pole field, checked) and 2 × 4-pole
    supply plugs;
  - the Core's 2 × USB A, RJ45, micro-USB and micro-HDMI;
  - the PSU's 3-pole input and 4-pole output blocks, its DC OK LED and its +V ADJ trimmer.
- **The front positions are not published.** KUNBUS's own STEP files would settle the RevPi's.
- **New source tags:**
  - *standard*: TS35 rail 35 × 7.5 mm (EN 60715), FR-4 1.6 mm, 2.54 mm shrouded headers.
  - *design*: chosen in this project, not measured.

**The adaptor PCB's scale.** The documents give the board's layout but no dimensions. The drawing
is scaled with its 34-pin ST3 box header as the ruler: 17 × 2.54 + 10.16 = 53.34 mm, which gives
0.1235 mm per pixel. A second ruler checks it: ST1 and ST2 (20-pole, 35.56 mm) come out at 37.2
and 34.6 mm, within 5 %. The build refuses if they do not. The layout follows the drawing:

- ST1 and ST2 at the back;
- R1–R8 in groups of 2, 4 and 2;
- ST3 in front of them;
- V1–V4 on the left edge;
- terminals 1–30 along the PLC edge;
- four M3 holes.

## Checks (all pass; nothing is written otherwise)

- **Each housing's exact B-rep bounding box equals its envelope within 0.01 mm.** For the WDR this
  is the nominal size; its datasheet allows ±1 mm.
- **Every sub-part is a valid solid.**
- **The DIO's I/O plug pole field is 14 × 3.5 = 49.000 mm.**
- **The PCB's two ruler checks pass.**
- **The factory CAD agrees with the datasheets** (`electrical.py`). Its PSU and RevPi Core boxes
  are within 0.5 mm of their datasheet housings.

## In the twin

- **The 3D factory draws the devices as these models.** The cabinet's PSU and Core, every
  module's adaptor PCB, and every remote I/O node's coupler and slices are covered; each is
  fitted into the box the factory CAD gives it, turned a quarter where the box lies the other way.
- **Each device has a page in the component viewer** (group "Control and power") with its accuracy
  check, sources and where it is used.
- **The viewer frames each part from its loaded bounds.** A 110 mm RevPi used to start cut off.

## The engineering upgrade (Industry 4.0 / 5.0)

1. **The supply is monitored.** The WDR's DC OK relay contact was wired to nothing. It now runs
   from +24 V to the warehouse node's first spare input (DI2.1, signal `PS_OK`). The PLC sees a
   sagging or failed 24 V before the loads misbehave, and can log it and stop safely. This is
   condition data, and it makes the line more resilient (Industry 5.0).
   - Tested: the contact opening drops the input.
2. **Every device has a digital nameplate.** The Asset Administration Shell environment
   (`aas/build.py`, IEC 63278) grows from 12 to 18 shells. Each device gets:
   - a Digital Nameplate, with its IEC 61406 identification link as `URIOfTheProduct` and in
     `IdentificationLink`;
   - Technical Data, with every value's source;
   - Handover Documentation (its document as kept in `docs/`);
   - Provision of 3D Models (STEP and glTF).

   The cell's bill of materials gains the control cabinet and the air station. All AAS proofs
   pass: AAS v3 metamodel verification, template conformance, references, the AASX round trip, and
   five mutants caught.
3. **Every device model has an identification plate**, a flush recess on the front or side where
   its IEC 61406 QR code goes. The QR image itself is not generated: the project has no QR encoder.

## Findings

- **The PSU's pins in `electrical.json` were wrong** (L, N, PE). The WDR has two-phase input with
  no neutral: TB1 is FG, AC/L2, AC/L1; TB2 is the DC OK contact, −V and +V. Corrected.
- **The CAD reserves 160 × 100 × 22 mm for each adaptor PCB.** The board is 123.8 × 81.0 mm. With
  the assumed 15.5 mm relays, the populated board on 5 mm standoffs stands 22.1 mm, 0.1 mm over the
  reserved height. Measure the relays.
- **The CAD's cabinet names a "RevPi Core 3"**, but the datasheet in `docs/` is the Core S/SE
  (BCM2711). They share the housing; the electrics follow the Core S.
- **The remote I/O is still a placeholder.** Choosing a real coupler and slices with published
  datasheets and AAS would turn the "design" values into "datasheet" ones.
