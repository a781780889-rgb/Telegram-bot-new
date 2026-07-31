import { eq, and, desc } from 'drizzle-orm';
import { getDb } from '../db';
import { accounts } from '../../drizzle/schema';
import type { InsertAccount, Account } from '../../drizzle/schema';

/**
 * Account Management Service
 * Handles Telegram and WhatsApp account operations
 */

export class AccountService {
  /**
   * Create a new account
   */
  static async createAccount(
    userId: number,
    data: {
      name: string;
      username?: string;
      platform: 'telegram' | 'whatsapp';
      accountType?: string;
      credentials?: string;
    }
  ): Promise<Account> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const accountData: InsertAccount = {
      userId,
      name: data.name,
      username: data.username,
      platform: data.platform,
      accountType: data.accountType || 'personal',
      credentials: data.credentials,
      status: 'active',
      isEnabled: true,
      searchCount: 0,
      linksExtracted: 0,
    };

    await db.insert(accounts).values(accountData);

    const result = await db
      .select()
      .from(accounts)
      .where(
        and(
          eq(accounts.userId, userId),
          eq(accounts.name, data.name),
          eq(accounts.platform, data.platform)
        )
      )
      .orderBy(desc(accounts.createdAt))
      .limit(1);

    if (result.length === 0) throw new Error('Failed to create account');
    return result[0];
  }

  /**
   * Get all accounts for a user
   */
  static async getAccounts(userId: number): Promise<Account[]> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    return await db
      .select()
      .from(accounts)
      .where(eq(accounts.userId, userId))
      .orderBy(desc(accounts.createdAt));
  }

  /**
   * Get account by ID
   */
  static async getAccountById(userId: number, accountId: number): Promise<Account | null> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const result = await db
      .select()
      .from(accounts)
      .where(
        and(
          eq(accounts.userId, userId),
          eq(accounts.id, accountId)
        )
      )
      .limit(1);

    return result.length > 0 ? result[0] : null;
  }

  /**
   * Update account
   */
  static async updateAccount(
    userId: number,
    accountId: number,
    data: Partial<{
      name: string;
      username: string;
      status: 'active' | 'inactive' | 'error' | 'paused';
      isEnabled: boolean;
      lastError: string;
    }>
  ): Promise<Account> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    // Verify ownership
    const existing = await this.getAccountById(userId, accountId);
    if (!existing) throw new Error('Account not found');

    const updateData: any = {
      ...data,
      updatedAt: new Date(),
    };

    await db
      .update(accounts)
      .set(updateData)
      .where(
        and(
          eq(accounts.userId, userId),
          eq(accounts.id, accountId)
        )
      );

    const result = await this.getAccountById(userId, accountId);
    if (!result) throw new Error('Failed to update account');
    return result;
  }

  /**
   * Toggle account status
   */
  static async toggleAccountStatus(userId: number, accountId: number): Promise<Account> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const existing = await this.getAccountById(userId, accountId);
    if (!existing) throw new Error('Account not found');

    const newStatus = existing.isEnabled ? false : true;

    await db
      .update(accounts)
      .set({
        isEnabled: newStatus,
        status: newStatus ? 'active' : 'inactive',
        updatedAt: new Date(),
      })
      .where(
        and(
          eq(accounts.userId, userId),
          eq(accounts.id, accountId)
        )
      );

    const result = await this.getAccountById(userId, accountId);
    if (!result) throw new Error('Failed to toggle account');
    return result;
  }

  /**
   * Delete account
   */
  static async deleteAccount(userId: number, accountId: number): Promise<boolean> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    // Verify ownership
    const existing = await this.getAccountById(userId, accountId);
    if (!existing) throw new Error('Account not found');

    await db
      .delete(accounts)
      .where(
        and(
          eq(accounts.userId, userId),
          eq(accounts.id, accountId)
        )
      );

    return true;
  }

  /**
   * Update account search count
   */
  static async incrementSearchCount(accountId: number, linksCount: number): Promise<void> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    const account = await db
      .select()
      .from(accounts)
      .where(eq(accounts.id, accountId))
      .limit(1);

    if (account.length > 0) {
      await db
        .update(accounts)
        .set({
          searchCount: (account[0].searchCount || 0) + 1,
          linksExtracted: (account[0].linksExtracted || 0) + linksCount,
          lastUsed: new Date(),
          updatedAt: new Date(),
        })
        .where(eq(accounts.id, accountId));
    }
  }

  /**
   * Set account error status
   */
  static async setAccountError(accountId: number, errorMessage: string): Promise<void> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    await db
      .update(accounts)
      .set({
        status: 'error',
        lastError: errorMessage,
        updatedAt: new Date(),
      })
      .where(eq(accounts.id, accountId));
  }

  /**
   * Get accounts by platform
   */
  static async getAccountsByPlatform(
    userId: number,
    platform: 'telegram' | 'whatsapp'
  ): Promise<Account[]> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    return await db
      .select()
      .from(accounts)
      .where(
        and(
          eq(accounts.userId, userId),
          eq(accounts.platform, platform),
          eq(accounts.isEnabled, true)
        )
      )
      .orderBy(desc(accounts.createdAt));
  }

  /**
   * Get active accounts
   */
  static async getActiveAccounts(userId: number): Promise<Account[]> {
    const db = await getDb();
    if (!db) throw new Error('Database not available');

    return await db
      .select()
      .from(accounts)
      .where(
        and(
          eq(accounts.userId, userId),
          eq(accounts.isEnabled, true),
          eq(accounts.status, 'active')
        )
      )
      .orderBy(desc(accounts.createdAt));
  }
}
