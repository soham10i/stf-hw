// Shapes mirrored from services/api/wire.py. Hand-kept for the slice; the plan
// generates these from the Pydantic contracts so Python and TypeScript cannot
// drift, but that codegen is a later step.

export interface JointDesc {
  kind: "prismatic" | "revolute";
  axis: "+x" | "-x" | "+y" | "-y" | "+z" | "-z";
  limits: [number, number];
  home: number;
  positions: Record<string, number>;
  motor_id: string | null;
}

export interface DeviceDesc {
  kind: string;
  base: [number, number, number];
  tool: string | null;
  joints: Record<string, JointDesc>;
}

export interface SceneDescriptor {
  fingerprint: string;
  scene_scale: number;
  up: string;
  joint_refs: string[];
  devices: Record<string, DeviceDesc>;
  rack: {
    origin: [number, number, number];
    rows: { count: number; pitch: number; labels: string[] };
    cols: { count: number; pitch: number; labels: string[] };
    order: string;
    slot_envelope: [number, number, number];
    slots: Record<string, [number, number, number]>;
  };
  conveyor: {
    pose: [number, number, number];
    length: number;
    width: number;
    axis: string;
    sensors: Record<string, { at_mm: number | null; kind: string }>;
  };
  stations: Record<string, { pose: [number, number, number]; description: string | null }>;
  modules: Record<
    string,
    { origin: [number, number, number]; size: [number, number]; label: string | null }
  >;
}

export interface Carrier {
  flavor: string | null;
  holder: string | null; // null | "slot:B2" | "fork" | "belt" | "suction" | "oven" | "delivery"
  slot: string | null;
}

// Brennofen state, animated server-side: Ofenschieber (1 = out, 0 = inside the
// chamber), Ofentuer (1 = open, 0 = closed), baking lamp.
export interface OvenState {
  slider: number;
  door: number;
  lamp: boolean;
}

export interface Frame {
  type: "frame";
  seq: number;
  t: number;
  busy: boolean;
  joints: Record<string, number>;
  tracking_error: Record<string, number>;
  motors: Record<string, { amps: number; health: number; phase: string }>;
  belt: { position: number; object: number | null };
  sensors: Record<string, boolean>;
  carrier?: Carrier;
  oven?: OvenState;
}

export interface Order {
  id: number;
  op: string;
  slot: string | null;
  status: string;
  error: string | null;
}
