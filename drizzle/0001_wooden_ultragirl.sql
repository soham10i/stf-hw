CREATE TABLE `alertLogs` (
	`id` bigint AUTO_INCREMENT NOT NULL,
	`alertType` enum('HARDWARE_ERROR','COLLISION_PREVENTION','INVENTORY_THRESHOLD','MAINTENANCE_REQUIRED','SYSTEM_WARNING') NOT NULL,
	`severity` enum('INFO','WARNING','CRITICAL') NOT NULL,
	`deviceId` varchar(32),
	`message` text NOT NULL,
	`details` text,
	`acknowledged` boolean NOT NULL DEFAULT false,
	`acknowledgedBy` int,
	`acknowledgedAt` timestamp,
	`timestamp` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `alertLogs_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `carriers` (
	`id` int AUTO_INCREMENT NOT NULL,
	`currentZone` varchar(32) NOT NULL DEFAULT 'HBW',
	`isLocked` boolean NOT NULL DEFAULT false,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `carriers_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `commandLogs` (
	`id` bigint AUTO_INCREMENT NOT NULL,
	`commandType` varchar(64) NOT NULL,
	`targetDevice` varchar(32) NOT NULL,
	`payload` text,
	`status` enum('PENDING','EXECUTING','COMPLETED','FAILED') NOT NULL DEFAULT 'PENDING',
	`issuedBy` int,
	`completedAt` timestamp,
	`errorMessage` text,
	`timestamp` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `commandLogs_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `cookies` (
	`batchUuid` varchar(64) NOT NULL,
	`carrierId` int,
	`flavor` enum('CHOCO','VANILLA','STRAWBERRY') NOT NULL,
	`expiryDate` datetime NOT NULL,
	`status` enum('BAKING','STORED','SHIPPED') NOT NULL DEFAULT 'BAKING',
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `cookies_batchUuid` PRIMARY KEY(`batchUuid`)
);
--> statement-breakpoint
CREATE TABLE `energyLogs` (
	`id` bigint AUTO_INCREMENT NOT NULL,
	`deviceId` varchar(32) NOT NULL,
	`energyConsumed` float NOT NULL,
	`voltage` float,
	`current` float,
	`powerFactor` float,
	`timestamp` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `energyLogs_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `hardwareStates` (
	`deviceId` varchar(32) NOT NULL,
	`currentPositionX` float NOT NULL DEFAULT 0,
	`currentPositionY` float NOT NULL DEFAULT 0,
	`targetPositionX` float,
	`targetPositionY` float,
	`status` enum('IDLE','MOVING','ERROR','MAINTENANCE') NOT NULL DEFAULT 'IDLE',
	`lastHeartbeat` timestamp NOT NULL DEFAULT (now()),
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `hardwareStates_deviceId` PRIMARY KEY(`deviceId`)
);
--> statement-breakpoint
CREATE TABLE `inventorySlots` (
	`slotName` varchar(8) NOT NULL,
	`xPos` int NOT NULL,
	`yPos` int NOT NULL,
	`carrierId` int,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `inventorySlots_slotName` PRIMARY KEY(`slotName`)
);
--> statement-breakpoint
CREATE TABLE `telemetryHistory` (
	`id` bigint AUTO_INCREMENT NOT NULL,
	`deviceId` varchar(32) NOT NULL,
	`positionX` float NOT NULL,
	`positionY` float NOT NULL,
	`isMoving` boolean NOT NULL DEFAULT false,
	`speed` float,
	`timestamp` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `telemetryHistory_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
ALTER TABLE `alertLogs` ADD CONSTRAINT `alertLogs_acknowledgedBy_users_id_fk` FOREIGN KEY (`acknowledgedBy`) REFERENCES `users`(`id`) ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE `commandLogs` ADD CONSTRAINT `commandLogs_issuedBy_users_id_fk` FOREIGN KEY (`issuedBy`) REFERENCES `users`(`id`) ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE `cookies` ADD CONSTRAINT `cookies_carrierId_carriers_id_fk` FOREIGN KEY (`carrierId`) REFERENCES `carriers`(`id`) ON DELETE no action ON UPDATE no action;--> statement-breakpoint
ALTER TABLE `inventorySlots` ADD CONSTRAINT `inventorySlots_carrierId_carriers_id_fk` FOREIGN KEY (`carrierId`) REFERENCES `carriers`(`id`) ON DELETE no action ON UPDATE no action;--> statement-breakpoint
CREATE INDEX `idx_alert_type_time` ON `alertLogs` (`alertType`,`timestamp`);--> statement-breakpoint
CREATE INDEX `idx_alert_severity` ON `alertLogs` (`severity`,`acknowledged`);--> statement-breakpoint
CREATE INDEX `idx_command_device_time` ON `commandLogs` (`targetDevice`,`timestamp`);--> statement-breakpoint
CREATE INDEX `idx_command_status` ON `commandLogs` (`status`);--> statement-breakpoint
CREATE INDEX `idx_energy_device_time` ON `energyLogs` (`deviceId`,`timestamp`);--> statement-breakpoint
CREATE INDEX `idx_energy_timestamp` ON `energyLogs` (`timestamp`);--> statement-breakpoint
CREATE INDEX `idx_telemetry_device_time` ON `telemetryHistory` (`deviceId`,`timestamp`);--> statement-breakpoint
CREATE INDEX `idx_telemetry_timestamp` ON `telemetryHistory` (`timestamp`);