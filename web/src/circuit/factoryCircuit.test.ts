import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { FactoryCircuit, type ElectricalDoc } from "./factoryCircuit";

const DOC = JSON.parse(readFileSync(resolve(__dirname, "../../public/electrical.json"), "utf8")) as ElectricalDoc;
const ORIG = DOC.variants.original;
const UP = DOC.variants.upgraded;
const original = () => new FactoryCircuit(DOC, "original");
const at = (part_instance: string, pin_label: string) => ({ part_instance, pin_label });

describe("the original factory's electrics, from the board pinouts and the occupancy plans", () => {
  it("passes the strict schema: every wire ends on a pin its part has", () => {
    const c = original();
    expect(c.project.placed_parts.length).toBe(70);
    // every module's ribbon GND and +24V pins are on the supply's rails (no rail left floating)
    for (const m of ["hbw", "vgr", "oven", "sorting"]) {
      expect(c.solver.connected(at(`${m}.pcb`, "GND"), at("psu", "-V"))).toBe(true);
      expect(c.solver.connected(at(`${m}.pcb`, "+24V_SENSOR"), at("psu", "+V"))).toBe(true);
    }
    expect(c.solver.connected(at("hbw.pcb", "ST1.9"), at("psu", "-V"))).toBe(true); // trail sensor GND
    expect(c.solver.connected(at("hbw.pcb", "ST1.2"), at("psu", "+V"))).toBe(true); // sensor supply
  });

  it("is fault-free as built, at rest", () => {
    const c = original();
    expect(c.faults()).toEqual([]);
    expect(c.volts(at("hbw.dio", "X4.24V"))).toBe(24);
    expect(c.volts(at("sorting.A4", "9V"))).toBe(9); // the colour sensor on the board's 9 V
  });

  it("brakes a motor at rest: both leads on GND through the relays' NC contacts", () => {
    const c = original();
    expect(c.volts(at("hbw.M2", "M+"))).toBe(0);
    expect(c.volts(at("hbw.M2", "M-"))).toBe(0);
  });

  it("runs the travel motor from Q3: its relay puts one lead on +24 V, and back from Q4", () => {
    const c = original();
    c.setOutput("hbw.Q3", true);
    expect([c.volts(at("hbw.M2", "M+")), c.volts(at("hbw.M2", "M-"))]).toEqual([24, 0]);
    c.setOutput("hbw.Q3", false);
    c.setOutput("hbw.Q4", true);
    expect([c.volts(at("hbw.M2", "M+")), c.volts(at("hbw.M2", "M-"))]).toEqual([0, 24]);
    // both on: both leads on +24 V - the motor stops, and it is no short (the board's design)
    c.setOutput("hbw.Q3", true);
    expect([c.volts(at("hbw.M2", "M+")), c.volts(at("hbw.M2", "M-"))]).toEqual([24, 24]);
    expect(c.faults()).toEqual([]);
  });

  it("a pressed reference switch puts +24 V on its DIO input", () => {
    const c = original();
    expect(c.volts(at("hbw.dio", "IN1"))).toBe(null); // open: the input floats (the DIO reads 0)
    c.press("hbw.I1", true);
    expect(c.volts(at("hbw.dio", "IN1"))).toBe(24);
  });

  it("follows the occupancy plan to the DIO terminal: the gripper's six encoder channels", () => {
    const c = original();
    const enc = ORIG.io.vgr.filter((r) => r.signal.startsWith("B")).map((r) => r.channel);
    expect(enc).toEqual(["IN5", "IN6", "IN7", "IN8", "IN9", "IN10"]);
    expect(c.solver.connected(at("vgr.M3", "PULS1"), at("vgr.dio", "IN9"))).toBe(true); // B5, the swivel
    expect(c.solver.connected(at("vgr.M3", "PULS2"), at("vgr.dio", "IN10"))).toBe(true); // B6
  });

  it("catches a miswire: the colour sensor's supply on the 24 V rail is an overvoltage", () => {
    const c = original();
    const nets = c.project.wire_nets.map((n) => ({ ...n, connections: n.connections.filter((p) => !(p.part_instance === "sorting.A4" && p.pin_label === "9V")) }));
    nets.find((n) => n.net_id === "24V")!.connections.push(at("sorting.A4", "9V"));
    c.rewire(nets);
    const f = c.faults();
    expect(f.map((d) => d.status)).toContain("OVERVOLTAGE");
    expect(f.flatMap((d) => d.affectedInstances)).toContain("sorting.A4");
  });

  it("catches a short: a sensor-supply pin wired to ground", () => {
    const c = original();
    const nets = c.project.wire_nets.map((n) => ({ ...n, connections: [...n.connections] }));
    nets.find((n) => n.net_id === "0V")!.connections.push(at("hbw.pcb", "ST1.2")); // +24V sensor supply pin
    c.rewire(nets);
    expect(c.faults().map((d) => d.status)).toContain("SHORT_CIRCUIT");
  });

  it("refuses an output the plan does not have", () => {
    const c = original();
    expect(() => c.setOutput("hbw.Q12", true)).toThrow(/no PLC output/);
  });

  it("carries its rating checks and findings, each with its source", () => {
    expect(ORIG.checks.filter((k) => k.severity === "fail")).toEqual([]);
    expect(ORIG.checks.filter((k) => k.check.startsWith("inventory")).every((k) => k.ok)).toBe(true);
    expect(ORIG.findings.some((f) => f.includes("A4"))).toBe(true);
    for (const p of Object.values(DOC.parts)) for (const pin of p.pins) expect(pin.voltage_source).toBeTruthy();
  });
});

describe("the upgraded factory the 3D twin shows: remote I/O, safety contactors, central air", () => {
  const upgraded = () => new FactoryCircuit(DOC, "upgraded");

  it("is fault-free as built, and every part is placed from the CAD export", () => {
    const c = upgraded();
    expect(c.faults()).toEqual([]);
    expect(Object.values(UP.placement).every((p) => p !== null)).toBe(true);
    expect(UP.checks.filter((k) => k.severity === "fail")).toEqual([]);
  });

  it("places each part where its CAD part is: the travel motor on the warehouse's rail", () => {
    const m2 = UP.placement["hbw.M2"]!;
    expect(m2.cad).toBe("hbw/M2_travel_motor");
    const [x0, y0, z0, x1, y1, z1] = m2.box_mm;
    expect([x1 - x0, y1 - y0, z1 - z0].sort((a, b) => a - b)).toEqual([30, 30, 60]); // the datasheet's 60 x 30 x 30
    const at = UP.project.placed_parts.find((p) => p.instance_id === "hbw.M2")!.world_position_mm;
    expect(at).toEqual([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]);
    expect(UP.placement["vgr.M1"]!.frame).toBe("swivel"); // the plunge motor rides the turntable
  });

  it("runs a motor only while the safety contactors hold the actuator 24 V", () => {
    const c = upgraded();
    c.setOutput("hbw.Q3", true);
    expect(c.volts(at("hbw.M2", "M+"))).toBe(24);
    c.setContact("safety.K1", false); // a guard opened: K0 drops K1
    expect(c.volts(at("hbw.M2", "M+"))).toBe(null); // the relay's +24 V Motor side is dead
    expect(c.volts(at("hbw.I1", "1"))).toBe(24); // the sensors keep their supply
    expect(c.faults()).toEqual([]);
  });

  it("wires the colour sensor to the sorting node's analogue slice (the original leaves it off the PLC)", () => {
    const c = upgraded();
    expect(c.solver.connected(at("sorting.A4", "OUT"), at("sorting.node.AI1", "1"))).toBe(true);
    expect(UP.findings.some((f) => f.includes("A4"))).toBe(false);
  });

  it("the air station's pressure switch runs the compressor; its second contact is the arm's I5", () => {
    const c = upgraded();
    expect(c.volts(at("air.compressor", "+"))).toBe(24);
    c.setContact("vgr.I5.pump", false); // at 0.8 bar the switch opens
    expect(c.volts(at("air.compressor", "+"))).toBe(null);
    expect(c.solver.connected(at("vgr.I5", "OUT"), at("vgr.node.DI1", "5"))).toBe(true);
  });

  it("has no module compressors any more, and the upgrades' sensors on their node channels", () => {
    const ids = UP.project.placed_parts.map((p) => p.instance_id);
    expect(ids.filter((i) => i.endsWith(".compressor"))).toEqual(["air.compressor"]);
    const c = upgraded();
    c.press("oven.I10", true); // the door-open reed switch
    expect(c.volts(at("oven.node.DI2", "2"))).toBe(24);
    expect(c.solver.connected(at("hbw.RF1", "C/Q"), at("hbw.node.IOL1", "1"))).toBe(true);
  });

  it("monitors the supply: its DC OK contact puts 24 V on the warehouse node's DI2.1 while the output is good", () => {
    const c = upgraded();
    const pins = DOC.parts.psu.pins.map((p) => p.label);
    expect(pins).toEqual(["FG", "AC/L2", "AC/L1", "DCOK.1", "DCOK.2", "-V", "+V"]); // Mean Well's TB1 and TB2
    expect(c.volts(at("hbw.node.DI2", "1"))).toBe(24);
    c.setContact("psu.dc_ok", false); // the output sags: the relay opens
    expect(c.volts(at("hbw.node.DI2", "1"))).toBe(null); // the input reads 0
    expect(UP.io.hbw.some((r) => r.signal === "PS_OK" && r.channel === "DI2.1")).toBe(true);
  });
});
