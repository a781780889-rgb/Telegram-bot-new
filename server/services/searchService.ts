import { eq, and, desc, sql } from 'drizzle-orm';
import { getDb } from '../db';
import { searches, links, duplicateLinks } from '../../drizzle/schema';
import type { InsertSearch, Search } from '../../drizzle/schema';

/**
 * Search Management Service
 * Handles search job operations and tracking
 */

export class SearchService {
  /**
   * Create a new search job
   */
  static async createSearch(
    userId: number,
    data: {
      searchName?: string;
      platforms: 'telegram' | 'whatsapp' | 'both';
      searchType: 'fast' | 'normal' | 'deep';
      dateRange: string;
      startDate?: Date;
      endDate?: Date;
      accountIds: number[];
      maxResults?: number;
      settings?: any;
    }
  ): Promise<Search> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const searchData: InsertSearch = {
      userId,
      searchName: data.searchName || `Search ${new Date().toLocaleString()}`,
      platforms: data.platforms === 'both' ? 'telegram,whatsapp' : data.platforms,
      searchType: data.searchType,
      dateRange: data.dateRange,
      startDate: data.startDate,
      endDate: data.endDate,
      accountIds: JSON.stringify(data.accountIds),
      maxResults: (data.maxResults || 1000) as any,
      status: 'pending',
      progress: 0 as any,
      settings: data.settings,
    };

    await db.insert(searches).values(searchData);

    const result = await db
      .select()
      .from(searches)
      .where(eq(searches.userId, userId))
      .orderBy(desc(searches.createdAt))
      .limit(1);

    if (result.length === 0) throw new Error('Failed to create search');
    return result[0];
  }

  /**
   * Get search by ID
   */
  static async getSearchById(userId: number, searchId: number): Promise<Search | null> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const result = await db
      .select()
      .from(searches)
      .where(
        and(
          eq(searches.userId, userId),
          eq(searches.id, searchId)
        )
      )
      .limit(1);

    return result.length > 0 ? result[0] : null;
  }

  /**
   * Get all searches for a user
   */
  static async getSearches(
    userId: number,
    filters?: {
      status?: string;
      limit?: number;
      offset?: number;
    }
  ): Promise<{ searches: Search[]; total: number }> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const conditions = [eq(searches.userId, userId)];

    if (filters?.status) {
      conditions.push(eq(searches.status, filters.status as any));
    }

    const limit = filters?.limit || 50;
    const offset = filters?.offset || 0;

    const result = await db
      .select()
      .from(searches)
      .where(and(...conditions))
      .orderBy(desc(searches.createdAt))
      .limit(limit)
      .offset(offset);

    // Get total count
    const countResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(searches)
      .where(and(...conditions));

    const total = countResult[0]?.count as number || 0;

    return { searches: result, total };
  }

  /**
   * Update search status
   */
  static async updateSearchStatus(
    userId: number,
    searchId: number,
    status: 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled'
  ): Promise<Search> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const existing = await this.getSearchById(userId, searchId);
    if (!existing) throw new Error('Search not found');

    const updateData: any = {
      status,
      updatedAt: new Date(),
    };

    if (status === 'running') {
      updateData.startedAt = new Date();
    } else if (status === 'completed' || status === 'failed') {
      updateData.completedAt = new Date();
      if (existing.startedAt) {
        updateData.duration = Math.floor(
          (new Date().getTime() - existing.startedAt.getTime()) / 1000
        );
      }
    }

    await db
      .update(searches)
      .set(updateData)
      .where(
        and(
          eq(searches.userId, userId),
          eq(searches.id, searchId)
        )
      );

    const result = await this.getSearchById(userId, searchId);
    if (!result) throw new Error('Failed to update search');
    return result;
  }

  /**
   * Update search progress and statistics
   */
  static async updateSearchProgress(
    userId: number,
    searchId: number,
    data: {
      progress?: number;
      totalFound?: number;
      totalNew?: number;
      totalDuplicate?: number;
      totalInvalid?: number;
      telegramCount?: number;
      whatsappCount?: number;
    }
  ): Promise<void> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const updateData: any = {
      updatedAt: new Date(),
    };

    if (data.progress !== undefined) updateData.progress = data.progress;
    if (data.totalFound !== undefined) updateData.totalFound = data.totalFound;
    if (data.totalNew !== undefined) updateData.totalNew = data.totalNew;
    if (data.totalDuplicate !== undefined) updateData.totalDuplicate = data.totalDuplicate;
    if (data.totalInvalid !== undefined) updateData.totalInvalid = data.totalInvalid;
    if (data.telegramCount !== undefined) updateData.telegramCount = data.telegramCount;
    if (data.whatsappCount !== undefined) updateData.whatsappCount = data.whatsappCount;

    await db
      .update(searches)
      .set(updateData)
      .where(
        and(
          eq(searches.userId, userId),
          eq(searches.id, searchId)
        )
      );
  }

  /**
   * Set search error
   */
  static async setSearchError(
    userId: number,
    searchId: number,
    errorMessage: string
  ): Promise<void> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    await db
      .update(searches)
      .set({
        status: 'failed',
        errorMessage,
        completedAt: new Date(),
        updatedAt: new Date(),
      })
      .where(
        and(
          eq(searches.userId, userId),
          eq(searches.id, searchId)
        )
      );
  }

  /**
   * Get search statistics
   */
  static async getSearchStatistics(userId: number): Promise<{
    totalSearches: number;
    activeSearches: number;
    completedSearches: number;
    failedSearches: number;
    pausedSearches: number;
    lastSearch?: Search;
  }> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const totalResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(searches)
      .where(eq(searches.userId, userId));
    const totalSearches = totalResult[0]?.count as number || 0;

    const activeResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(searches)
      .where(
        and(
          eq(searches.userId, userId),
          eq(searches.status, 'running')
        )
      );
    const activeSearches = activeResult[0]?.count as number || 0;

    const completedResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(searches)
      .where(
        and(
          eq(searches.userId, userId),
          eq(searches.status, 'completed')
        )
      );
    const completedSearches = completedResult[0]?.count as number || 0;

    const failedResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(searches)
      .where(
        and(
          eq(searches.userId, userId),
          eq(searches.status, 'failed')
        )
      );
    const failedSearches = failedResult[0]?.count as number || 0;

    const pausedResult = await db
      .select({ count: sql`COUNT(*)` })
      .from(searches)
      .where(
        and(
          eq(searches.userId, userId),
          eq(searches.status, 'paused')
        )
      );
    const pausedSearches = pausedResult[0]?.count as number || 0;

    const lastSearchResult = await db
      .select()
      .from(searches)
      .where(eq(searches.userId, userId))
      .orderBy(desc(searches.createdAt))
      .limit(1);

    return {
      totalSearches,
      activeSearches,
      completedSearches,
      failedSearches,
      pausedSearches,
      lastSearch: lastSearchResult.length > 0 ? lastSearchResult[0] : undefined,
    };
  }

  /**
   * Parse account IDs from search
   */
  static parseAccountIds(search: Search): number[] {
    try {
      return JSON.parse(search.accountIds || '[]');
    } catch {
      return [];
    }
  }
}
