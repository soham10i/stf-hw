---
name: stf-single-source-thesis
description: The one problem the STF project is built to solve — model drift across CAD, kinematics, control I/O
metadata:
  type: project
---
The differentiating problem the STF project attacks: **in every real digital
twin, geometry, kinematics, control logic and the I/O map live in different
tools and silently disagree.** This repo has already been bitten by it — four
mutually contradictory coordinate tables, documented at the top of
`packages/stf_layout/factory.layout.yaml`.

**Why:** it is a genuine, painful, universal industry problem with no good
off-the-shelf answer, and it is demonstrable in a way "I built a 3D viewer" is
not.

**How to apply:** one parameter table is authoritative; CAD, simulation
geometry, kinematic limits and the PLC I/O map are all *generated* from it, and
CI fails when any consumer drifts. Never let CAD become the source and the
layout a hand-copied echo. See [[stf-cad-pipeline]] and [[user-goal-portfolio]].
