import { z } from 'zod';
import { protectedProcedure, router } from '../_core/trpc';
import { SearchService } from '../services/searchService';
import { TRPCError } from '@trpc/server';

export const searchRouter = router({
  /**
   * Create new search
   */
  createSearch: protectedProcedure
    .input(
      z.object({
        searchName: z.string().optional(),
        platforms: z.enum(['telegram', 'whatsapp', 'both']),
        searchType: z.enum(['fast', 'normal', 'deep']),
        dateRange: z.string(),
        startDate: z.date().or(z.string()).optional(),
        endDate: z.date().or(z.string()).optional(),
        accountIds: z.array(z.number()),
        maxResults: z.number().optional(),
        settings: z.record(z.string(), z.any()).optional(),
      })
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const startDate = typeof input.startDate === 'string' ? new Date(input.startDate) : input.startDate;
        const endDate = typeof input.endDate === 'string' ? new Date(input.endDate) : input.endDate;
        const search = await SearchService.createSearch(ctx.user.id, {
          ...input,
          startDate,
          endDate,
        });
        return search;
      } catch (error) {
        console.error('Error creating search:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to create search',
        });
      }
    }),

  /**
   * Get search by ID
   */
  getSearch: protectedProcedure
    .input(z.object({ id: z.number() }))
    .query(async ({ ctx, input }) => {
      try {
        const search = await SearchService.getSearchById(ctx.user.id, input.id);
        if (!search) {
          throw new TRPCError({
            code: 'NOT_FOUND',
            message: 'Search not found',
          });
        }
        return search;
      } catch (error) {
        if (error instanceof TRPCError) throw error;
        console.error('Error fetching search:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to fetch search',
        });
      }
    }),

  /**
   * Get all searches
   */
  getSearches: protectedProcedure
    .input(
      z.object({
        status: z.string().optional(),
        limit: z.number().default(50),
        offset: z.number().default(0),
      })
    )
    .query(async ({ ctx, input }) => {
      try {
        const result = await SearchService.getSearches(ctx.user.id, input);
        return result;
      } catch (error) {
        console.error('Error fetching searches:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to fetch searches',
        });
      }
    }),

  /**
   * Update search status
   */
  updateSearchStatus: protectedProcedure
    .input(
      z.object({
        id: z.number(),
        status: z.enum(['pending', 'running', 'paused', 'completed', 'failed', 'cancelled']),
      })
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const search = await SearchService.updateSearchStatus(ctx.user.id, input.id, input.status);
        return search;
      } catch (error) {
        if (error instanceof TRPCError) throw error;
        console.error('Error updating search status:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to update search status',
        });
      }
    }),

  /**
   * Update search progress
   */
  updateSearchProgress: protectedProcedure
    .input(
      z.object({
        id: z.number(),
        progress: z.number().optional(),
        totalFound: z.number().optional(),
        totalNew: z.number().optional(),
        totalDuplicate: z.number().optional(),
        totalInvalid: z.number().optional(),
        telegramCount: z.number().optional(),
        whatsappCount: z.number().optional(),
      })
    )
    .mutation(async ({ ctx, input }) => {
      try {
        const { id, ...data } = input;
        await SearchService.updateSearchProgress(ctx.user.id, id, data);
        const search = await SearchService.getSearchById(ctx.user.id, id);
        return search;
      } catch (error) {
        if (error instanceof TRPCError) throw error;
        console.error('Error updating search progress:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to update search progress',
        });
      }
    }),

  /**
   * Set search error
   */
  setSearchError: protectedProcedure
    .input(
      z.object({
        id: z.number(),
        errorMessage: z.string(),
      })
    )
    .mutation(async ({ ctx, input }) => {
      try {
        await SearchService.setSearchError(ctx.user.id, input.id, input.errorMessage);
        const search = await SearchService.getSearchById(ctx.user.id, input.id);
        return search;
      } catch (error) {
        if (error instanceof TRPCError) throw error;
        console.error('Error setting search error:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to set search error',
        });
      }
    }),

  /**
   * Get search statistics
   */
  getStatistics: protectedProcedure.query(async ({ ctx }) => {
    try {
      const stats = await SearchService.getSearchStatistics(ctx.user.id);
      return stats;
    } catch (error) {
      console.error('Error fetching search statistics:', error);
      throw new TRPCError({
        code: 'INTERNAL_SERVER_ERROR',
        message: 'Failed to fetch search statistics',
      });
    }
  }),
});
