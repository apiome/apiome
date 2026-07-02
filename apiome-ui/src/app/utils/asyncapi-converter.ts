/**
 * AsyncAPI to OpenAPI 3.1.x Converter (for Import)
 *
 * Converts AsyncAPI 2.x / 3.x definition files to an OpenAPI 3.1–shaped document
 * so the existing import pipeline (components.schemas, $ref) can be reused.
 *
 * Only components.schemas are imported; channels, operations, and message bindings
 * are not mapped to the class model.
 */

export interface AsyncAPIConversionResult {
  success: boolean;
  document: any;
  error?: string;
  warnings: string[];
}

/**
 * Detect if the document is an AsyncAPI specification.
 */
export function isAsyncAPI(doc: any): boolean {
  return doc != null && typeof doc === 'object' && typeof doc.asyncapi === 'string';
}

/**
 * Convert AsyncAPI document to an OpenAPI 3.1–like document for import.
 * Preserves components.schemas and normalizes info; $ref paths (#/components/schemas/...)
 * are left unchanged as they match OpenAPI.
 */
export function convertAsyncAPIToOpenAPI(doc: any, _fileName?: string): AsyncAPIConversionResult {
  const warnings: string[] = [];

  if (!doc || typeof doc !== 'object') {
    return {
      success: false,
      document: null,
      error: 'Invalid or empty document',
      warnings: [],
    };
  }

  if (!isAsyncAPI(doc)) {
    return {
      success: false,
      document: null,
      error: 'Document is not an AsyncAPI specification',
      warnings: [],
    };
  }

  const version = doc.asyncapi;
  const isV3 = version.startsWith('3.');
  const isV2 = version.startsWith('2.');

  if (!isV2 && !isV3) {
    return {
      success: false,
      document: null,
      error: `Unsupported AsyncAPI version: ${version}. Only 2.x and 3.x are supported.`,
      warnings: [],
    };
  }

  // AsyncAPI 2.x and 3.x both use components.schemas; $ref format is #/components/schemas/Name
  const schemas = doc.components?.schemas ?? {};
  if (typeof schemas !== 'object') {
    return {
      success: false,
      document: null,
      error: 'Invalid components.schemas in AsyncAPI document',
      warnings: [],
    };
  }

  const schemaCount = Object.keys(schemas).length;
  const hasChannels = doc.channels && typeof doc.channels === 'object' && Object.keys(doc.channels).length > 0;
  if (schemaCount === 0) {
    warnings.push('No components.schemas found. Only schema definitions are imported; channels and message payloads are not extracted.');
  } else if (hasChannels) {
    warnings.push('Channels and operations are not imported; only components.schemas are added as classes.');
  }

  // Build minimal OpenAPI 3.1 document for the importer
  const info = doc.info ?? {};
  const openApiDoc = {
    openapi: '3.1.0',
    info: {
      title: info.title ?? 'Imported from AsyncAPI',
      version: info.version ?? '1.0.0',
      description: info.description ?? (isV3 ? 'Converted from AsyncAPI 3.x' : 'Converted from AsyncAPI 2.x'),
    },
    components: {
      schemas: { ...schemas },
    },
  };

  return {
    success: true,
    document: openApiDoc,
    warnings,
  };
}
