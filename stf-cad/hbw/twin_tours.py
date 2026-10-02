"""
The VGR tours the twin's order mode needs (STF_VARIANT=up12).

The exported plan (hbw_parts_up12.json) holds one demo tour: raw cookie belt -> oven, then a
baked cookie from the red Lagerstelle -> belt. With real orders the VGR collects the oldest
finished cookie from WHICHEVER Lagerstelle holds one, or nothing when all are empty. Each of
those four tours is planned by vgr_path.plan() and swept by vgr_path.check() - the same
planner and the same collision proof as the demo tour - and nothing is written unless every
one is clear. A separate file, so the proven Upgrade 12 export stays byte-identical.

    STF_VARIANT=up12 python3 twin_tours.py        -> web/public/vgr_tours.json
"""
import json
import os

import sorting_model as SM
import vgr_path as VP

OUT = os.path.expanduser("~/workspace/stf-hw/web/public/vgr_tours.json")
TO_OVEN = [("belt", "pick", "raw", "warehouse belt"), ("oven", "place", None, "oven's Ofenschieber")]


def tours():
    out = {"none": TO_OVEN}
    for c in SM.COLOURS:
        out[c] = TO_OVEN + [(f"bay_{c}", "pick", "baked", f"{c} Lagerstelle"), ("belt", "place", None, "warehouse belt")]
    return out


def main():
    res, fails = {}, []
    for name, tour in tours().items():
        f = VP.check(verbose=False, tour=tour)
        fails += [f"{name}: {x}" for x in f]
        res[name] = VP.plan(tour)
    if fails:
        raise SystemExit("a tour is not clear:\n" + "\n".join(fails[:20]))
    with open(OUT, "w") as fh:
        json.dump({"tours": res, "blend": VP.BLEND["on"],
                   "proof": "each tour swept by vgr_path.check(): no VGR part or carried cookie touches a module"}, fh,
                  separators=(",", ":"))
    print(f"{len(res)} tours clear: " + ", ".join(f"{k} {len(v)} waypoints" for k, v in res.items()))


if __name__ == "__main__":
    main()
