# Alarm codes

Each PLC step has a watchdog: a step that takes too long raises its alarm. Codes are
`MODULE-UNIT##`.

| Code | Meaning |
|---|---|
| HBW-C01 / C02 / C03 | crane: I6 (fork rear) / I4 (lift reference) / I1 (travel reference) not reached in time |
| HBW-C04 / C05 | crane: target position not reached in time |
| HBW-C06 | crane: I5 (fork front) not reached in time |
| HBW-B01 / B02 / B03 | warehouse belt: mould not at I3 with RP1 read / RP2 tag not matching / not at I2 with RP1 read |
| VGR-A01 / A02 / A03 | robot: I1 / I2 / I3 reference not reached in time |
| VGR-A04 | robot: target not reached in time (e.g. a stalled motor) |
| VGR-A05 / A06 | robot: vacuum (I4) not built / not released in time |
| VGR-V01 | vacuum lost while carrying |
| OVN-D01 - D04 | oven door and tray: I10, I6, I11, I7 not reached in time |
| OVN-S01 - S04 | oven gripper: I13, I5, I8, I12 not reached in time |
| OVN-T01 - T05 | turntable, saw, pusher: I15, I1, I4, I2, I14 not reached in time |
| OVN-B01 | oven belt: I3 not reached in time |
| SRT-L01 - L03 | sorting line: I3 not reached / pulse count not reached / bay barrier not broken |
| SYS-01 | E-stop pressed (ES1, ES2 or ES3) |
| SYS-02 | guard door open (SA, SB or SC) |
| SYS-03 | safety relay feedback fault (EDM) |
| SYS-04 | remote I/O node lost (Modbus TCP watchdog) |
| SYS-05 | air pressure low at the air station |
| TRC-01 / 02 / 03 | no tag read / tag differs from the record / flavour differs from the record |
| ORD-01 | bay full (4 cookies) |
| SEC-01 | output read-back differs from the program's image |
| SEC-02 | a sensor arrived faster than the plant can move |
| SEC-03 | the running program's hash differs from the signed manifest |
| SEC-04 | the cell firewall dropped a packet on a conduit |

The PLC panel's *Program & HMI > Alarms* shows each alarm's cause, reaction and recovery; the
dashboard's *Alarms* page shows their history.
