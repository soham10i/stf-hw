import { describe, expect, it } from "vitest";

import { parseCatalogue, parsePartDefinition, parseProjectState, parseSystemContext, pinIndex, pinTable, SchemaError } from "./schema";

const PLC = {
  part_id: "siemens_s7_1200_plc",
  dimensions_mm: { x: 110, y: 100, z: 75 },
  mass_g: 415,
  bounding_box_type: "OBB",
  mesh_data: { glb_url: "parts/s7_1200.glb", collision_margin_mm: 0.05 },
  mating_connectors: [{ node_id: "din_rail_latch_1", local_position_mm: [0, 12.5, -5], normal_vector: [0, 0, -1], allowed_mating_type: "DIN_35mm" }],
  electrical_pins: [
    { pin_number: 1, label: "24V_VCC", local_position_mm: [-2.54, 0, 2], electrical_type: "power_input", voltage_limits: [0, 28.8] },
    { pin_number: 2, label: "I0.0", local_position_mm: [0, 0, 2], electrical_type: "digital_io", voltage_limits: [0, 28.8] },
  ],
};
const SENSOR = {
  ...PLC,
  part_id: "omron_e3z_sensor",
  mating_connectors: [],
  electrical_pins: [{ pin_number: 1, label: "OUT", local_position_mm: [0, 0, 0], electrical_type: "digital_io", voltage_limits: [0, 28.8] }],
};
const PROJECT = {
  placed_parts: [
    { instance_id: "plc", part_id: "siemens_s7_1200_plc", world_position_mm: [0, 0, 0], world_quaternion: [0, 0, 0, 1] },
    { instance_id: "b1", part_id: "omron_e3z_sensor", world_position_mm: [250.5, -10, 40], world_quaternion: [0, 0, Math.SQRT1_2, Math.SQRT1_2] },
  ],
  wire_nets: [{ net_id: "I0.0", connections: [{ part_instance: "b1", pin_label: "OUT" }, { part_instance: "plc", pin_label: "I0.0" }] }],
};
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

describe("part definitions", () => {
  it("accept the schema's own example", () => {
    const p = parsePartDefinition(PLC);
    expect(p.electrical_pins[0].voltage_limits).toEqual([0, 28.8]);
    expect(parseSystemContext({ target: "STF Digital Twin High-Precision Upgrade", precision_grid_mm: 0.1, electrical_netlist_type: "nodal_adjacency_matrix" }).precision_grid_mm).toBe(0.1);
  });

  it("refuse unknown keys, missing keys, bad numbers and non-unit normals, with the path", () => {
    expect(() => parsePartDefinition({ ...PLC, colour: "grey" })).toThrow(/part\.colour: is not in the schema/);
    const { mass_g: _m, ...noMass } = PLC;
    expect(() => parsePartDefinition(noMass)).toThrow(/part\.mass_g: is required/);
    expect(() => parsePartDefinition({ ...PLC, mass_g: 0 })).toThrow(SchemaError);
    expect(() => parsePartDefinition({ ...PLC, dimensions_mm: { x: 1, y: Number.NaN, z: 1 } })).toThrow(/dimensions_mm\.y/);
    const bent = clone(PLC);
    bent.mating_connectors[0].normal_vector = [0, 0.1, -1];
    expect(() => parsePartDefinition(bent)).toThrow(/normal_vector: must have length 1/);
    const reversed = clone(PLC);
    reversed.electrical_pins[0].voltage_limits = [28.8, 0];
    expect(() => parsePartDefinition(reversed)).toThrow(/min <= max/);
    const twice = clone(PLC);
    twice.electrical_pins[1].label = "24V_VCC";
    expect(() => parsePartDefinition(twice)).toThrow(/label "24V_VCC" appears twice/);
  });
});

describe("projects", () => {
  const cat = parseCatalogue([PLC, SENSOR]);

  it("accept a project whose nets name pins that exist", () => {
    const p = parseProjectState(PROJECT, cat);
    const rows = pinTable(p, cat);
    expect(rows.map((r) => `${r.instance_id}.${r.label}`)).toEqual(["plc.24V_VCC", "plc.I0.0", "b1.OUT"]);
    expect(pinIndex(rows, "b1", "OUT")).toBe(2);
    expect(pinIndex(rows, "b1", "IN")).toBe(-1);
  });

  it("refuse unknown parts, repeated instances, non-unit quaternions and pins that do not exist", () => {
    const unknown = clone(PROJECT);
    unknown.placed_parts[0].part_id = "abb_robot";
    expect(() => parseProjectState(unknown, cat)).toThrow(/not in the part catalogue/);
    const twice = clone(PROJECT);
    twice.placed_parts[1].instance_id = "plc";
    expect(() => parseProjectState(twice, cat)).toThrow(/instance_id "plc" appears twice/);
    const skew = clone(PROJECT);
    skew.placed_parts[0].world_quaternion = [0, 0, 0.1, 1];
    expect(() => parseProjectState(skew, cat)).toThrow(/world_quaternion: must have length 1/);
    const badPin = clone(PROJECT);
    badPin.wire_nets[0].connections[1].pin_label = "I9.9";
    expect(() => parseProjectState(badPin, cat)).toThrow(/has no pin "I9\.9"/);
    const lonely = clone(PROJECT);
    lonely.wire_nets[0].connections.pop();
    expect(() => parseProjectState(lonely, cat)).toThrow(/at least two pins/);
    expect(() => parseCatalogue([PLC, PLC])).toThrow(/part_id "siemens_s7_1200_plc" appears twice/);
  });
});
