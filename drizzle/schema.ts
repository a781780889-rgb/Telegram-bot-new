import {
  int,
  mysqlEnum,
  mysqlTable,
  text,
  timestamp,
  varchar,
  boolean,
  decimal,
  json,
  index,
  unique,
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
  role: mysqlEnum("role", ["super_admin", "admin", "operator", "viewer"]).default("viewer").notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  lastSignedIn: timestamp("lastSignedIn").defaultNow().notNull(),
});

export type User = typeof users.$inferSelect;
export type InsertUser = typeof users.$inferInsert;

/**
 * Telegram/WhatsApp accounts for searching
 */
export const accounts = mysqlTable(
  "accounts",
  {
    id: int("id").autoincrement().primaryKey(),
    userId: int("userId").notNull(),
    name: varchar("name", { length: 255 }).notNull(),
    username: varchar("username", { length: 255 }),
    platform: mysqlEnum("platform", ["telegram", "whatsapp"]).notNull(),
    accountType: varchar("accountType", { length: 50 }), // "personal", "bot", etc
    status: mysqlEnum("status", ["active", "inactive", "error", "paused"]).default("active").notNull(),
    isEnabled: boolean("isEnabled").default(true).notNull(),
    credentials: text("credentials"), // encrypted
    lastUsed: timestamp("lastUsed"),
    lastError: text("lastError"),
    searchCount: int("searchCount").default(0).notNull(),
    linksExtracted: int("linksExtracted").default(0).notNull(),
    metadata: json("metadata"), // store additional info
    createdAt: timestamp("createdAt").defaultNow().notNull(),
    updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  },
  (table) => ({
    userIdIdx: index("accounts_userId_idx").on(table.userId),
    platformIdx: index("accounts_platform_idx").on(table.platform),
    statusIdx: index("accounts_status_idx").on(table.status),
  })
);

export type Account = typeof accounts.$inferSelect;
export type InsertAccount = typeof accounts.$inferInsert;

/**
 * Search jobs/operations
 */
export const searches = mysqlTable(
  "searches",
  {
    id: int("id").autoincrement().primaryKey(),
    userId: int("userId").notNull(),
    searchName: varchar("searchName", { length: 255 }),
    platforms: varchar("platforms", { length: 100 }).notNull(), // "telegram", "whatsapp", "both"
    searchType: mysqlEnum("searchType", ["fast", "normal", "deep"]).default("normal").notNull(),
    dateRange: varchar("dateRange", { length: 50 }).notNull(), // "today", "week", "month", "year", "custom"
    startDate: timestamp("startDate"),
    endDate: timestamp("endDate"),
    accountIds: text("accountIds"), // JSON array of account IDs
    maxResults: int("maxResults").default(1000),
    status: mysqlEnum("status", ["pending", "running", "paused", "completed", "failed", "cancelled"]).default("pending").notNull(),
    progress: decimal("progress", { precision: 5, scale: 2 }).default('0'), // 0-100
    totalFound: int("totalFound").default(0).notNull(),
    totalNew: int("totalNew").default(0).notNull(),
    totalDuplicate: int("totalDuplicate").default(0).notNull(),
    totalInvalid: int("totalInvalid").default(0).notNull(),
    telegramCount: int("telegramCount").default(0).notNull(),
    whatsappCount: int("whatsappCount").default(0).notNull(),
    startedAt: timestamp("startedAt"),
    completedAt: timestamp("completedAt"),
    duration: int("duration"), // in seconds
    errorMessage: text("errorMessage"),
    settings: json("settings"), // store search-specific settings
    createdAt: timestamp("createdAt").defaultNow().notNull(),
    updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  },
  (table) => ({
    userIdIdx: index("searches_userId_idx").on(table.userId),
    statusIdx: index("searches_status_idx").on(table.status),
    createdAtIdx: index("searches_createdAt_idx").on(table.createdAt),
  })
);

export type Search = typeof searches.$inferSelect;
export type InsertSearch = typeof searches.$inferInsert;

/**
 * Links database - main table for storing discovered links
 */
export const links = mysqlTable(
  "links",
  {
    id: int("id").autoincrement().primaryKey(),
    userId: int("userId").notNull(),
    platform: mysqlEnum("platform", ["telegram", "whatsapp"]).notNull(),
    linkType: mysqlEnum("linkType", ["public_group", "private_group", "channel", "group", "unknown"]).notNull(),
    originalUrl: text("originalUrl").notNull(),
    normalizedUrl: text("normalizedUrl").notNull(),
    urlHash: varchar("urlHash", { length: 64 }).notNull(), // SHA256 hash of normalized URL
    title: varchar("title", { length: 500 }),
    username: varchar("username", { length: 255 }),
    description: text("description"),
    source: varchar("source", { length: 255 }), // where the link came from
    sourceAccount: varchar("sourceAccount", { length: 255 }), // which account found it
    discoveredAt: timestamp("discoveredAt"),
    firstSeenAt: timestamp("firstSeenAt").defaultNow().notNull(),
    lastSeenAt: timestamp("lastSeenAt").defaultNow().onUpdateNow().notNull(),
    searchId: int("searchId"), // which search found this link
    status: mysqlEnum("status", ["active", "invalid", "deleted", "unknown"]).default("active").notNull(),
    isDuplicate: boolean("isDuplicate").default(false).notNull(),
    duplicateCount: int("duplicateCount").default(0).notNull(), // how many times this link was found
    metadata: json("metadata"), // store additional info
    createdAt: timestamp("createdAt").defaultNow().notNull(),
    updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
  },
  (table) => ({
    userIdIdx: index("links_userId_idx").on(table.userId),
    platformIdx: index("links_platform_idx").on(table.platform),
    statusIdx: index("links_status_idx").on(table.status),
    firstSeenAtIdx: index("links_firstSeenAt_idx").on(table.firstSeenAt),
    urlHashIdx: index("links_urlHash_idx").on(table.urlHash),
    // Unique constraint to prevent duplicates at DB level
    uniqueLink: unique("unique_platform_urlHash").on(table.userId, table.platform, table.urlHash),
  })
);

export type Link = typeof links.$inferSelect;
export type InsertLink = typeof links.$inferInsert;

/**
 * Duplicate links tracking - records when a duplicate is found
 */
export const duplicateLinks = mysqlTable(
  "duplicate_links",
  {
    id: int("id").autoincrement().primaryKey(),
    userId: int("userId").notNull(),
    originalUrl: text("originalUrl").notNull(),
    normalizedUrl: text("normalizedUrl").notNull(),
    urlHash: varchar("urlHash", { length: 64 }).notNull(),
    platform: mysqlEnum("platform", ["telegram", "whatsapp"]).notNull(),
    linkType: mysqlEnum("linkType", ["public_group", "private_group", "channel", "group", "unknown"]),
    existingLinkId: int("existingLinkId").notNull(),
    searchId: int("searchId"),
    accountId: int("accountId"),
    detectedAt: timestamp("detectedAt").defaultNow().notNull(),
    metadata: json("metadata"),
    createdAt: timestamp("createdAt").defaultNow().notNull(),
  },
  (table) => ({
    userIdIdx: index("duplicateLinks_userId_idx").on(table.userId),
    existingLinkIdIdx: index("duplicateLinks_existingLinkId_idx").on(table.existingLinkId),
    searchIdIdx: index("duplicateLinks_searchId_idx").on(table.searchId),
  })
);

export type DuplicateLink = typeof duplicateLinks.$inferSelect;
export type InsertDuplicateLink = typeof duplicateLinks.$inferInsert;

/**
 * Audit logs - track all user actions
 */
export const auditLogs = mysqlTable(
  "audit_logs",
  {
    id: int("id").autoincrement().primaryKey(),
    userId: int("userId").notNull(),
    action: varchar("action", { length: 100 }).notNull(),
    section: varchar("section", { length: 100 }), // "accounts", "search", "links", etc
    resourceId: int("resourceId"), // ID of the resource being acted upon
    resourceType: varchar("resourceType", { length: 50 }), // "account", "search", "link", etc
    details: text("details"), // JSON details of what changed
    result: mysqlEnum("result", ["success", "failure"]).default("success").notNull(),
    ipAddress: varchar("ipAddress", { length: 45 }),
    userAgent: text("userAgent"),
    createdAt: timestamp("createdAt").defaultNow().notNull(),
  },
  (table) => ({
    userIdIdx: index("auditLogs_userId_idx").on(table.userId),
    actionIdx: index("auditLogs_action_idx").on(table.action),
    createdAtIdx: index("auditLogs_createdAt_idx").on(table.createdAt),
  })
);

export type AuditLog = typeof auditLogs.$inferSelect;
export type InsertAuditLog = typeof auditLogs.$inferInsert;

/**
 * Notifications - system notifications for users
 */
export const notifications = mysqlTable(
  "notifications",
  {
    id: int("id").autoincrement().primaryKey(),
    userId: int("userId").notNull(),
    type: mysqlEnum("type", ["search_completed", "search_failed", "large_discovery", "error", "info"]).notNull(),
    title: varchar("title", { length: 255 }).notNull(),
    message: text("message").notNull(),
    resourceId: int("resourceId"),
    resourceType: varchar("resourceType", { length: 50 }),
    isRead: boolean("isRead").default(false).notNull(),
    readAt: timestamp("readAt"),
    createdAt: timestamp("createdAt").defaultNow().notNull(),
  },
  (table) => ({
    userIdIdx: index("notifications_userId_idx").on(table.userId),
    isReadIdx: index("notifications_isRead_idx").on(table.isRead),
    createdAtIdx: index("notifications_createdAt_idx").on(table.createdAt),
  })
);

export type Notification = typeof notifications.$inferSelect;
export type InsertNotification = typeof notifications.$inferInsert;

/**
 * Exports - track generated export files
 */
export const exports = mysqlTable(
  "exports",
  {
    id: int("id").autoincrement().primaryKey(),
    userId: int("userId").notNull(),
    searchId: int("searchId"),
    fileName: varchar("fileName", { length: 255 }).notNull(),
    fileType: mysqlEnum("fileType", ["txt", "csv"]).notNull(),
    platform: mysqlEnum("platform", ["telegram", "whatsapp", "all"]).notNull(),
    fileSize: int("fileSize"),
    fileUrl: text("fileUrl"),
    recordCount: int("recordCount").default(0).notNull(),
    createdAt: timestamp("createdAt").defaultNow().notNull(),
    expiresAt: timestamp("expiresAt"),
  },
  (table) => ({
    userIdIdx: index("exports_userId_idx").on(table.userId),
    searchIdIdx: index("exports_searchId_idx").on(table.searchId),
    createdAtIdx: index("exports_createdAt_idx").on(table.createdAt),
  })
);

export type Export = typeof exports.$inferSelect;
export type InsertExport = typeof exports.$inferInsert;

/**
 * Settings - user preferences
 */
export const settings = mysqlTable("settings", {
  id: int("id").autoincrement().primaryKey(),
  userId: int("userId").notNull().unique(),
  language: varchar("language", { length: 10 }).default("ar").notNull(),
  timezone: varchar("timezone", { length: 50 }).default("UTC").notNull(),
  defaultSearchType: mysqlEnum("defaultSearchType", ["fast", "normal", "deep"]).default("normal").notNull(),
  defaultDateRange: varchar("defaultDateRange", { length: 50 }).default("month").notNull(),
  defaultMaxResults: int("defaultMaxResults").default(1000).notNull(),
  enableNotifications: boolean("enableNotifications").default(true).notNull(),
  enableAutoExport: boolean("enableAutoExport").default(false).notNull(),
  duplicateDetection: boolean("duplicateDetection").default(true).notNull(),
  urlNormalization: boolean("urlNormalization").default(true).notNull(),
  separateByPlatform: boolean("separateByPlatform").default(true).notNull(),
  metadata: json("metadata"),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt").defaultNow().onUpdateNow().notNull(),
});

export type Setting = typeof settings.$inferSelect;
export type InsertSetting = typeof settings.$inferInsert;
