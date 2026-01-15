/**
 * STF Digital Twin - Shared Types and Constants
 */

// Coordinate mapping for warehouse slots (3x3 grid)
export const SLOT_COORDINATES: Record<string, { x: number; y: number }> = {
  A1: { x: 100, y: 100 },
  A2: { x: 200, y: 100 },
  A3: { x: 300, y: 100 },
  B1: { x: 100, y: 200 },
  B2: { x: 200, y: 200 },
  B3: { x: 300, y: 200 },
  C1: { x: 100, y: 300 },
  C2: { x: 200, y: 300 },
  C3: { x: 300, y: 300 },
};

export const ALL_SLOT_NAMES = Object.keys(SLOT_COORDINATES);

// Hardware device identifiers
export const DEVICES = {
  HBW_X: "HBW_X",
  HBW_Y: "HBW_Y",
  HBW: "HBW",
  CONVEYOR: "CONVEYOR",
  VGR: "VGR",
} as const;

// Zones in the factory
export const ZONES = {
  HBW: "HBW",
  CONVEYOR: "CONVEYOR",
  VGR: "VGR",
  OVEN: "OVEN",
} as const;

// Cookie flavors with display colors
export const FLAVOR_COLORS: Record<string, string> = {
  CHOCO: "#8B4513",
  VANILLA: "#F5DEB3",
  STRAWBERRY: "#FF69B4",
};

// Status colors for hardware
export const STATUS_COLORS: Record<string, string> = {
  IDLE: "#22c55e",
  MOVING: "#3b82f6",
  ERROR: "#ef4444",
  MAINTENANCE: "#f59e0b",
};

// Alert severity colors
export const SEVERITY_COLORS: Record<string, string> = {
  INFO: "#3b82f6",
  WARNING: "#f59e0b",
  CRITICAL: "#ef4444",
};

// MQTT Topics
export const MQTT_TOPICS = {
  HBW_CMD_MOVE_X: "stf/hbw/cmd/move_x",
  HBW_CMD_MOVE_Y: "stf/hbw/cmd/move_y",
  HBW_STATUS: "stf/hbw/status",
  GLOBAL_REQ_RETRIEVE: "stf/global/req/retrieve",
  GLOBAL_REQ_STORE: "stf/global/req/store",
  CONVEYOR_STATUS: "stf/conveyor/status",
  VGR_STATUS: "stf/vgr/status",
} as const;

// Simulation constants
export const SIMULATION = {
  TICK_RATE_HZ: 10,
  TICK_INTERVAL_MS: 100,
  MOVEMENT_SPEED: 10.0, // units per tick
  MAX_POSITION: 500,
  MIN_POSITION: 0,
} as const;

// Energy calculation constants
export const ENERGY = {
  IDLE_POWER: 5, // Watts
  MOVING_POWER: 50, // Watts
  VOLTAGE: 24, // Volts
} as const;

// Inventory thresholds for alerts
export const INVENTORY_THRESHOLDS = {
  LOW_STOCK: 2,
  CRITICAL_STOCK: 1,
} as const;

// Dashboard refresh interval
export const DASHBOARD_REFRESH_MS = 1000;
