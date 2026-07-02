
/**
 * URL Import Utility
 *
 * Provides functionality to fetch OpenAPI specifications from URLs
 * with support for authentication and various options.
 */

import { isProtobuf } from './protobuf-converter';
import { isAvroSchemaObject } from './avro-converter';
import { isThrift } from './thrift-converter';

const URL_IMPORT_CACHE_STORAGE_KEY = 'apiome:url-import-cache:v1';
const URL_IMPORT_CACHE_TTL_MS = 24 * 60 * 60 * 1000;

type UrlImportCacheEntry = {
  content: string;
  filename: string;
  storedAt: number;
  contentType?: string;
  fileType?: string;
};

type UrlImportCacheStore = Record<string, UrlImportCacheEntry>;

function normalizeUrlKey(url: string): string {
  try {
    return new URL(url.trim()).href;
  } catch {
    return url.trim();
  }
}

/**
 * FNV-1a 32-bit hash – fast, non-reversible, no secrets stored in the key.
 */
function fnv1a32(str: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16);
}

/**
 * Builds a stable cache key that is scoped to the URL *and* the auth inputs so
 * that changing credentials always results in a fresh fetch.  Auth secrets are
 * hashed (FNV-1a) so they are never stored verbatim in the key.
 */
function buildCacheKey(options: UrlImportOptions): string {
  const urlPart = normalizeUrlKey(options.url);
  const authParts: string[] = [options.authType ?? 'none'];
  if (options.authType === 'bearer' && options.authToken) {
    authParts.push(fnv1a32(options.authToken));
  } else if (options.authType === 'apiKey') {
    authParts.push(options.apiKeyHeader ?? 'X-API-Key');
    if (options.authToken) authParts.push(fnv1a32(options.authToken));
  } else if (options.authType === 'basic') {
    if (options.username) authParts.push(fnv1a32(options.username));
    if (options.password) authParts.push(fnv1a32(options.password));
  }
  return `${urlPart}::${authParts.join(':')}`;
}

function readUrlImportCache(cacheKey: string): UrlImportCacheEntry | null {
  if (typeof sessionStorage === 'undefined') return null;
  try {
    const raw = sessionStorage.getItem(URL_IMPORT_CACHE_STORAGE_KEY);
    if (!raw) return null;
    const store = JSON.parse(raw) as UrlImportCacheStore;
    const entry = store[cacheKey];
    if (!entry?.content || typeof entry.filename !== 'string') return null;
    const storedAt = entry.storedAt;
    if (typeof storedAt !== 'number' || !isFinite(storedAt) || Date.now() - storedAt > URL_IMPORT_CACHE_TTL_MS) {
      delete store[cacheKey];
      sessionStorage.setItem(URL_IMPORT_CACHE_STORAGE_KEY, JSON.stringify(store));
      return null;
    }
    return entry;
  } catch {
    return null;
  }
}

function writeUrlImportCache(cacheKey: string, content: string, filename: string, contentType?: string, fileType?: string): void {
  if (typeof sessionStorage === 'undefined') return;
  try {
    const raw = sessionStorage.getItem(URL_IMPORT_CACHE_STORAGE_KEY);
    const store = (raw ? JSON.parse(raw) : {}) as UrlImportCacheStore;
    store[cacheKey] = { content, filename, storedAt: Date.now(), contentType, fileType };
    sessionStorage.setItem(URL_IMPORT_CACHE_STORAGE_KEY, JSON.stringify(store));
  } catch {
    // ignore quota / private mode
  }
}

export interface UrlImportOptions {
  /** The URL to fetch the specification from */
  url: string;
  /** Authentication type */
  authType?: 'none' | 'bearer' | 'apiKey' | 'basic';
  /** Authentication token/key */
  authToken?: string;
  /** API Key header name (for apiKey auth type) */
  apiKeyHeader?: string;
  /** Username for basic auth */
  username?: string;
  /** Password for basic auth */
  password?: string;
  /** Whether to follow redirects */
  followRedirects?: boolean;
  /** When true, reuse a recent successful fetch from session cache (same normalized URL). */
  useCache?: boolean;
  /**
   * Reserved for analysis/import: whether to attempt resolving external $ref URLs.
   * The initial GET does not bundle refs; this flag is stored for downstream steps.
   */
  resolveExternalRefs?: boolean;
  /** Request timeout in milliseconds */
  timeout?: number;
}

export interface UrlImportResult {
  success: boolean;
  content?: string;
  contentType?: string;
  filename?: string;
  error?: string;
  statusCode?: number;
  headers?: Record<string, string>;
}

/**
 * Validates a URL for import
 */
export function validateImportUrl(url: string): { valid: boolean; error?: string } {
  if (!url) {
    return { valid: false, error: 'URL is required' };
  }

  const trimmedUrl = url.trim();

  if (!trimmedUrl) {
    return { valid: false, error: 'URL cannot be empty' };
  }

  // Check URL format
  try {
    const parsed = new URL(trimmedUrl);

    // Only allow http and https protocols
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      return { valid: false, error: 'Only HTTP and HTTPS URLs are supported' };
    }

    return { valid: true };
  } catch {
    return { valid: false, error: 'Invalid URL format' };
  }
}

/**
 * Extracts filename from URL or Content-Disposition header
 */
function extractFilename(url: string, headers?: Headers): string {
  // Try Content-Disposition header first
  if (headers) {
    const disposition = headers.get('content-disposition');
    if (disposition) {
      const filenameMatch = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
      if (filenameMatch && filenameMatch[1]) {
        return filenameMatch[1].replace(/['"]/g, '');
      }
    }
  }

  // Fall back to URL path
  try {
    const parsed = new URL(url);
    const pathParts = parsed.pathname.split('/').filter(Boolean);
    if (pathParts.length > 0) {
      const lastPart = pathParts[pathParts.length - 1];
      // Check if it looks like a filename
      if (lastPart.includes('.')) {
        return lastPart;
      }
    }
  } catch {
    // Ignore URL parse errors
  }

  // Default filename based on content type
  return 'openapi-spec.yaml';
}

/**
 * Detects file type from content type header or content
 */
function detectFileType(contentType: string | null, content: string): 'yaml' | 'json' | 'graphql' | 'protobuf' | 'avro' | 'thrift' | 'unknown' {
  // Check content type header
  if (contentType) {
    const lowerType = contentType.toLowerCase();
    if (lowerType.includes('yaml') || lowerType.includes('yml')) {
      return 'yaml';
    }
    if (lowerType.includes('json')) {
      return 'json';
    }
    if (lowerType.includes('avro') || lowerType.includes('x-avro')) {
      return 'avro';
    }
    if (lowerType.includes('graphql')) {
      return 'graphql';
    }
    if (lowerType.includes('protobuf') || lowerType.includes('x-protobuf')) {
      return 'protobuf';
    }
    if (lowerType.includes('thrift') || lowerType.includes('x-thrift')) {
      return 'thrift';
    }
  }

  // Detect from content
  const trimmed = content.trim();

  // JSON starts with { or [ — detect Avro schema (#239)
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      const data = JSON.parse(trimmed);
      if (isAvroSchemaObject(data)) return 'avro';
    } catch {
      // not valid JSON, fall through
    }
    return 'json';
  }

  // Protobuf (.proto) — #238
  if (isProtobuf(trimmed)) {
    return 'protobuf';
  }

  // Thrift IDL (.thrift) — #240
  if (isThrift(trimmed)) {
    return 'thrift';
  }

  // GraphQL SDL patterns
  const graphqlPatterns = [
    /^\s*type\s+\w+/m,
    /^\s*input\s+\w+/m,
    /^\s*interface\s+\w+/m,
    /^\s*enum\s+\w+/m,
    /^\s*union\s+\w+/m,
    /^\s*scalar\s+\w+/m,
    /^\s*schema\s*\{/m,
  ];

  if (graphqlPatterns.some(pattern => pattern.test(trimmed))) {
    return 'graphql';
  }

  // YAML indicators
  if (
    trimmed.startsWith('openapi:') ||
    trimmed.startsWith('swagger:') ||
    trimmed.startsWith('---') ||
    /^[a-zA-Z_][a-zA-Z0-9_]*:/.test(trimmed)
  ) {
    return 'yaml';
  }

  return 'unknown';
}

/**
 * Builds authorization headers based on auth options
 */
function buildAuthHeaders(options: UrlImportOptions): Record<string, string> {
  const headers: Record<string, string> = {};

  switch (options.authType) {
    case 'bearer':
      if (options.authToken) {
        headers['Authorization'] = `Bearer ${options.authToken}`;
      }
      break;

    case 'apiKey':
      if (options.authToken && options.apiKeyHeader) {
        headers[options.apiKeyHeader] = options.authToken;
      } else if (options.authToken) {
        // Default to X-API-Key header
        headers['X-API-Key'] = options.authToken;
      }
      break;

    case 'basic':
      if (options.username && options.password) {
        const credentials = Buffer.from(`${options.username}:${options.password}`).toString('base64');
        headers['Authorization'] = `Basic ${credentials}`;
      }
      break;
  }

  return headers;
}

/**
 * Fetches an OpenAPI specification from a URL
 */
export async function fetchSpecificationFromUrl(options: UrlImportOptions): Promise<UrlImportResult> {
  // Validate URL
  const validation = validateImportUrl(options.url);
  if (!validation.valid) {
    return {
      success: false,
      error: validation.error
    };
  }

  if (options.useCache) {
    const cacheKey = buildCacheKey(options);
    const cached = readUrlImportCache(cacheKey);
    if (cached) {
      return {
        success: true,
        content: cached.content,
        contentType: cached.contentType,
        filename: cached.filename,
        statusCode: 200,
      };
    }
  }

  try {
    // Build request headers
    const headers: Record<string, string> = {
      'Accept': 'application/json, application/yaml, application/x-yaml, text/yaml, text/x-yaml, */*',
      'User-Agent': 'Apiome-OpenAPI-Import/1.0',
      ...buildAuthHeaders(options)
    };

    // Build fetch options
    const fetchOptions: RequestInit = {
      method: 'GET',
      headers,
      redirect: options.followRedirects !== false ? 'follow' : 'manual',
    };

    // Create abort controller for timeout
    const controller = new AbortController();
    const timeout = options.timeout || 30000; // Default 30 seconds
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    try {
      const response = await fetch(options.url, {
        ...fetchOptions,
        signal: controller.signal
      });

      clearTimeout(timeoutId);

      // Check for successful response
      if (!response.ok) {
        return {
          success: false,
          error: `HTTP ${response.status}: ${response.statusText}`,
          statusCode: response.status
        };
      }

      // Get response content
      const content = await response.text();

      if (!content || !content.trim()) {
        return {
          success: false,
          error: 'Empty response received from URL',
          statusCode: response.status
        };
      }

      // Detect content type and validate it's a specification
      const contentType = response.headers.get('content-type');
      const fileType = detectFileType(contentType, content);

      if (fileType === 'unknown') {
        // Try to validate if it's valid YAML/JSON anyway
        try {
          // eslint-disable-next-line @typescript-eslint/no-require-imports
          const yaml = require('yaml');
          yaml.parse(content);
        } catch {
          return {
            success: false,
            error: 'Unable to parse response as JSON or YAML. Please check the URL returns a valid OpenAPI specification.',
            statusCode: response.status
          };
        }
      }

      // Extract filename
      const filename = extractFilename(options.url, response.headers);

      // Build headers map
      const responseHeaders: Record<string, string> = {};
      response.headers.forEach((value, key) => {
        responseHeaders[key] = value;
      });

      if (options.useCache) {
        const cacheKey = buildCacheKey(options);
        writeUrlImportCache(cacheKey, content, filename, contentType || undefined, fileType);
      }

      return {
        success: true,
        content,
        contentType: contentType || undefined,
        filename,
        statusCode: response.status,
        headers: responseHeaders
      };

    } catch (fetchError: unknown) {
      clearTimeout(timeoutId);

      if (fetchError instanceof Error) {
        if (fetchError.name === 'AbortError') {
          return {
            success: false,
            error: `Request timed out after ${timeout / 1000} seconds`
          };
        }

        return {
          success: false,
          error: `Network error: ${fetchError.message}`
        };
      }

      return {
        success: false,
        error: 'Unknown network error occurred'
      };
    }

  } catch (error: unknown) {
    if (error instanceof Error) {
      return {
        success: false,
        error: `Failed to fetch URL: ${error.message}`
      };
    }
    return {
      success: false,
      error: 'An unexpected error occurred'
    };
  }
}

/**
 * Tests if a URL is accessible (HEAD request)
 */
export async function testUrlAccessibility(options: UrlImportOptions): Promise<{
  accessible: boolean;
  statusCode?: number;
  contentType?: string;
  error?: string;
}> {
  // Validate URL
  const validation = validateImportUrl(options.url);
  if (!validation.valid) {
    return {
      accessible: false,
      error: validation.error
    };
  }

  try {
    // Build request headers
    const headers: Record<string, string> = {
      'Accept': 'application/json, application/yaml, application/x-yaml, text/yaml, text/x-yaml, */*',
      'User-Agent': 'Apiome-OpenAPI-Import/1.0',
      ...buildAuthHeaders(options)
    };

    // Create abort controller for timeout
    const controller = new AbortController();
    const timeout = options.timeout || 10000; // Default 10 seconds for HEAD
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    try {
      // Try HEAD first
      let response = await fetch(options.url, {
        method: 'HEAD',
        headers,
        redirect: options.followRedirects !== false ? 'follow' : 'manual',
        signal: controller.signal
      });

      // Some servers don't support HEAD, try GET if HEAD fails
      if (response.status === 405 || response.status === 501) {
        response = await fetch(options.url, {
          method: 'GET',
          headers,
          redirect: options.followRedirects !== false ? 'follow' : 'manual',
          signal: controller.signal
        });
      }

      clearTimeout(timeoutId);

      if (!response.ok) {
        return {
          accessible: false,
          statusCode: response.status,
          error: `HTTP ${response.status}: ${response.statusText}`
        };
      }

      return {
        accessible: true,
        statusCode: response.status,
        contentType: response.headers.get('content-type') || undefined
      };

    } catch (fetchError: unknown) {
      clearTimeout(timeoutId);

      if (fetchError instanceof Error) {
        if (fetchError.name === 'AbortError') {
          return {
            accessible: false,
            error: `Request timed out after ${timeout / 1000} seconds`
          };
        }

        return {
          accessible: false,
          error: `Network error: ${fetchError.message}`
        };
      }

      return {
        accessible: false,
        error: 'Unknown network error occurred'
      };
    }

  } catch (error: unknown) {
    if (error instanceof Error) {
      return {
        accessible: false,
        error: `Failed to test URL: ${error.message}`
      };
    }
    return {
      accessible: false,
      error: 'An unexpected error occurred'
    };
  }
}

