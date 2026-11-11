"""
The renderer's parameters for the browser (web/src/vision/render.ts), from vision/render.py,
so the live camera feed draws its images with the same numbers the CNN was trained on.

    python3 -m vision.params          (from stf-cad/hbw; part of `make vision-live`)
"""
import json
import os

from vision import render

OUT = os.path.join(os.path.dirname(render.__file__), "..", "..", "..", "web", "public", "vision", "render.json")


def main():
    out = {"N": render.N, "MM": render.MM, "REF": render.REF, "belt": render.BELT, "wp_d": render.SM.S["WP_D"],
           "dough": [float(v) for v in render.DOUGH], "colour": {f: [float(v) for v in c] for f, c in render.COLOUR.items()},
           "flavours": render.FLAVOURS, "conditions": render.CONDITIONS,
           "ranges": {"narrow": render.NARROW, "wide": render.WIDE, "shift": render.SHIFT}}
    json.dump(out, open(OUT, "w"), indent=1)
    print("wrote", os.path.relpath(OUT))


if __name__ == "__main__":
    main()
