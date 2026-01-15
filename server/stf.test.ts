import { describe, expect, it, beforeAll, vi } from "vitest";
import { appRouter } from "./routers";
import type { TrpcContext } from "./_core/context";

// Mock database functions
vi.mock("./db", () => ({
  getDb: vi.fn().mockResolvedValue({}),
  getAllCarriers: vi.fn().mockResolvedValue([
    { id: 1, currentZone: "HBW", isLocked: false },
    { id: 2, currentZone: "CONVEYOR", isLocked: true },
  ]),
  getCarrierById: vi.fn().mockImplementation((id: number) => {
    if (id === 1) return Promise.resolve({ id: 1, currentZone: "HBW", isLocked: false });
    if (id === 2) return Promise.resolve({ id: 2, currentZone: "CONVEYOR", isLocked: true });
    return Promise.resolve(undefined);
  }),
  createCarrier: vi.fn().mockImplementation((data) => Promise.resolve({ id: 3, ...data })),
  updateCarrier: vi.fn().mockResolvedValue(undefined),
  getAvailableCarrier: vi.fn().mockResolvedValue({ id: 1, currentZone: "HBW", isLocked: false }),
  getAllCookies: vi.fn().mockResolvedValue([
    { batchUuid: "test-123", carrierId: 1, flavor: "CHOCO", status: "STORED" },
  ]),
  getCookieByBatchUuid: vi.fn().mockImplementation((uuid: string) => {
    if (uuid === "test-123") {
      return Promise.resolve({ batchUuid: "test-123", carrierId: 1, flavor: "CHOCO", status: "STORED" });
    }
    return Promise.resolve(undefined);
  }),
  createCookie: vi.fn().mockImplementation((data) => Promise.resolve(data)),
  updateCookie: vi.fn().mockResolvedValue(undefined),
  getCookiesByStatus: vi.fn().mockResolvedValue([]),
  getAllInventorySlots: vi.fn().mockResolvedValue([
    { slotName: "A1", xPos: 100, yPos: 100, carrierId: 1 },
    { slotName: "A2", xPos: 200, yPos: 100, carrierId: null },
  ]),
  getInventorySlotByName: vi.fn().mockImplementation((name: string) => {
    if (name === "A1") return Promise.resolve({ slotName: "A1", xPos: 100, yPos: 100, carrierId: 1 });
    if (name === "A2") return Promise.resolve({ slotName: "A2", xPos: 200, yPos: 100, carrierId: null });
    return Promise.resolve(undefined);
  }),
  updateInventorySlot: vi.fn().mockResolvedValue(undefined),
  getEmptySlot: vi.fn().mockResolvedValue({ slotName: "A2", xPos: 200, yPos: 100, carrierId: null }),
  getInventoryWithDetails: vi.fn().mockResolvedValue([
    { slotName: "A1", xPos: 100, yPos: 100, carrierId: 1, carrier: { id: 1 }, cookie: { flavor: "CHOCO" } },
    { slotName: "A2", xPos: 200, yPos: 100, carrierId: null, carrier: null, cookie: null },
  ]),
  initializeInventorySlots: vi.fn().mockResolvedValue(undefined),
  getAllHardwareStates: vi.fn().mockResolvedValue([
    { deviceId: "HBW", currentPositionX: 0, currentPositionY: 0, status: "IDLE" },
  ]),
  getHardwareState: vi.fn().mockImplementation((deviceId: string) => {
    if (deviceId === "HBW") {
      return Promise.resolve({ deviceId: "HBW", currentPositionX: 0, currentPositionY: 0, status: "IDLE" });
    }
    return Promise.resolve(undefined);
  }),
  upsertHardwareState: vi.fn().mockResolvedValue(undefined),
  resetAllHardwarePositions: vi.fn().mockResolvedValue(undefined),
  initializeHardwareStates: vi.fn().mockResolvedValue(undefined),
  insertTelemetry: vi.fn().mockResolvedValue(undefined),
  getTelemetryHistory: vi.fn().mockResolvedValue([]),
  getTelemetryInRange: vi.fn().mockResolvedValue([]),
  insertEnergyLog: vi.fn().mockResolvedValue(undefined),
  getEnergyLogs: vi.fn().mockResolvedValue([]),
  getTotalEnergyConsumed: vi.fn().mockResolvedValue(100),
  insertAlert: vi.fn().mockImplementation((data) => Promise.resolve({ id: 1, ...data })),
  getRecentAlerts: vi.fn().mockResolvedValue([]),
  getUnacknowledgedAlerts: vi.fn().mockResolvedValue([]),
  acknowledgeAlert: vi.fn().mockResolvedValue(undefined),
  getAlertsByType: vi.fn().mockResolvedValue([]),
  insertCommand: vi.fn().mockImplementation((data) => Promise.resolve({ id: 1, ...data })),
  updateCommandStatus: vi.fn().mockResolvedValue(undefined),
  getRecentCommands: vi.fn().mockResolvedValue([]),
  getPendingCommands: vi.fn().mockResolvedValue([]),
  getInventoryStats: vi.fn().mockResolvedValue({ total: 9, occupied: 3, empty: 6 }),
  getCookieStats: vi.fn().mockResolvedValue({ baking: 1, stored: 2, shipped: 1, total: 4 }),
  getSystemHealth: vi.fn().mockResolvedValue({ healthy: true, devices: [] }),
  upsertUser: vi.fn().mockResolvedValue(undefined),
  getUserByOpenId: vi.fn().mockResolvedValue(undefined),
}));

// Mock notification
vi.mock("./_core/notification", () => ({
  notifyOwner: vi.fn().mockResolvedValue(true),
}));

type AuthenticatedUser = NonNullable<TrpcContext["user"]>;

function createPublicContext(): TrpcContext {
  return {
    user: null,
    req: {
      protocol: "https",
      headers: {},
    } as TrpcContext["req"],
    res: {
      clearCookie: vi.fn(),
    } as unknown as TrpcContext["res"],
  };
}

function createAuthContext(): TrpcContext {
  const user: AuthenticatedUser = {
    id: 1,
    openId: "test-user",
    email: "test@example.com",
    name: "Test User",
    loginMethod: "manus",
    role: "admin",
    createdAt: new Date(),
    updatedAt: new Date(),
    lastSignedIn: new Date(),
  };

  return {
    user,
    req: {
      protocol: "https",
      headers: {},
    } as TrpcContext["req"],
    res: {
      clearCookie: vi.fn(),
    } as unknown as TrpcContext["res"],
  };
}

describe("STF Digital Twin - Inventory Router", () => {
  it("should list all inventory slots with details", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.inventory.list();

    expect(result).toBeDefined();
    expect(Array.isArray(result)).toBe(true);
    expect(result.length).toBeGreaterThan(0);
  });

  it("should get inventory statistics", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.inventory.stats();

    expect(result).toBeDefined();
    expect(result.inventory).toBeDefined();
    expect(result.inventory.total).toBe(9);
    expect(result.inventory.occupied).toBe(3);
    expect(result.inventory.empty).toBe(6);
    expect(result.cookies).toBeDefined();
  });

  it("should initialize inventory slots when authenticated", async () => {
    const ctx = createAuthContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.inventory.initialize();

    expect(result.success).toBe(true);
    expect(result.message).toBe("Inventory slots initialized");
  });
});

describe("STF Digital Twin - Carriers Router", () => {
  it("should list all carriers", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.carriers.list();

    expect(result).toBeDefined();
    expect(Array.isArray(result)).toBe(true);
    expect(result.length).toBe(2);
  });

  it("should get a specific carrier", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.carriers.get({ id: 1 });

    expect(result).toBeDefined();
    expect(result.id).toBe(1);
    expect(result.currentZone).toBe("HBW");
  });

  it("should create a new carrier when authenticated", async () => {
    const ctx = createAuthContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.carriers.create({ currentZone: "VGR" });

    expect(result).toBeDefined();
    expect(result.id).toBe(3);
    expect(result.currentZone).toBe("VGR");
  });
});

describe("STF Digital Twin - Hardware Router", () => {
  it("should list all hardware states", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.hardware.list();

    expect(result).toBeDefined();
    expect(Array.isArray(result)).toBe(true);
  });

  it("should get specific hardware state", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.hardware.get({ deviceId: "HBW" });

    expect(result).toBeDefined();
    expect(result.deviceId).toBe("HBW");
    expect(result.status).toBe("IDLE");
  });

  it("should update hardware state", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.hardware.updateState({
      deviceId: "HBW",
      currentPositionX: 100,
      currentPositionY: 200,
      status: "MOVING",
    });

    expect(result.success).toBe(true);
  });

  it("should reset hardware positions when authenticated", async () => {
    const ctx = createAuthContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.hardware.reset();

    expect(result.success).toBe(true);
    expect(result.message).toBe("All hardware positions reset to 0");
  });

  it("should get system health", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.hardware.health();

    expect(result).toBeDefined();
    expect(result.healthy).toBe(true);
  });
});

describe("STF Digital Twin - Telemetry Router", () => {
  it("should record telemetry data", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.telemetry.record({
      deviceId: "HBW",
      positionX: 150,
      positionY: 250,
      isMoving: true,
      speed: 10,
    });

    expect(result.success).toBe(true);
  });

  it("should get telemetry history", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.telemetry.history({
      deviceId: "HBW",
      limit: 50,
    });

    expect(result).toBeDefined();
    expect(Array.isArray(result)).toBe(true);
  });
});

describe("STF Digital Twin - Energy Router", () => {
  it("should record energy consumption", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.energy.record({
      deviceId: "HBW",
      energyConsumed: 50,
      voltage: 24,
      current: 2.08,
    });

    expect(result.success).toBe(true);
  });

  it("should get total energy consumed", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);

    const now = new Date();
    const oneHourAgo = new Date(now.getTime() - 3600000);

    const result = await caller.energy.total({
      deviceId: "HBW",
      startTime: oneHourAgo,
      endTime: now,
    });

    expect(result).toBeDefined();
    expect(result.deviceId).toBe("HBW");
    expect(result.totalEnergy).toBe(100);
  });
});

describe("STF Digital Twin - Alerts Router", () => {
  it("should get recent alerts", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.alerts.list({ limit: 10 });

    expect(result).toBeDefined();
    expect(Array.isArray(result)).toBe(true);
  });

  it("should get unacknowledged alerts", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.alerts.unacknowledged();

    expect(result).toBeDefined();
    expect(Array.isArray(result)).toBe(true);
  });

  it("should create a manual alert when authenticated", async () => {
    const ctx = createAuthContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.alerts.create({
      alertType: "SYSTEM_WARNING",
      severity: "INFO",
      message: "Test alert message",
    });

    expect(result).toBeDefined();
    expect(result.id).toBe(1);
    expect(result.alertType).toBe("SYSTEM_WARNING");
  });
});

describe("STF Digital Twin - Dashboard Router", () => {
  it("should get dashboard overview data", async () => {
    const ctx = createPublicContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.dashboard.overview();

    expect(result).toBeDefined();
    expect(result.inventory).toBeDefined();
    expect(result.hardware).toBeDefined();
    expect(result.alerts).toBeDefined();
    expect(result.stats).toBeDefined();
    expect(result.health).toBeDefined();
    expect(result.recentCommands).toBeDefined();
  });
});

describe("STF Digital Twin - Maintenance Router", () => {
  it("should reset system when authenticated", async () => {
    const ctx = createAuthContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.maintenance.reset();

    expect(result.success).toBe(true);
    expect(result.message).toBe("System reset complete");
  });

  it("should initialize all systems when authenticated", async () => {
    const ctx = createAuthContext();
    const caller = appRouter.createCaller(ctx);

    const result = await caller.maintenance.initialize();

    expect(result.success).toBe(true);
    expect(result.message).toBe("All systems initialized");
  });
});
