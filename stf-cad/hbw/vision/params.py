"""
The renderer's parameters for the browser (web/src/vision/render.ts), from vision/render.py,
so the live camera feed draws its images with the same numbers the CNN was trained on.

    python3 -m vision.params          (from stf-cad/hbw; part of `make vision-live`)
"""
import json
import os

from vision import render as R

OUT = os.path.join(os.path.dirname(R.__file__), "..", "..", "..", "web", "public", "vision", "render.json")


def main():
    out = {"N": R.N, "MM": R.MM, "REF": R.REF, "belt": R.BELT, "wp_d": R.SM.S["WP_D"],
           "dough": [float(v) for v in R.DOUGH], "colour": {f: [float(v) for v in c] for f, c in R.COLOUR.items()},
           "flavours": R.FLAVOURS, "conditions": R.CONDITIONS,
           "ranges": {"narrow": R.NARROW, "wide": R.WIDE, "shift": R.SHIFT}}
    json.dump(out, open(OUT, "w"), indent=1)
    print("wrote", os.path.relpath(OUT))


if __name__ == "__main__":
    main()
