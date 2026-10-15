// Live state that changes every frame lives HERE, in a plain mutable object -
// deliberately NOT in React state. At 30 Hz a setState per frame would reconcile
// the whole tree and drop the 3D view to single-digit fps with a sawtooth heap.
// The scene reads `hot` imperatively inside useFrame; React never re-renders
// because of it.
//
// Only discrete state (connection status, order list, the low-rate telemetry
// sampled for the side panel) flows through React, via the tiny store below.

import type { Carrier, Frame, OvenState } from "./types";

const NO_CARRIER: Carrier = { flavor: null, holder: null, slot: null };
const OVEN_IDLE: OvenState = { slider: 1, door: 1, lamp: false };

export const hot: {
  joints: Record<string, number>;
  tracking_error: Record<string, number>;
  motors: Record<string, { amps: number; health: number; phase: string }>;
  belt: { position: number; object: number | null };
  sensors: Record<string, boolean>;
  carrier: Carrier;
  oven: OvenState;
  seq: number;
  t: number;
  busy: boolean;
} = {
  joints: {},
  tracking_error: {},
  motors: {},
  belt: { position: 0, object: null },
  sensors: {},
  carrier: NO_CARRIER,
  oven: OVEN_IDLE,
  seq: 0,
  t: 0,
  busy: false,
};

export function applyFrame(frame: Frame): void {
  hot.joints = frame.joints;
  hot.tracking_error = frame.tracking_error;
  hot.motors = frame.motors;
  hot.belt = frame.belt;
  hot.sensors = frame.sensors;
  hot.carrier = frame.carrier ?? NO_CARRIER;
  hot.oven = frame.oven ?? OVEN_IDLE;
  hot.seq = frame.seq;
  hot.t = frame.t;
  hot.busy = frame.busy;
}

// --- discrete store: a minimal observable for React-side state ---------------

export type ConnState = "connecting" | "open" | "closed";

interface DiscreteState {
  conn: ConnState;
  layoutFingerprint: string | null;
}

type Listener = () => void;

class Store {
  private state: DiscreteState = { conn: "connecting", layoutFingerprint: null };
  private listeners = new Set<Listener>();

  get = (): DiscreteState => this.state;

  set = (patch: Partial<DiscreteState>): void => {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((l) => l());
  };

  subscribe = (l: Listener): (() => void) => {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  };
}

export const store = new Store();
