import { z } from 'zod';
import { protectedProcedure, router } from '../_core/trpc';
import { LinkService } from '../services/linkService';
import { SearchService } from '../services/searchService';
import { AccountService } from '../services/accountService';
import { processUrl } from '../services/urlNormalizer';
import { TRPCError } from '@trpc/server';

export const linkRouter = router({
  /**
   * Get all links with filters
   */
  getLinks: protectedProcedure
    .input(
      z.object({
        platform: z.enum(['telegram', 'whatsapp']).optional(),
        linkType: z.string().optional(),
        status: z.string().optional(),
        searchId: z.number().optional(),
        limit: z.number().default(50),
        offset: z.number().default(0),
      })
    )
    .query(async ({ ctx, input }) => {
      try {
        const result = await LinkService.getLinks(ctx.user.id, input);
        return result;
      } catch (error) {
        console.error('Error fetching links:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to fetch links',
        });
      }
    }),

  /**
   * Search links by query
   */
  searchLinks: protectedProcedure
    .input(
      z.object({
        query: z.string().min(1),
        platform: z.enum(['telegram', 'whatsapp']).optional(),
        limit: z.number().default(50),
        offset: z.number().default(0),
      })
    )
    .query(async ({ ctx, input }) => {
      try {
        const result = await LinkService.searchLinks(ctx.user.id, input.query, {
          platform: input.platform,
          limit: input.limit,
          offset: input.offset,
        });
        return result;
      } catch (error) {
        console.error('Error searching links:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to search links',
        });
      }
    }),

  /**
   * Get dashboard statistics
   */
  getStatistics: protectedProcedure.query(async ({ ctx }) => {
    try {
      const stats = await LinkService.getStatistics(ctx.user.id);
      const searchStats = await SearchService.getSearchStatistics(ctx.user.id);
      
      return {
        ...stats,
        ...searchStats,
      };
    } catch (error) {
      console.error('Error fetching statistics:', error);
      throw new TRPCError({
        code: 'INTERNAL_SERVER_ERROR',
        message: 'Failed to fetch statistics',
      });
    }
  }),

  /**
   * Get duplicates for a search
   */
  getDuplicates: protectedProcedure
    .input(z.object({ searchId: z.number() }))
    .query(async ({ ctx, input }) => {
      try {
        // Verify search ownership
        const search = await SearchService.getSearchById(ctx.user.id, input.searchId);
        if (!search) {
          throw new TRPCError({
            code: 'NOT_FOUND',
            message: 'Search not found',
          });
        }

        const duplicates = await LinkService.getDuplicatesForSearch(input.searchId);
        return duplicates;
      } catch (error) {
        if (error instanceof TRPCError) throw error;
        console.error('Error fetching duplicates:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to fetch duplicates',
        });
      }
    }),

  /**
   * Export links
   */
  exportLinks: protectedProcedure
    .input(
      z.object({
        platform: z.enum(['telegram', 'whatsapp']).optional(),
        searchId: z.number().optional(),
        format: z.enum(['txt', 'csv']).default('txt'),
      })
    )
    .query(async ({ ctx, input }) => {
      try {
        const links = await LinkService.exportLinks(ctx.user.id, input.platform, input.searchId);

        if (input.format === 'txt') {
          // Generate TXT file content (one URL per line)
          const content = links
            .map((link) => link.normalizedUrl)
            .join('\n');

          return {
            format: 'txt',
            filename: `links_${new Date().toISOString().split('T')[0]}.txt`,
            content,
          };
        } else {
          // Generate CSV file content
          const headers = [
            'Platform',
            'Link Type',
            'URL',
            'Title',
            'Username',
            'Source',
            'First Seen',
            'Last Seen',
            'Status',
          ];

          const rows = links.map((link) => [
            link.platform,
            link.linkType,
            link.normalizedUrl,
            link.title || '',
            link.username || '',
            link.source || '',
            link.firstSeenAt?.toISOString() || '',
            link.lastSeenAt?.toISOString() || '',
            link.status,
          ]);

          const csv = [
            headers.join(','),
            ...rows.map((row) =>
              row
                .map((cell) => `"${String(cell).replace(/"/g, '""')}"`)
                .join(',')
            ),
          ].join('\n');

          return {
            format: 'csv',
            filename: `links_${new Date().toISOString().split('T')[0]}.csv`,
            content: csv,
          };
        }
      } catch (error) {
        console.error('Error exporting links:', error);
        throw new TRPCError({
          code: 'INTERNAL_SERVER_ERROR',
          message: 'Failed to export links',
        });
      }
    }),

  /**
   * Validate and process URL
   */
  validateUrl: protectedProcedure
    .input(
      z.object({
        url: z.string().min(1),
        platform: z.enum(['telegram', 'whatsapp']),
      })
    )
    .query(async ({ input }) => {
      try {
        const result = processUrl(input.url, input.platform);
        return result;
      } catch (error) {
        console.error('Error validating URL:', error);
        throw new TRPCError({
          code: 'BAD_REQUEST',
          message: 'Invalid URL',
        });
      }
    }),
});
