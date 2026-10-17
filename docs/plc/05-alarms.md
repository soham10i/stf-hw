# PLC alarms

Every alarm the program can raise. On an alarm the unit drops its outputs and goes to
`FAULT`; it is given no new job, and the other units finish their current step and hold.

## crane

| Code | Alarm | Cause | Reaction | Recovery |
|---|---|---|---|---|
| HBW-C01 | HBW crane: travel, lift, Ausleger: I6 not reached in time | I6 reference switch cantilever back: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| HBW-C02 | HBW crane: travel, lift, Ausleger: I4 not reached in time | I4 reference switch vertical: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| HBW-C03 | HBW crane: travel, lift, Ausleger: I1 not reached in time | I1 reference switch horizontal: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| HBW-C04 | HBW crane: travel, lift, Ausleger: target not reached in time | counter B1 encoder horizontal signal A; B2 encoder horizontal signal B stopped short: motor or its relay, the encoder, or a jam | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| HBW-C05 | HBW crane: travel, lift, Ausleger: target not reached in time | counter B3 encoder vertical signal A; B4 encoder vertical signal B stopped short: motor or its relay, the encoder, or a jam | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| HBW-C06 | HBW crane: travel, lift, Ausleger: I5 not reached in time | I5 reference switch cantilever front: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |

## belt

| Code | Alarm | Cause | Reaction | Recovery |
|---|---|---|---|---|
| HBW-B01 | HBW belt and the two RFID read points: I3 AND RF1.valid not reached in time | I3 phototransistor outside: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| HBW-B02 | HBW belt and the two RFID read points: RF2.valid AND RF2.tag = record not reached in time | : the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| HBW-B03 | HBW belt and the two RFID read points: I2 AND RF1.valid not reached in time | I2 phototransistor inside: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |

## arm

| Code | Alarm | Cause | Reaction | Recovery |
|---|---|---|---|---|
| VGR-A01 | VGR arm and vacuum: I1 not reached in time | I1 reference vertical: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| VGR-A02 | VGR arm and vacuum: I2 not reached in time | I2 reference horizontal: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| VGR-A03 | VGR arm and vacuum: I3 not reached in time | I3 reference rotate: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| VGR-A04 | VGR arm and vacuum: target not reached in time | counter B1 encoder vertical signal A; B2 encoder vertical signal B; B3 encoder horizontal signal A; B4 encoder horizontal signal B; B5 encoder rotate signal A; B6 encoder rotate signal B stopped short: motor or its relay, the encoder, or a jam | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| VGR-A05 | VGR arm and vacuum: I4 not reached in time | I4 vacuum switch: the cup is sealed on a part (-0.3 bar): the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| VGR-A06 | VGR arm and vacuum: NOT I4 not reached in time | I4 vacuum switch: the cup is sealed on a part (-0.3 bar): the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |

## door

| Code | Alarm | Cause | Reaction | Recovery |
|---|---|---|---|---|
| OVN-D01 | oven door, Ofenschieber and lamp: I10 not reached in time | I10 reed switch: oven door open: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| OVN-D02 | oven door, Ofenschieber and lamp: I6 not reached in time | I6 oven feeder inside: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| OVN-D03 | oven door, Ofenschieber and lamp: I11 not reached in time | I11 reed switch: oven door shut: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| OVN-D04 | oven door, Ofenschieber and lamp: I7 not reached in time | I7 oven feeder outside: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |

## sauger

| Code | Alarm | Cause | Reaction | Recovery |
|---|---|---|---|---|
| OVN-S01 | oven Sauggreifer: I13 not reached in time | I13 reed switch: Sauger up: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| OVN-S02 | oven Sauggreifer: I5 not reached in time | I5 reference vacuum (turntable position): the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| OVN-S03 | oven Sauggreifer: I8 not reached in time | I8 vacuum at oven: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| OVN-S04 | oven Sauggreifer: I12 not reached in time | I12 reed switch: Sauger lowered: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |

## turntable

| Code | Alarm | Cause | Reaction | Recovery |
|---|---|---|---|---|
| OVN-T01 | Drehtisch, Saege and Auswerfer: I15 not reached in time | I15 reed switch: Auswerfer home: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| OVN-T02 | Drehtisch, Saege and Auswerfer: I1 not reached in time | I1 reference turntable (vacuum position): the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| OVN-T03 | Drehtisch, Saege and Auswerfer: I4 not reached in time | I4 reference turntable (saw position): the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| OVN-T04 | Drehtisch, Saege and Auswerfer: I2 not reached in time | I2 reference turntable (belt position): the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| OVN-T05 | Drehtisch, Saege and Auswerfer: I14 not reached in time | I14 reed switch: Auswerfer out: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |

## ovenbelt

| Code | Alarm | Cause | Reaction | Recovery |
|---|---|---|---|---|
| OVN-B01 | oven belt: I3 not reached in time | I3 light barrier end of conveyor belt: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |

## line

| Code | Alarm | Cause | Reaction | Recovery |
|---|---|---|---|---|
| SRT-L01 | sorting line and ejectors: I3 not reached in time | I3 light barrier behind colour sensor: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| SRT-L02 | sorting line and ejectors: count(I1) = N_eject not reached in time | I1 pulse counter (Impulstaster): the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |
| SRT-L03 | sorting line and ejectors: I5 broken (the bay's light barrier) not reached in time | I5 light barrier white; I6 light barrier red; I7 light barrier blue: the drive did not arrive, or the switch/barrier failed | the unit drops its outputs and goes to FAULT; no new job is given to it; the other units finish their current step and hold | clear the cause; acknowledge on the HMI; the unit re-homes, and the job restarts from its first step (the place records say where the cookie is) |

## system

| Code | Alarm | Cause | Reaction | Recovery |
|---|---|---|---|---|
| SYS-01 | E-stop pressed (ES1, ES2 or ES3) | a person pressed it, or a channel fault | K0 drops K1/K2: actuator 24 V off, Y1 vents the air; every unit to ESTOP | release the E-stop, reset with S3, then every unit re-homes |
| SYS-02 | guard door open (SA, SB or SC) | door opened while the cell was running | as SYS-01; the door stays unlocked only at standstill | close the door, reset with S3, re-home |
| SYS-03 | safety relay feedback fault (EDM) | K1 or K2 contact welded, or wiring | K0 will not re-enable | replace the contactor; test the E-stop chain before production |
| SYS-04 | remote I/O node lost (Modbus TCP watchdog) | Ethernet cable, switch port or node supply | the node sets its outputs to 0 (its watchdog); the orchestrator holds every unit | restore the link; acknowledge; the units on that node re-home |
| SYS-05 | air pressure low at the air station (vgr I5) | compressor fault or a leak | hold every pneumatic step before it starts | restore pressure; acknowledge |
| TRC-01 | RP1/RP2: no tag read | tag missing or damaged, head fault, mould misplaced | belt stops; the job holds | check the mould; re-read, or enter the ID by hand with the operator's name logged |
| TRC-02 | RP2: tag differs from the record | wrong mould on the belt: the record and the rack disagree | the VGR does not pick; the belt holds | inspect; correct the record at the HMI (logged) or remove the mould |
| TRC-03 | A4: flavour class differs from the record | wrong cookie, or the sensor drifted | the ejector does not fire; the line stops with the cookie before the bays | remove the cookie by hand; its record is closed as 'rejected'; recalibrate A4 if it repeats |
| ORD-01 | bay full (4 cookies) | the bay was not emptied | sorting holds; the oven belt stops upstream | empty the bay and confirm on the HMI |
| VGR-V01 | vacuum lost while carrying (vgr I4 dropped) | cup seal broke, hose off, or air lost | the arm stops where it is; Q8 stays on; the cookie is down somewhere under the arm | the operator puts the cookie back at the job's source and confirms; the arm retraces its tour to transit height, re-homes, and the job restarts |
| SEC-01 | output read-back differs from the program's image | a write the program did not make (rogue client, spoofed master) or a node fault | every unit holds; the node's outputs are forced off; the firewall log is pulled | find the source in the firewall log; acknowledge with the security role |
| SEC-02 | a sensor arrived faster than the plant can move | a spoofed reply, or a sensor wired wrong | the unit goes to FAULT at once, before it acts on the signal | inspect the sensor and the node; acknowledge |
| SEC-03 | the running program's hash differs from the signed manifest | an unauthorised download | the PLC does not leave INIT | reload the signed program from the engineering station (maintenance mode) |
| SEC-04 | the cell firewall dropped a packet on a conduit | a device outside its allow-list: scan, misconfiguration or an attack | none on the machine: logged and shown | review the log entry |


*Sources: `web/public/hbw_parts_up12.json (control.alarms)`.*

*Generated from the twin's exports by `docs/gen/plc_docs.py`; do not edit.*
