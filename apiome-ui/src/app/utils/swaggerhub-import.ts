/**
 * SwaggerHub Import Utility
 *
 * Handles importing OpenAPI specifications from SwaggerHub.
 * Supports both public and private APIs with API key authentication.
 */

export interface SwaggerHubImportOptions {
  owner: string;
  api: string;
  version?: string; // Optional - if not provided, fetches latest
  apiKey?: string; // Required for private APIs
}

export interface SwaggerHubImportResult {
  success: boolean;
  content?: string;
  filename?: string;
  version?: string;
  error?: string;
  isPrivate?: boolean;
}

export interface SwaggerHubApiInfo {
  name: string;
  owner: string;
  version: string;
  title?: string;
  description?: string;
  isPrivate: boolean;
}

const SWAGGERHUB_API_BASE = 'https://api.swaggerhub.com';

/**
 * Validates SwaggerHub import options
 */
export function validateSwaggerHubOptions(options: Partial<SwaggerHubImportOptions>): { valid: boolean; error?: string } {
  if (!options.owner || !options.owner.trim()) {
    return { valid: false, error: 'Owner/organization name is required' };
  }

  if (!options.api || !options.api.trim()) {
    return { valid: false, error: 'API name is required' };
  }

  // Validate owner format (alphanumeric, hyphens, underscores)
  if (!/^[a-zA-Z0-9_-]+$/.test(options.owner)) {
    return { valid: false, error: 'Invalid owner name format' };
  }

  // Validate API name format
  if (!/^[a-zA-Z0-9_-]+$/.test(options.api)) {
    return { valid: false, error: 'Invalid API name format' };
  }

  // Validate version format if provided
  if (options.version && !/^[a-zA-Z0-9._-]+$/.test(options.version)) {
    return { valid: false, error: 'Invalid version format' };
  }

  return { valid: true };
}

/**
 * Fetches an OpenAPI specification from SwaggerHub
 */
export async function fetchFromSwaggerHub(options: SwaggerHubImportOptions): Promise<SwaggerHubImportResult> {
  const validation = validateSwaggerHubOptions(options);
  if (!validation.valid) {
    return {
      success: false,
      error: validation.error
    };
  }

  try {
    const { owner, api, version, apiKey } = options;

    // If no version specified, fetch the latest version first
    let targetVersion = version;
    if (!targetVersion) {
      const versionResult = await getLatestVersion(owner, api, apiKey);
      if (!versionResult.success || !versionResult.version) {
        return {
          success: false,
          error: versionResult.error || 'Failed to determine latest version'
        };
      }
      targetVersion = versionResult.version;
    }

    // Construct the API URL
    const specUrl = `${SWAGGERHUB_API_BASE}/apis/${owner}/${api}/${targetVersion}`;

    // Prepare headers
    const headers: HeadersInit = {
      'Accept': 'application/json'
    };

    if (apiKey) {
      headers['Authorization'] = apiKey;
    }

    // Fetch the specification
    const response = await fetch(specUrl, {
      headers,
      method: 'GET'
    });

    if (!response.ok) {
      if (response.status === 401) {
        return {
          success: false,
          error: 'Authentication failed. Please check your API key.',
          isPrivate: true
        };
      } else if (response.status === 403) {
        return {
          success: false,
          error: 'Access denied. This API may be private or your API key lacks permissions.',
          isPrivate: true
        };
      } else if (response.status === 404) {
        return {
          success: false,
          error: `API not found: ${owner}/${api}/${targetVersion}`
        };
      } else {
        return {
          success: false,
          error: `Failed to fetch specification: ${response.status} ${response.statusText}`
        };
      }
    }

    // Parse response
    const content = await response.text();

    if (!content || content.trim().length === 0) {
      return {
        success: false,
        error: 'Received empty response from SwaggerHub'
      };
    }

    // Determine filename
    const filename = `${api}-${targetVersion}.json`;

    return {
      success: true,
      content,
      filename,
      version: targetVersion,
      isPrivate: !!apiKey
    };
  } catch (error) {
    console.error('SwaggerHub import error:', error);
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Failed to fetch from SwaggerHub'
    };
  }
}

/**
 * Gets the latest version of an API from SwaggerHub
 */
async function getLatestVersion(owner: string, api: string, apiKey?: string): Promise<{ success: boolean; version?: string; error?: string }> {
  try {
    const url = `${SWAGGERHUB_API_BASE}/apis/${owner}/${api}`;

    const headers: HeadersInit = {
      'Accept': 'application/json'
    };

    if (apiKey) {
      headers['Authorization'] = apiKey;
    }

    const response = await fetch(url, {
      headers,
      method: 'GET'
    });

    if (!response.ok) {
      return {
        success: false,
        error: `Failed to fetch API info: ${response.status} ${response.statusText}`
      };
    }

    const data = await response.json();

    // SwaggerHub returns APIs with versions
    if (data.apis && Array.isArray(data.apis) && data.apis.length > 0) {
      // Get the first (latest) version
      const latestApi = data.apis[0];
      const versionMatch = latestApi.properties?.find((p: any) => p.type === 'X-Version');
      if (versionMatch && versionMatch.value) {
        return {
          success: true,
          version: versionMatch.value
        };
      }

      // Fallback: parse from API URL
      const urlParts = latestApi.url?.split('/');
      if (urlParts && urlParts.length > 0) {
        const version = urlParts[urlParts.length - 1];
        return {
          success: true,
          version
        };
      }
    }

    return {
      success: false,
      error: 'Could not determine latest version'
    };
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Failed to fetch API version info'
    };
  }
}

/**
 * Searches for APIs in SwaggerHub (requires API key for private APIs)
 */
export async function searchSwaggerHubApis(query: string, apiKey?: string): Promise<{ success: boolean; apis?: SwaggerHubApiInfo[]; error?: string }> {
  try {
    const url = `${SWAGGERHUB_API_BASE}/specs?query=${encodeURIComponent(query)}&limit=20`;

    const headers: HeadersInit = {
      'Accept': 'application/json'
    };

    if (apiKey) {
      headers['Authorization'] = apiKey;
    }

    const response = await fetch(url, {
      headers,
      method: 'GET'
    });

    if (!response.ok) {
      return {
        success: false,
        error: `Search failed: ${response.status} ${response.statusText}`
      };
    }

    const data = await response.json();

    const apis: SwaggerHubApiInfo[] = [];
    if (data.apis && Array.isArray(data.apis)) {
      for (const apiData of data.apis) {
        const urlParts = apiData.url?.split('/') || [];
        apis.push({
          name: apiData.name || urlParts[urlParts.length - 2] || 'Unknown',
          owner: apiData.owner || urlParts[urlParts.length - 3] || 'Unknown',
          version: apiData.version || urlParts[urlParts.length - 1] || '1.0.0',
          title: apiData.title,
          description: apiData.description,
          isPrivate: apiData.private || false
        });
      }
    }

    return {
      success: true,
      apis
    };
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Search failed'
    };
  }
}

