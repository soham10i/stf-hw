# PLC I/O map

Every signal the program reads or writes, with its address in the process image. Inputs
are sinking (the sensor switches +24 V onto the input), outputs sourcing.

## Digital inputs (%IX)

| Address | Module | Signal | Meaning |
|---|---|---|---|
| %IX0.0 | high-bay warehouse | I1 | reference switch horizontal |
| %IX0.1 | high-bay warehouse | I4 | reference switch vertical |
| %IX0.2 | high-bay warehouse | I5 | reference switch cantilever front |
| %IX0.3 | high-bay warehouse | I6 | reference switch cantilever back |
| %IX0.4 | high-bay warehouse | I2 | phototransistor inside |
| %IX0.5 | high-bay warehouse | I3 | phototransistor outside |
| %IX0.6 | vacuum gripper robot | I1 | reference vertical |
| %IX0.7 | vacuum gripper robot | I2 | reference horizontal |
| %IX1.0 | vacuum gripper robot | I3 | reference rotate |
| %IX1.1 | vacuum gripper robot | I4 | vacuum switch: the cup is sealed on a part (-0.3 bar) |
| %IX1.2 | multi-processing oven | I6 | oven feeder inside |
| %IX1.3 | multi-processing oven | I7 | oven feeder outside |
| %IX1.4 | multi-processing oven | I10 | reed switch: oven door open |
| %IX1.5 | multi-processing oven | I11 | reed switch: oven door shut |
| %IX1.6 | multi-processing oven | I5 | reference vacuum (turntable position) |
| %IX1.7 | multi-processing oven | I8 | vacuum at oven |
| %IX2.0 | multi-processing oven | I12 | reed switch: Sauger lowered |
| %IX2.1 | multi-processing oven | I13 | reed switch: Sauger up |
| %IX2.2 | multi-processing oven | I1 | reference turntable (vacuum position) |
| %IX2.3 | multi-processing oven | I2 | reference turntable (belt position) |
| %IX2.4 | multi-processing oven | I4 | reference turntable (saw position) |
| %IX2.5 | multi-processing oven | I14 | reed switch: Auswerfer out |
| %IX2.6 | multi-processing oven | I15 | reed switch: Auswerfer home |
| %IX2.7 | multi-processing oven | I3 | light barrier end of conveyor belt |
| %IX3.0 | sorting line | I1 | pulse counter (Impulstaster) |
| %IX3.1 | sorting line | I3 | light barrier behind colour sensor |
| %IX3.2 | sorting line | I5 | light barrier white |
| %IX3.3 | sorting line | I6 | light barrier red |
| %IX3.4 | sorting line | I7 | light barrier blue |
| %IX3.5 | high-bay warehouse | RF1_Valid | RFID read point RP1: belt, crane end (IO-Link port 1) |
| %IX3.6 | high-bay warehouse | RF2_Valid | RFID read point RP2: belt, VGR hand-over (IO-Link port 2) |
| %IX3.7 | cell | SafetyOK | safety relay K0: OK |

## Digital outputs (%QX)

| Address | Module | Signal | Meaning |
|---|---|---|---|
| %QX0.0 | high-bay warehouse | Q3 | horizontal towards rack (M2) |
| %QX0.1 | high-bay warehouse | Q4 | horizontal towards belt (M2) |
| %QX0.2 | high-bay warehouse | Q5 | vertical axis down (M3) |
| %QX0.3 | high-bay warehouse | Q6 | vertical axis up (M3) |
| %QX0.4 | high-bay warehouse | Q7 | cantilever forward (M4) |
| %QX0.5 | high-bay warehouse | Q8 | cantilever back (M4) |
| %QX0.6 | high-bay warehouse | Q1 | conveyor belt forward (M1) |
| %QX0.7 | high-bay warehouse | Q2 | conveyor belt backward (M1) |
| %QX1.0 | vacuum gripper robot | Q1 | vertical up (M1) |
| %QX1.1 | vacuum gripper robot | Q2 | vertical down (M1) |
| %QX1.2 | vacuum gripper robot | Q3 | horizontal backward (M2) |
| %QX1.3 | vacuum gripper robot | Q4 | horizontal forward (M2) |
| %QX1.4 | vacuum gripper robot | Q5 | rotate clockwise (M3) |
| %QX1.5 | vacuum gripper robot | Q6 | rotate counter-clockwise (M3) |
| %QX1.6 | vacuum gripper robot | Q8 |  |
| %QX1.7 | multi-processing oven | Q5 | oven feeder retract (M4) |
| %QX2.0 | multi-processing oven | Q6 | oven feeder extend (M4) |
| %QX2.1 | multi-processing oven | Q9 | oven lamp |
| %QX2.2 | multi-processing oven | Q13 |  |
| %QX2.3 | multi-processing oven | Q7 | vacuum towards oven (M5) |
| %QX2.4 | multi-processing oven | Q8 | vacuum towards turntable (M5) |
| %QX2.5 | multi-processing oven | Q11 |  |
| %QX2.6 | multi-processing oven | Q12 |  |
| %QX2.7 | multi-processing oven | Q1 | turntable clockwise (M1) |
| %QX3.0 | multi-processing oven | Q2 | turntable counter-clockwise (M1) |
| %QX3.1 | multi-processing oven | Q4 | saw (M3) |
| %QX3.2 | multi-processing oven | Q14 |  |
| %QX3.3 | multi-processing oven | Q3 | conveyor belt (M2) |
| %QX3.4 | sorting line | Q1 | conveyor belt |
| %QX3.5 | sorting line | Q3 |  |
| %QX3.6 | sorting line | Q4 |  |
| %QX3.7 | sorting line | Q5 |  |

## Analogue and RFID words (%IW)

| Address | Name | Meaning |
|---|---|---|
| %IW0 | hbw_RF2_Tag | RFID RP2: the tag read (mould number) |
| %IW1 | sorting_A4 | colour sensor, mV |

## Encoder positions (%ID)

| Address | Unit | Axis | Meaning |
|---|---|---|---|
| %ID0 | crane | travel | crane travel encoder position |
| %ID1 | crane | lift | crane lift encoder position |
| %ID2 | arm | plunge | arm plunge encoder position |
| %ID3 | arm | reach | arm reach encoder position |
| %ID4 | arm | swivel | arm swivel encoder position |

## Monitoring words for the HMI (%MW)

Written by the program every scan for the operator screen and the twin's PLC panel.

| Address | Name | Meaning |
|---|---|---|
| %MW0 | mon_phase | 0 homing, 1 production, 2 order complete |
| %MW1 | mon_jobs | jobs completed |
| %MW10 | mon_crane_sn | crane: active state |
| %MW11 | mon_crane_job | crane: job it leads (MAIN code) |
| %MW12 | mon_crane_b1 | crane: binding 1 |
| %MW13 | mon_crane_b2 | crane: binding 2 |
| %MW14 | mon_crane_b3 | crane: binding 3 |
| %MW15 | mon_crane_b4 | crane: binding 4 |
| %MW16 | mon_crane_b5 | crane: binding 5 |
| %MW17 | mon_crane_b6 | crane: binding 6 |
| %MW18 | mon_crane_alarm | crane: alarm state |
| %MW19 | mon_crane_seg | crane: unit running its segment |
| %MW101 | mon_crane_n | crane: jobs it has started (a job ending and the next starting in one scan) |
| %MW20 | mon_belt_sn | belt: active state |
| %MW21 | mon_belt_job | belt: job it leads (MAIN code) |
| %MW22 | mon_belt_b1 | belt: binding 1 |
| %MW23 | mon_belt_b2 | belt: binding 2 |
| %MW24 | mon_belt_b3 | belt: binding 3 |
| %MW25 | mon_belt_b4 | belt: binding 4 |
| %MW26 | mon_belt_b5 | belt: binding 5 |
| %MW27 | mon_belt_b6 | belt: binding 6 |
| %MW28 | mon_belt_alarm | belt: alarm state |
| %MW29 | mon_belt_seg | belt: unit running its segment |
| %MW102 | mon_belt_n | belt: jobs it has started (a job ending and the next starting in one scan) |
| %MW30 | mon_arm_sn | arm: active state |
| %MW31 | mon_arm_job | arm: job it leads (MAIN code) |
| %MW32 | mon_arm_b1 | arm: binding 1 |
| %MW33 | mon_arm_b2 | arm: binding 2 |
| %MW34 | mon_arm_b3 | arm: binding 3 |
| %MW35 | mon_arm_b4 | arm: binding 4 |
| %MW36 | mon_arm_b5 | arm: binding 5 |
| %MW37 | mon_arm_b6 | arm: binding 6 |
| %MW38 | mon_arm_alarm | arm: alarm state |
| %MW39 | mon_arm_seg | arm: unit running its segment |
| %MW103 | mon_arm_n | arm: jobs it has started (a job ending and the next starting in one scan) |
| %MW40 | mon_door_sn | door: active state |
| %MW41 | mon_door_job | door: job it leads (MAIN code) |
| %MW42 | mon_door_b1 | door: binding 1 |
| %MW43 | mon_door_b2 | door: binding 2 |
| %MW44 | mon_door_b3 | door: binding 3 |
| %MW45 | mon_door_b4 | door: binding 4 |
| %MW46 | mon_door_b5 | door: binding 5 |
| %MW47 | mon_door_b6 | door: binding 6 |
| %MW48 | mon_door_alarm | door: alarm state |
| %MW49 | mon_door_seg | door: unit running its segment |
| %MW104 | mon_door_n | door: jobs it has started (a job ending and the next starting in one scan) |
| %MW50 | mon_sauger_sn | sauger: active state |
| %MW51 | mon_sauger_job | sauger: job it leads (MAIN code) |
| %MW52 | mon_sauger_b1 | sauger: binding 1 |
| %MW53 | mon_sauger_b2 | sauger: binding 2 |
| %MW54 | mon_sauger_b3 | sauger: binding 3 |
| %MW55 | mon_sauger_b4 | sauger: binding 4 |
| %MW56 | mon_sauger_b5 | sauger: binding 5 |
| %MW57 | mon_sauger_b6 | sauger: binding 6 |
| %MW58 | mon_sauger_alarm | sauger: alarm state |
| %MW59 | mon_sauger_seg | sauger: unit running its segment |
| %MW105 | mon_sauger_n | sauger: jobs it has started (a job ending and the next starting in one scan) |
| %MW60 | mon_turntable_sn | turntable: active state |
| %MW61 | mon_turntable_job | turntable: job it leads (MAIN code) |
| %MW62 | mon_turntable_b1 | turntable: binding 1 |
| %MW63 | mon_turntable_b2 | turntable: binding 2 |
| %MW64 | mon_turntable_b3 | turntable: binding 3 |
| %MW65 | mon_turntable_b4 | turntable: binding 4 |
| %MW66 | mon_turntable_b5 | turntable: binding 5 |
| %MW67 | mon_turntable_b6 | turntable: binding 6 |
| %MW68 | mon_turntable_alarm | turntable: alarm state |
| %MW69 | mon_turntable_seg | turntable: unit running its segment |
| %MW106 | mon_turntable_n | turntable: jobs it has started (a job ending and the next starting in one scan) |
| %MW70 | mon_ovenbelt_sn | ovenbelt: active state |
| %MW71 | mon_ovenbelt_job | ovenbelt: job it leads (MAIN code) |
| %MW72 | mon_ovenbelt_b1 | ovenbelt: binding 1 |
| %MW73 | mon_ovenbelt_b2 | ovenbelt: binding 2 |
| %MW74 | mon_ovenbelt_b3 | ovenbelt: binding 3 |
| %MW75 | mon_ovenbelt_b4 | ovenbelt: binding 4 |
| %MW76 | mon_ovenbelt_b5 | ovenbelt: binding 5 |
| %MW77 | mon_ovenbelt_b6 | ovenbelt: binding 6 |
| %MW78 | mon_ovenbelt_alarm | ovenbelt: alarm state |
| %MW79 | mon_ovenbelt_seg | ovenbelt: unit running its segment |
| %MW107 | mon_ovenbelt_n | ovenbelt: jobs it has started (a job ending and the next starting in one scan) |
| %MW80 | mon_line_sn | line: active state |
| %MW81 | mon_line_job | line: job it leads (MAIN code) |
| %MW82 | mon_line_b1 | line: binding 1 |
| %MW83 | mon_line_b2 | line: binding 2 |
| %MW84 | mon_line_b3 | line: binding 3 |
| %MW85 | mon_line_b4 | line: binding 4 |
| %MW86 | mon_line_b5 | line: binding 5 |
| %MW87 | mon_line_b6 | line: binding 6 |
| %MW88 | mon_line_alarm | line: alarm state |
| %MW89 | mon_line_seg | line: unit running its segment |
| %MW108 | mon_line_n | line: jobs it has started (a job ending and the next starting in one scan) |


*Sources: `web/public/sil/plc.json (io)`; `web/public/sil/stf_plc.st`.*

*Generated from the twin's exports by `docs/gen/plc_docs.py`; do not edit.*
