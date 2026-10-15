"""
One grounding rule, shared by every module.

The support test each model already had only asked "does this part touch the
thing it names?". Naming `plate` skipped even that, so a part could declare the
base plate as its support while floating 90 mm above it and pass. That is what
made modules appear to hang in mid-air.

The rule now:

  * support == "plate"  ->  the part's underside must actually BE on the plate
                            (bottom z ~ 0). No exceptions, no free pass.
  * anything else       ->  it must touch its support AND either have solid
                            material directly beneath its footprint, or be
                            explicitly declared a CANTILEVER - a part bolted to
                            a vertical face, which is how ft shelf brackets and
                            sensor mounts really work. A cantilever must have a
                            substantial side contact, not a sliver.
"""

CANTILEVER_MIN_CONTACT = 40.0     # mm^2 of face contact before we believe a bolt


def _box(p):
    return p.aabb() if hasattr(p, "aabb") else p.local_aabb()


def check_grounding(parts, aliases=None, cantilevers=(), tol=0.6, plate_tol=0.05):
    aliases = aliases or {}
    cant = set(cantilevers)
    idx = {p.name: p for p in parts}
    boxes = [(p, _box(p)) for p in parts if p.group != "frame"]
    fails = []
    for p, a in boxes:
        sup = aliases.get(p.support, p.support)
        if sup == "table":
            continue
        if sup == "plate":
            if a[2] > plate_tol:
                fails.append(f"UNGROUNDED {p.name}: declares the plate as its support "
                             f"but its underside is at z={a[2]:.1f} - it needs a real "
                             f"leg, pedestal or bracket")
            continue
        if sup not in idx:
            fails.append(f"UNSUPPORTED {p.name}: '{p.support}' does not exist")
            continue
        b = _box(idx[sup])
        sep = max(max(a[i], b[i]) - min(a[i + 3], b[i + 3]) for i in range(3))
        if sep > tol:
            fails.append(f"FLOATING {p.name}: does not touch {sup}")
            continue
        if p.name in cant:
            ox = min(a[3], b[3]) - max(a[0], b[0])
            oy = min(a[4], b[4]) - max(a[1], b[1])
            oz = min(a[5], b[5]) - max(a[2], b[2])
            face = max(ox * oy, ox * oz, oy * oz)
            if face < CANTILEVER_MIN_CONTACT:
                fails.append(f"WEAK CANTILEVER {p.name}: only {face:.0f} mm2 of face "
                             f"against {sup}")
            continue
        if a[2] <= plate_tol:
            continue
        under = any(q is not p and abs(c[5] - a[2]) <= tol
                    and min(a[3], c[3]) - max(a[0], c[0]) > 0.5
                    and min(a[4], c[4]) - max(a[1], c[1]) > 0.5
                    for q, c in boxes)
        if not under:
            fails.append(f"NOTHING UNDERNEATH {p.name} at z={a[2]:.1f}: no solid below "
                         f"its footprint, and it is not declared a cantilever")
    return fails
