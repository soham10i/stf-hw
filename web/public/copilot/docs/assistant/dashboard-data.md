# Dashboard: Data

Dashboard group: Engineer. Page id: `data`.

Where the dashboard's data would come from on a real machine: the MQTT topics and the I/O register map.

## In brief

Where the dashboard's data would come from on a real machine: the MQTT topics and the I/O register map.

## How to read it

1. Topics: the path from the PLC through MQTT and a historian to this page.
2. Register map: every PLC signal's Modbus address on the remote I/O nodes.

## Sections

### Topics (PLC → MQTT → historian → this page)

The message topics the page would read on real hardware.

### Register map

Each signal, its node and its Modbus register.

## Where the numbers come from

The register map; the live MQTT/Sparkplug namespace is in the twin's 'MQTT Sparkplug · UNS' panel.

Every number is simulated from the twin's models, not measured on a real machine.

*Generated from `web/src/dashboard/guide.ts`; edit the guide, not this file.*
