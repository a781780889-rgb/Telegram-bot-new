import crypto from 'crypto';

/**
 * URL Normalization and Fingerprinting Service
 * Handles URL cleaning, validation, and deduplication
 */

export interface NormalizedLink {
  originalUrl: string;
  normalizedUrl: string;
  urlHash: string;
  platform: 'telegram' | 'whatsapp';
  linkType: 'public_group' | 'private_group' | 'channel' | 'group' | 'unknown';
  username?: string;
  isValid: boolean;
  validationError?: string;
}

/**
 * Normalize URL by removing unnecessary characters and standardizing format
 */
export function normalizeUrl(url: string, platform: 'telegram' | 'whatsapp'): string {
  let normalized = url.trim();

  // Remove common whitespace and special characters
  normalized = normalized.replace(/\s+/g, '');
  normalized = normalized.replace(/["'`]/g, '');

  if (platform === 'telegram') {
    // Handle Telegram URLs
    // Convert t.me to https://t.me
    if (normalized.startsWith('t.me/')) {
      normalized = 'https://t.me/' + normalized.substring(5);
    }

    // Remove trailing slashes
    normalized = normalized.replace(/\/+$/, '');

    // Normalize protocol
    if (normalized.startsWith('http://t.me/')) {
      normalized = 'https://t.me/' + normalized.substring(12);
    }

    // Remove query parameters for Telegram (they're usually tracking)
    if (normalized.includes('?')) {
      normalized = normalized.split('?')[0];
    }

    // Remove hash fragments
    if (normalized.includes('#')) {
      normalized = normalized.split('#')[0];
    }

    // Lowercase the path for consistency
    const [protocol, ...rest] = normalized.split('://');
    if (protocol) {
      normalized = protocol + '://' + rest.join('://').toLowerCase();
    }
  } else if (platform === 'whatsapp') {
    // Handle WhatsApp URLs
    // Convert wa.me or chat.whatsapp.com URLs
    if (normalized.startsWith('wa.me/')) {
      normalized = 'https://wa.me/' + normalized.substring(6);
    }

    if (normalized.startsWith('chat.whatsapp.com/')) {
      normalized = 'https://chat.whatsapp.com/' + normalized.substring(18);
    }

    // Normalize protocol
    if (normalized.startsWith('http://')) {
      normalized = 'https://' + normalized.substring(7);
    }

    // Remove trailing slashes
    normalized = normalized.replace(/\/+$/, '');

    // Remove query parameters
    if (normalized.includes('?')) {
      normalized = normalized.split('?')[0];
    }

    // Remove hash fragments
    if (normalized.includes('#')) {
      normalized = normalized.split('#')[0];
    }

    // Lowercase for consistency
    const [protocol, ...rest] = normalized.split('://');
    if (protocol) {
      normalized = protocol + '://' + rest.join('://').toLowerCase();
    }
  }

  return normalized;
}

/**
 * Generate SHA256 hash of normalized URL
 */
export function generateUrlHash(normalizedUrl: string): string {
  return crypto
    .createHash('sha256')
    .update(normalizedUrl)
    .digest('hex');
}

/**
 * Detect link type and extract username
 */
export function detectLinkType(
  url: string,
  platform: 'telegram' | 'whatsapp'
): { linkType: 'public_group' | 'private_group' | 'channel' | 'group' | 'unknown'; username?: string } {
  if (platform === 'telegram') {
    // t.me/username (public group or channel)
    const publicMatch = url.match(/t\.me\/([a-zA-Z0-9_]+)/i);
    if (publicMatch) {
      const username = publicMatch[1];
      // Channels usually have + prefix or specific patterns
      // Without more info, we default to public_group
      return {
        linkType: 'public_group',
        username,
      };
    }

    // Private group/channel invite links (joinchat or invite)
    if (url.includes('joinchat') || url.includes('invite')) {
      return {
        linkType: 'private_group',
      };
    }

    return { linkType: 'unknown' };
  } else if (platform === 'whatsapp') {
    // wa.me/number (direct message)
    const waMatch = url.match(/wa\.me\/(\d+)/i);
    if (waMatch) {
      return {
        linkType: 'group',
        username: waMatch[1],
      };
    }

    // chat.whatsapp.com/invite (group invite)
    if (url.includes('chat.whatsapp.com')) {
      return {
        linkType: 'group',
      };
    }

    return { linkType: 'unknown' };
  }

  return { linkType: 'unknown' };
}

/**
 * Validate URL format
 */
export function validateUrl(url: string, platform: 'telegram' | 'whatsapp'): { isValid: boolean; error?: string } {
  if (!url || typeof url !== 'string') {
    return { isValid: false, error: 'URL must be a non-empty string' };
  }

  const trimmed = url.trim();

  if (platform === 'telegram') {
    // Check if it's a valid Telegram URL
    const telegramPatterns = [
      /^https?:\/\/t\.me\/[a-zA-Z0-9_]+/i,
      /^t\.me\/[a-zA-Z0-9_]+/i,
      /^https?:\/\/telegram\.me\/[a-zA-Z0-9_]+/i,
      /^https?:\/\/t\.me\/joinchat\//i,
      /^https?:\/\/t\.me\/\+/i,
    ];

    const isValid = telegramPatterns.some((pattern) => pattern.test(trimmed));
    if (!isValid) {
      return { isValid: false, error: 'Invalid Telegram URL format' };
    }

    return { isValid: true };
  } else if (platform === 'whatsapp') {
    // Check if it's a valid WhatsApp URL
    const whatsappPatterns = [
      /^https?:\/\/wa\.me\/\d+/i,
      /^wa\.me\/\d+/i,
      /^https?:\/\/chat\.whatsapp\.com\/[a-zA-Z0-9]+/i,
      /^chat\.whatsapp\.com\/[a-zA-Z0-9]+/i,
    ];

    const isValid = whatsappPatterns.some((pattern) => pattern.test(trimmed));
    if (!isValid) {
      return { isValid: false, error: 'Invalid WhatsApp URL format' };
    }

    return { isValid: true };
  }

  return { isValid: false, error: 'Unknown platform' };
}

/**
 * Complete URL processing pipeline
 */
export function processUrl(
  url: string,
  platform: 'telegram' | 'whatsapp'
): NormalizedLink {
  // Step 1: Validate
  const validation = validateUrl(url, platform);
  if (!validation.isValid) {
    return {
      originalUrl: url,
      normalizedUrl: '',
      urlHash: '',
      platform,
      linkType: 'unknown',
      isValid: false,
      validationError: validation.error,
    };
  }

  // Step 2: Normalize
  const normalizedUrl = normalizeUrl(url, platform);

  // Step 3: Generate fingerprint
  const urlHash = generateUrlHash(normalizedUrl);

  // Step 4: Detect type
  const { linkType, username } = detectLinkType(normalizedUrl, platform);

  return {
    originalUrl: url,
    normalizedUrl,
    urlHash,
    platform,
    linkType,
    username,
    isValid: true,
  };
}

/**
 * Batch process multiple URLs
 */
export function batchProcessUrls(
  urls: string[],
  platform: 'telegram' | 'whatsapp'
): NormalizedLink[] {
  return urls.map((url) => processUrl(url, platform));
}

/**
 * Check if two URLs are duplicates (same hash)
 */
export function areDuplicates(hash1: string, hash2: string): boolean {
  return hash1 === hash2;
}

/**
 * Extract unique URLs from a batch (by hash)
 */
export function extractUnique(links: NormalizedLink[]): NormalizedLink[] {
  const seen = new Set<string>();
  const unique: NormalizedLink[] = [];

  for (const link of links) {
    if (link.isValid && !seen.has(link.urlHash)) {
      seen.add(link.urlHash);
      unique.push(link);
    }
  }

  return unique;
}
