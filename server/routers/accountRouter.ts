import { z } from 'zod';
import { protectedProcedure, router } from '../_core/trpc';
import { AccountService } from '../services/accountService';
import { TRPCError } from '@trpc/server';

export const accountRouter = router({
  /**
   * Get all accounts
   */
  getAccounts: protectedProcedure.query(async ({ ctx }) => {
    try {
      const accounts = await AccountService.getAccounts(ctx.user.id);
      return accounts;
    } catch (error) {
      console.error('Error fetching accounts:', error);
      throw new TRPCError({
        code: 'INTERNAL_SERVER_ERROR',
        message: 'Failed to fetch accounts',
      });
    }
  }),

  /**
   * Get account by ID
   */
  getAccount: protectedProcedure
    .input(z.object({ id: z.number() }))
    .query(async ({ ctx, input }) => {
      try {
        const account = await AccountService.getAccountById(ctx.user.id, input.id);
        if (!account) {
          throw new TRPCError({
            code: 'NOT_FOUND',
            message: 'Account not found',
          });
        }
        return account;
      } catch (error) {
        if (error instanceof TRPCError) throw error;
        console.error('Error fetching account:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to fetch account',
        });
      }
    }),

  /**
   * Create new account
   */
  createAccount: protectedProcedure
    .input(
      z.object({
        name: z.string().min(1).max(255),
        username: z.string().optional(),
        platform: z.enum(['telegram', 'whatsapp']),
        accountType: z.string().optional(),
        credentials: z.string().optional(),
      })
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const account = await AccountService.createAccount(ctx.user.id, input);
        return account;
      } catch (error) {
        console.error('Error creating account:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to create account',
        });
      }
    }),

  /**
   * Update account
   */
  updateAccount: protectedProcedure
    .input(
      z.object({
        id: z.number(),
        name: z.string().optional(),
        username: z.string().optional(),
        status: z.enum(['active', 'inactive', 'error', 'paused']).optional(),
        isEnabled: z.boolean().optional(),
        lastError: z.string().optional(),
      })
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { id, ...data } = input;
        const account = await AccountService.updateAccount(ctx.user.id, id, data);
        return account;
      } catch (error) {
        if (error instanceof TRPCError) throw error;
        console.error('Error updating account:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to update account',
        });
      }
    }),

  /**
   * Toggle account status
   */
  toggleAccount: protectedProcedure
    .input(z.object({ id: z.number() }))
    .mutation(async ({ ctx, input }) => {
      try {
        const account = await AccountService.toggleAccountStatus(ctx.user.id, input.id);
        return account;
      } catch (error) {
        if (error instanceof TRPCError) throw error;
        console.error('Error toggling account:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to toggle account',
        });
      }
    }),

  /**
   * Delete account
   */
  deleteAccount: protectedProcedure
    .input(z.object({ id: z.number() }))
    .mutation(async ({ ctx, input }) => {
      try {
        await AccountService.deleteAccount(ctx.user.id, input.id);
        return { success: true };
      } catch (error) {
        if (error instanceof TRPCError) throw error;
        console.error('Error deleting account:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to delete account',
        });
      }
    }),

  /**
   * Get accounts by platform
   */
  getAccountsByPlatform: protectedProcedure
    .input(z.object({ platform: z.enum(['telegram', 'whatsapp']) }))
    .query(async ({ ctx, input }) => {
      try {
        const accounts = await AccountService.getAccountsByPlatform(ctx.user.id, input.platform);
        return accounts;
      } catch (error) {
        console.error('Error fetching accounts by platform:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to fetch accounts',
        });
      }
    }),

  /**
   * Get active accounts
   */
  getActiveAccounts: protectedProcedure.query(async ({ ctx }) => {
    try {
      const accounts = await AccountService.getActiveAccounts(ctx.user.id);
      return accounts;
    } catch (error) {
      console.error('Error fetching active accounts:', error);
      throw new TRPCError({
        code: 'INTERNAL_SERVER_ERROR',
        message: 'Failed to fetch active accounts',
      });
    }
  }),
});

