"""
Regenerate the golden trajectories.

    python -m tests.generate_goldens

Prints a summary table before writing. Read it: the table is the reviewable
part of the change, and a diff that alters every cycle time should be an
explicit decision rather than a silent binary update.
"""

from __future__ import annotations

import sys

import numpy as np

from stf_layout import load_layout

from .test_golden_trajectories import GOLDEN_DIR, OPERATIONS, golden_path, record


def main() -> int:
    layout = load_layout()
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

    print(f"layout fingerprint: {layout.fingerprint()}")
    print(f"travel speed:       {layout.joint('hbw.travel').drive.max_speed:.4f} mm/s")
    print()
    print(f"{'trajectory':<18}{'plan (s)':>10}{'sim (s)':>10}{'segments':>10}{'pulses':>10}"
          f"{'delta':>10}")
    print("-" * 68)

    changed = 0
    for operation in sorted(OPERATIONS):
        for slot in layout.all_slots():
            data = record(layout, operation, slot)
            path = golden_path(operation, slot)

            delta = "new"
            if path.exists():
                previous = float(np.load(path)["summary"][0])
                shift = data["summary"][0] - previous
                delta = "same" if abs(shift) < 1e-6 else f"{shift:+.2f}s"
                if abs(shift) >= 1e-6:
                    changed += 1
            else:
                changed += 1

            np.savez_compressed(path, **data)
            print(
                f"{operation + ':' + slot:<18}"
                f"{data['summary'][0]:>10.2f}"
                f"{data['summary'][3]:>10.2f}"
                f"{int(data['summary'][1]):>10d}"
                f"{int(data['summary'][2]):>10d}"
                f"{delta:>10}"
            )

    print("-" * 68)
    print(f"wrote {len(OPERATIONS) * len(layout.all_slots())} goldens to {GOLDEN_DIR}")
    print(f"{changed} changed - review the durations above before committing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
