/**
 * OpenAPI Version Configuration
 *
 * This file manages OpenAPI specification versions and their corresponding templates.
 * Update this configuration when upgrading to newer OpenAPI versions.
 */

export interface OpenAPIVersion {
  version: string;
  templateFile: string;
  description: string;
  supportedFeatures: string[];
}

/**
 * Available OpenAPI versions and their configurations
 */
export const OPENAPI_VERSIONS: Record<string, OpenAPIVersion> = {
  '3.1.0': {
    version: '3.1.0',
    templateFile: 'openapi/openapi-spec.hbs',
    description: 'OpenAPI 3.1.0 specification (JSON Schema 2020-12 compatible)',
    supportedFeatures: [
      'JSON Schema 2020-12',
      'Webhooks',
      'Schema composition (allOf, anyOf, oneOf)',
      'Nested properties',
      'Full JSON Schema vocabulary'
    ]
  },
  '3.2.0': {
    version: '3.2.0',
    templateFile: 'openapi/openapi-spec.hbs',
    description: 'OpenAPI 3.2.0 specification (Studio export default for merged paths + components)',
    supportedFeatures: [
      'Paths + components export',
      'JSON Schema 2020-12 (as in OAS 3.2)',
      'Schema composition (allOf, anyOf, oneOf)',
      'Nested properties'
    ]
  },
};

/**
 * Default OpenAPI version for class-only and legacy callers
 */
export const DEFAULT_OPENAPI_VERSION = '3.1.0';

/** Studio merged export (paths + components) uses OpenAPI 3.2 (#2655). */
export const STUDIO_EXPORT_OPENAPI_VERSION = '3.2.0';

/**
 * Get configuration for a specific OpenAPI version
 */
export function getOpenAPIVersionConfig(version?: string): OpenAPIVersion {
  const targetVersion = version || DEFAULT_OPENAPI_VERSION;
  const config = OPENAPI_VERSIONS[targetVersion];

  if (!config) {
    throw new Error(`Unsupported OpenAPI version: ${targetVersion}. Supported versions: ${Object.keys(OPENAPI_VERSIONS).join(', ')}`);
  }

  return config;
}

