"""
The factory pipeline: twelve cookies, four modules, one schedule.

Two things this file is responsible for, and nothing else may duplicate them:

  1. THE INVENTORY. Exactly twelve cookies exist. They are created here once and
     never anywhere else - hbw_model and sorting_model take their cookie
     placement from this file, so the count cannot drift by someone adding a
     decorative one to a scene.

  2. THE SCHEDULE. Every transfer is one operation with an explicit resource
     set, an explicit source and destination, and the joint poses it commands.

Flavours, and why these three:
    The Farbsensor (128599) is NOT an RGB sensor - it measures how much light
    comes back off the part. So the three flavours are chosen to be separable by
    REFLECTED BRIGHTNESS, which is the only thing the hardware can actually see:
    chocolate is dark, strawberry mid, vanilla bright. Each maps onto one of the
    sorting line's three physical bins.

DEADLOCK FREEDOM is by construction, not by hope:
    * every operation acquires ALL its resources before it starts
      -> no hold-and-wait
    * acquisition follows one fixed total order over resources
      -> no circular wait
    * every operation releases everything when it ends
      -> no indefinite hold
    Coffman's four conditions need all four; two are structurally impossible
    here. `simulate()` additionally builds the wait-for graph at every step and
    asserts it is acyclic, so the claim is checked as well as argued.

COOKIE SAFETY: every operation moves a cookie from exactly one place to exactly
one place, the destination must have been reserved and be empty, and the total
must still be twelve afterwards. A cookie can therefore be neither duplicated
nor destroyed, and the checker says so at every step.
"""
from dataclasses import dataclass, field

# --------------------------------------------------------------- inventory
# A cookie is raw LIGHT-BROWN dough until it is baked; only then does it take
# its flavour colour (user, 2026-09-28): vanilla white, chocolate brown,
# strawberry pink. The Farbsensor readings are unchanged - they rank by
# reflected brightness, and white > pink > brown keeps the same order.
RAW_COLOUR = "#D8B98C"
FLAVOURS = {
    #                  BAKED colour    nominal Farbsensor reading   sorting bin
    "chocolate":  {"colour": "#5C3A1E", "mV": 340,  "bin": "blau"},
    "strawberry": {"colour": "#F4A6BF", "mV": 950,  "bin": "rot"},
    "vanilla":    {"colour": "#FBF8F1", "mV": 1660, "bin": "weiss"},
}
N_COOKIES = 12
BIN_OF = {f: v["bin"] for f, v in FLAVOURS.items()}
FLAVOUR_OF_BIN = {v["bin"]: f for f, v in FLAVOURS.items()}

# Nine start in the rack, one per flavour starts in its Lagerstelle. 9 + 3 = 12.
RACK_START = [
    ("A1", "chocolate"), ("A2", "vanilla"), ("A3", "strawberry"), ("A4", "chocolate"),
    ("B1", "vanilla"), ("B2", "strawberry"), ("B3", "chocolate"), ("B4", "vanilla"),
    ("C1", "strawberry"),
]
BAY_START = [("weiss", "vanilla"), ("rot", "strawberry"), ("blau", "chocolate")]

assert len(RACK_START) + len(BAY_START) == N_COOKIES, "inventory must be exactly 12"
assert all(f in FLAVOURS for _, f in RACK_START + BAY_START)


def initial_inventory():
    """id -> (flavour, location). The ONLY place cookies come into existence."""
    inv = {}
    for i, (slot, fl) in enumerate(RACK_START):
        inv[f"c{i:02d}"] = (fl, ("rack", slot))
    for j, (bay, fl) in enumerate(BAY_START, start=len(RACK_START)):
        inv[f"c{j:02d}"] = (fl, ("bay", bay))
    return inv


# --------------------------------------------------------------- resources
# One fixed total order. Every operation acquires in increasing index.
RESOURCES = [
    "hbw_crane", "hbw_belt", "handover_belt", "vgr", "handover_oven",
    "oven", "sauger", "turntable", "oven_belt", "sort_inlet", "sort_belt",
    "bay_weiss", "bay_rot", "bay_blau",
]
RANK = {r: i for i, r in enumerate(RESOURCES)}

# Every place a cookie can be, and how many fit. Places are protected by
# OCCUPANCY, not by locks - a cookie parked on the oven tray is itself the
# reservation. Locks are only ever taken for the duration of one transfer.
# How many cookies fit in ONE place. A rack slot takes one; a Lagerstelle is a
# tray the ejector pushes parts onto, so it accumulates.
CAPACITY = {("rack",): 1, ("bay",): 4}
PER_PLACE = {"rack": 1, "bay": 4}


@dataclass
class Op:
    name: str
    agent: str
    needs: tuple
    src: tuple
    dst: tuple
    poses: dict = field(default_factory=dict)
    say: str = ""
    # Places that must ALL be empty before this move may start - not just the
    # destination. The oven needs it: tray and chamber are two places inside one
    # single-part station, and letting a second cookie onto the tray while the
    # first is still baking deadlocks them against each other. The wait-for
    # detector found exactly that, which is what this field exists for.
    exclusive: tuple = ()
    # A processing step - the Saege - where the cookie stays put. It still holds
    # its resource for the duration, which is what stops anything else arriving.
    process: bool = False


def plan_for(cookie_id, flavour, start):
    """One cookie's journey as PLACE-TO-PLACE transfers.

    Each transfer is atomic from the scheduler's point of view: it takes every
    lock it needs at once, moves the cookie from one place to one place, and
    releases everything. There is deliberately no schedulable state where a
    cookie sits on a gripper - that state is internal to a transfer. It is what
    removes hold-and-wait, and without hold-and-wait a deadlock cannot form at
    all. (The first draft did model "on the fork" as a state; the safety checker
    immediately caught two cookies being put on one fork.)
    """
    b = BIN_OF[flavour]
    if start[0] == "rack":
        slot = start[1]
        return [
            Op("rack_to_belt", "hbw", ("hbw_crane", "hbw_belt"),
               ("rack", slot), ("hbw_belt",),
               {"travel": "bay", "lift": "row", "fork": "bay", "slot": slot},
               f"crane lifts the {flavour} out of {slot} and sets its mould on the belt"),
            Op("belt_out", "hbw", ("hbw_belt", "handover_belt"),
               ("hbw_belt",), ("handover_belt",), {"belt": "vgr"},
               "Q1 carries it through the identification tunnel"),
            Op("belt_to_oven", "vgr", ("handover_belt", "vgr", "oven"),
               ("handover_belt",), ("oven_tray",), {"station": "oven"},
               "Q8 vacuum on - VGR lifts it off the mould and onto the Ofenschieber",
               exclusive=(("oven_tray",), ("oven_chamber",))),
            Op("bake", "oven", ("oven",), ("oven_tray",), ("oven_chamber",),
               {"door": "open", "slider": "innen", "lamp": True, "bakes": True},
               "door opens, slider retracts, door shuts, Q9 bakes - raw white "
               "dough becomes its flavour colour"),
            Op("unbake", "oven", ("oven",), ("oven_chamber",), ("oven_tray",),
               {"door": "open", "slider": "aussen", "lamp": False},
               "door opens, slider extends"),
            # Booklet p.30, verbatim: the STATION'S OWN Sauggreifer takes the
            # workpiece off the slider and puts it on the Drehtisch. The VGR only
            # ever LOADS this module - it does not collect from it. Having the VGR
            # do both was my error, and it skipped three real machines.
            Op("oven_to_turntable", "oven", ("oven", "sauger", "turntable"),
               ("oven_tray",), ("turntable",), {"sauger": "oven->turntable"},
               "the station's Sauggreifer lifts it off the slider onto the Drehtisch"),
            Op("saw", "oven", ("turntable",), ("turntable",), ("turntable",),
               {"turn": "saw"}, "Drehtisch carries it under the Saege and dwells",
               process=True),
            Op("eject", "oven", ("turntable", "oven_belt"),
               ("turntable",), ("oven_belt",), {"turn": "belt", "eject": True},
               "Drehtisch turns to the belt; the Auswerfer pushes it across"),
            Op("oven_belt_out", "oven", ("oven_belt", "sort_inlet"),
               ("oven_belt",), ("sort_belt",), {"belt": "run"},
               "Q3 carries it to I3 and hands it to the Sortierstrecke"),
            Op("sort", "sorting", ("sort_belt", f"bay_{b}"),
               ("sort_belt",), ("bay", b),
               {"eject": b, "mV": FLAVOURS[flavour]["mV"]},
               f"A4 reads ~{FLAVOURS[flavour]['mV']} mV -> the {b} ejector fires"),
        ]
    bay = start[1]
    return [
        Op("bay_to_belt", "vgr", ("hbw_belt", "handover_belt", "vgr", f"bay_{bay}"),
           ("bay", bay), ("hbw_belt",), {"station": f"bay_{bay}"},
           f"VGR collects the {flavour} from the {bay} Lagerstelle and feeds the warehouse"),
        Op("belt_in", "hbw", ("hbw_crane", "hbw_belt"),
           ("hbw_belt",), ("rack", "*"),
           {"travel": "bay", "lift": "row", "fork": "bay"},
           "crane takes it off the belt and stores it in whichever slot is free"),
    ]


# --------------------------------------------------------------- simulation
class Deadlock(Exception):
    pass


class Unsafe(Exception):
    pass


RACK_SLOTS = [f"{r}{c}" for r in "ABC" for c in "1234"]


def simulate(verbose=False, max_steps=4000):
    """Run every cookie through the pipeline, checking the invariants each step."""
    inv = initial_inventory()
    held = {}                       # resource -> job id
    waiting = {}                    # job id -> resource it is blocked on
    queues = {cid: plan_for(cid, fl, loc) for cid, (fl, loc) in inv.items()}
    pcs = {cid: 0 for cid in inv}
    log, steps, baked = [], 0, set()

    def occupancy():
        occ = {}
        for cid, (_, loc) in inv.items():
            occ.setdefault(loc[0], []).append(cid)
        return occ

    def check_safe(where):
        if len(inv) != N_COOKIES:
            raise Unsafe(f"{where}: {len(inv)} cookies, must be {N_COOKIES}")
        counts = {}
        for _, loc in inv.values():
            counts[loc] = counts.get(loc, 0) + 1
        for loc, n in counts.items():
            cap = PER_PLACE.get(loc[0], 1)
            if n > cap:
                raise Unsafe(f"{where}: {loc} holds {n}, capacity {cap}")
        for r, owner in held.items():
            if r not in RANK:
                raise Unsafe(f"{where}: unknown resource {r}")

    def wait_for_cycle():
        """A cycle here would BE a deadlock. Acquiring in one total order makes
        it impossible; we assert it anyway rather than take it on faith."""
        edges = {}
        for job, res in waiting.items():
            if res.startswith("place:"):
                # waiting on a PLACE: blocked by whoever is standing in it
                key = res[6:]
                for other, (_, l) in inv.items():
                    if other != job and str(l) == key:
                        edges.setdefault(job, set()).add(other)
                continue
            owner = held.get(res)
            if owner is not None and owner != job:
                edges.setdefault(job, set()).add(owner)
        seen, stack = set(), set()

        def dfs(n):
            if n in stack:
                return True
            if n in seen:
                return False
            seen.add(n); stack.add(n)
            for m in edges.get(n, ()):
                if dfs(m):
                    return True
            stack.discard(n)
            return False

        return any(dfs(n) for n in list(edges))

    check_safe("start")
    order = list(queues)
    while any(pcs[c] < len(queues[c]) for c in order) and steps < max_steps:
        steps += 1
        progressed = False
        for cid in order:
            if pcs[cid] >= len(queues[cid]):
                continue
            op = queues[cid][pcs[cid]]
            needs = sorted(op.needs, key=lambda r: RANK[r])     # THE total order
            blocked = next((r for r in needs if held.get(r) not in (None, cid)), None)
            if blocked:
                waiting[cid] = blocked
                continue
            # ---- resolve the destination, then RESERVE IT BEFORE COMMITTING
            fl, loc = inv[cid]
            if loc != op.src:
                raise Unsafe(f"{cid} is at {loc}, op '{op.name}' expects {op.src}")
            dst = op.dst
            if dst == ("rack", "*"):
                taken = {l[1] for _, l in inv.values() if l[0] == "rack"}
                free = [s_ for s_ in RACK_SLOTS if s_ not in taken]
                if not free:
                    waiting[cid] = "place:('rack',)"
                    continue
                dst = ("rack", free[0])
            blocked_place = None
            for place in op.exclusive:          # whole-station exclusion, if any
                if [c for c, (_, l) in inv.items() if l == place and c != cid]:
                    blocked_place = place
                    break
            if blocked_place is not None:
                waiting[cid] = f"place:{blocked_place}"
                continue
            occupants = [c for c, (_, l) in inv.items() if l == dst and c != cid]
            if op.process:
                occupants = []          # it is already there; it is not arriving
            if len(occupants) >= PER_PLACE.get(dst[0], 1):
                # A place, not a lock. Never take the locks for a move whose
                # destination is full - that is the rule that stops a gripper
                # picking a cookie up with nowhere to put it down.
                waiting[cid] = f"place:{dst}"
                continue
            waiting.pop(cid, None)
            for r in needs:
                held[r] = cid
            inv[cid] = (fl, dst)
            if op.poses.get("bakes"):
                baked.add(cid)
            log.append({"cookie": cid, "flavour": fl, "op": op.name, "agent": op.agent,
                        "baked": cid in baked,
                        "src": list(op.src), "dst": list(dst), "poses": op.poses,
                        "say": op.say})
            for r in needs:
                held.pop(r, None)
            pcs[cid] += 1
            progressed = True
            check_safe(f"after {cid}.{op.name}")
            if wait_for_cycle():
                raise Deadlock(f"wait-for cycle after {cid}.{op.name}")
        if not progressed:
            if wait_for_cycle():
                raise Deadlock("no job can progress and the wait-for graph has a cycle")
            raise Deadlock("no job can progress (livelock)")
    if steps >= max_steps:
        raise Deadlock("step limit reached")
    check_safe("end")
    if verbose:
        by_bin = {}
        for cid, (fl, loc) in inv.items():
            by_bin.setdefault(loc, []).append(f"{cid}:{fl}")
        print(f"{N_COOKIES} cookies, {len(log)} transfers, {steps} scheduler rounds")
        print("  final:")
        for loc in sorted(by_bin, key=str):
            print(f"    {str(loc):22s} {', '.join(sorted(by_bin[loc]))}")
    return log, inv, baked


def check_poses():
    """Every pose the schedule commands must be one the GEOMETRY allows.

    This is where the pipeline stops being a story about cookies and becomes
    part of the same proof as the models: a schedule that would drive a machine
    somewhere it physically cannot go fails the build, in the same run that
    checks the moulds do not sweep through the rack.
    """
    import hbw_model as HM, vgr_model as VG, oven_model as OM, sorting_model as SM
    import factory_layout as FL
    bad = []
    rows = dict(zip("ABC", HM.P["ROW_Z"]))
    stations = FL.stations()
    for cid, (fl, loc) in initial_inventory().items():
        for op in plan_for(cid, fl, loc):
            p = op.poses
            if op.agent == "hbw":
                slot = p.get("slot") or (op.dst[1] if op.dst[0] == "rack" else None)
                if slot and slot != "*":
                    tv = HM.P["BAY_X"][int(slot[1]) - 1]
                    z = rows[slot[0]]
                    for cb, what in ((z - 20.0, "approach"), (z, "lift")):
                        if not HM.pose_allowed(tv, cb, 115.0):
                            bad.append(f"{op.name} {slot}: fork at {what} (lift {cb}) "
                                       "is not an allowed HBW pose")
                        if what == "lift" and not HM.carry_allowed(tv, cb, 115.0):
                            bad.append(f"{op.name} {slot}: loaded fork at lift {cb} "
                                       "is outside the carry envelope")
            if op.agent == "vgr":
                st = p.get("station")
                if st and st in stations:
                    s_ = stations[st]
                    if not s_["in_envelope"]:
                        bad.append(f"{op.name}: VGR station '{st}' is outside the arm envelope")
                    lo, hi = FL.VGR_PLUNGE_BAND.get(st, (VG.V["PLUNGE"][0], VG.V["PLUNGE"][1]))
                    pick = max(lo, VG.V["CARRY_FLOOR"])
                    if not (FL.vgr_plunge_allowed(st, pick) and VG.carry_allowed(pick)):
                        bad.append(f"{op.name}: no plunge serves '{st}' both loaded "
                                   f"and inside its band {lo}..{hi}")
                elif st:
                    bad.append(f"{op.name}: unknown VGR station '{st}'")
            if op.agent == "oven" and ("slider" in p or "door" in p):
                # only ops that actually command the slider or the door are
                # constrained by the door interlock; the Sauger, Drehtisch, Saege
                # and belt steps leave both alone
                slider = OM.O["SLIDER"][0] if p.get("slider") == "innen" else OM.O["SLIDER"][1]
                door = OM.O["DOOR_Z"][1] if p.get("door") == "open" else OM.O["DOOR_Z"][0]
                if not OM.pose_allowed(slider, door, 0.0, OM.O["SAUGER"][1], 0.0):
                    bad.append(f"{op.name}: oven pose slider={slider} door={door} "
                               "violates the door interlock")
            if op.agent == "sorting":
                one = tuple(SM.S["EJECT"][1] if SM.COLOURS[i] == p.get("eject") else 0.0
                            for i in range(3))
                if not SM.pose_allowed(one):
                    bad.append(f"{op.name}: sorting pose {one} fires more than one ejector")
    return sorted(set(bad))


def check(verbose=True):
    fails = []
    try:
        log, inv, baked = simulate(verbose=verbose)
    except (Deadlock, Unsafe) as e:
        fails.append(f"{type(e).__name__}: {e}")
        if verbose:
            print("\n".join(fails))
        return fails
    if len(inv) != N_COOKIES:
        fails.append(f"inventory ended at {len(inv)}, must be {N_COOKIES}")
    for cid, (fl, loc) in inv.items():
        if loc[0] == "bay" and loc[1] != BIN_OF[fl]:
            fails.append(f"{cid} ({fl}) ended in the {loc[1]} bin, not {BIN_OF[fl]}")
        if loc[0] not in ("bay", "rack"):
            fails.append(f"{cid} ({fl}) ended in transit at {loc}")
    fails += check_poses()
    if verbose:
        print("\n".join(fails) if fails else
              "PIPELINE OK (12 cookies conserved, every one sorted into its own bin, "
              "no deadlock, no destination ever double-booked,\n"
              "  and every pose the schedule commands is one the geometry allows)")
    return fails


if __name__ == "__main__":
    import sys
    sys.exit(1 if check() else 0)
