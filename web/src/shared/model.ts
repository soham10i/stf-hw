// The twin's data model: the shape of the export stf-cad/hbw/hbw_export.py writes
// (hbw_parts_up12.json), and the hook that loads and checks it. Types only, no rendering.
import type { Fit, WiringDoc } from "../scene/FactoryDetail";
import type { ChainSpec } from "../scene/DragChain";
import { useJson } from "./data";

export interface CadPart {
  n: string; f: "world" | "travel" | "lift" | "fork"; g: string;
  k: "box" | "cyl"; p: [number, number, number];
  s: [number, number, number] | [string, number, number];
  c: string; tag: string; mech: string; note: string;
  fit?: Fit;
}
export interface CadDoc {
  fingerprint: string;
  plate: [number, number, number];
  pitch_mm: number;
  home: { travel: number; lift: number; fork: number };
  joints: Record<string, { limits: [number, number]; stops: Record<string, number> }>;
  belt: {
    x: number; surface: number; gap: number; y0: number; y1: number;
    handover: number; I2: number; I3: number; pulley_d: number;
  };
  slots: Record<string, [number, number, number]>;
  moulds: {
    slots: string[]; with_cookie: string[]; free_slot: string;
    size: [number, number, number]; rim_h: number; cookie_flavour: Record<string, string>;
  };
  vgr: {
    plate: [number, number, number];
    centre: [number, number];
    pitch_mm: number;
    frames: { name: string; parent: string | null }[];
    joints: Record<string, { kind: string; limits: [number, number]; stops: Record<string, number> }>;
    cup_drop: number;
    authoring: { swivel: number; plunge: number; reach: number };
    spring: number;
    plan: {
      keys: PlanKey[]; cup_drop: number; overtravel: number; transit: number;
      cookie_tops: Record<string, number>;
    };
    parts: CadPart[];
  };
  oven: {
    plate: [number, number, number];
    turntable: [number, number];
    frames: { name: string; parent: string | null }[];
    authoring: Record<string, number>;
    joints: Record<string, { kind: string; limits: [number, number]; stops: Record<string, number> }>;
    handover: [number, number, number];
    cup_up: number; tray_top: number; disc_top: number; wp_h: number;
    flow: {
      x_line: number; z_w: number; wp_h: number; wp_d: number; tray_y: number; tray_w: number;
      cup_up: number; stroke: number; tt: [number, number]; tt_r: number;
      stations: Record<string, number>; push: number; belt: [number, number];
      exit: [number, number, number];
    };
    parts: CadPart[];
  };
  sorting: {
    plate: [number, number, number];
    frames: { name: string; parent: string | null }[];
    joints: Record<string, { kind: string; axis?: string; limits: [number, number]; stops: Record<string, number> }>;
    colours: string[];
    sensor_gap: number;
    handovers: Record<string, [number, number, number]>;
    parts: CadPart[];
  };
  pipeline: {
    raw_colour: string;
    n_cookies: number;
    flavours: Record<string, { colour: string; mV: number; bin: string }>;
    initial: Record<string, [string, string[]]>;      // cookie -> [flavour, its place]
    transfers: unknown[];
    safety: string[];
  };
  factory: {
    plate: [number, number, number];
    vgr_at: [number, number];
    oven_at: [number, number];
    oven_placement: { rotate_deg: number; translate: [number, number] };
    oven_rect: [number, number, number, number];
    sort_placement: { rotate_deg: number; translate: [number, number] };
    stations: Record<string, { swivel: number; reach: number; target: [number, number]; in_envelope: boolean }>;
    vgr_plunge_band: Record<string, [number, number]>;
    placement: { rotate_deg: number; translate: [number, number] };
    hbw_rect: [number, number, number, number];
    neighbours: { id: string; n: number; label: string; rect: [number, number, number, number] }[];
  };
  stations: { vgr_pick: [number, number, number]; hbw_pick: [number, number, number] };
  interlocks: string[];
  parts: CadPart[];
  plc: { at: [number, number]; plate: [number, number, number]; parts: CadPart[] };
  wiring: WiringDoc;
  upgrade?: UpgradeDoc;
  safety?: SafetyDoc;
  chains?: ChainsDoc;
  io3?: Io3Doc;
  control?: ControlDoc;
  vc?: VcDoc;
  health?: HealthDoc;
  lifecycle?: LifecycleDoc;
}

// Upgrade 6: stf-cad/hbw/health.py
export interface HealthComp {
  id: string; name: string; part: string; unit: string; kind: string; metric: string; source: string[];
  life: number; wear_part: boolean; r_fail: number; soft: number; per_order: number; per_shift: number;
  warn: number | null; warn_by: string | null; fail: number | null; lead_cycles: number | null;
  lead_shifts: number | null; false_warnings: number; healthy_cycles: number;
  curve: [number, number, number, number | null][];     // n, ewma, HI, RUL cycles
  pm_interval: number; pm_shifts: number;
}
export interface HealthDoc {
  components: HealthComp[];
  detect_only: { mode: string; why: string; cover: string }[];
  topics: { topic: string; rate: string; fields: string; sources: string[] }[];
  orders_per_shift: number; shift_h: number; air_duty0: number;
  rules: { ewma: number; soft: number; window: number; rul_warn_shifts: number; noise: number; ecb_trip: number };
  new_hardware: string; assumed: string;
}
// Upgrade 7: stf-cad/hbw/lifecycle.py
export interface TolChain {
  id: string; what: string; nominal: number; worst: number; rss: number;
  contrib: { what: string; tol: number }[]; fix: string | null; ok: boolean;
}
export interface LifecycleDoc {
  chains: TolChain[]; chains_before: TolChain[] | null;
  access: { module: string; part: string; above_clear: boolean; blocked_by: string[]; side: string | null;
            from: string; door: string; reach_mm: number; in_reach: boolean; ok: boolean }[];
  spares: { item: string; what: string; qty: number; wear: boolean; per_year: number | null; stock: number; examples: string[] }[];
  plan: { task: string; every_shifts: number; trigger: string; door: string; signal: string }[];
  structure: { member: string; load: string; L_mm: number; section: string; E: number; I: number; m_tip_g: number;
               a_ms2: number; defl_mm: number; f1_hz: number; ok: boolean; note: string }[];
  rules: { reach_mm: number; defl_dyn_mm: number; f_min_hz: number };
  assumed: string;
}

// Upgrade 5: stf-cad/hbw/vc.py
export interface VcMatrixRow {
  id: string; fault: string; what: string; expected: string; observed: string[]; latency_s: number | null;
  bound_s: number; reaction: string; recovery: string; makespan: number; lost_s: number; notes: string[];
  pass: boolean; fails: string[];
}
export interface VcDoc {
  scan_ms: Record<string, number>; bus_ms: number; node_wd_ms: number; mb_timeout_ms: number;
  repair_s: number; reset_s: number; tol_makespan: number;
  phys: { a_mm: Record<string, number>; a_deg: Record<string, number>; v: Record<string, number>; [k: string]: unknown };
  accuracy: { axis: string; unit: string; v: number; a: number; scan_ms: number; lead: number; error_mm: number;
              tol_mm: number; why: string; no_lead_mm: number; ok: boolean; at_10ms_mm: number }[];
  healthy: { makespan: number; worst_watchdog: number | null; bars: GanttBar[] };
  matrix: VcMatrixRow[];
  before: { id: string; detected: string; after_s: number; harm: string }[];
  sensors: Record<string, Record<string, { part: string; what: string }>>;
  map: { tag: string; module: string; signal: string; type: string; node: string; slice: string; ch: number;
         table: string; addr: number; regs: number; twin: string; desc: string }[];
  performance: { makespan: number; model: number; busy: Record<string, number>; bottleneck: string;
                 availability: number; performance: number; quality: number; oee: number; shift_s: number;
                 buffer_makespan: number | null; oee_note: string };
  ip: Record<string, string>;
  assumed: string;
}

// Upgrade 4: stf-cad/hbw/control.py
export interface SfcState {
  id: string; say: string; out: string[]; done?: string; t?: number; limit?: number | null;
  supervised?: boolean; motion?: boolean; job?: string | null; sig?: string[];
}
export interface GanttBar {
  job: string; bind: string[]; units: string[]; t0: number; t1: number;
  steps?: [string, string, number, number][];
}
export interface TraceRec {
  id: string; flavour: string; kind: "production" | "return"; mould: string | null;
  slot_from: string | null; slot_to: string | null; reads: [string, string, number][];
  t: Record<string, number>; colour_mV?: number; class?: string; bin?: string; verified?: boolean;
  bake_s?: number; nest?: number;
}
export interface AlarmRow {
  code: string; unit: string; text: string; cause: string; reaction: string; recovery: string;
  limit: number | null; steps: string[];
}
export interface ControlDoc {
  policy: string;
  policies: Record<string, {
    say: string; deadlock: boolean; states: number; makespan?: number; busy?: Record<string, number>;
    bars?: GanttBar[]; trace?: string[]; why?: string;
  }>;
  study: ({ bake_s: number } & Record<string, number>)[];
  bake_demo: number;
  units: Record<string, { module: string; outputs: string[]; label: string; states: SfcState[];
                          edges: [string, string, string][]; jobs: string[] }>;
  retired: Record<string, string[]>;
  alarms: AlarmRow[];
  unsupervised: { unit: string; state: string; say: string; out: string[] }[];
  trace: TraceRec[];
  moulds: Record<string, string>;
  rfid: { y: [number, number]; pick_hbw: number; pick_vgr: number; reach_y: number; belt_speed: number };
  read_points: Record<string, string>;
  bands: Record<string, [number, number]>;
  jog: { unit: string; axis: string; out: string; when: string; model: string }[];
  st: Record<string, string>;
  assumed: string;
}

export interface ChainsDoc {
  chains: Record<string, ChainSpec & { fixed: string; moving: string; stroke: [number, number]; devices: string[] }>;
  rows: { module: string; id: string; axis: string; stroke: [number, number]; R: number; h: number; w: number;
          length: number; conductors: number; fill: number; bend_min: number; span: number; devices: string[] }[];
  rules: { bend: string; fill_max: number; self_support_mm: number };
  swivel: string; sizes: string;
}
export interface Io3Doc {
  nodes: Record<string, { at: [number, number]; along: string; where: string; length: number;
                          slices: { id: string; type: string; channels: (string | null)[] }[] }>;
  allocation: { module: string; slice: string; type: string; ch: number; signal: string | null }[];
  spare_min: number; sizes: string;
  rail: { used_mm: number; length_mm: number; free: number };
  parts: CadPart[];
}

export interface Hazard {
  id: string; name: string; what: string; zone: number[] | null; S: string; F: string; P: string; PLr: string;
  cyl?: { centre: [number, number]; r: number; z: [number, number]; poly?: number[][] };
}
export interface SafetyDoc {
  name: string; outline: [number, number, number, number]; height: number; post: number; gap: number; z_bot: number;
  hazards: Hazard[];
  functions: { id: string; name: string; devices: string; PLr: string; category: string; stop: string }[];
  circuit: {
    inputs: { id: string; label: string; channels: string[]; kind: string }[];
    reset: { id: string; label: string }; relay: { id: string; label: string };
    outputs: { id: string; label: string }[]; edm: string; locking: string; switched: string;
  };
  air_graph: Record<string, string[]>; cylinders_vented: string[]; logic_states: number;
  parts: CadPart[]; notes: string[];
}

export interface SagRow {
  member: string; carries: string; case: string; F_N: number; L_mm: number; section: string;
  E_MPa: number; I_mm4: number; sag_mm: number; limit_mm: number; ok: boolean;
}
export interface UpgradeMetrics {
  compressors: number; air_hose_m: number; cable_m: number; cables: number; hoses: number; vgr_stations: number;
}
export interface UpgradeDoc {
  name: string;
  parts: CadPart[];
  sag_before: SagRow[];
  report: {
    sag: SagRow[];
    nests: { nest: string; at: [number, number]; swivel: number; reach: number;
             reach_margin_mm: number; swivel_margin_deg: number }[];
    corner: { rect: [number, number, number, number]; area_m2: number; used_m2: number };
  };
  buffer_tour: PlanKey[];
  proofs: string[];
  metrics: { before: UpgradeMetrics | null; after: UpgradeMetrics };
  guides?: { module: string; host: string; guest: string; kind: string; clearance_mm: number }[];
  precise?: { file: string; generator: string; rich: string[]; rule: string };
  components?: { id: string; ft: string; size: string; source: string }[];
  scale_note?: string;
}

/** One waypoint of the VGR tour proven by stf-cad/hbw/vgr_path.py. */
export interface PlanKey {
  sw: number; rr: number; pz: number; compress: number;
  cup: boolean; carry: string | null; station: string | null; say: string;
}

/** The machine the twin shows: Upgrade 12, which contains every upgrade before it. */
export const MACHINE_FILE = "hbw_parts_up12.json";

// A JSON from an older export is worse than none: it renders half a machine or
// crashes the Canvas. These are the blocks the 3D view cannot do without.
const NEED: (keyof CadDoc)[] = ["parts", "joints", "slots", "moulds", "factory", "vgr", "oven", "sorting", "pipeline", "plc", "wiring"];

export function useCadDoc(file = MACHINE_FILE): { doc: CadDoc | null; err: string | null } {
  const { data, error } = useJson<CadDoc>(file);
  const run = "STF_VARIANT=up12 python3 hbw_export.py";
  if (error) return { doc: null, err: `${file} missing - run \`${run}\` in stf-cad/hbw` };
  if (!data) return { doc: null, err: null };
  const missing = NEED.filter((k) => data[k] === undefined);
  return missing.length
    ? { doc: null, err: `${file} is from an older export (no ${missing.join(", ")}). Re-run \`${run}\` in stf-cad/hbw.` }
    : { doc: data, err: null };
}
