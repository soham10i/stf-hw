// The main thread's handle on the physics worker: it starts the worker, gives it the simulation
// bridge, sends commands, and reads consistent snapshots for the renderer. It never steps physics.
//
//   const physics = await PhysicsClient.start(world);
//   physics.run(true);
//   // in the render loop:
//   if (physics.read(snapshot)) applyToScene(snapshot);
//
// With cross-origin isolation the bridge is a SharedArrayBuffer both threads use in place; without
// it the worker transfers a copy after each publish and `read` uses the newest copy.
import { BridgeReader, createBridge, makeSnapshot, type BridgeLayout, type Snapshot } from "./SimulationBridge";
import { parseCatalogue, parseProjectState, pinTable, type PinRow, type PlacedPart } from "./schema";
import type { Contact, Diagnostic } from "../circuit/NetlistSolver";
import type { WireNet } from "./schema";
import type { AxisCommand, BodyRole, FromWorker, Mode, TelemetrySample, ToWorker, WorkerStats, WorldInit } from "../workers/protocol";

export interface PhysicsClientOptions {
  /** use a SharedArrayBuffer when the page allows it (default true) */
  preferShared?: boolean;
  onStats?: (s: WorkerStats) => void;
  onError?: (message: string) => void;
  onTelemetry?: (s: { connected: boolean; lastTimestamp: number | null; error?: string }) => void;
  /** the circuit checks, whenever a status changes (the first set arrives right after start) */
  onCircuit?: (d: Diagnostic[]) => void;
  /** a worker of your own (tests); default: physics.worker.ts */
  worker?: Worker;
}

export class PhysicsClient {
  readonly shared: boolean;
  readonly pins: PinRow[];
  readonly layout: BridgeLayout;
  rapierVersion = "";
  /** instance ids in bridge order: snapshot transform i is partOrder[i] */
  partOrder: string[] = [];
  running = false;
  /** the real-time rate last asked for (run) */
  rate = 1;
  /** the newest circuit checks */
  diagnostics: Diagnostic[] = [];
  private reader: BridgeReader;
  private disposed = false;

  private constructor(private readonly worker: Worker, reader: BridgeReader, shared: boolean, pins: PinRow[]) {
    this.reader = reader;
    this.shared = shared;
    this.pins = pins;
    this.layout = reader.views.layout;
  }

  /** Validates the world, starts the worker and resolves once the world is built. */
  static start(world: WorldInit, opts: PhysicsClientOptions = {}): Promise<PhysicsClient> {
    const catalogue = parseCatalogue(world.parts);
    const project = parseProjectState(world.project, catalogue);
    const pins = pinTable(project, catalogue);
    const parts = project.placed_parts.length + (world.extra_part_capacity ?? 64);
    const axes = world.axes?.length ?? 0;
    const views = createBridge(parts, pins.length, opts.preferShared ?? true, axes);
    const shared = views.shared;
    const worker = opts.worker ?? new Worker(new URL("../workers/physics.worker.ts", import.meta.url), { type: "module", name: "stf-physics" });
    // the transfer fallback starts from an empty copy of the layout until the first frame arrives
    const reader = new BridgeReader(shared ? views : createBridge(parts, pins.length, false, axes));
    const client = new PhysicsClient(worker, reader, shared, pins);
    return new Promise((resolve, reject) => {
      let ready = false;
      worker.onmessage = (e: MessageEvent<FromWorker>) => {
        const m = e.data;
        switch (m.type) {
          case "ready":
            ready = true;
            client.rapierVersion = m.rapier;
            client.partOrder = m.partOrder;
            resolve(client);
            return;
          case "frame":
            client.reader.adopt(m.buffer);
            return;
          case "parts":
            client.partOrder = m.partOrder;
            return;
          case "stats":
            opts.onStats?.(m.stats);
            return;
          case "telemetry-status":
            opts.onTelemetry?.(m);
            return;
          case "circuit":
            client.diagnostics = m.diagnostics;
            opts.onCircuit?.(m.diagnostics);
            return;
          case "error":
            if (!ready) reject(new Error(m.message));
            else opts.onError?.(m.message);
            return;
        }
      };
      worker.onerror = (e) => {
        if (!ready) reject(new Error(e.message || "the physics worker failed to start"));
        else opts.onError?.(e.message);
      };
      client.send({ type: "init", world: { ...world, project }, bridge: shared ? (views.buffer as SharedArrayBuffer) : null });
    });
  }

  private send(msg: ToWorker): void {
    if (this.disposed) throw new Error("the physics client was disposed");
    this.worker.postMessage(msg);
  }

  /** A snapshot sized for this world, to pass to `read` every frame. */
  snapshot(): Snapshot {
    return makeSnapshot(this.layout);
  }

  /** Copies the newest consistent state into `out`; false if there is none yet. Also writes any
      inputs the UI forced since the last frame. */
  read(out: Snapshot): boolean {
    if (this.shared) this.reader.flushInputs();
    return this.reader.read(out);
  }

  setMode(mode: Mode): void {
    this.send({ type: "mode", mode });
  }

  /** Runs or pauses the fixed-step loop; `rate` scales real time (1 = real time, up to 16). */
  run(running: boolean, rate?: number): void {
    this.running = running;
    if (rate !== undefined) this.rate = rate;
    this.send({ type: "run", running, rate });
  }

  /** Exactly `steps` fixed steps, at once (paused worlds; tests and review). */
  step(steps = 1): void {
    this.send({ type: "step", steps });
  }

  telemetry(samples: TelemetrySample[]): void {
    this.send({ type: "telemetry", samples });
  }

  /** Live telemetry straight into the worker from a WebSocket (JSON samples, one or an array). */
  connect(url: string): void {
    this.send({ type: "connect", url });
  }

  disconnect(): void {
    this.send({ type: "disconnect" });
  }

  spawn(part: PlacedPart, role: BodyRole = { kind: "dynamic" }): void {
    this.send({ type: "spawn", part, role });
  }

  remove(instance_id: string): void {
    this.send({ type: "remove", instance_id });
  }

  setConveyor(instance_id: string, speed_mm_s: number): void {
    this.send({ type: "conveyor", instance_id, speed_mm_s });
  }

  /** Forces a pin (a pushed button), or releases it with null. Shared: written into the bridge
      under its mutex (a paused world is woken to take it); otherwise posted. */
  setInput(pin: number, volts: number | null): void {
    if (this.shared) {
      this.reader.setInput(pin, volts);
      if (!this.running) this.send({ type: "inputs", inputs: [] });
    } else {
      this.send({ type: "inputs", inputs: [[pin, volts]] });
    }
  }

  /** Moves a driven joint to a value, along its motion profile. */
  setTarget(joint: number, value: number): void {
    this.send({ type: "target", joint, value });
  }

  /** One stroke of a driven joint: out to `value`, hold, back (an ejector firing). */
  pulse(joint: number, value: number, hold_s = 0.15): void {
    this.send({ type: "pulse", joint, value, hold_s });
  }

  /** Tells an axis's positioning block what to do (home, move to a position, jog, stop). */
  axis(id: string, command: AxisCommand): void {
    this.send({ type: "axis", id, command });
  }

  /** Replaces the wiring; the next check runs on it. */
  setNets(wire_nets: WireNet[]): void {
    this.send({ type: "nets", wire_nets });
  }

  /** Opens or closes a contact (a relay, a button, a jumper). */
  setContact(contact: Contact): void {
    this.send({ type: "contact", contact });
  }

  dispose(): void {
    if (this.disposed) return;
    this.send({ type: "dispose" });
    this.disposed = true;
    this.worker.terminate();
  }
}
