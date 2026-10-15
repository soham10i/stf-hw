"""
Master parts table - one row per solid, across all four modules.

Source of truth for every geometric column is the model itself (hbw_model,
vgr_model, oven_model, sorting_model) at its HOME pose, so this table can
never drift from the CAD/collision-checked geometry the way a hand-typed
BOM would. Everything else - ft part numbers, materials, masses, RevPi
terminals - is joined in from the datasheets and the Belegungsplan in
stf-cad/hw/, and is marked with a confidence flag rather than presented
as fact when the documents don't actually say it.

Run:  python3 parts_table.py
Writes stf_parts.csv (for the generators) and stf_parts.xlsx (for Soham to
fill in the "measured (mm)" column at the machine).
"""
from __future__ import annotations

import csv
import re
from dataclasses import fields

import hbw_model as HM
import oven_model as OM
import sorting_model as SM
import vgr_model as VG

# Same named-colour -> hex table hbw_export.py uses for the web scene, reused
# here rather than re-typed, so the table's colours can't drift from the render.
from hbw_export import COLOUR as NAMED_COLOUR, col as resolve_colour

# --------------------------------------------------------------------------
# Facts pulled from the datasheets in stf-cad/hw/. Every entry here is a
# claim I can point at a specific document for; nothing here was guessed.
DATASHEET = {
    # the five booklet components (536634 p.8-11): ratings only, no dimensions
    "s_motor_S-24V": ("ABS housing, U-Getriebe", None,
                      "24 VDC, max 300 mA, 5 mNm, 10700 rpm no-load, U-Getriebe 64.8:1 side output",
                      "536634-Fabrik_Simulation_24V.pdf p.9"),
    "compressor_K-24V": ("ABS housing, membrane pump", None,
                         "24 VDC, 0.7 bar overpressure, max 70 mA",
                         "536634-Fabrik_Simulation_24V.pdf p.10"),
    "pneumatic_cylinder_PZ": ("ABS caps, PC barrel, steel rod, return spring", None,
                              "single-acting, spring return; pairs make vacuum",
                              "536634-Fabrik_Simulation_24V.pdf p.10"),
    "ir_track_sensor_128598": ("ABS housing, 2 IR emitters + 2 receivers", None,
                               "digital, 5-30 mm range, push-pull, 9 VDC via adapter PCB",
                               "536634-Fabrik_Simulation_24V.pdf p.9"),
    "solenoid_valve_MV-3/2": ("steel bracket, copper coil, PA nipples", None,
                              "3/2-way, normally closed: energised P->A, off A->R",
                              "536634-Fabrik_Simulation_24V.pdf p.11"),
    # ft description, part no. -> (material, mass_g, key spec, source)
    "encoder_motor_144643": (
        "ABS housing / steel gears (ft standard)", None,
        "24 VDC, quadrature encoder push-pull 0/24V max 10 mA / 1 kHz, 4-pin "
        "header; shaft D4 x L7.5 mm with 2 flats 0.7 mm; no-load 440 rpm, stall "
        "1800 g.cm, max 0.60 A, max 2.03 W (T-N-I chart, datasheet p.1)",
        "144643-Encodermotor24V.pdf",
    ),
    "mini_switch_37783": (
        "ABS housing", "3.4",
        "digital 0/1, 2A/50V switching, NO/NC selectable by contact 1-3 vs 1-2",
        "37783-Mini-switch.pdf",
    ),
    "phototransistor_36134": (
        "ABS housing, NPN-Si phototransistor", "1.7",
        "digital 5kOhm at TXT I1-I8, needs LED 162135 on the other side of the gap",
        "36134-Photo-transistor.pdf",
    ),
    "colour_sensor_128599": (
        "ABS housing", "6.8",
        "NOT RGB - reflected-brightness only, analogue 0-2 VDC / 0-2000 mV, "
        "6-10 VDC supply, ~15 mA; reading depends on ambient light and distance",
        "128599-Color-sensor.pdf",
    ),
}

# Which real ft component a model part IS. Decided by the Belegungsplan, not by
# name alone: a motor is the ENCODER motor 144643 only if encoder channels (B..)
# are wired to it - the HBW belt/fork motors and every oven motor have none - and
# a light barrier's transmitter is the LED 162135, only its receiver is the
# phototransistor 36134.
def _kind(p):
    n, tag = p.name, p.tag or ""
    if re.search(r"motor$", n) and re.search(r"\bB\d", tag):
        return "encoder_motor_144643"
    # booklet p.9: the S-Motor drives "e.g. the conveyor belts"; every motor with
    # NO encoder wired is an S-Motor by elimination
    if re.search(r"motor$", n):
        return "s_motor_S-24V"
    if "compressor" in n:
        return "compressor_K-24V"
    if "valve" in n:
        return "solenoid_valve_MV-3/2"
    if (p.mech == "pneumatic" and "cylinder" in n) or n == "vacuum_cylinders":
        return "pneumatic_cylinder_PZ"
    # HBW A1/A2: booklet p.4 "Spursensor Signal 1 unten / Signal 2 oben" - the
    # two channels of ONE IR track sensor (the model draws two parts)
    if tag in ("A1", "A2") and "trail" in n:
        return "ir_track_sensor_128598"
    if re.search(r"(^|_)ref_|impulstaster", n):
        return "mini_switch_37783"
    # receivers, plus the oven's end-of-belt barrier (modelled as one part); the
    # HBW cover sensors LB1/LB2 are model additions with no terminal (AUX3/4)
    if (n.endswith("_rx") and "_post_" not in n) or n.endswith("lightbarrier_end") or n.startswith("LB"):
        return "phototransistor_36134"
    if re.search(r"^(CS\d_colour|A4_colour_sensor)", n):
        return "colour_sensor_128599"
    return None


# RevPi terminal + PLC channel, from the Belegungsplan / occupancy .ods,
# keyed by the I/O tag the models already stamp onto every active part.
IO_MAP = {
    # tag: (module, klemme, plc_channel, function_de, function_en)
    ("hbw", "I1"): ("5", "IN 1", "Referenztaster horizontal", "reference switch horizontal axis"),
    ("hbw", "I2"): ("6", "IN 2", "Lichtschranke innen", "light-barrier inside"),
    ("hbw", "I3"): ("7", "IN 3", "Lichtschranke aussen", "light-barrier outside"),
    ("hbw", "I4"): ("8", "IN 4", "Referenztaster vertikal", "reference switch vertical axis"),
    ("hbw", "A1"): ("9", "IN 5", "Spursensor unten", "trail sensor, lower"),
    ("hbw", "A2"): ("10", "IN 6", "Spursensor oben", "trail sensor, upper"),
    ("hbw", "B1"): ("11", "IN 7 (counter)", "Encoder horizontal Impuls 1", "encoder horizontal impulse 1"),
    ("hbw", "B2"): ("12", "IN 8 (counter)", "Encoder horizontal Impuls 2", "encoder horizontal impulse 2"),
    ("hbw", "B3"): ("13", "IN 9 (counter)", "Encoder vertikal Impuls 1", "encoder vertical impulse 1"),
    ("hbw", "B4"): ("14", "IN 10 (counter)", "Encoder vertikal Impuls 2", "encoder vertical impulse 2"),
    ("hbw", "I5"): ("15", "IN 11", "Referenztaster Ausleger vorne", "reference switch cantilever front"),
    ("hbw", "I6"): ("16", "IN 12", "Referenztaster Ausleger hinten", "reference switch cantilever back"),
    ("hbw", "Q1"): ("17", "OUT 1", "Motor Foerderband vorwaerts (M1)", "belt motor forward"),
    ("hbw", "Q2"): ("18", "OUT 2", "Motor Foerderband rueckwarts (M1)", "belt motor backward"),
    ("hbw", "Q3"): ("19", "OUT 3", "Motor horizontal zum Regal (M2)", "travel motor towards rack"),
    ("hbw", "Q4"): ("20", "OUT 4", "Motor horizontal zum Foerderband (M2)", "travel motor towards belt"),
    ("hbw", "Q5"): ("21", "OUT 5", "Motor vertikal runter (M3)", "lift motor down"),
    ("hbw", "Q6"): ("22", "OUT 6", "Motor vertikal hoch (M3)", "lift motor up"),
    ("hbw", "Q7"): ("23", "OUT 7", "Motor Ausleger vorwaerts (M4)", "fork motor forward"),
    ("hbw", "Q8"): ("24", "OUT 8", "Motor Ausleger rueckwarts (M4)", "fork motor backward"),

    ("oven", "I1"): ("5", "IN 1", "Referenzschalter Drehkranz Pos. Sauger", "turntable ref: vacuum position"),
    ("oven", "I2"): ("6", "IN 2", "Referenzschalter Drehkranz Pos. Foerderband", "turntable ref: belt position"),
    ("oven", "I3"): ("7", "IN 3", "Lichtschranke Ende Foerderband", "light-barrier end of belt"),
    ("oven", "I4"): ("8", "IN 4", "Referenzschalter Drehkranz Pos. Saege", "turntable ref: saw position"),
    ("oven", "I5"): ("9", "IN 5", "Referenzschalter Sauger Pos. Drehkranz", "sauger ref: at turntable"),
    ("oven", "I6"): ("10", "IN 6", "Referenzschalter Ofenschieber innen", "feeder ref: inside"),
    ("oven", "I7"): ("11", "IN 7", "Referenzschalter Ofenschieber aussen", "feeder ref: outside"),
    ("oven", "I8"): ("12", "IN 8", "Referenzschalter Sauger Pos. Brennofen", "sauger ref: at oven"),
    ("oven", "I9"): ("13", "IN 9", "Lichtschranke Brennofen", "light-barrier oven"),
    ("oven", "Q1"): ("17", "OUT 1", "Motor Drehkranz CW (M1)", "turntable motor clockwise"),
    ("oven", "Q2"): ("18", "OUT 2", "Motor Drehkranz CCW (M1)", "turntable motor counter-clockwise"),
    ("oven", "Q3"): ("19", "OUT 3", "Motor Foerderband vorwaerts (M2)", "belt motor forward"),
    ("oven", "Q4"): ("20", "OUT 4", "Motor Saege (M3)", "saw motor"),
    ("oven", "Q5"): ("21", "OUT 5", "Motor Ofenschieber einfahren (M4)", "feeder motor retract"),
    ("oven", "Q6"): ("22", "OUT 6", "Motor Ofenschieber ausfahren (M4)", "feeder motor extend"),
    ("oven", "Q7"): ("23", "OUT 7", "Motor Sauger zum Ofen (M5)", "sauger motor towards oven"),
    ("oven", "Q8"): ("24", "OUT 8", "Motor Sauger zum Drehkranz (M5)", "sauger motor towards turntable"),
    ("oven", "Q9"): ("25", "OUT 9", "Leuchte Ofen", "oven lamp"),
    ("oven", "Q10"): ("26", "OUT 10", "Kompressor", "compressor"),
    ("oven", "Q11"): ("27", "OUT 11", "Ventil Vakuum", "valve: vacuum"),
    ("oven", "Q12"): ("28", "OUT 12", "Ventil Senken", "valve: lowering"),
    ("oven", "Q13"): ("29", "OUT 13", "Ventil Ofentuer", "valve: oven door"),
    ("oven", "Q14"): ("30", "OUT 14", "Ventil Schieber (Drehkranz)", "valve: turntable pusher/stopper"),

    ("sorting", "I1"): ("5", "IN1", "Impulstaster", "pulse counter (belt position)"),
    ("sorting", "I2"): ("6", "IN2", "Lichtschranke Eingang", "light-barrier inlet"),
    ("sorting", "I3"): ("7", "IN3", "Lichtschranke nach Farbsensor", "light-barrier behind colour sensor"),
    ("sorting", "A4"): ("9", "NOT WIRED on DIO", "Farbsensor 0-10VDC (RevPi terminal)",
                         "colour sensor - marked 'nicht verwendet' on the DIO occupancy plan; "
                         "needs an analogue-input module not among the current docs"),
    ("sorting", "I5"): ("10", "IN4", "Lichtschranke weiss", "light-barrier white bay"),
    ("sorting", "I6"): ("11", "IN5", "Lichtschranke rot", "light-barrier red bay"),
    ("sorting", "I7"): ("12", "IN6", "Lichtschranke blau", "light-barrier blue bay"),
    ("sorting", "Q1"): ("17", "OUT1", "Motor Foerderband", "belt motor (single direction)"),
    ("sorting", "Q2"): ("18", "OUT2", "Kompressor", "compressor"),
    ("sorting", "Q3"): ("20", "OUT3", "Ventil 1. Auswurf (weiss)", "ejector valve 1: white"),
    ("sorting", "Q4"): ("21", "OUT4", "Ventil 2. Auswurf (rot)", "ejector valve 2: red"),
    ("sorting", "Q5"): ("22", "OUT5", "Ventil 3. Auswurf (blau)", "ejector valve 3: blue"),

    ("vgr", "I1"): ("5", "IN 1", "Referenzschalter vertikal", "reference switch: vertical axis"),
    ("vgr", "I2"): ("6", "IN 2", "Referenzschalter horizontal", "reference switch: horizontal axis"),
    ("vgr", "I3"): ("7", "IN 3", "Referenzschalter drehen", "reference switch: rotate"),
    ("vgr", "B1"): ("9", "IN 5 (counter)", "Encoder vertikal Impuls 1", "encoder vertical impulse 1"),
    ("vgr", "B2"): ("10", "IN 6 (counter)", "Encoder vertikal Impuls 2", "encoder vertical impulse 2"),
    ("vgr", "B3"): ("11", "IN 7 (counter)", "Encoder horizontal Impuls 1", "encoder horizontal impulse 1"),
    ("vgr", "B4"): ("12", "IN 8 (counter)", "Encoder horizontal Impuls 2", "encoder horizontal impulse 2"),
    ("vgr", "B5"): ("13", "IN 9 (counter)", "Encoder drehen Impuls 1", "encoder rotate impulse 1"),
    ("vgr", "B6"): ("14", "IN 10 (counter)", "Encoder drehen Impuls 2", "encoder rotate impulse 2"),
    ("vgr", "Q1"): ("17", "OUT 1", "Motor vertikal hoch (M1)", "lift motor up"),
    ("vgr", "Q2"): ("18", "OUT 2", "Motor vertikal runter (M1)", "lift motor down"),
    ("vgr", "Q3"): ("19", "OUT 3", "Motor horizontal rueckwaerts (M2)", "reach motor backward"),
    ("vgr", "Q4"): ("20", "OUT 4", "Motor horizontal vorwaerts (M2)", "reach motor forward"),
    ("vgr", "Q5"): ("21", "OUT 5", "Motor drehen CW (M3)", "swivel motor clockwise"),
    ("vgr", "Q6"): ("22", "OUT 6", "Motor drehen CCW (M3)", "swivel motor counter-clockwise"),
    ("vgr", "Q7"): ("23", "OUT 7", "Kompressor", "compressor"),
    ("vgr", "Q8"): ("24", "OUT 8", "Ventil Vakuum", "valve: vacuum"),
}

# Family-level material assumptions where NO datasheet exists (most ft
# building-block plastics and structural aluminium extrusions). Confidence
# is explicit: these are NOT sourced from a document.
GROUP_MATERIAL_GUESS = {
    "frame": ("aluminium composite plate (ft base plate)", "assumed - typical ft plate finish"),
    "rack": ("ABS (ft building block red/black)", "assumed - ft standard block colours"),
    "mould": ("ABS / POM (ft grey building parts)", "assumed"),
    "workpiece": ("simulated cookie - no ft part, colour is the pipeline flavour marker", "n/a"),
    "rail": ("aluminium (rails/spindles) + ABS (mounts)", "assumed"),
    "conveyor": ("aluminium frame + rubber/PVC belt + ABS pulleys", "assumed"),
    "cover": ("ABS (ft cover parts), sensors as tagged", "assumed"),
    "control": ("PCB + ABS terminal housing", "assumed"),
    "crane": ("aluminium (tubes/spindles) + ABS (yokes)", "assumed"),
    "fork": ("aluminium (Ausleger stages) + ABS bearings", "assumed"),
    "tool": ("ABS (fork table)", "assumed"),
    "oven": ("sheet steel (chamber) + ABS (housing)", "assumed - Brennofen runs hot, steel is likely not ft plastic"),
    "door": ("ABS / polycarbonate (Ofentuer)", "assumed"),
    "slider_fix": ("aluminium rail + ABS carriage", "assumed"),
    "turn_fix": ("ABS (Drehkranz disc + pusher)", "assumed"),
    "lower": ("aluminium (Q12 lowering cylinder) + rubber (suction cup)", "assumed"),
    "sort": ("aluminium frame + ABS bays", "assumed"),
}


def datasheet_for(p):
    key = _kind(p)
    return (key, DATASHEET[key]) if key else (None, None)


def rows_for_module(module: str, parts, home_pose_note: str):
    rows = []
    for p in parts:
        # hbw_model.Part calls this field "joint"; vgr/oven/sorting call it
        # "frame" - same meaning (which moving group the solid rides on).
        joint = getattr(p, "joint", None) if hasattr(p, "joint") else getattr(p, "frame", "")
        ds_key, ds = datasheet_for(p)
        io_rows = []
        if p.tag:
            # A motor's tag is often a compound string, e.g. "Q3/Q4 + B1/B2"
            # (both directions plus its encoder pair) rather than one terminal -
            # split it and join every real terminal it resolves to.
            for token in re.split(r"[\s/+,]+", p.tag):
                hit = IO_MAP.get((module, token))
                if hit:
                    io_rows.append((token, hit))
        shape = p.kind
        if shape == "box":
            dims = f"{p.s[0]:.1f} x {p.s[1]:.1f} x {p.s[2]:.1f} mm (L x W x H)"
        else:
            axis, length, dia = p.s
            dims = f"cyl, axis {axis}, L={length:.1f} mm, D={dia:.1f} mm"
        mat_guess, mat_conf = GROUP_MATERIAL_GUESS.get(p.group, ("unknown", "unassigned"))
        row = {
            "module": module,
            "assembly/joint": joint or p.group,
            "part_name": p.name,
            "shape": shape,
            "model_dims": dims,
            "measured_dims_mm": "",  # <- fill in at the machine
            "colour_hex": resolve_colour(p.colour),
            "colour_name": p.colour if not p.colour.startswith("#") else "",
            "ft_part_no": ds_key.split("_")[-1] if ds_key else "",
            "material": (DATASHEET[ds_key][0] if ds_key else mat_guess),
            "material_confidence": ("datasheet: " + DATASHEET[ds_key][3]) if ds_key else mat_conf,
            "mass_g": (DATASHEET[ds_key][1] if ds_key else ""),
            "key_spec": (DATASHEET[ds_key][2] if ds_key else ""),
            "io_tag": p.tag,
            "revpi_klemme": "; ".join(f"{t}:{h[0]}" for t, h in io_rows) if io_rows
                            else ("NO MATCH in Belegungsplan" if p.tag else ""),
            "plc_channel": "; ".join(f"{t}:{h[1]}" for t, h in io_rows),
            "function_de": "; ".join(h[2] for _, h in io_rows),
            "function_en": "; ".join(h[3] for _, h in io_rows),
            "mech": p.mech,
            "note": p.note,
            "pose_note": home_pose_note,
        }
        rows.append(row)
    return rows


def build_all():
    rows = []
    rows += rows_for_module("hbw", HM.build(), "default pose: travel=665 lift=120 fork=0 (parked, off the rack)")
    rows += rows_for_module("vgr", VG.build(0.0, 0.0, 0.0), "swivel=0 plunge=0 reach=0")
    rows += rows_for_module("oven", OM.build(), "authoring defaults (slider=205 aussen, door=160 open, turn=0, sauger=150 at Drehtisch, lower=0, push=0)")
    rows += rows_for_module("sorting", SM.build(), "push=(0,0,0)")
    return rows


def write_csv(rows, path):
    cols = list(rows[0].keys())
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def write_xlsx(rows, path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "parts"
    cols = list(rows[0].keys())
    header_fill = PatternFill("solid", fgColor="2B2B2F")
    header_font = Font(color="FFFFFF", bold=True)
    measure_fill = PatternFill("solid", fgColor="FFF3C4")  # highlight the column to fill in
    assumed_fill = PatternFill("solid", fgColor="FFE3E3")

    for j, c in enumerate(cols, start=1):
        cell = ws.cell(row=1, column=j, value=c)
        cell.fill = header_fill
        cell.font = header_font
        ws.column_dimensions[get_column_letter(j)].width = max(12, min(42, len(c) + 4))

    measure_col = cols.index("measured_dims_mm") + 1
    conf_col = cols.index("material_confidence") + 1
    ws.column_dimensions[get_column_letter(measure_col)].width = 22
    ws.column_dimensions[get_column_letter(conf_col)].width = 30

    for i, row in enumerate(rows, start=2):
        for j, c in enumerate(cols, start=1):
            val = row[c]
            cell = ws.cell(row=i, column=j, value=val)
            cell.alignment = Alignment(vertical="top", wrap_text=(c in ("note", "key_spec", "material_confidence")))
            if c == "measured_dims_mm":
                cell.fill = measure_fill
            if c == "material_confidence" and isinstance(val, str) and val.startswith("assumed"):
                cell.fill = assumed_fill

    ws.freeze_panes = "A2"

    # Second sheet: per-module summary counts
    ws2 = wb.create_sheet("summary")
    from collections import Counter
    mod_counts = Counter(r["module"] for r in rows)
    ws2.append(["module", "solid_count"])
    for m, c in mod_counts.items():
        ws2.append([m, c])
    ws2.append([])
    ws2.append(["TOTAL", len(rows)])
    ws2.append([])
    ws2.append(["Open hardware question:"])
    ws2.append(["The Farbsensor (colour sensor, 128599) outputs analogue 0-2 VDC. The RevPi DIO"])
    ws2.append(["module datasheet has no analogue input at all, and the Belegungsplan itself marks"])
    ws2.append(["that terminal 'nicht verwendet' (not used). Whatever module actually reads it"])
    ws2.append(["(RevPi AIO, or a TXT controller as the sensor's own datasheet suggests) is not"])
    ws2.append(["among the current docs - flagged, not guessed."])

    wb.save(path)


if __name__ == "__main__":
    rows = build_all()
    write_csv(rows, "stf_parts.csv")
    write_xlsx(rows, "stf_parts.xlsx")
    from collections import Counter
    print(f"{len(rows)} solids across {len(set(r['module'] for r in rows))} modules")
    for m, c in Counter(r["module"] for r in rows).items():
        print(f"  {m:10s} {c}")
    print("wrote stf_parts.csv, stf_parts.xlsx")
