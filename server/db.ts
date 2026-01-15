import { eq, desc, and, gte, lte, isNull, sql } from "drizzle-orm";
import { drizzle } from "drizzle-orm/mysql2";
import {
  InsertUser,
  users,
  carriers,
  cookies,
  inventorySlots,
  hardwareStates,
  telemetryHistory,
  energyLogs,
  alertLogs,
  commandLogs,
  InsertCarrier,
  InsertCookie,
  InsertInventorySlot,
  InsertHardwareState,
  InsertTelemetryHistory,
  InsertEnergyLog,
  InsertAlertLog,
  InsertCommandLog,
} from "../drizzle/schema";
import { ENV } from "./_core/env";
import { SLOT_COORDINATES } from "../shared/stf-types";

let _db: ReturnType<typeof drizzle> | null = null;

export async function getDb() {
  if (!_db && process.env.DATABASE_URL) {
    try {
      _db = drizzle(process.env.DATABASE_URL);
    } catch (error) {
      console.warn("[Database] Failed to connect:", error);
      _db = null;
    }
  }
  return _db;
}

// ============ USER OPERATIONS ============
export async function upsertUser(user: InsertUser): Promise<void> {
  if (!user.openId) {
    throw new Error("User openId is required for upsert");
  }

  const db = await getDb();
  if (!db) {
    console.warn("[Database] Cannot upsert user: database not available");
    return;
  }

  try {
    const values: InsertUser = { openId: user.openId };
    const updateSet: Record<string, unknown> = {};

    const textFields = ["name", "email", "loginMethod"] as const;
    type TextField = (typeof textFields)[number];

    const assignNullable = (field: TextField) => {
      const value = user[field];
      if (value === undefined) return;
      const normalized = value ?? null;
      values[field] = normalized;
      updateSet[field] = normalized;
    };

    textFields.forEach(assignNullable);

    if (user.lastSignedIn !== undefined) {
      values.lastSignedIn = user.lastSignedIn;
      updateSet.lastSignedIn = user.lastSignedIn;
    }
    if (user.role !== undefined) {
      values.role = user.role;
      updateSet.role = user.role;
    } else if (user.openId === ENV.ownerOpenId) {
      values.role = "admin";
      updateSet.role = "admin";
    }

    if (!values.lastSignedIn) {
      values.lastSignedIn = new Date();
    }

    if (Object.keys(updateSet).length === 0) {
      updateSet.lastSignedIn = new Date();
    }

    await db.insert(users).values(values).onDuplicateKeyUpdate({ set: updateSet });
  } catch (error) {
    console.error("[Database] Failed to upsert user:", error);
    throw error;
  }
}

export async function getUserByOpenId(openId: string) {
  const db = await getDb();
  if (!db) return undefined;
  const result = await db.select().from(users).where(eq(users.openId, openId)).limit(1);
  return result.length > 0 ? result[0] : undefined;
}

// ============ CARRIER OPERATIONS ============
export async function getAllCarriers() {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(carriers);
}

export async function getCarrierById(id: number) {
  const db = await getDb();
  if (!db) return undefined;
  const result = await db.select().from(carriers).where(eq(carriers.id, id)).limit(1);
  return result[0];
}

export async function createCarrier(data: Omit<InsertCarrier, "id">) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.insert(carriers).values(data);
  return { id: Number(result[0].insertId), ...data };
}

export async function updateCarrier(id: number, data: Partial<InsertCarrier>) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  await db.update(carriers).set(data).where(eq(carriers.id, id));
}

export async function getAvailableCarrier() {
  const db = await getDb();
  if (!db) return undefined;
  const result = await db
    .select()
    .from(carriers)
    .where(and(eq(carriers.isLocked, false), eq(carriers.currentZone, "HBW")))
    .limit(1);
  return result[0];
}

// ============ COOKIE OPERATIONS ============
export async function getAllCookies() {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(cookies);
}

export async function getCookieByBatchUuid(batchUuid: string) {
  const db = await getDb();
  if (!db) return undefined;
  const result = await db.select().from(cookies).where(eq(cookies.batchUuid, batchUuid)).limit(1);
  return result[0];
}

export async function createCookie(data: InsertCookie) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  await db.insert(cookies).values(data);
  return data;
}

export async function updateCookie(batchUuid: string, data: Partial<InsertCookie>) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  await db.update(cookies).set(data).where(eq(cookies.batchUuid, batchUuid));
}

export async function getCookiesByStatus(status: "BAKING" | "STORED" | "SHIPPED") {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(cookies).where(eq(cookies.status, status));
}

// ============ INVENTORY SLOT OPERATIONS ============
export async function getAllInventorySlots() {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(inventorySlots);
}

export async function getInventorySlotByName(slotName: string) {
  const db = await getDb();
  if (!db) return undefined;
  const result = await db.select().from(inventorySlots).where(eq(inventorySlots.slotName, slotName)).limit(1);
  return result[0];
}

export async function updateInventorySlot(slotName: string, data: Partial<InsertInventorySlot>) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  await db.update(inventorySlots).set(data).where(eq(inventorySlots.slotName, slotName));
}

export async function getEmptySlot() {
  const db = await getDb();
  if (!db) return undefined;
  const result = await db.select().from(inventorySlots).where(isNull(inventorySlots.carrierId)).limit(1);
  return result[0];
}

export async function getInventoryWithDetails() {
  const db = await getDb();
  if (!db) return [];

  const slots = await db.select().from(inventorySlots);
  const allCarriers = await db.select().from(carriers);
  const allCookies = await db.select().from(cookies);

  return slots.map((slot) => {
    const carrier = slot.carrierId ? allCarriers.find((c) => c.id === slot.carrierId) : null;
    const cookie = carrier ? allCookies.find((c) => c.carrierId === carrier.id) : null;
    return { ...slot, carrier, cookie };
  });
}

export async function initializeInventorySlots() {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  for (const [slotName, coords] of Object.entries(SLOT_COORDINATES)) {
    const existing = await getInventorySlotByName(slotName);
    if (!existing) {
      await db.insert(inventorySlots).values({
        slotName,
        xPos: coords.x,
        yPos: coords.y,
        carrierId: null,
      });
    }
  }
}

// ============ HARDWARE STATE OPERATIONS ============
export async function getAllHardwareStates() {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(hardwareStates);
}

export async function getHardwareState(deviceId: string) {
  const db = await getDb();
  if (!db) return undefined;
  const result = await db.select().from(hardwareStates).where(eq(hardwareStates.deviceId, deviceId)).limit(1);
  return result[0];
}

export async function upsertHardwareState(data: InsertHardwareState) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  await db
    .insert(hardwareStates)
    .values(data)
    .onDuplicateKeyUpdate({
      set: {
        currentPositionX: data.currentPositionX,
        currentPositionY: data.currentPositionY,
        targetPositionX: data.targetPositionX,
        targetPositionY: data.targetPositionY,
        status: data.status,
        lastHeartbeat: new Date(),
      },
    });
}

export async function resetAllHardwarePositions() {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  await db.update(hardwareStates).set({
    currentPositionX: 0,
    currentPositionY: 0,
    targetPositionX: null,
    targetPositionY: null,
    status: "IDLE",
  });
}

export async function initializeHardwareStates() {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  const devices = ["HBW", "CONVEYOR", "VGR"];
  for (const deviceId of devices) {
    const existing = await getHardwareState(deviceId);
    if (!existing) {
      await db.insert(hardwareStates).values({
        deviceId,
        currentPositionX: 0,
        currentPositionY: 0,
        status: "IDLE",
      });
    }
  }
}

// ============ TELEMETRY HISTORY OPERATIONS ============
export async function insertTelemetry(data: Omit<InsertTelemetryHistory, "id">) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  await db.insert(telemetryHistory).values(data);
}

export async function getTelemetryHistory(deviceId: string, limit = 100) {
  const db = await getDb();
  if (!db) return [];
  return db
    .select()
    .from(telemetryHistory)
    .where(eq(telemetryHistory.deviceId, deviceId))
    .orderBy(desc(telemetryHistory.timestamp))
    .limit(limit);
}

export async function getTelemetryInRange(deviceId: string, startTime: Date, endTime: Date) {
  const db = await getDb();
  if (!db) return [];
  return db
    .select()
    .from(telemetryHistory)
    .where(
      and(
        eq(telemetryHistory.deviceId, deviceId),
        gte(telemetryHistory.timestamp, startTime),
        lte(telemetryHistory.timestamp, endTime)
      )
    )
    .orderBy(desc(telemetryHistory.timestamp));
}

// ============ ENERGY LOG OPERATIONS ============
export async function insertEnergyLog(data: Omit<InsertEnergyLog, "id">) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  await db.insert(energyLogs).values(data);
}

export async function getEnergyLogs(deviceId: string, limit = 100) {
  const db = await getDb();
  if (!db) return [];
  return db
    .select()
    .from(energyLogs)
    .where(eq(energyLogs.deviceId, deviceId))
    .orderBy(desc(energyLogs.timestamp))
    .limit(limit);
}

export async function getTotalEnergyConsumed(deviceId: string, startTime: Date, endTime: Date) {
  const db = await getDb();
  if (!db) return 0;

  const result = await db
    .select({ total: sql<number>`SUM(${energyLogs.energyConsumed})` })
    .from(energyLogs)
    .where(
      and(eq(energyLogs.deviceId, deviceId), gte(energyLogs.timestamp, startTime), lte(energyLogs.timestamp, endTime))
    );

  return result[0]?.total ?? 0;
}

// ============ ALERT LOG OPERATIONS ============
export async function insertAlert(data: Omit<InsertAlertLog, "id">) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.insert(alertLogs).values(data);
  return { id: Number(result[0].insertId), ...data };
}

export async function getRecentAlerts(limit = 50) {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(alertLogs).orderBy(desc(alertLogs.timestamp)).limit(limit);
}

export async function getUnacknowledgedAlerts() {
  const db = await getDb();
  if (!db) return [];
  return db
    .select()
    .from(alertLogs)
    .where(eq(alertLogs.acknowledged, false))
    .orderBy(desc(alertLogs.timestamp));
}

export async function acknowledgeAlert(alertId: number, userId: number) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  await db
    .update(alertLogs)
    .set({
      acknowledged: true,
      acknowledgedBy: userId,
      acknowledgedAt: new Date(),
    })
    .where(eq(alertLogs.id, alertId));
}

export async function getAlertsByType(
  alertType: "HARDWARE_ERROR" | "COLLISION_PREVENTION" | "INVENTORY_THRESHOLD" | "MAINTENANCE_REQUIRED" | "SYSTEM_WARNING"
) {
  const db = await getDb();
  if (!db) return [];
  return db
    .select()
    .from(alertLogs)
    .where(eq(alertLogs.alertType, alertType))
    .orderBy(desc(alertLogs.timestamp))
    .limit(100);
}

// ============ COMMAND LOG OPERATIONS ============
export async function insertCommand(data: Omit<InsertCommandLog, "id">) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");
  const result = await db.insert(commandLogs).values(data);
  return { id: Number(result[0].insertId), ...data };
}

export async function updateCommandStatus(
  commandId: number,
  status: "PENDING" | "EXECUTING" | "COMPLETED" | "FAILED",
  errorMessage?: string
) {
  const db = await getDb();
  if (!db) throw new Error("Database not available");

  const updateData: Partial<InsertCommandLog> = { status };
  if (status === "COMPLETED" || status === "FAILED") {
    updateData.completedAt = new Date();
  }
  if (errorMessage) {
    updateData.errorMessage = errorMessage;
  }

  await db.update(commandLogs).set(updateData).where(eq(commandLogs.id, commandId));
}

export async function getRecentCommands(limit = 50) {
  const db = await getDb();
  if (!db) return [];
  return db.select().from(commandLogs).orderBy(desc(commandLogs.timestamp)).limit(limit);
}

export async function getPendingCommands() {
  const db = await getDb();
  if (!db) return [];
  return db
    .select()
    .from(commandLogs)
    .where(eq(commandLogs.status, "PENDING"))
    .orderBy(commandLogs.timestamp);
}

// ============ ANALYTICS HELPERS ============
export async function getInventoryStats() {
  const db = await getDb();
  if (!db) return { total: 0, occupied: 0, empty: 0 };

  const slots = await db.select().from(inventorySlots);
  const occupied = slots.filter((s) => s.carrierId !== null).length;

  return {
    total: slots.length,
    occupied,
    empty: slots.length - occupied,
  };
}

export async function getCookieStats() {
  const db = await getDb();
  if (!db) return { baking: 0, stored: 0, shipped: 0, total: 0 };

  const allCookies = await db.select().from(cookies);
  return {
    baking: allCookies.filter((c) => c.status === "BAKING").length,
    stored: allCookies.filter((c) => c.status === "STORED").length,
    shipped: allCookies.filter((c) => c.status === "SHIPPED").length,
    total: allCookies.length,
  };
}

export async function getSystemHealth() {
  const db = await getDb();
  if (!db) return { healthy: false, devices: [] };

  const devices = await db.select().from(hardwareStates);
  const unhealthyDevices = devices.filter((d) => d.status === "ERROR" || d.status === "MAINTENANCE");

  return {
    healthy: unhealthyDevices.length === 0,
    devices: devices.map((d) => ({
      deviceId: d.deviceId,
      status: d.status,
      lastHeartbeat: d.lastHeartbeat,
    })),
  };
}
