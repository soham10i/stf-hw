import {
  int,
  mysqlEnum,
  mysqlTable,
  text,
  timestamp,
  varchar,
  boolean,
  float,
  datetime,
  bigint,
  index,
} from "drizzle-orm/mysql-core";

/**
 * Core user table backing auth flow.
 */
export const users = mysqlTable("users", {
  id: int("id").autoincrement().primaryKey(),
  openId: varchar("openId", { length: 64 }).notNull().unique(),
  name: text("name"),
  email: varchar("email", { length: 320 }),
  loginMethod: varchar("loginMethod", { length: 64 }),
  role: mysqlEnum("role", ["user", "admin"]).default("user").notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  lastSignedIn: timestamp("lastSignedIn").defaultNow().notNull(),
});

export type User = typeof users.$inferSelect;
export type InsertUser = typeof users.$inferInsert;

/**
 * Carrier - The physical mold/container that holds cookies
 */
export const carriers = mysqlTable("carriers", {
  id: int("id").autoincrement().primaryKey(),
  currentZone: varchar("currentZone", { length: 32 }).notNull().default("HBW"),
  isLocked: boolean("isLocked").notNull().default(false),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
});

export type Carrier = typeof carriers.$inferSelect;
export type InsertCarrier = typeof carriers.$inferInsert;

/**
 * Cookie - The product being manufactured/stored
 */
export const cookies = mysqlTable("cookies", {
  batchUuid: varchar("batchUuid", { length: 64 }).primaryKey(),
  carrierId: int("carrierId").references(() => carriers.id),
  flavor: mysqlEnum("flavor", ["CHOCO", "VANILLA", "STRAWBERRY"]).notNull(),
  expiryDate: datetime("expiryDate").notNull(),
  status: mysqlEnum("status", ["BAKING", "STORED", "SHIPPED"]).notNull().default("BAKING"),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
});

export type Cookie = typeof cookies.$inferSelect;
export type InsertCookie = typeof cookies.$inferInsert;

/**
 * InventorySlot - Physical shelf positions in the warehouse
 */
export const inventorySlots = mysqlTable("inventorySlots", {
  slotName: varchar("slotName", { length: 8 }).primaryKey(),
  xPos: int("xPos").notNull(),
  yPos: int("yPos").notNull(),
  carrierId: int("carrierId").references(() => carriers.id),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
});

export type InventorySlot = typeof inventorySlots.$inferSelect;
export type InsertInventorySlot = typeof inventorySlots.$inferInsert;

/**
 * HardwareState - Current telemetry state of hardware devices
 */
export const hardwareStates = mysqlTable("hardwareStates", {
  deviceId: varchar("deviceId", { length: 32 }).primaryKey(),
  currentPositionX: float("currentPositionX").notNull().default(0),
  currentPositionY: float("currentPositionY").notNull().default(0),
  targetPositionX: float("targetPositionX"),
  targetPositionY: float("targetPositionY"),
  status: mysqlEnum("status", ["IDLE", "MOVING", "ERROR", "MAINTENANCE"]).notNull().default("IDLE"),
  lastHeartbeat: timestamp("lastHeartbeat").defaultNow().notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
});

export type HardwareState = typeof hardwareStates.$inferSelect;
export type InsertHardwareState = typeof hardwareStates.$inferInsert;

/**
 * TelemetryHistory - Time-series data for trend analysis
 */
export const telemetryHistory = mysqlTable(
  "telemetryHistory",
  {
    id: bigint("id", { mode: "number" }).autoincrement().primaryKey(),
    deviceId: varchar("deviceId", { length: 32 }).notNull(),
    positionX: float("positionX").notNull(),
    positionY: float("positionY").notNull(),
    isMoving: boolean("isMoving").notNull().default(false),
    speed: float("speed"),
    timestamp: timestamp("timestamp").defaultNow().notNull(),
  },
  (table) => [
    index("idx_telemetry_device_time").on(table.deviceId, table.timestamp),
    index("idx_telemetry_timestamp").on(table.timestamp),
  ]
);

export type TelemetryHistory = typeof telemetryHistory.$inferSelect;
export type InsertTelemetryHistory = typeof telemetryHistory.$inferInsert;

/**
 * EnergyLog - Energy consumption tracking for predictive maintenance
 */
export const energyLogs = mysqlTable(
  "energyLogs",
  {
    id: bigint("id", { mode: "number" }).autoincrement().primaryKey(),
    deviceId: varchar("deviceId", { length: 32 }).notNull(),
    energyConsumed: float("energyConsumed").notNull(),
    voltage: float("voltage"),
    current: float("current"),
    powerFactor: float("powerFactor"),
    timestamp: timestamp("timestamp").defaultNow().notNull(),
  },
  (table) => [
    index("idx_energy_device_time").on(table.deviceId, table.timestamp),
    index("idx_energy_timestamp").on(table.timestamp),
  ]
);

export type EnergyLog = typeof energyLogs.$inferSelect;
export type InsertEnergyLog = typeof energyLogs.$inferInsert;

/**
 * AlertLog - Critical events and notifications
 */
export const alertLogs = mysqlTable(
  "alertLogs",
  {
    id: bigint("id", { mode: "number" }).autoincrement().primaryKey(),
    alertType: mysqlEnum("alertType", [
      "HARDWARE_ERROR",
      "COLLISION_PREVENTION",
      "INVENTORY_THRESHOLD",
      "MAINTENANCE_REQUIRED",
      "SYSTEM_WARNING",
    ]).notNull(),
    severity: mysqlEnum("severity", ["INFO", "WARNING", "CRITICAL"]).notNull(),
    deviceId: varchar("deviceId", { length: 32 }),
    message: text("message").notNull(),
    details: text("details"),
    acknowledged: boolean("acknowledged").notNull().default(false),
    acknowledgedBy: int("acknowledgedBy").references(() => users.id),
    acknowledgedAt: timestamp("acknowledgedAt"),
    timestamp: timestamp("timestamp").defaultNow().notNull(),
  },
  (table) => [
    index("idx_alert_type_time").on(table.alertType, table.timestamp),
    index("idx_alert_severity").on(table.severity, table.acknowledged),
  ]
);

export type AlertLog = typeof alertLogs.$inferSelect;
export type InsertAlertLog = typeof alertLogs.$inferInsert;

/**
 * CommandLog - Track all commands sent to hardware
 */
export const commandLogs = mysqlTable(
  "commandLogs",
  {
    id: bigint("id", { mode: "number" }).autoincrement().primaryKey(),
    commandType: varchar("commandType", { length: 64 }).notNull(),
    targetDevice: varchar("targetDevice", { length: 32 }).notNull(),
    payload: text("payload"),
    status: mysqlEnum("status", ["PENDING", "EXECUTING", "COMPLETED", "FAILED"]).notNull().default("PENDING"),
    issuedBy: int("issuedBy").references(() => users.id),
    completedAt: timestamp("completedAt"),
    errorMessage: text("errorMessage"),
    timestamp: timestamp("timestamp").defaultNow().notNull(),
  },
  (table) => [
    index("idx_command_device_time").on(table.targetDevice, table.timestamp),
    index("idx_command_status").on(table.status),
  ]
);

export type CommandLog = typeof commandLogs.$inferSelect;
export type InsertCommandLog = typeof commandLogs.$inferInsert;
