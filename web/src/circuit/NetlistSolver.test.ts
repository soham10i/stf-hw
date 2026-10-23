import { describe, expect, it } from "vitest";

import { PIN_FAULT, PIN_FORCED, PIN_HIGH } from "../core/SimulationBridge";
import { parseCatalogue, type PartDefinition, type ProjectState, type WireNet } from "../core/schema";
import { applyFaults, NetlistSolver, type Supply } from "./NetlistSolver";

type Pin = PartDefinition["electrical_pins"][number];
const pin = (pin_number: number, label: string, max: number, electrical_type: Pin["electrical_type"] = "digital_io"): Pin =>
  ({ pin_number, label, local_position_mm: [0, 0, 0], electrical_type, voltage_limits: [0, max] });
const def = (part_id: string, pins: Pin[]): PartDefinition => ({
  part_id, dimensions_mm: { x: 10, y: 10, z: 10 }, mass_g: 10, bounding_box_type: "OBB",
  mesh_data: { glb_url: "x.glb", collision_margin_mm: 0 }, mating_connectors: [], electrical_pins: pins,
});
const CAT = parseCatalogue([
  def("psu_24v", [pin(1, "+24V", 28.8, "power_input"), pin(2, "GND", 28.8, "power_input")]),
  def("psu_5v", [pin(1, "+5V", 5.5, "power_input"), pin(2, "0V", 5.5, "power_input")]),
  def("plc", [pin(1, "L+", 28.8, "power_input"), pin(2, "M", 28.8, "power_input"), pin(3, "I0.0", 28.8)]),
  def("sensor_5v", [pin(1, "VCC", 5.5, "power_input"), pin(2, "OUT", 5.5), pin(3, "GND", 5.5)]),
  def("relay", [pin(1, "COM", 250), pin(2, "NO", 250)]),
]);
const placed = (instance_id: string, part_id: string) => ({ instance_id, part_id, world_position_mm: [0, 0, 0] as [number, number, number], world_quaternion: [0, 0, 0, 1] as [number, number, number, number] });
const PLACED = [placed("psu", "psu_24v"), placed("psu5", "psu_5v"), placed("plc", "plc"), placed("s1", "sensor_5v"), placed("k1", "relay")];
const SUPPLIES: Supply[] = [
  { id: "PSU 24 V", positive: { part_instance: "psu", pin_label: "+24V" }, negative: { part_instance: "psu", pin_label: "GND" }, volts: 24 },
  { id: "PSU 5 V", positive: { part_instance: "psu5", pin_label: "+5V" }, negative: { part_instance: "psu5", pin_label: "0V" }, volts: 5 },
];
const net = (net_id: string, ...pins: string[]): WireNet =>
  ({ net_id, connections: pins.map((p) => ({ part_instance: p.split(".")[0], pin_label: p.slice(p.indexOf(".") + 1) })) });
const project = (...wire_nets: WireNet[]): ProjectState => ({ placed_parts: PLACED, wire_nets });
const status = (s: NetlistSolver, ...args: Parameters<NetlistSolver["evaluate"]>) =>
  Object.fromEntries(s.evaluate(...args).diagnostics.map((d) => [d.netId, d.status]));

describe("the adjacency matrix", () => {
  it("joins every pin of a net, symmetrically, and its components are the nodes", () => {
    const s = new NetlistSolver(project(net("24V", "psu.+24V", "plc.L+", "k1.COM")), CAT, SUPPLIES);
    const { n, adjacency: m } = s;
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) expect(m[i * n + j]).toBe(m[j * n + i]);
    expect(s.connected({ part_instance: "plc", pin_label: "L+" }, { part_instance: "k1", pin_label: "COM" })).toBe(true);
    expect(s.connected({ part_instance: "plc", pin_label: "L+" }, { part_instance: "plc", pin_label: "M" })).toBe(false);
  });
});

describe("shorts", () => {
  it("leaves a properly powered PLC alone", () => {
    const s = new NetlistSolver(project(net("24V", "psu.+24V", "plc.L+"), net("0V", "psu.GND", "plc.M")), CAT, SUPPLIES);
    const ev = s.evaluate();
    expect(ev.ok).toBe(true);
    expect(ev.diagnostics.map((d) => [d.netId, d.status, d.volts])).toEqual([["24V", "OK", 24], ["0V", "OK", 0]]);
  });

  it("finds +24 V wired to ground with no load", () => {
    const s = new NetlistSolver(project(net("oops", "psu.+24V", "plc.L+", "plc.M", "psu.GND")), CAT, SUPPLIES);
    const ev = s.evaluate();
    expect(ev.diagnostics[0]).toMatchObject({ status: "SHORT_CIRCUIT", netId: "oops" });
    expect(ev.diagnostics[0].affectedInstances.sort()).toEqual(["plc", "psu"]);
    expect(ev.diagnostics[0].message).toMatch(/straight to ground/);
    expect(ev.faultPins.size).toBe(4);
  });

  it("follows a relay contact: a short only while it is closed", () => {
    const s = new NetlistSolver(project(net("a", "psu.+24V", "k1.COM"), net("b", "k1.NO", "psu.GND")), CAT, SUPPLIES,
      [{ id: "K1", a: { part_instance: "k1", pin_label: "COM" }, b: { part_instance: "k1", pin_label: "NO" }, closed: false }]);
    expect(status(s)).toEqual({ a: "OK", b: "OK" });
    s.setContact({ id: "K1", a: { part_instance: "k1", pin_label: "COM" }, b: { part_instance: "k1", pin_label: "NO" }, closed: true });
    expect(status(s)).toEqual({ a: "SHORT_CIRCUIT", b: "SHORT_CIRCUIT" });
    s.setContact({ id: "K1", a: { part_instance: "k1", pin_label: "COM" }, b: { part_instance: "k1", pin_label: "NO" }, closed: false });
    expect(status(s)).toEqual({ a: "OK", b: "OK" });
  });

  it("finds two supplies at different voltages joined", () => {
    const s = new NetlistSolver(project(net("rails", "psu.+24V", "psu5.+5V")), CAT, SUPPLIES);
    const d = s.evaluate().diagnostics[0];
    expect(d.status).toBe("SHORT_CIRCUIT");
    expect(d.message).toMatch(/24 V and 5 V/);
  });

  it("reports a fault on a node no net names (a contact straight across a supply)", () => {
    const s = new NetlistSolver(project(), CAT, SUPPLIES,
      [{ id: "jumper", a: { part_instance: "psu", pin_label: "+24V" }, b: { part_instance: "psu", pin_label: "GND" }, closed: true }]);
    const ev = s.evaluate();
    expect(ev.diagnostics).toHaveLength(1);
    expect(ev.diagnostics[0]).toMatchObject({ status: "SHORT_CIRCUIT", netId: "", affectedInstances: ["psu"] });
  });
});

describe("overvoltage", () => {
  it("finds a 5 V sensor on the 24 V rail", () => {
    const s = new NetlistSolver(project(net("24V", "psu.+24V", "s1.VCC")), CAT, SUPPLIES);
    const d = s.evaluate().diagnostics[0];
    expect(d).toMatchObject({ status: "OVERVOLTAGE", netId: "24V", affectedInstances: ["psu", "s1"], volts: 24 });
    expect(d.message).toMatch(/s1\.VCC takes 0 to 5\.5 V but its node is at 24 V/);
  });

  it("judges a node the simulation drives by the voltage it drives", () => {
    const s = new NetlistSolver(project(net("5V", "psu5.+5V", "s1.VCC"), net("sig", "s1.OUT", "plc.I0.0")), CAT, SUPPLIES);
    const out = s.pins.findIndex((p) => p.instance_id === "s1" && p.label === "OUT");
    const volts = new Float64Array(s.n);
    const flags = new Int32Array(s.n);
    expect(status(s, volts, flags)).toEqual({ "5V": "OK", sig: "OK" }); // floating: nothing to judge
    volts[out] = 5;
    flags[out] = PIN_HIGH;
    expect(status(s, volts, flags)).toEqual({ "5V": "OK", sig: "OK" });
    volts[out] = 24;
    flags[out] = PIN_FORCED | PIN_HIGH; // someone forces 24 V onto the 5 V sensor's output
    expect(status(s, volts, flags)).toEqual({ "5V": "OK", sig: "OVERVOLTAGE" });
  });
});

describe("for the 3D view", () => {
  it("flags the faulted pins and clears them once fixed", () => {
    const s = new NetlistSolver(project(net("24V", "psu.+24V", "s1.VCC")), CAT, SUPPLIES);
    const flags = new Int32Array(s.n).fill(PIN_HIGH);
    applyFaults(flags, s.evaluate().faultPins);
    const vcc = s.pins.findIndex((p) => p.instance_id === "s1" && p.label === "VCC");
    expect(flags[vcc]).toBe(PIN_HIGH | PIN_FAULT);
    s.setNets([net("5V", "psu5.+5V", "s1.VCC")]);
    applyFaults(flags, s.evaluate().faultPins);
    expect(flags[vcc]).toBe(PIN_HIGH);
  });

  it("refuses supplies, contacts and nets on pins that do not exist", () => {
    expect(() => new NetlistSolver(project(), CAT, [{ ...SUPPLIES[0], positive: { part_instance: "psu", pin_label: "+12V" } }])).toThrow(/no pin "\+12V"/);
    expect(() => new NetlistSolver(project(), CAT, [{ ...SUPPLIES[0], volts: 0 }])).toThrow(/greater than 0/);
    const s = new NetlistSolver(project(), CAT, SUPPLIES);
    expect(() => s.setNets([net("x", "plc.Q9", "psu.GND")])).toThrow(/no pin "Q9"/);
  });
});
