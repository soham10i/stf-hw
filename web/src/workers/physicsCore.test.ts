import RAPIER from "@dimforge/rapier3d-deterministic-compat";
import { beforeAll, describe, expect, it } from "vitest";

import { BridgeReader, BridgeWriter, createBridge, FLAG_TELEMETRY_STALE, makeSnapshot, PIN_FAULT, PIN_FORCED, PIN_HIGH, PIN_TELEMETRY } from "../core/SimulationBridge";
import type { PartDefinition, PlacedPart } from "../core/schema";
import { logicHigh, parseTelemetrySample, PhysicsCore, trackValue, WorldError } from "./physicsCore";
import type { WorldInit } from "./protocol";

beforeAll(async () => {
  await RAPIER.init();
});

const part = (part_id: string, x: number, y: number, z: number, mass_g: number, pins: PartDefinition["electrical_pins"] = []): PartDefinition => ({
  part_id, dimensions_mm: { x, y, z }, mass_g, bounding_box_type: "OBB",
  mesh_data: { glb_url: `${part_id}.glb`, collision_margin_mm: 0.05 }, mating_connectors: [], electrical_pins: pins,
});
const PARTS: PartDefinition[] = [
  part("belt", 600, 60, 20, 1000),
  part("cookie", 30, 30, 8, 15),
  part("barrier", 4, 80, 40, 20, [{ pin_number: 1, label: "OUT", local_position_mm: [0, 40, 0], electrical_type: "digital_io", voltage_limits: [0, 28.8] }]),
  part("slide", 20, 20, 20, 200),
  part("gripper", 10, 10, 10, 50),
];
const at = (instance_id: string, part_id: string, p: [number, number, number], q: [number, number, number, number] = [0, 0, 0, 1]): PlacedPart =>
  ({ instance_id, part_id, world_position_mm: p, world_quaternion: q });

/** A belt carrying one cookie through a light barrier, and a slide with a gripper on it. */
function world(extra: Partial<WorldInit> = {}): WorldInit {
  return {
    parts: PARTS,
    project: {
      placed_parts: [
        at("belt", "belt", [300, 0, 10]),
        at("cookie", "cookie", [20, 0, 24.2]),
        at("barrier", "barrier", [400, 0, 40]),
        at("slide", "slide", [1000, 0, 100]),
        at("gripper", "gripper", [1000, 0, 50]),
      ],
      wire_nets: [],
    },
    roles: {
      belt: { kind: "conveyor", direction_local: [1, 0, 0], speed_mm_s: 100 },
      cookie: { kind: "dynamic", friction: 0.5 },
      barrier: { kind: "sensor", pin: { part_instance: "barrier", pin_label: "OUT" } },
      slide: { kind: "kinematic" },
      gripper: { kind: "kinematic" },
    },
    bindings: [
      { joint: 0, instance_id: "slide", type: "prismatic", axis_local: [1, 0, 0], unit: "mm" },
      { joint: 1, instance_id: "gripper", type: "revolute", axis_local: [0, 0, 1], unit: "deg", parent: "slide" },
    ],
    tracks: [
      { joint: 0, times_s: [0, 1], values: [0, 123.4] },
      { joint: 1, times_s: [0, 1], values: [0, 90] },
    ],
    telemetry_sensors: [{ part_instance: "barrier", pin_label: "OUT" }],
    ...extra,
  };
}

const run = (core: PhysicsCore, steps: number) => { for (let i = 0; i < steps; i++) core.stepOnce(); };

describe("the fixed step", () => {
  it("counts time from the integer step, 10 ms each", () => {
    const core = PhysicsCore.create(RAPIER, world());
    run(core, 300);
    expect(core.step).toBe(300);
    expect(core.simTime).toBe(300 * 0.01);
    core.dispose();
  });
});

describe("conveyors", () => {
  it("carry a cookie at the belt's speed, on top of the belt", () => {
    const core = PhysicsCore.create(RAPIER, world());
    run(core, 200); // 2 s at 100 mm/s, from x = 20
    const p = core.pose("cookie")!.p;
    expect(p[0]).toBeGreaterThan(205);
    expect(p[0]).toBeLessThan(222);
    expect(Math.abs(p[1])).toBeLessThan(0.5);
    expect(p[2]).toBeCloseTo(24, 0); // resting on the belt's top (z = 20) at half its 8 mm height
    core.dispose();
  });

  it("stop carrying when the belt stops", () => {
    const core = PhysicsCore.create(RAPIER, world());
    run(core, 100);
    core.enqueue({ type: "conveyor", instance_id: "belt", speed_mm_s: 0 });
    run(core, 20);
    const x = core.pose("cookie")!.p[0];
    run(core, 100);
    expect(Math.abs(core.pose("cookie")!.p[0] - x)).toBeLessThan(0.5);
    core.dispose();
  });
});

describe("sensors", () => {
  it("drive their pin to 24 V while a cookie passes through the light barrier", () => {
    const core = PhysicsCore.create(RAPIER, world());
    const seen: number[] = [];
    for (let i = 0; i < 450; i++) {
      core.stepOnce();
      seen.push(core.pinVolts[0]);
      if (core.pinVolts[0] > 0) expect(core.pinFlags[0] & PIN_HIGH).toBe(PIN_HIGH);
    }
    const first = seen.indexOf(24);
    const last = seen.lastIndexOf(24);
    expect(seen[0]).toBe(0);
    expect(first).toBeGreaterThan(330); // the cookie's front reaches x = 398 after ~3.6 s
    expect(first).toBeLessThan(380);
    expect(last).toBeGreaterThan(first);
    expect(seen[449]).toBe(0); // and has left it
    core.dispose();
  });
});

describe("kinematic chains", () => {
  it("place a joint's part exactly in float64, and its children with it", () => {
    const core = PhysicsCore.create(RAPIER, world());
    run(core, 100); // t = 1 s: the tracks are at their ends
    expect(core.pose("slide")!.p).toEqual([1000 + 123.4, 0, 100]);
    const g = core.pose("gripper")!;
    expect(g.p[0]).toBe(1000 + 123.4);
    expect(g.p[2]).toBe(50);
    expect(g.q[2]).toBeCloseTo(Math.SQRT1_2, 15);
    expect(g.q[3]).toBeCloseTo(Math.SQRT1_2, 15);
    core.dispose();
  });

  it("interpolate tracks linearly and hold their ends", () => {
    const t = { joint: 0, times_s: [0, 1, 3], values: [0, 10, 30] };
    expect(trackValue(t, -1)).toBe(0);
    expect(trackValue(t, 0.5)).toBe(5);
    expect(trackValue(t, 2)).toBe(20);
    expect(trackValue(t, 9)).toBe(30);
  });
});

describe("live telemetry", () => {
  it("overrides the joints and the sensors, a playout delay behind the newest sample", () => {
    const core = PhysicsCore.create(RAPIER, world({ playout_delay_ms: 100 }));
    core.enqueue({ type: "mode", mode: "LIVE_TELEMETRY_MODE" });
    core.enqueue({
      type: "telemetry",
      samples: [
        { timestamp: 1200, joint_angles: [20, 0], sensor_states: [1] },
        { timestamp: 1000, joint_angles: [0, 0], sensor_states: [0] },
        { timestamp: 1100, joint_angles: [10, 0], sensor_states: [1] },
      ],
    });
    core.stepOnce(); // plays t = 1100 + 10 ms: between the 1100 and 1200 samples
    expect(core.pose("slide")!.p[0]).toBeCloseTo(1000 + 11, 9);
    expect(core.pinVolts[0]).toBe(24);
    expect(core.pinFlags[0]).toBe(PIN_TELEMETRY | PIN_HIGH);

    run(core, 30); // past the newest sample: it holds, and says so
    expect(core.pose("slide")!.p[0]).toBe(1000 + 20);
    const v = createBridge(core.partCapacity, core.pins.length);
    core.publish(new BridgeWriter(v));
    const snap = makeSnapshot(v.layout);
    new BridgeReader(v).read(snap);
    expect(snap.flags & FLAG_TELEMETRY_STALE).toBe(FLAG_TELEMETRY_STALE);
    expect(snap.mode).toBe(1);
    core.dispose();
  });

  it("accepts only well-formed samples", () => {
    expect(parseTelemetrySample({ timestamp: 1, joint_angles: [1.5], sensor_states: [0] }).joint_angles).toEqual([1.5]);
    expect(() => parseTelemetrySample({ timestamp: 1, joint_angles: ["x"], sensor_states: [] })).toThrow(WorldError);
    expect(() => parseTelemetrySample({ timestamp: 1, joint_angles: [], sensor_states: [], extra: 1 })).toThrow(/unknown field/);
  });
});

describe("forced inputs", () => {
  it("win over the sensor until released", () => {
    const core = PhysicsCore.create(RAPIER, world());
    core.enqueue({ type: "input", pin: 0, volts: 24 });
    core.flush(); // a paused world takes it without stepping
    expect(core.step).toBe(0);
    expect(core.pinFlags[0]).toBe(PIN_FORCED | PIN_HIGH);
    core.enqueue({ type: "input", pin: 0, volts: null });
    core.stepOnce();
    expect(core.pinVolts[0]).toBe(0);
    expect(logicHigh(14.9, [0, 28.8])).toBe(false);
    expect(logicHigh(15, [0, 28.8])).toBe(true);
    expect(logicHigh(2.5, [0, 5])).toBe(true);
    core.dispose();
  });
});

describe("determinism", () => {
  const script = (core: PhysicsCore) => {
    for (let i = 0; i < 400; i++) {
      if (i === 50) core.enqueue({ type: "spawn", part: at("cookie2", "cookie", [60, 3, 30]), role: { kind: "dynamic" } });
      if (i === 120) core.enqueue({ type: "conveyor", instance_id: "belt", speed_mm_s: 140 });
      core.stepOnce();
    }
    return core.stateHash();
  };

  it("ends two runs of the same commands in bit-identical states", () => {
    const a = PhysicsCore.create(RAPIER, world());
    const b = PhysicsCore.create(RAPIER, world());
    const ha = script(a);
    expect(script(b)).toBe(ha);
    expect(a.pose("cookie2")!.p).toEqual(b.pose("cookie2")!.p);
    a.dispose();
    b.dispose();
  });

  it("tells a different run apart", () => {
    const a = PhysicsCore.create(RAPIER, world());
    const ha = script(a);
    const c = PhysicsCore.create(RAPIER, world());
    c.enqueue({ type: "conveyor", instance_id: "belt", speed_mm_s: 99 });
    expect(script(c)).not.toBe(ha);
    a.dispose();
    c.dispose();
  });
});

describe("the world is checked", () => {
  it("refuses joints on parts that are not kinematic, cycles, unknown pins and spawned pins", () => {
    expect(() => PhysicsCore.create(RAPIER, world({ bindings: [{ joint: 0, instance_id: "cookie", type: "prismatic", axis_local: [1, 0, 0], unit: "mm" }] })))
      .toThrow(/must be kinematic/);
    expect(() => PhysicsCore.create(RAPIER, world({
      bindings: [
        { joint: 0, instance_id: "slide", type: "prismatic", axis_local: [1, 0, 0], unit: "mm", parent: "gripper" },
        { joint: 1, instance_id: "gripper", type: "revolute", axis_local: [0, 0, 1], unit: "deg", parent: "slide" },
      ],
    }))).toThrow(/cycle/);
    expect(() => PhysicsCore.create(RAPIER, world({ telemetry_sensors: [{ part_instance: "barrier", pin_label: "NOPE" }] }))).toThrow(/no pin/);
    expect(() => PhysicsCore.create(RAPIER, world({ bindings: [{ joint: 0, instance_id: "slide", type: "prismatic", axis_local: [1, 0, 0], unit: "deg" }] })))
      .toThrow(/must be in mm/);
    const core = PhysicsCore.create(RAPIER, world());
    core.enqueue({ type: "spawn", part: at("b2", "barrier", [0, 0, 100]), role: { kind: "dynamic" } });
    expect(() => core.flush()).toThrow(/cannot carry pins/);
    core.dispose();
  });
});

describe("the circuit, checked every step", () => {
  const psu = part("psu", 40, 60, 80, 300, [
    { pin_number: 1, label: "+24V", local_position_mm: [0, 0, 0], electrical_type: "power_input", voltage_limits: [0, 28.8] },
    { pin_number: 2, label: "GND", local_position_mm: [0, 0, 0], electrical_type: "power_input", voltage_limits: [0, 28.8] },
  ]);
  const relay = part("relay", 15, 30, 30, 40, [
    { pin_number: 1, label: "COM", local_position_mm: [0, 0, 0], electrical_type: "digital_io", voltage_limits: [0, 250] },
    { pin_number: 2, label: "NO", local_position_mm: [0, 0, 0], electrical_type: "digital_io", voltage_limits: [0, 250] },
  ]);
  const K1 = { id: "K1", a: { part_instance: "k1", pin_label: "COM" }, b: { part_instance: "k1", pin_label: "NO" }, closed: false };
  const circuitWorld = (): WorldInit => {
    const w = world();
    return {
      ...w,
      parts: [...PARTS, psu, relay],
      project: {
        placed_parts: [...w.project.placed_parts, at("psu", "psu", [-200, 0, 40]), at("k1", "relay", [-150, 0, 15])],
        wire_nets: [
          { net_id: "24V", connections: [{ part_instance: "psu", pin_label: "+24V" }, { part_instance: "k1", pin_label: "COM" }] },
          { net_id: "0V", connections: [{ part_instance: "k1", pin_label: "NO" }, { part_instance: "psu", pin_label: "GND" }] },
        ],
      },
      roles: { ...w.roles, psu: { kind: "fixed" }, k1: { kind: "fixed" } },
      supplies: [{ id: "PSU", positive: { part_instance: "psu", pin_label: "+24V" }, negative: { part_instance: "psu", pin_label: "GND" }, volts: 24 }],
      contacts: [K1],
    };
  };

  it("reports a short the moment a contact closes, and flags its pins in the bridge", () => {
    const core = PhysicsCore.create(RAPIER, circuitWorld());
    expect(core.takeCircuitChanged()).toBe(true); // the first checks
    expect(core.diagnostics.map((d) => d.status)).toEqual(["OK", "OK"]);
    run(core, 5);
    expect(core.takeCircuitChanged()).toBe(false); // unchanged: nothing to send
    core.enqueue({ type: "contact", contact: { ...K1, closed: true } });
    core.flush();
    expect(core.takeCircuitChanged()).toBe(true);
    expect(core.diagnostics[0]).toMatchObject({ status: "SHORT_CIRCUIT", netId: "24V" });
    const v = createBridge(core.partCapacity, core.pins.length);
    core.publish(new BridgeWriter(v));
    const snap = makeSnapshot(v.layout);
    new BridgeReader(v).read(snap);
    const plus = core.pins.findIndex((p) => p.instance_id === "psu" && p.label === "+24V");
    expect(snap.pinFlags[plus] & PIN_FAULT).toBe(PIN_FAULT);
    expect(snap.pinFlags[0] & PIN_FAULT).toBe(0); // the light barrier is not on the faulted node
    core.dispose();
  });

  it("checks rewiring against the schema", () => {
    const core = PhysicsCore.create(RAPIER, circuitWorld());
    core.enqueue({ type: "nets", wire_nets: [{ net_id: "x", connections: [{ part_instance: "psu", pin_label: "+24V" }] }] });
    expect(() => core.flush()).toThrow(/at least two pins/);
    core.dispose();
  });
});
