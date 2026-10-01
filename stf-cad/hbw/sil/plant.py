"""
Upgrade 13 - the plant the PLC program runs against, as numbers from the models.

The plant itself is web/src/sil/plant.ts: one implementation, run by the proof
(under Node) and by the public twin (in the browser). It sees only the PLC's
outputs and answers only with its inputs. Everything it needs to know about
the machine is here, taken from the same models the CAD and the proofs use:

  HBW       travel / lift / Ausleger at 150 mm/s; the reference switches at
            the conveyor (I1), the bottom (I4) and the Ausleger's two stops
            (I5/I6); the rack's columns and rows; the belt ends, the light
            barriers I2/I3 at the belt's two ends, RP1/RP2 where the RFID
            heads are. A mould is picked up or set down when the lift passes
            the shelf (or the belt) with the Ausleger out.
  VGR       swivel 60 deg/s, plunge and reach 120 mm/s; every station's
            swivel, reach and contact height (vgr_path); the vacuum switch I4
            makes when the cup is sealed on a cookie.
  OVEN      the Ofenschieber's stroke and the door, Sauger, lifting cylinder,
            Drehtisch and Auswerfer, with the booklet's times; a cookie is
            baked when it has had the lamp for the bake time.
  SORTING   the belt at 50 mm/s, the colour sensor's window, the light
            barriers, one I1 pulse per PULSE_MM, the ejectors and the bays.
ASSUMED and flagged: the cylinder times (vc.PHYS: 80 % of the booklet), the
pulse pitch, the colour sensor's readings of the belt and of raw dough, the
light-barrier polarity (TRUE = a part in the beam, as control.py writes it),
and that a motor stops when its output drops (vc.py adds the ramps).
"""
import json
import os

import control as C
import hbw_model as HM
import oven_model as OM
import pipeline as PL
import sorting_model as SM
import vc as V
import vgr_model as VG
import vgr_path as VP

from sil import iec

OUT = os.path.expanduser("~/workspace/stf-hw/web/public/sil")


def oven_joints():
    import json as _j
    doc = _j.load(open(os.path.expanduser("~/workspace/stf-hw/web/public/hbw_parts_up12.json")))
    return doc["oven"]["joints"]


def params():
    J = oven_joints()
    cyl = V.PHYS["cyl"]
    stations = {}
    for name, s in VP.FL.stations().items():
        stations[name] = {"swivel": round(s["swivel"], 3), "reach": round(s["reach"], 3),
                          "contact": round(VP.contact_plunge(name), 3)}
    s0 = C.initial()
    slots = {}
    for i, sl in enumerate(s0["slots"]):
        if sl:
            slots[C.SLOTS[i]] = {"mould": iec.MIX[sl[0]], "cookie": iec.CIX[sl[1]] if sl[1] else 0}
    cookies = {iec.CIX[c]: {"id": c, "flavour": C.FLAV[c], "mV": PL.FLAVOURS[C.FLAV[c]]["mV"],
                            "colour": PL.FLAVOURS[C.FLAV[c]]["colour"], "baked": c not in C.PRODUCE}
               for c in C.CIDS}
    bays = [[iec.CIX[c] for c in s0["bays"][b]] for b in range(len(C.BAYS))]
    oven_rows = {r: C.MO.OVEN_CYCLE[r][0] for r in (1, 2, 8, 9, 16)}
    return {
        "scan_ms": iec.SCAN_MS,
        "hbw": {
            "v": C.V_HBW, "cv_x": HM.P["CV_X"], "fork_out": HM.P["FORK"][1], "transit": C.TR,
            "cols": list(HM.P["BAY_X"]), "rows": dict(zip("ABC", HM.P["ROW_Z"], strict=False)), "slots": C.SLOTS,
            "belt_z": 90.0,                     # between the 100 (above) and 80 (below) of the conveyor legs
            "belt": {"v": C.V_BELT, "crane_end": HM.P["PICK_HBW"], "vgr_end": HM.P["PICK_VGR"],
                     "rp1": HM.RFID_Y[0], "rp2": HM.RFID_Y[1], "rfid_s": V.PHYS["rfid"], "rp_window": 10.0},
            "init": {"travel": 420.0, "lift": 170.0, "fork": 40.0},     # anywhere: homing must cope
        },
        "vgr": {
            "v_mm": C.V_MM, "v_deg": C.V_DEG, "transit": VG.V["TRANSIT"], "plunge": list(VG.V["PLUNGE"]),
            "reach": list(VG.V["REACH"]), "stations": stations, "overtravel": VP.OVERTRAVEL,
            "seal": {"swivel": iec.TOL["swivel"] * 2, "reach": iec.TOL["reach"] * 2, "plunge": 1.0},
            "vac_on": V.PHYS["vac_on"], "vac_off": V.PHYS["vac_off"],
            "init": {"swivel": 30.0, "reach": 120.0, "plunge": 380.0},
        },
        "oven": {
            "slider": {"in": J["slider"]["stops"]["innen"], "out": J["slider"]["stops"]["aussen"],
                       "v": (J["slider"]["stops"]["aussen"] - J["slider"]["stops"]["innen"]) / oven_rows[2]},
            "door_s": oven_rows[1] * cyl,
            "sauger": {"oven": J["sauger"]["stops"]["oven"], "tt": J["sauger"]["stops"]["turntable"],
                       "v": (J["sauger"]["stops"]["turntable"] - J["sauger"]["stops"]["oven"]) / oven_rows[8]},
            "lower_s": oven_rows[9] * cyl,
            "turn": {"v": 90.0 / oven_rows[16], "sauger": J["turn"]["stops"]["sauger"],
                     "saege": J["turn"]["stops"]["saege"], "band": J["turn"]["stops"]["band"]},
            "push_s": C.MO.OVEN_CYCLE[19][0] * cyl,
            "belt": {"start": OM.O["BELT_Y"][0], "end": OM.O["BELT_Y"][1], "v": C.V_BELT},
            "bake_s": C.BAKE["s"],
            "init": {"slider": 300.0, "door": 0.4, "sauger": 200.0, "lower": 0.0, "turn": -40.0, "push": 0.3},
        },
        "sorting": {
            "v": C.V_BELT, "inlet_x": SM.S["INLET_X"], "sensor_x": SM.S["SENSOR_X"], "after_x": SM.S["AFTER_X"],
            "eject_x": list(SM.S["EJECT_X"]), "pulse_mm": iec.PULSE_MM, "sensor_window": 20.0,
            "eject_window": 20.0, "eject_push_s": 0.2, "barrier_s": 0.3,
            "belt_mv": 1900, "raw_mv": 1500,        # ASSUMED: a bright belt, pale dough
            "bays": list(C.BAYS), "bay_cap": C.BAY_CAP,
        },
        "cookies": cookies, "slots0": slots, "bays0": bays,
        "moulds": {iec.MIX[m]: m for m in iec.MIX},
        "tol": iec.TOL,
    }


def export(out=OUT):
    os.makedirs(out, exist_ok=True)
    p = params()
    with open(os.path.join(out, "plant.json"), "w") as f:
        json.dump(p, f, indent=1)
    return p


if __name__ == "__main__":
    export()
    print("plant.json written")
