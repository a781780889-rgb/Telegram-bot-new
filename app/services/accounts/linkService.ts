import { eq, and, inArray, desc, sql } from 'drizzle-orm';
import { getDb } from '../db';
import { links, duplicateLinks, accounts, searches, notifications } from '../../drizzle/schema';
import type { InsertLink, Link, InsertDuplicateLink } from '../../drizzle/schema';
import { NormalizedLink } from './urlNormalizer';

/**
 * Link Management Service
 * Handles all link database operations with deduplication logic
 */

export class LinkService {
  /**
   * Check if a link already exists in the database
   */
  static async checkDuplicate(
    userId: number,
    platform: 'telegram' | 'whatsapp',
    urlHash: string
  ): Promise<Link | null> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const result = await db
      .select()
      .from(links)
      .where(
        and(
          eq(links.userId, userId),
          eq(links.platform, platform),
          eq(links.urlHash, urlHash)
        )
      )
      .limit(1);

    return result.length > 0 ? result[0] : null;
  }

  /**
   * Save a new link to the database
   */
  static async saveLink(
    userId: number,
    normalizedLink: NormalizedLink,
    searchId?: number,
    sourceAccount?: string
  ): Promise<Link> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const linkData: InsertLink = {
      userId,
      platform: normalizedLink.platform,
      linkType: normalizedLink.linkType,
      originalUrl: normalizedLink.originalUrl,
      normalizedUrl: normalizedLink.normalizedUrl,
      urlHash: normalizedLink.urlHash,
      username: normalizedLink.username,
      searchId,
      sourceAccount,
      discoveredAt: new Date(),
      status: 'active',
      isDuplicate: false,
      duplicateCount: 1,
    };

    try {
      await db.insert(links).values(linkData);
      const saved = await db
        .select()
        .from(links)
        .where(
          and(
            eq(links.userId, userId),
            eq(links.urlHash, normalizedLink.urlHash)
          )
        )
        .limit(1);

      if (saved.length === 0) throw new Error('Failed to save link');
      return saved[0];
    } catch (error: any) {
      // Handle unique constraint violation (duplicate found)
      if (error.code === 'ER_DUP_ENTRY' || error.message.includes('Duplicate entry')) {
        // Link already exists, return existing
        const existing = await this.checkDuplicate(userId, normalizedLink.platform, normalizedLink.urlHash);
        if (existing) {
          // Record the duplicate occurrence
          await this.recordDuplicateOccurrence(
            userId,
            existing.id,
            normalizedLink,
            searchId,
            sourceAccount
          );
          return existing;
        }
      }
      throw error;
    }
  }

  /**
   * Record a duplicate link occurrence
   */
  static async recordDuplicateOccurrence(
    userId: number,
    existingLinkId: number,
    normalizedLink: NormalizedLink,
    searchId?: number,
    accountId?: string
  ): Promise<void> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const duplicateData: InsertDuplicateLink = {
      userId,
      originalUrl: normalizedLink.originalUrl,
      normalizedUrl: normalizedLink.normalizedUrl,
      urlHash: normalizedLink.urlHash,
      platform: normalizedLink.platform,
      linkType: normalizedLink.linkType,
      existingLinkId,
      searchId,
      accountId: accountId ? parseInt(accountId) : undefined,
      detectedAt: new Date(),
    };

    try {
      await db.insert(duplicateLinks).values(duplicateData);

      // Update duplicate count on the original link
      const existing = await db.select().from(links).where(eq(links.id, existingLinkId)).limit(1);
      if (existing.length > 0) {
        await db
          .update(links)
          .set({
            duplicateCount: (existing[0].duplicateCount || 0) + 1,
            lastSeenAt: new Date(),
          })
          .where(eq(links.id, existingLinkId));
      }
    } catch (error) {
      console.error('Failed to record duplicate occurrence:', error);
      // Don't throw - this is non-critical
    }
  }

  /**
   * Get links with filters
   */
  static async getLinks(
    userId: number,
    filters?: {
      platform?: 'telegram' | 'whatsapp';
      linkType?: string;
      status?: string;
      searchId?: number;
      limit?: number;
      offset?: number;
    }
  ): Promise<{ links: Link[]; total: number }> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const conditions = [eq(links.userId, userId)];

    if (filters?.platform) {
      conditions.push(eq(links.platform, filters.platform));
    }
    if (filters?.linkType) {
      conditions.push(eq(links.linkType, filters.linkType as any));
    }
    if (filters?.status) {
      conditions.push(eq(links.status, filters.status as any));
    }
    if (filters?.searchId) {
      conditions.push(eq(links.searchId, filters.searchId));
    }

    const limit = filters?.limit || 50;
    const offset = filters?.offset || 0;

    const result = await db
      .select()
      .from(links)
      .where(and(...conditions))
      .orderBy(desc(links.createdAt))
      .limit(limit)
      .offset(offset);

    // Get total count
    const countResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(links)
      .where(and(...conditions));

    const total = countResult[0]?.count as number || 0;

    return { links: result, total };
  }

  /**
   * Search links by query
   */
  static async searchLinks(
    userId: number,
    query: string,
    filters?: {
      platform?: 'telegram' | 'whatsapp';
      limit?: number;
      offset?: number;
    }
  ): Promise<{ links: Link[]; total: number }> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const searchQuery = `%${query}%`;
    const conditions = [eq(links.userId, userId)];

    if (filters?.platform) {
      conditions.push(eq(links.platform, filters.platform));
    }

    // Search in multiple fields
    const result = await db
      .select()
      .from(links)
      .where(
        and(
          ...conditions,
          sql`(
            ${links.normalizedUrl} LIKE ${searchQuery} OR
            ${links.username} LIKE ${searchQuery} OR
            ${links.title} LIKE ${searchQuery} OR
            ${links.description} LIKE ${searchQuery}
          )`
        )
      )
      .orderBy(desc(links.createdAt))
      .limit(filters?.limit || 50)
      .offset(filters?.offset || 0);

    // Get total count
    const countResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(links)
      .where(
        and(
          ...conditions,
          sql`(
            ${links.normalizedUrl} LIKE ${searchQuery} OR
            ${links.username} LIKE ${searchQuery} OR
            ${links.title} LIKE ${searchQuery} OR
            ${links.description} LIKE ${searchQuery}
          )`
        )
      );

    const total = countResult[0]?.count as number || 0;

    return { links: result, total };
  }

  /**
   * Get statistics for dashboard
   */
  static async getStatistics(userId: number): Promise<{
    totalLinks: number;
    telegramLinks: number;
    whatsappLinks: number;
    newLinksToday: number;
    newLinksThisWeek: number;
    newLinksThisMonth: number;
    duplicateCount: number;
    duplicatePercentage: number;
    telegramPublicGroups: number;
    telegramPrivateGroups: number;
    telegramChannels: number;
    whatsappGroups: number;
    whatsappChannels: number;
  }> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const weekAgo = new Date(today.getTime() - 7 * 24 * 60 * 60 * 1000);
    const monthAgo = new Date(today.getFullYear(), today.getMonth() - 1, today.getDate());

    // Total links
    const totalResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(links)
      .where(eq(links.userId, userId));
    const totalLinks = totalResult[0]?.count as number || 0;

    // By platform
    const telegramResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(links)
      .where(and(eq(links.userId, userId), eq(links.platform, 'telegram')));
    const telegramLinks = telegramResult[0]?.count as number || 0;

    const whatsappResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(links)
      .where(and(eq(links.userId, userId), eq(links.platform, 'whatsapp')));
    const whatsappLinks = whatsappResult[0]?.count as number || 0;

    // New links by time period
    const newTodayResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(links)
      .where(
        and(
          eq(links.userId, userId),
          sql`DATE(${links.firstSeenAt}) = DATE(${today})`
        )
      );
    const newLinksToday = newTodayResult[0]?.count as number || 0;

    const newWeekResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(links)
      .where(
        and(
          eq(links.userId, userId),
          sql`${links.firstSeenAt} >= ${weekAgo}`
        )
      );
    const newLinksThisWeek = newWeekResult[0]?.count as number || 0;

    const newMonthResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(links)
      .where(
        and(
          eq(links.userId, userId),
          sql`${links.firstSeenAt} >= ${monthAgo}`
        )
      );
    const newLinksThisMonth = newMonthResult[0]?.count as number || 0;

    // Duplicates
    const duplicateCountResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(duplicateLinks)
      .where(eq(duplicateLinks.userId, userId));
    const duplicateCount = duplicateCountResult[0]?.count as number || 0;

    const duplicatePercentage = totalLinks > 0 ? Math.round((duplicateCount / totalLinks) * 100) : 0;

    // By link type
    const telegramPublicResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(links)
      .where(
        and(
          eq(links.userId, userId),
          eq(links.platform, 'telegram'),
          eq(links.linkType, 'public_group')
        )
      );
    const telegramPublicGroups = telegramPublicResult[0]?.count as number || 0;

    const telegramPrivateResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(links)
      .where(
        and(
          eq(links.userId, userId),
          eq(links.platform, 'telegram'),
          eq(links.linkType, 'private_group')
        )
      );
    const telegramPrivateGroups = telegramPrivateResult[0]?.count as number || 0;

    const telegramChannelResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(links)
      .where(
        and(
          eq(links.userId, userId),
          eq(links.platform, 'telegram'),
          eq(links.linkType, 'channel')
        )
      );
    const telegramChannels = telegramChannelResult[0]?.count as number || 0;

    const whatsappGroupResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(links)
      .where(
        and(
          eq(links.userId, userId),
          eq(links.platform, 'whatsapp'),
          eq(links.linkType, 'group')
        )
      );
    const whatsappGroups = whatsappGroupResult[0]?.count as number || 0;

    const whatsappChannelResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(links)
      .where(
        and(
          eq(links.userId, userId),
          eq(links.platform, 'whatsapp'),
          eq(links.linkType, 'channel')
        )
      );
    const whatsappChannels = whatsappChannelResult[0]?.count as number || 0;

    return {
      totalLinks,
      telegramLinks,
      whatsappLinks,
      newLinksToday,
      newLinksThisWeek,
      newLinksThisMonth,
      duplicateCount,
      duplicatePercentage,
      telegramPublicGroups,
      telegramPrivateGroups,
      telegramChannels,
      whatsappGroups,
      whatsappChannels,
    };
  }

  /**
   * Get duplicate links for a search
   */
  static async getDuplicatesForSearch(searchId: number): Promise<any[]> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    return await db
      .select()
      .from(duplicateLinks)
      .where(eq(duplicateLinks.searchId, searchId))
      .orderBy(desc(duplicateLinks.detectedAt));
  }

  /**
   * Export links to array
   */
  static async exportLinks(
    userId: number,
    platform?: 'telegram' | 'whatsapp',
    searchId?: number
  ): Promise<Link[]> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const conditions = [eq(links.userId, userId), eq(links.status, 'active')];

    if (platform) {
      conditions.push(eq(links.platform, platform));
    }
    if (searchId) {
      conditions.push(eq(links.searchId, searchId));
    }

    return await db
      .select()
      .from(links)
      .where(and(...conditions))
      .orderBy(desc(links.createdAt));
  }
}
