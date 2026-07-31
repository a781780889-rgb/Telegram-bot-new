CREATE TABLE `accounts` (
	`id` int AUTO_INCREMENT NOT NULL,
	`userId` int NOT NULL,
	`name` varchar(255) NOT NULL,
	`username` varchar(255),
	`platform` enum('telegram','whatsapp') NOT NULL,
	`accountType` varchar(50),
	`status` enum('active','inactive','error','paused') NOT NULL DEFAULT 'active',
	`isEnabled` boolean NOT NULL DEFAULT true,
	`credentials` text,
	`lastUsed` timestamp,
	`lastError` text,
	`searchCount` int NOT NULL DEFAULT 0,
	`linksExtracted` int NOT NULL DEFAULT 0,
	`metadata` json,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `accounts_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `audit_logs` (
	`id` int AUTO_INCREMENT NOT NULL,
	`userId` int NOT NULL,
	`action` varchar(100) NOT NULL,
	`section` varchar(100),
	`resourceId` int,
	`resourceType` varchar(50),
	`details` text,
	`result` enum('success','failure') NOT NULL DEFAULT 'success',
	`ipAddress` varchar(45),
	`userAgent` text,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `audit_logs_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `duplicate_links` (
	`id` int AUTO_INCREMENT NOT NULL,
	`userId` int NOT NULL,
	`originalUrl` text NOT NULL,
	`normalizedUrl` text NOT NULL,
	`urlHash` varchar(64) NOT NULL,
	`platform` enum('telegram','whatsapp') NOT NULL,
	`linkType` enum('public_group','private_group','channel','group','unknown'),
	`existingLinkId` int NOT NULL,
	`searchId` int,
	`accountId` int,
	`detectedAt` timestamp NOT NULL DEFAULT (now()),
	`metadata` json,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `duplicate_links_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `exports` (
	`id` int AUTO_INCREMENT NOT NULL,
	`userId` int NOT NULL,
	`searchId` int,
	`fileName` varchar(255) NOT NULL,
	`fileType` enum('txt','csv') NOT NULL,
	`platform` enum('telegram','whatsapp','all') NOT NULL,
	`fileSize` int,
	`fileUrl` text,
	`recordCount` int NOT NULL DEFAULT 0,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`expiresAt` timestamp,
	CONSTRAINT `exports_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `links` (
	`id` int AUTO_INCREMENT NOT NULL,
	`userId` int NOT NULL,
	`platform` enum('telegram','whatsapp') NOT NULL,
	`linkType` enum('public_group','private_group','channel','group','unknown') NOT NULL,
	`originalUrl` text NOT NULL,
	`normalizedUrl` text NOT NULL,
	`urlHash` varchar(64) NOT NULL,
	`title` varchar(500),
	`username` varchar(255),
	`description` text,
	`source` varchar(255),
	`sourceAccount` varchar(255),
	`discoveredAt` timestamp,
	`firstSeenAt` timestamp NOT NULL DEFAULT (now()),
	`lastSeenAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	`searchId` int,
	`status` enum('active','invalid','deleted','unknown') NOT NULL DEFAULT 'active',
	`isDuplicate` boolean NOT NULL DEFAULT false,
	`duplicateCount` int NOT NULL DEFAULT 0,
	`metadata` json,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `links_id` PRIMARY KEY(`id`),
	CONSTRAINT `unique_platform_urlHash` UNIQUE(`userId`,`platform`,`urlHash`)
);
--> statement-breakpoint
CREATE TABLE `notifications` (
	`id` int AUTO_INCREMENT NOT NULL,
	`userId` int NOT NULL,
	`type` enum('search_completed','search_failed','large_discovery','error','info') NOT NULL,
	`title` varchar(255) NOT NULL,
	`message` text NOT NULL,
	`resourceId` int,
	`resourceType` varchar(50),
	`isRead` boolean NOT NULL DEFAULT false,
	`readAt` timestamp,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	CONSTRAINT `notifications_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `searches` (
	`id` int AUTO_INCREMENT NOT NULL,
	`userId` int NOT NULL,
	`searchName` varchar(255),
	`platforms` varchar(100) NOT NULL,
	`searchType` enum('fast','normal','deep') NOT NULL DEFAULT 'normal',
	`dateRange` varchar(50) NOT NULL,
	`startDate` timestamp,
	`endDate` timestamp,
	`accountIds` text,
	`maxResults` int DEFAULT 1000,
	`status` enum('pending','running','paused','completed','failed','cancelled') NOT NULL DEFAULT 'pending',
	`progress` decimal DEFAULT 0,
	`totalFound` int NOT NULL DEFAULT 0,
	`totalNew` int NOT NULL DEFAULT 0,
	`totalDuplicate` int NOT NULL DEFAULT 0,
	`totalInvalid` int NOT NULL DEFAULT 0,
	`telegramCount` int NOT NULL DEFAULT 0,
	`whatsappCount` int NOT NULL DEFAULT 0,
	`startedAt` timestamp,
	`completedAt` timestamp,
	`duration` int,
	`errorMessage` text,
	`settings` json,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `searches_id` PRIMARY KEY(`id`)
);
--> statement-breakpoint
CREATE TABLE `settings` (
	`id` int AUTO_INCREMENT NOT NULL,
	`userId` int NOT NULL,
	`language` varchar(10) NOT NULL DEFAULT 'ar',
	`timezone` varchar(50) NOT NULL DEFAULT 'UTC',
	`defaultSearchType` enum('fast','normal','deep') NOT NULL DEFAULT 'normal',
	`defaultDateRange` varchar(50) NOT NULL DEFAULT 'month',
	`defaultMaxResults` int NOT NULL DEFAULT 1000,
	`enableNotifications` boolean NOT NULL DEFAULT true,
	`enableAutoExport` boolean NOT NULL DEFAULT false,
	`duplicateDetection` boolean NOT NULL DEFAULT true,
	`urlNormalization` boolean NOT NULL DEFAULT true,
	`separateByPlatform` boolean NOT NULL DEFAULT true,
	`metadata` json,
	`createdAt` timestamp NOT NULL DEFAULT (now()),
	`updatedAt` timestamp NOT NULL DEFAULT (now()) ON UPDATE CURRENT_TIMESTAMP,
	CONSTRAINT `settings_id` PRIMARY KEY(`id`),
	CONSTRAINT `settings_userId_unique` UNIQUE(`userId`)
);
--> statement-breakpoint
ALTER TABLE `users` MODIFY COLUMN `role` enum('super_admin','admin','operator','viewer') NOT NULL DEFAULT 'viewer';--> statement-breakpoint
CREATE INDEX `accounts_userId_idx` ON `accounts` (`userId`);--> statement-breakpoint
CREATE INDEX `accounts_platform_idx` ON `accounts` (`platform`);--> statement-breakpoint
CREATE INDEX `accounts_status_idx` ON `accounts` (`status`);--> statement-breakpoint
CREATE INDEX `auditLogs_userId_idx` ON `audit_logs` (`userId`);--> statement-breakpoint
CREATE INDEX `auditLogs_action_idx` ON `audit_logs` (`action`);--> statement-breakpoint
CREATE INDEX `auditLogs_createdAt_idx` ON `audit_logs` (`createdAt`);--> statement-breakpoint
CREATE INDEX `duplicateLinks_userId_idx` ON `duplicate_links` (`userId`);--> statement-breakpoint
CREATE INDEX `duplicateLinks_existingLinkId_idx` ON `duplicate_links` (`existingLinkId`);--> statement-breakpoint
CREATE INDEX `duplicateLinks_searchId_idx` ON `duplicate_links` (`searchId`);--> statement-breakpoint
CREATE INDEX `exports_userId_idx` ON `exports` (`userId`);--> statement-breakpoint
CREATE INDEX `exports_searchId_idx` ON `exports` (`searchId`);--> statement-breakpoint
CREATE INDEX `exports_createdAt_idx` ON `exports` (`createdAt`);--> statement-breakpoint
CREATE INDEX `links_userId_idx` ON `links` (`userId`);--> statement-breakpoint
CREATE INDEX `links_platform_idx` ON `links` (`platform`);--> statement-breakpoint
CREATE INDEX `links_status_idx` ON `links` (`status`);--> statement-breakpoint
CREATE INDEX `links_firstSeenAt_idx` ON `links` (`firstSeenAt`);--> statement-breakpoint
CREATE INDEX `links_urlHash_idx` ON `links` (`urlHash`);--> statement-breakpoint
CREATE INDEX `notifications_userId_idx` ON `notifications` (`userId`);--> statement-breakpoint
CREATE INDEX `notifications_isRead_idx` ON `notifications` (`isRead`);--> statement-breakpoint
CREATE INDEX `notifications_createdAt_idx` ON `notifications` (`createdAt`);--> statement-breakpoint
CREATE INDEX `searches_userId_idx` ON `searches` (`userId`);--> statement-breakpoint
CREATE INDEX `searches_status_idx` ON `searches` (`status`);--> statement-breakpoint
CREATE INDEX `searches_createdAt_idx` ON `searches` (`createdAt`);