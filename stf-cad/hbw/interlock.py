"""
Upgrade 12 - the hardwired interlocks, as data (no heavy imports: io_nodes reads it).

Every jog rule of control.JOG was enforced by the PLC program only. A rule
becomes a HARDWIRED interlock when hardening.py proves all three:
  (1) a permissive signal exists without new sensors (a switch or reed the
      machine already has, or a relay contact),
  (2) the interlock never blocks a step of the production program - replayed
      over every job's steps and every homing sequence,
  (3) violating it damages the machine (a collision, not a lost cycle).
The interlock is an interface relay on the node's DIN rail: its coil sits in
parallel with the PLC input that reads the permissive, and its NO contact is in
series with the coil supply of the motor or valve relays it guards. A command
from the network - the PLC's own, or anyone's - then cannot power the motor
while the permissive is false. These protect the MACHINE; they are not safety
functions and no performance level is claimed (Upgrade 2's guard does that).

ADOPTED is what hardening.py must reproduce from the analysis; the export
refuses if the two ever differ.
"""
# id -> (module, guarded outputs, permissive, the relay's contact, why)
CANDIDATES = {
    "IL1": ("hbw", ("Q3", "Q4"), "I6", "fork back",
            "crane travel only with the Ausleger at its rear stop: travelling with the fork in a shelf tears the rack"),
    "IL2": ("hbw", ("Q5", "Q6"), "I6", "fork back",
            "crane lift only with the Ausleger back: lifting with the fork in a shelf"),
    "IL3": ("hbw", ("Q7",), "POS", "at a slot or the conveyor",
            "Ausleger out only at a rack column or the conveyor, at slot height"),
    "IL4": ("vgr", ("Q5", "Q6"), "TRANSIT", "plunge at transit height",
            "VGR swivel only at transit height, above everything on the table"),
    "IL5": ("oven", ("Q5", "Q6"), "I10", "door open",
            "Ofenschieber only with the oven door open: the slider drives into the shut door"),
    "IL6": ("oven", ("Q7", "Q8"), "I13", "Sauger up",
            "Sauger travel only with the Sauger up: dragging the lowered cup across the tray"),
    "IL7": ("oven", ("Q1", "Q2"), "I15", "Auswerfer home",
            "Drehtisch turn only with the Auswerfer home: turning with the pusher out shears it"),
    "IL8": ("sorting", ("Q3", "Q4", "Q5"), "NOT Q1", "belt stopped",
            "ejectors only with the sorting belt stopped: firing into a moving cookie jams it at the chute"),
}
ADOPTED = ("IL1", "IL5", "IL6", "IL7", "IL8")


def relays(module):
    """The interlock relays on a module's node rail: [(id, permissive, contact)]."""
    return [(k, CANDIDATES[k][2], CANDIDATES[k][3]) for k in ADOPTED if CANDIDATES[k][0] == module]
