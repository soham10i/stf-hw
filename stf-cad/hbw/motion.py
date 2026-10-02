"""
Motion for the FreeCAD twin: every joint container is driven from the models'
own proven sequences - nothing here invents a move.

  HBW      hbw_model.cycle()          25 waypoints, swept by check_path()
  VGR      vgr_path.plan()            42 waypoints, 2 191 swept poses proven clear
  Oven     OVEN_CYCLE below           booklet p.30, step by step; EVERY keyframe
                                      and every interpolated frame must pass
                                      oven_model.pose_allowed() (door/slider,
                                      Q12-at-a-stop, Auswerfer-at-the-belt)
  Sorting  one ejector at a time      sorting_model.pose_allowed()

timeline() -> {machine: [(t_seconds, {joint: value})]}; pose_at(t) interpolates
linearly; apply(doc, pose) moves the App::Part joints of STF_Factory_MCP.
Plain Python (no FreeCAD) except apply().
"""
import vgr_model as VG
import oven_model as OM
import sorting_model as SM
import hbw_model as HM
import vgr_path

# (seconds for the move, {joint: target}, what the booklet says happens)
O = OM.O
S_IN, S_OUT = O["SLIDER"]
D_SHUT, D_OPEN = O["DOOR_Z"]
SG_OVEN, SG_TT = O["SAUGER"]
LOW = O["LOWER"][1]
PUSH = O["PUSH"][1]
OVEN_CYCLE = [
    (0.0, dict(slider=S_IN, door=D_SHUT, turn=0.0, sauger=SG_TT, lower=0.0, push=0.0),
     "idle: slider in, door shut, Sauger parked over the Drehtisch"),
    (1.0, dict(door=D_OPEN), "Q13: door opens"),
    (2.0, dict(slider=S_OUT), "Q6: Ofenschieber extends - the VGR lays the workpiece on it (I9 breaks)"),
    (2.0, dict(slider=S_IN), "Q5: slider retracts into the oven"),
    (1.0, dict(door=D_SHUT), "door shuts - bake (Q9 lamp)"),
    (2.0, dict(), "baking"),
    (1.0, dict(door=D_OPEN), "door opens"),
    (2.0, dict(slider=S_OUT), "slider extends"),
    (2.0, dict(sauger=SG_OVEN), "Q7: Sauger to the oven (I8)"),
    (0.6, dict(lower=LOW), "Q12: lower onto the workpiece, Q11 vacuum"),
    (0.6, dict(lower=0.0), "lift"),
    (2.0, dict(sauger=SG_TT), "Q8: Sauger to the Drehtisch (I5)"),
    (0.6, dict(lower=LOW), "lower, release onto the disc"),
    (0.6, dict(lower=0.0), "lift"),
    (2.0, dict(slider=S_IN), "slider retracts"),
    (1.0, dict(door=D_SHUT), "door shuts"),
    (1.5, dict(turn=-90.0), "Q1: Drehtisch to the Säge (I4)"),
    (2.0, dict(), "Q4: saw runs"),
    (1.5, dict(turn=-180.0), "Drehtisch to the belt (I2)"),
    (0.6, dict(push=PUSH), "Q14: Auswerfer pushes the workpiece onto the belt"),
    (0.6, dict(push=0.0), "Auswerfer home"),
    (1.5, dict(turn=0.0), "I3 passed: Drehtisch home"),
]


def _keys(seq, start):
    """[(dur, delta, say)] -> [(t, full_pose, say)] with absolute times."""
    t, pose, out = 0.0, dict(start), []
    for dur, delta, say in seq:
        t += dur
        pose = {**pose, **delta}
        out.append((t, dict(pose), say))
    return out


def oven_keys():
    start = OVEN_CYCLE[0][1]
    keys = [(0.0, dict(start), OVEN_CYCLE[0][2])] + _keys(OVEN_CYCLE[1:], start)
    return keys


def check_oven(steps=12):
    """Every keyframe and every interpolated frame must be an allowed pose."""
    fails = []
    keys = oven_keys()
    for (t0, a, s0), (t1, b, s1) in zip(keys, keys[1:]):
        for k in range(steps + 1):
            u = k / steps
            p = {j: a[j] + (b[j] - a[j]) * u for j in a}
            if not OM.pose_allowed(p["slider"], p["door"], p["turn"], p["sauger"], p["lower"], p["push"]):
                fails.append(f"oven: '{s1}' passes a forbidden pose at u={u:.2f}: {p}")
                break
    return fails


def vgr_keys(speed_deg=60.0, speed_mm=120.0):
    plan = vgr_path.plan()
    out, t = [], 0.0
    prev = None
    for w in plan:
        cur = dict(swivel=w["sw"], plunge=w["pz"], reach=w["rr"])
        if prev is not None:
            dt = max(abs(cur["swivel"] - prev["swivel"]) / speed_deg,
                     abs(cur["plunge"] - prev["plunge"]) / speed_mm,
                     abs(cur["reach"] - prev["reach"]) / speed_mm, 0.4)
            t += dt
        cur["carry"] = 1.0 if w.get("carry") else 0.0
        out.append((t, cur, w.get("say", "")))
        prev = cur
    return out


def hbw_keys(speed=150.0):
    out, t, prev = [], 0.0, None
    for tr, lf, fk, _ in HM.cycle():
        cur = dict(travel=tr, lift=lf, fork=fk)
        if prev is not None:
            t += max(max(abs(cur[j] - prev[j]) for j in cur) / speed, 0.4)
        out.append((t, cur, ""))
        prev = cur
    return out


def sorting_keys():
    out, t = [(0.0, dict(push0=0.0, push1=0.0, push2=0.0), "belt runs")], 0.0
    e = SM.S["EJECT"][1]
    for i, col in enumerate(SM.COLOURS):
        for dur, v in ((2.0, 0.0), (0.5, e), (0.5, 0.0)):
            t += dur
            pose = dict(push0=0.0, push1=0.0, push2=0.0)
            pose[f"push{i}"] = v
            if not SM.pose_allowed((pose["push0"], pose["push1"], pose["push2"])):
                raise AssertionError("sorting: two ejectors at once")
            out.append((t, pose, f"eject {col}"))
    return out


def timeline():
    return {"hbw": hbw_keys(), "vgr": vgr_keys(), "oven": oven_keys(), "sorting": sorting_keys()}


def pose_at(keys, t):
    """Linear interpolation, looping each machine's own cycle."""
    T = keys[-1][0]
    if T <= 0:
        return dict(keys[0][1])
    t = t % T
    for (t0, a, _), (t1, b, _) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            u = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            return {j: a[j] + (b[j] - a[j]) * u for j in a}
    return dict(keys[-1][1])


# ------------------------------------------------------------- FreeCAD side
def apply(doc, poses):
    """poses: {machine: {joint: value}}. Moves the joint containers; values are
    absolute joint coordinates in the models' own units."""
    import FreeCAD as App
    Vc, R = App.Vector, App.Rotation
    g = doc.getObject
    if "hbw" in poses:
        p = poses["hbw"]
        g("J1_Travel_X").Placement = App.Placement(Vc(p["travel"], 0, 0), R())
        g("J2_Lift_Z").Placement = App.Placement(Vc(0, 0, p["lift"]), R())
        g("J3_Ausleger_Y").Placement = App.Placement(Vc(0, p["fork"], 0), R())
    if "vgr" in poses:
        p = poses["vgr"]
        a = VG.V
        g("J_Swivel").Placement = App.Placement(Vc(a["CX"], a["CY"], 0), R(Vc(0, 0, 1), p["swivel"]))
        g("J_Plunge").Placement = App.Placement(Vc(0, 0, p["plunge"] - 250.0), R())
        g("J_Reach").Placement = App.Placement(Vc(0, -p["reach"], 0), R())
        held = g("VGR_held_cookie")
        if held is not None and held.ViewObject is not None:
            held.ViewObject.Visibility = p.get("carry", 0.0) > 0.5
    if "oven" in poses:
        p = poses["oven"]
        tcx, tcy = O["TT"]
        g("J_Ofenschieber").Placement = App.Placement(Vc(p["slider"] - 435.0, 0, 0), R())
        g("J_Ofentuer").Placement = App.Placement(Vc(0, 0, p["door"] - 170.0), R())
        g("J_Drehkranz").Placement = App.Placement(Vc(tcx, tcy, 0), R(Vc(0, 0, 1), p["turn"]))
        g("J_Sauger").Placement = App.Placement(Vc(0, p["sauger"] - 335.0, 0), R())
        g("J_Senken").Placement = App.Placement(Vc(0, 0, -p["lower"]), R())
        g("J_Auswerfer").Placement = App.Placement(Vc(0, p["push"], 0), R())
    if "sorting" in poses:
        p = poses["sorting"]
        for i, col in enumerate(SM.COLOURS):
            g(f"J_Auswurf_{col}").Placement = App.Placement(Vc(0, -p[f"push{i}"], 0), R())


if __name__ == "__main__":
    f = check_oven()
    tl = timeline()
    for m, k in tl.items():
        print(f"{m:8s} {len(k):3d} keyframes, cycle {k[-1][0]:6.1f} s")
    print("oven cycle:", "every frame allowed" if not f else "\n".join(f))
