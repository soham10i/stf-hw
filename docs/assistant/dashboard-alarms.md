# Dashboard: Alarms

Dashboard group: Operate. Page id: `alarms`.

Every alarm the PLC can raise, and how the machine reacted when each fault was injected into the twin.

## How to read it

1. Fault matrix: each injected fault, the alarm it raised, how quickly, and whether the reaction was right ('pass').
2. Alarm list: the catalogue an operator would see, with cause, reaction and recovery for each code.

## Sections

### Detection time per fault

How fast each injected fault raised its alarm.

### Time lost per fault

Production lost when the fault happens once, against the mean (MTTR).

### Fault matrix (commissioned)

Each fault's alarm, reaction and recovery.

### Alarm list

Every watchdog alarm in the program: its code, the step it guards, and what to do.

## Where the numbers come from

Virtual commissioning of the PLC program against the twin.

Every number is simulated from the twin's models, not measured on a real machine.

## Terms

- **Watchdog**: A time limit on each PLC step. A step that takes too long raises an alarm - the first sign of a stuck switch or a stalled motor.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
