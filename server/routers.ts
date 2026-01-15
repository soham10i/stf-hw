import { COOKIE_NAME } from "@shared/const";
import { TRPCError } from "@trpc/server";
import { z } from "zod";
import { nanoid } from "nanoid";
import { getSessionCookieOptions } from "./_core/cookies";
import { systemRouter } from "./_core/systemRouter";
import { publicProcedure, protectedProcedure, router } from "./_core/trpc";
import { notifyOwner } from "./_core/notification";
import {
  getAllCarriers,
  getCarrierById,
  createCarrier,
  updateCarrier,
  getAvailableCarrier,
  getAllCookies,
  getCookieByBatchUuid,
  createCookie,
  updateCookie,
  getCookiesByStatus,
  getAllInventorySlots,
  getInventorySlotByName,
  updateInventorySlot,
  getEmptySlot,
  getInventoryWithDetails,
  initializeInventorySlots,
  getAllHardwareStates,
  getHardwareState,
  upsertHardwareState,
  resetAllHardwarePositions,
  initializeHardwareStates,
  insertTelemetry,
  getTelemetryHistory,
  getTelemetryInRange,
  insertEnergyLog,
  getEnergyLogs,
  getTotalEnergyConsumed,
  insertAlert,
  getRecentAlerts,
  getUnacknowledgedAlerts,
  acknowledgeAlert,
  getAlertsByType,
  insertCommand,
  updateCommandStatus,
  getRecentCommands,
  getPendingCommands,
  getInventoryStats,
  getCookieStats,
  getSystemHealth,
} from "./db";
import { SLOT_COORDINATES, INVENTORY_THRESHOLDS } from "../shared/stf-types";

export const appRouter = router({
  system: systemRouter,

  auth: router({
    me: publicProcedure.query((opts) => opts.ctx.user),
    logout: publicProcedure.mutation(({ ctx }) => {
      const cookieOptions = getSessionCookieOptions(ctx.req);
      ctx.res.clearCookie(COOKIE_NAME, { ...cookieOptions, maxAge: -1 });
      return { success: true } as const;
    }),
  }),

  // ============ INVENTORY MANAGEMENT ============
  inventory: router({
    // Get all inventory slots with carrier and cookie details
    list: publicProcedure.query(async () => {
      return getInventoryWithDetails();
    }),

    // Get a specific slot
    getSlot: publicProcedure.input(z.object({ slotName: z.string() })).query(async ({ input }) => {
      const slot = await getInventorySlotByName(input.slotName);
      if (!slot) {
        throw new TRPCError({ code: "NOT_FOUND", message: "Slot not found" });
      }
      return slot;
    }),

    // Get inventory statistics
    stats: publicProcedure.query(async () => {
      const inventoryStats = await getInventoryStats();
      const cookieStats = await getCookieStats();
      return { inventory: inventoryStats, cookies: cookieStats };
    }),

    // Initialize inventory slots (admin only)
    initialize: protectedProcedure.mutation(async () => {
      await initializeInventorySlots();
      return { success: true, message: "Inventory slots initialized" };
    }),
  }),

  // ============ CARRIER MANAGEMENT ============
  carriers: router({
    list: publicProcedure.query(async () => {
      return getAllCarriers();
    }),

    get: publicProcedure.input(z.object({ id: z.number() })).query(async ({ input }) => {
      const carrier = await getCarrierById(input.id);
      if (!carrier) {
        throw new TRPCError({ code: "NOT_FOUND", message: "Carrier not found" });
      }
      return carrier;
    }),

    create: protectedProcedure
      .input(z.object({ currentZone: z.string().optional() }))
      .mutation(async ({ input }) => {
        return createCarrier({ currentZone: input.currentZone || "HBW", isLocked: false });
      }),

    updateZone: protectedProcedure
      .input(z.object({ id: z.number(), zone: z.string() }))
      .mutation(async ({ input }) => {
        await updateCarrier(input.id, { currentZone: input.zone });
        return { success: true };
      }),

    lock: protectedProcedure.input(z.object({ id: z.number() })).mutation(async ({ input }) => {
      await updateCarrier(input.id, { isLocked: true });
      return { success: true };
    }),

    unlock: protectedProcedure.input(z.object({ id: z.number() })).mutation(async ({ input }) => {
      await updateCarrier(input.id, { isLocked: false });
      return { success: true };
    }),
  }),

  // ============ COOKIE (PRODUCT) MANAGEMENT ============
  cookies: router({
    list: publicProcedure.query(async () => {
      return getAllCookies();
    }),

    get: publicProcedure.input(z.object({ batchUuid: z.string() })).query(async ({ input }) => {
      const cookie = await getCookieByBatchUuid(input.batchUuid);
      if (!cookie) {
        throw new TRPCError({ code: "NOT_FOUND", message: "Cookie not found" });
      }
      return cookie;
    }),

    byStatus: publicProcedure
      .input(z.object({ status: z.enum(["BAKING", "STORED", "SHIPPED"]) }))
      .query(async ({ input }) => {
        return getCookiesByStatus(input.status);
      }),
  }),

  // ============ ORDER MANAGEMENT ============
  orders: router({
    // Create a new cookie order
    create: protectedProcedure
      .input(
        z.object({
          flavor: z.enum(["CHOCO", "VANILLA", "STRAWBERRY"]),
        })
      )
      .mutation(async ({ input, ctx }) => {
        // Find an available carrier
        const carrier = await getAvailableCarrier();
        if (!carrier) {
          // Create a new carrier if none available
          const newCarrier = await createCarrier({ currentZone: "HBW", isLocked: false });

          // Create the cookie
          const batchUuid = nanoid(12);
          const expiryDate = new Date();
          expiryDate.setDate(expiryDate.getDate() + 30); // 30 days expiry

          const cookie = await createCookie({
            batchUuid,
            carrierId: newCarrier.id,
            flavor: input.flavor,
            expiryDate,
            status: "BAKING",
          });

          // Log the command
          await insertCommand({
            commandType: "CREATE_ORDER",
            targetDevice: "SYSTEM",
            payload: JSON.stringify({ flavor: input.flavor, batchUuid }),
            status: "COMPLETED",
            issuedBy: ctx.user.id,
          });

          return { success: true, batchUuid, carrierId: newCarrier.id };
        }

        // Lock the carrier
        await updateCarrier(carrier.id, { isLocked: true });

        // Create the cookie
        const batchUuid = nanoid(12);
        const expiryDate = new Date();
        expiryDate.setDate(expiryDate.getDate() + 30);

        await createCookie({
          batchUuid,
          carrierId: carrier.id,
          flavor: input.flavor,
          expiryDate,
          status: "BAKING",
        });

        // Log the command
        await insertCommand({
          commandType: "CREATE_ORDER",
          targetDevice: "SYSTEM",
          payload: JSON.stringify({ flavor: input.flavor, batchUuid }),
          status: "COMPLETED",
          issuedBy: ctx.user.id,
        });

        return { success: true, batchUuid, carrierId: carrier.id };
      }),

    // Store a cookie in a slot
    store: protectedProcedure
      .input(
        z.object({
          batchUuid: z.string(),
          slotName: z.string().optional(),
        })
      )
      .mutation(async ({ input, ctx }) => {
        const cookie = await getCookieByBatchUuid(input.batchUuid);
        if (!cookie) {
          throw new TRPCError({ code: "NOT_FOUND", message: "Cookie not found" });
        }

        if (!cookie.carrierId) {
          throw new TRPCError({ code: "BAD_REQUEST", message: "Cookie has no carrier assigned" });
        }

        // Find empty slot
        let slot;
        if (input.slotName) {
          slot = await getInventorySlotByName(input.slotName);
          if (!slot) {
            throw new TRPCError({ code: "NOT_FOUND", message: "Slot not found" });
          }
          if (slot.carrierId) {
            throw new TRPCError({ code: "BAD_REQUEST", message: "Slot is already occupied" });
          }
        } else {
          slot = await getEmptySlot();
          if (!slot) {
            // Check inventory threshold and send alert
            const stats = await getInventoryStats();
            if (stats.empty <= INVENTORY_THRESHOLDS.CRITICAL_STOCK) {
              await insertAlert({
                alertType: "INVENTORY_THRESHOLD",
                severity: "CRITICAL",
                message: "Warehouse is full! No empty slots available.",
                details: JSON.stringify(stats),
              });
              await notifyOwner({
                title: "🚨 Critical: Warehouse Full",
                content: `The warehouse has no empty slots. Current status: ${stats.occupied}/${stats.total} slots occupied.`,
              });
            }
            throw new TRPCError({ code: "BAD_REQUEST", message: "No empty slots available" });
          }
        }

        // Update slot with carrier
        await updateInventorySlot(slot.slotName, { carrierId: cookie.carrierId });

        // Update cookie status
        await updateCookie(input.batchUuid, { status: "STORED" });

        // Update carrier zone
        await updateCarrier(cookie.carrierId, { currentZone: "HBW", isLocked: false });

        // Log the command
        await insertCommand({
          commandType: "STORE",
          targetDevice: "HBW",
          payload: JSON.stringify({ slotName: slot.slotName, batchUuid: input.batchUuid }),
          status: "COMPLETED",
          issuedBy: ctx.user.id,
        });

        // Check inventory threshold
        const stats = await getInventoryStats();
        if (stats.empty <= INVENTORY_THRESHOLDS.LOW_STOCK) {
          await insertAlert({
            alertType: "INVENTORY_THRESHOLD",
            severity: "WARNING",
            message: `Low inventory space: only ${stats.empty} slots remaining`,
            details: JSON.stringify(stats),
          });
        }

        return { success: true, slotName: slot.slotName };
      }),

    // Retrieve a cookie from a slot
    retrieve: protectedProcedure
      .input(z.object({ slotName: z.string() }))
      .mutation(async ({ input, ctx }) => {
        const slot = await getInventorySlotByName(input.slotName);
        if (!slot) {
          throw new TRPCError({ code: "NOT_FOUND", message: "Slot not found" });
        }

        if (!slot.carrierId) {
          throw new TRPCError({ code: "BAD_REQUEST", message: "Slot is empty" });
        }

        const carrier = await getCarrierById(slot.carrierId);
        if (!carrier) {
          throw new TRPCError({ code: "NOT_FOUND", message: "Carrier not found" });
        }

        // Check for collision prevention (safety interlock)
        const hbwState = await getHardwareState("HBW");
        if (hbwState && hbwState.status === "MOVING") {
          await insertAlert({
            alertType: "COLLISION_PREVENTION",
            severity: "WARNING",
            deviceId: "HBW",
            message: "Retrieve blocked: HBW is currently moving",
            details: JSON.stringify({ slotName: input.slotName, hbwStatus: hbwState.status }),
          });
          throw new TRPCError({
            code: "PRECONDITION_FAILED",
            message: "Cannot retrieve: HBW is currently moving. Safety interlock active.",
          });
        }

        // Lock the carrier during operation
        await updateCarrier(slot.carrierId, { isLocked: true, currentZone: "CONVEYOR" });

        // Clear the slot
        await updateInventorySlot(input.slotName, { carrierId: null });

        // Log the command
        await insertCommand({
          commandType: "RETRIEVE",
          targetDevice: "HBW",
          payload: JSON.stringify({ slotName: input.slotName, targetX: slot.xPos, targetY: slot.yPos }),
          status: "PENDING",
          issuedBy: ctx.user.id,
        });

        return {
          success: true,
          carrierId: slot.carrierId,
          targetPosition: { x: slot.xPos, y: slot.yPos },
        };
      }),

    // Ship a cookie (mark as shipped)
    ship: protectedProcedure
      .input(z.object({ batchUuid: z.string() }))
      .mutation(async ({ input, ctx }) => {
        const cookie = await getCookieByBatchUuid(input.batchUuid);
        if (!cookie) {
          throw new TRPCError({ code: "NOT_FOUND", message: "Cookie not found" });
        }

        await updateCookie(input.batchUuid, { status: "SHIPPED" });

        if (cookie.carrierId) {
          await updateCarrier(cookie.carrierId, { isLocked: false, currentZone: "VGR" });
        }

        await insertCommand({
          commandType: "SHIP",
          targetDevice: "VGR",
          payload: JSON.stringify({ batchUuid: input.batchUuid }),
          status: "COMPLETED",
          issuedBy: ctx.user.id,
        });

        return { success: true };
      }),
  }),

  // ============ HARDWARE STATE MANAGEMENT ============
  hardware: router({
    // Get all hardware states
    list: publicProcedure.query(async () => {
      return getAllHardwareStates();
    }),

    // Get specific device state
    get: publicProcedure.input(z.object({ deviceId: z.string() })).query(async ({ input }) => {
      const state = await getHardwareState(input.deviceId);
      if (!state) {
        throw new TRPCError({ code: "NOT_FOUND", message: "Device not found" });
      }
      return state;
    }),

    // Update hardware state (from simulation)
    updateState: publicProcedure
      .input(
        z.object({
          deviceId: z.string(),
          currentPositionX: z.number(),
          currentPositionY: z.number(),
          targetPositionX: z.number().nullable().optional(),
          targetPositionY: z.number().nullable().optional(),
          status: z.enum(["IDLE", "MOVING", "ERROR", "MAINTENANCE"]),
        })
      )
      .mutation(async ({ input }) => {
        await upsertHardwareState({
          deviceId: input.deviceId,
          currentPositionX: input.currentPositionX,
          currentPositionY: input.currentPositionY,
          targetPositionX: input.targetPositionX ?? null,
          targetPositionY: input.targetPositionY ?? null,
          status: input.status,
        });

        // Check for error status and create alert
        if (input.status === "ERROR") {
          await insertAlert({
            alertType: "HARDWARE_ERROR",
            severity: "CRITICAL",
            deviceId: input.deviceId,
            message: `Hardware error detected on device ${input.deviceId}`,
            details: JSON.stringify(input),
          });

          await notifyOwner({
            title: "🚨 Hardware Error Detected",
            content: `Device ${input.deviceId} has reported an error. Immediate attention required.`,
          });
        }

        return { success: true };
      }),

    // Reset all hardware positions
    reset: protectedProcedure.mutation(async ({ ctx }) => {
      await resetAllHardwarePositions();

      await insertCommand({
        commandType: "RESET",
        targetDevice: "ALL",
        payload: null,
        status: "COMPLETED",
        issuedBy: ctx.user.id,
      });

      return { success: true, message: "All hardware positions reset to 0" };
    }),

    // Initialize hardware states
    initialize: protectedProcedure.mutation(async () => {
      await initializeHardwareStates();
      return { success: true, message: "Hardware states initialized" };
    }),

    // Get system health
    health: publicProcedure.query(async () => {
      return getSystemHealth();
    }),

    // Send move command to HBW
    moveHBW: protectedProcedure
      .input(
        z.object({
          targetX: z.number(),
          targetY: z.number(),
        })
      )
      .mutation(async ({ input, ctx }) => {
        // Check if HBW is already moving
        const hbwState = await getHardwareState("HBW");
        if (hbwState && hbwState.status === "MOVING") {
          throw new TRPCError({
            code: "PRECONDITION_FAILED",
            message: "HBW is already moving",
          });
        }

        // Update target position
        await upsertHardwareState({
          deviceId: "HBW",
          currentPositionX: hbwState?.currentPositionX ?? 0,
          currentPositionY: hbwState?.currentPositionY ?? 0,
          targetPositionX: input.targetX,
          targetPositionY: input.targetY,
          status: "MOVING",
        });

        // Log the command
        const command = await insertCommand({
          commandType: "MOVE",
          targetDevice: "HBW",
          payload: JSON.stringify({ targetX: input.targetX, targetY: input.targetY }),
          status: "EXECUTING",
          issuedBy: ctx.user.id,
        });

        return { success: true, commandId: command.id };
      }),

    // Move HBW to a specific slot
    moveToSlot: protectedProcedure
      .input(z.object({ slotName: z.string() }))
      .mutation(async ({ input, ctx }) => {
        const coords = SLOT_COORDINATES[input.slotName];
        if (!coords) {
          throw new TRPCError({ code: "NOT_FOUND", message: "Invalid slot name" });
        }

        const hbwState = await getHardwareState("HBW");
        if (hbwState && hbwState.status === "MOVING") {
          throw new TRPCError({
            code: "PRECONDITION_FAILED",
            message: "HBW is already moving",
          });
        }

        await upsertHardwareState({
          deviceId: "HBW",
          currentPositionX: hbwState?.currentPositionX ?? 0,
          currentPositionY: hbwState?.currentPositionY ?? 0,
          targetPositionX: coords.x,
          targetPositionY: coords.y,
          status: "MOVING",
        });

        await insertCommand({
          commandType: "MOVE_TO_SLOT",
          targetDevice: "HBW",
          payload: JSON.stringify({ slotName: input.slotName, ...coords }),
          status: "EXECUTING",
          issuedBy: ctx.user.id,
        });

        return { success: true, targetPosition: coords };
      }),
  }),

  // ============ TELEMETRY & ANALYTICS ============
  telemetry: router({
    // Record telemetry data
    record: publicProcedure
      .input(
        z.object({
          deviceId: z.string(),
          positionX: z.number(),
          positionY: z.number(),
          isMoving: z.boolean(),
          speed: z.number().optional(),
        })
      )
      .mutation(async ({ input }) => {
        await insertTelemetry({
          deviceId: input.deviceId,
          positionX: input.positionX,
          positionY: input.positionY,
          isMoving: input.isMoving,
          speed: input.speed ?? null,
        });
        return { success: true };
      }),

    // Get telemetry history
    history: publicProcedure
      .input(
        z.object({
          deviceId: z.string(),
          limit: z.number().optional().default(100),
        })
      )
      .query(async ({ input }) => {
        return getTelemetryHistory(input.deviceId, input.limit);
      }),

    // Get telemetry in time range
    range: publicProcedure
      .input(
        z.object({
          deviceId: z.string(),
          startTime: z.date(),
          endTime: z.date(),
        })
      )
      .query(async ({ input }) => {
        return getTelemetryInRange(input.deviceId, input.startTime, input.endTime);
      }),
  }),

  // ============ ENERGY MONITORING ============
  energy: router({
    // Record energy consumption
    record: publicProcedure
      .input(
        z.object({
          deviceId: z.string(),
          energyConsumed: z.number(),
          voltage: z.number().optional(),
          current: z.number().optional(),
          powerFactor: z.number().optional(),
        })
      )
      .mutation(async ({ input }) => {
        await insertEnergyLog({
          deviceId: input.deviceId,
          energyConsumed: input.energyConsumed,
          voltage: input.voltage ?? null,
          current: input.current ?? null,
          powerFactor: input.powerFactor ?? null,
        });

        // Check for high energy consumption (maintenance alert)
        if (input.energyConsumed > 100) {
          await insertAlert({
            alertType: "MAINTENANCE_REQUIRED",
            severity: "WARNING",
            deviceId: input.deviceId,
            message: `High energy consumption detected on ${input.deviceId}: ${input.energyConsumed}W`,
            details: JSON.stringify(input),
          });
        }

        return { success: true };
      }),

    // Get energy logs
    history: publicProcedure
      .input(
        z.object({
          deviceId: z.string(),
          limit: z.number().optional().default(100),
        })
      )
      .query(async ({ input }) => {
        return getEnergyLogs(input.deviceId, input.limit);
      }),

    // Get total energy consumed
    total: publicProcedure
      .input(
        z.object({
          deviceId: z.string(),
          startTime: z.date(),
          endTime: z.date(),
        })
      )
      .query(async ({ input }) => {
        const total = await getTotalEnergyConsumed(input.deviceId, input.startTime, input.endTime);
        return { deviceId: input.deviceId, totalEnergy: total };
      }),
  }),

  // ============ ALERTS & NOTIFICATIONS ============
  alerts: router({
    // Get recent alerts
    list: publicProcedure
      .input(z.object({ limit: z.number().optional().default(50) }))
      .query(async ({ input }) => {
        return getRecentAlerts(input.limit);
      }),

    // Get unacknowledged alerts
    unacknowledged: publicProcedure.query(async () => {
      return getUnacknowledgedAlerts();
    }),

    // Acknowledge an alert
    acknowledge: protectedProcedure
      .input(z.object({ alertId: z.number() }))
      .mutation(async ({ input, ctx }) => {
        await acknowledgeAlert(input.alertId, ctx.user.id);
        return { success: true };
      }),

    // Get alerts by type
    byType: publicProcedure
      .input(
        z.object({
          alertType: z.enum([
            "HARDWARE_ERROR",
            "COLLISION_PREVENTION",
            "INVENTORY_THRESHOLD",
            "MAINTENANCE_REQUIRED",
            "SYSTEM_WARNING",
          ]),
        })
      )
      .query(async ({ input }) => {
        return getAlertsByType(input.alertType);
      }),

    // Create a manual alert
    create: protectedProcedure
      .input(
        z.object({
          alertType: z.enum([
            "HARDWARE_ERROR",
            "COLLISION_PREVENTION",
            "INVENTORY_THRESHOLD",
            "MAINTENANCE_REQUIRED",
            "SYSTEM_WARNING",
          ]),
          severity: z.enum(["INFO", "WARNING", "CRITICAL"]),
          deviceId: z.string().optional(),
          message: z.string(),
          details: z.string().optional(),
        })
      )
      .mutation(async ({ input }) => {
        const alert = await insertAlert({
          alertType: input.alertType,
          severity: input.severity,
          deviceId: input.deviceId ?? null,
          message: input.message,
          details: input.details ?? null,
        });

        // Notify owner for critical alerts
        if (input.severity === "CRITICAL") {
          await notifyOwner({
            title: `🚨 Critical Alert: ${input.alertType}`,
            content: input.message,
          });
        }

        return alert;
      }),
  }),

  // ============ COMMAND HISTORY ============
  commands: router({
    // Get recent commands
    list: publicProcedure
      .input(z.object({ limit: z.number().optional().default(50) }))
      .query(async ({ input }) => {
        return getRecentCommands(input.limit);
      }),

    // Get pending commands
    pending: publicProcedure.query(async () => {
      return getPendingCommands();
    }),

    // Update command status
    updateStatus: publicProcedure
      .input(
        z.object({
          commandId: z.number(),
          status: z.enum(["PENDING", "EXECUTING", "COMPLETED", "FAILED"]),
          errorMessage: z.string().optional(),
        })
      )
      .mutation(async ({ input }) => {
        await updateCommandStatus(input.commandId, input.status, input.errorMessage);
        return { success: true };
      }),
  }),

  // ============ MAINTENANCE OPERATIONS ============
  maintenance: router({
    // Full system reset
    reset: protectedProcedure.mutation(async ({ ctx }) => {
      await resetAllHardwarePositions();

      await insertCommand({
        commandType: "MAINTENANCE_RESET",
        targetDevice: "ALL",
        payload: null,
        status: "COMPLETED",
        issuedBy: ctx.user.id,
      });

      await insertAlert({
        alertType: "SYSTEM_WARNING",
        severity: "INFO",
        message: "System maintenance reset performed",
        details: JSON.stringify({ performedBy: ctx.user.id, timestamp: new Date() }),
      });

      return { success: true, message: "System reset complete" };
    }),

    // Initialize all systems
    initialize: protectedProcedure.mutation(async ({ ctx }) => {
      await initializeInventorySlots();
      await initializeHardwareStates();

      await insertCommand({
        commandType: "INITIALIZE",
        targetDevice: "ALL",
        payload: null,
        status: "COMPLETED",
        issuedBy: ctx.user.id,
      });

      return { success: true, message: "All systems initialized" };
    }),
  }),

  // ============ DASHBOARD DATA ============
  dashboard: router({
    // Get all data needed for dashboard in one call
    overview: publicProcedure.query(async () => {
      const [inventory, hardware, alerts, stats, health, commands] = await Promise.all([
        getInventoryWithDetails(),
        getAllHardwareStates(),
        getUnacknowledgedAlerts(),
        getInventoryStats(),
        getSystemHealth(),
        getRecentCommands(10),
      ]);

      const cookieStats = await getCookieStats();

      return {
        inventory,
        hardware,
        alerts,
        stats: {
          inventory: stats,
          cookies: cookieStats,
        },
        health,
        recentCommands: commands,
      };
    }),
  }),
});

export type AppRouter = typeof appRouter;
