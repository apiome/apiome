
/**
 * URL Import Utility
 *
 * Provides functionality to fetch OpenAPI specifications from URLs
 * with support for authentication and various options.
 */

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
function detectFileType(contentType: string | null, content: string): 'yaml' | 'json' | 'graphql' | 'unknown' {
  // Check content type header
  if (contentType) {
    const lowerType = contentType.toLowerCase();
    if (lowerType.includes('yaml') || lowerType.includes('yml')) {
      return 'yaml';
    }
    if (lowerType.includes('json')) {
      return 'json';
    }
    if (lowerType.includes('graphql')) {
      return 'graphql';
    }
  }

  // Detect from content
  const trimmed = content.trim();

  // JSON starts with { or [
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    return 'json';
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

  try {
    // Build request headers
    const headers: Record<string, string> = {
      'Accept': 'application/json, application/yaml, application/x-yaml, text/yaml, text/x-yaml, */*',
      'User-Agent': 'Objectified-OpenAPI-Import/1.0',
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
      'User-Agent': 'Objectified-OpenAPI-Import/1.0',
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

