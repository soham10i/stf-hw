// The physics worker (Deliverable 2): a headless thread that owns the Rapier world and steps it at
// a fixed 100 Hz, publishing every state to the simulation bridge. The main thread never steps
// physics; it reads the bridge in its render loop (core/PhysicsClient.ts).
//
// The loop is an accumulator: real time (scaled by the run rate) is added, and as many fixed
// 10 ms steps run as it holds. Each step is the same 10 ms whatever the timer did, so the
// simulation is the same simulation however the thread was scheduled - only how far it has got
// at a given wall time varies. When the thread falls more than MAX_STEPS_PER_TICK behind (a
// background tab, a debugger), the backlog is dropped and counted as an overrun, rather than
// stepping in a burst that would freeze the page.
//
// Modes (message "mode"):
//   SIMULATION_MODE       kinematic parts follow their planned joint tracks; physics runs
//   LIVE_TELEMETRY_MODE   kinematic parts follow the live factory's joint_angles (WebSocket,
//                         or samples posted by the main thread), played out a fixed delay
//                         behind the newest sample; sensor pins follow its sensor_states
import RAPIER from "@dimforge/rapier3d-deterministic-compat";

import { attachBridge, BridgeWriter, createBridge, type BridgeViews } from "../core/SimulationBridge";
import { parseCatalogue, parseProjectState } from "../core/schema";
import { parseTelemetrySample, PhysicsCore, type Command } from "./physicsCore";
import type { FromWorker, ToWorker, WorkerStats } from "./protocol";

interface WorkerScope {
  postMessage(msg: FromWorker, transfer?: Transferable[]): void;
  onmessage: ((e: MessageEvent<ToWorker>) => void) | null;
  close(): void;
}
const scope = self as unknown as WorkerScope;
const post = (msg: FromWorker, transfer?: Transferable[]) => scope.postMessage(msg, transfer ?? []);

const fixedTimeStep = 1 / 100;
const MAX_STEPS_PER_TICK = 25; // 250 ms of simulation at most per wake-up
const TICK_MS = 4; // how often the thread wakes; the steps are fixed whatever this is

let accumulator = 0;
let lastTime = performance.now();
let core: PhysicsCore | null = null;
let views: BridgeViews | null = null;
let writer: BridgeWriter | null = null;
let shared = false;
let timer: ReturnType<typeof setTimeout> | null = null;
let socket: WebSocket | null = null;
let lastTelemetry: number | null = null;

// stats over one second
let statSteps = 0;
let statOverruns = 0;
let statStepMs = 0;
let statSince = performance.now();

function fail(e: unknown): void {
  post({ type: "error", message: e instanceof Error ? e.message : String(e) });
}

/** Publishes the state; in the transfer fallback, also sends a copy of the buffer. */
function publish(): void {
  if (!core || !writer || !views) return;
  core.publish(writer);
  if (core.takePartsChanged()) post({ type: "parts", partOrder: core.partOrder() });
  if (core.takeCircuitChanged()) post({ type: "circuit", diagnostics: core.diagnostics });
  if (!shared) {
    const copy = (views.buffer as ArrayBuffer).slice(0);
    post({ type: "frame", buffer: copy }, [copy]);
  }
}

function tick(): void {
  timer = null;
  if (!core || !core.running) return;
  const now = performance.now();
  accumulator += ((now - lastTime) / 1000) * core.rate;
  lastTime = now;
  let steps = 0;
  const t0 = performance.now();
  writer!.drainInputs((pin, volts) => core!.enqueue({ type: "input", pin, volts }));
  try {
    core.flush(); // the commands that came since the last tick: a refused one is reported, not fatal
  } catch (e) {
    fail(e);
  }
  try {
    while (accumulator >= fixedTimeStep && steps < MAX_STEPS_PER_TICK) {
      core.stepOnce();
      accumulator -= fixedTimeStep;
      steps++;
    }
  } catch (e) {
    core.running = false;
    fail(e);
    publish();
    return;
  }
  if (accumulator >= fixedTimeStep) {
    accumulator = 0; // fell behind: drop the backlog instead of bursting
    statOverruns++;
  }
  if (steps > 0) {
    statSteps += steps;
    statStepMs += performance.now() - t0;
    publish();
  }
  if (now - statSince >= 1000) {
    const stats: WorkerStats = {
      stepsPerSecond: (statSteps * 1000) / (now - statSince),
      overruns: statOverruns,
      stepMsMean: statSteps ? statStepMs / statSteps : 0,
      bodies: core.partOrder().length,
    };
    post({ type: "stats", stats });
    statSteps = 0;
    statOverruns = 0;
    statStepMs = 0;
    statSince = now;
  }
  timer = setTimeout(tick, TICK_MS);
}

function run(running: boolean, rate?: number): void {
  if (!core) throw new Error("the world is not initialised");
  if (rate !== undefined) {
    if (!(rate > 0 && rate <= 16)) throw new Error("the rate must be in (0, 16]");
    core.rate = rate;
  }
  core.running = running;
  if (running && timer === null) {
    accumulator = 0;
    lastTime = performance.now();
    timer = setTimeout(tick, 0);
  }
  if (!running && timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
  publish();
}

function connect(url: string): void {
  disconnect();
  const ws = new WebSocket(url);
  socket = ws;
  ws.onopen = () => post({ type: "telemetry-status", connected: true, lastTimestamp: lastTelemetry });
  ws.onclose = () => {
    if (socket === ws) socket = null;
    post({ type: "telemetry-status", connected: false, lastTimestamp: lastTelemetry });
  };
  ws.onerror = () => post({ type: "telemetry-status", connected: false, lastTimestamp: lastTelemetry, error: "the telemetry socket failed" });
  ws.onmessage = (e) => {
    try {
      const data: unknown = JSON.parse(typeof e.data === "string" ? e.data : "");
      const samples = (Array.isArray(data) ? data : [data]).map(parseTelemetrySample);
      if (samples.length) lastTelemetry = samples[samples.length - 1].timestamp;
      core?.enqueue({ type: "telemetry", samples });
    } catch (err) {
      post({ type: "telemetry-status", connected: true, lastTimestamp: lastTelemetry, error: err instanceof Error ? err.message : String(err) });
    }
  };
}

function disconnect(): void {
  if (socket) {
    const ws = socket;
    socket = null;
    ws.close();
  }
}

async function init(msg: Extract<ToWorker, { type: "init" }>): Promise<void> {
  await RAPIER.init();
  // the world is validated here too: the worker trusts nothing it is sent
  const catalogue = parseCatalogue(msg.world.parts);
  const project = parseProjectState(msg.world.project, catalogue);
  core?.dispose();
  core = PhysicsCore.create(RAPIER, { ...msg.world, parts: [...catalogue.values()], project });
  if (msg.bridge) {
    views = attachBridge(msg.bridge);
    shared = true;
  } else {
    views = createBridge(core.partCapacity, core.pins.length, false, core.axisCount);
    shared = false;
  }
  if (views.layout.partCapacity < core.partCapacity || views.layout.pinCapacity < core.pins.length || views.layout.axisCapacity < core.axisCount) {
    throw new Error(`the bridge holds ${views.layout.partCapacity} parts / ${views.layout.pinCapacity} pins; the world needs ${core.partCapacity} / ${core.pins.length}`);
  }
  writer = new BridgeWriter(views);
  core.takePartsChanged();
  post({ type: "ready", rapier: RAPIER.version(), shared, partCount: core.partOrder().length, pinCount: core.pins.length, partOrder: core.partOrder() });
  publish();
}

const COMMANDS = new Set(["mode", "spawn", "remove", "conveyor", "nets", "contact", "target", "pulse", "axis"]);

scope.onmessage = (e: MessageEvent<ToWorker>) => {
  const msg = e.data;
  try {
    if (msg.type === "init") {
      init(msg).catch(fail);
      return;
    }
    if (msg.type === "dispose") {
      disconnect();
      if (timer !== null) clearTimeout(timer);
      core?.dispose();
      core = null;
      scope.close();
      return;
    }
    if (!core) throw new Error(`"${msg.type}" before the world was initialised`);
    if (COMMANDS.has(msg.type)) {
      core.enqueue(msg as Command);
      if (!core.running) {
        core.flush(); // a paused world takes the command now, without stepping
        publish();
      }
      return;
    }
    switch (msg.type) {
      case "run":
        run(msg.running, msg.rate);
        return;
      case "step":
        if (!Number.isInteger(msg.steps) || msg.steps < 1 || msg.steps > 100_000) throw new Error("steps must be a whole number in 1..100000");
        for (let i = 0; i < msg.steps; i++) core.stepOnce();
        publish();
        return;
      case "telemetry": {
        const samples = msg.samples.map(parseTelemetrySample);
        if (samples.length) lastTelemetry = samples[samples.length - 1].timestamp;
        core.enqueue({ type: "telemetry", samples });
        return;
      }
      case "connect":
        connect(msg.url);
        return;
      case "disconnect":
        disconnect();
        return;
      case "inputs":
        // shared bridge: the UI wrote the inputs into it and this message only wakes a paused world;
        // transfer fallback: the inputs come in the message
        if (shared) writer!.drainInputs((pin, volts) => core!.enqueue({ type: "input", pin, volts }));
        for (const [pin, volts] of msg.inputs) core.enqueue({ type: "input", pin, volts });
        if (!core.running) {
          core.flush();
          publish();
        }
        return;
    }
  } catch (err) {
    fail(err);
  }
};
