/**
 * Postman Collection v2.1 to OpenAPI 3.1.x Converter
 *
 * Converts Postman Collection JSON (v2.1) to OpenAPI 3.1 for use in the
 * Apiome import pipeline. Extracts paths and operations from requests,
 * maps folders to tags, and infers request/response bodies where possible.
 *
 * Ticket: #333 - Ability to import Postman Collection in Panels Import section
 */

export interface PostmanConversionResult {
  success: boolean;
  document: any;
  error?: string;
  warnings: string[];
}

// Postman Collection v2.1 types (minimal for conversion)
interface PostmanUrl {
  raw?: string;
  protocol?: string;
  host?: string[] | string;
  path?: string[] | string;
  port?: string;
  query?: Array<{ key?: string; value?: string; disabled?: boolean }>;
}

interface PostmanHeader {
  key?: string;
  value?: string;
  disabled?: boolean;
  description?: string;
}

interface PostmanBody {
  mode?: 'raw' | 'urlencoded' | 'formdata' | 'graphql' | 'file';
  raw?: string;
  options?: { raw?: { language?: string } };
}

interface PostmanRequest {
  method?: string;
  header?: PostmanHeader[];
  body?: PostmanBody;
  url?: string | PostmanUrl;
  description?: string;
}

interface PostmanItem {
  name?: string;
  item?: PostmanItem[];
  request?: PostmanRequest;
  description?: string;
}

interface PostmanInfo {
  name?: string;
  description?: string;
  schema?: string;
}

interface PostmanCollection {
  info?: PostmanInfo;
  item?: PostmanItem[];
  variable?: Array<{ key?: string; value?: string }>;
}

const POSTMAN_SCHEMA_V2_1 =
  'https://schema.getpostman.com/json/collection/v2.1.0/collection.json';
const POSTMAN_SCHEMA_V2_1_ALT =
  'https://schema.postman.com/collection/json/v2.1.0/draft-07/collection.json';

function isPostmanCollection(doc: any): boolean {
  if (!doc || typeof doc !== 'object') return false;
  const schema =
    doc.info?.schema ?? doc.schema ?? doc.__postman_variable?.schema;
  if (typeof schema === 'string') {
    return (
      schema.includes('postman.com') &&
      schema.toLowerCase().includes('collection') &&
      (schema.includes('v2.1') || schema.includes('v2.0'))
    );
  }
  // Heuristic: has info (or no openapi/swagger), has item array
  if (doc.openapi || doc.swagger) return false;
  return Array.isArray(doc.item) && (doc.info != null || doc.item.length > 0);
}

function normalizePath(url: string | PostmanUrl | undefined): string {
  if (!url) return '/';
  if (typeof url === 'string') {
    try {
      const parsed = new URL(url.startsWith('http') ? url : `https://host${url}`);
      return parsed.pathname || '/';
    } catch {
      return url.startsWith('/') ? url : `/${url}`;
    }
  }
  const path = url.path;
  if (Array.isArray(path)) return '/' + path.filter(Boolean).join('/');
  if (typeof path === 'string') return path.startsWith('/') ? path : `/${path}`;
  if (url.raw) {
    try {
      const parsed = new URL(url.raw.startsWith('http') ? url.raw : `https://host${url.raw}`);
      return parsed.pathname || '/';
    } catch {
      return (url.raw as string).startsWith('/') ? (url.raw as string) : `/${url.raw}`;
    }
  }
  return '/';
}

function normalizeMethod(method: string | undefined): string {
  const m = (method || 'GET').toUpperCase();
  const allowed = ['GET', 'PUT', 'POST', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'];
  return allowed.includes(m) ? m : 'GET';
}

function buildOpenApiPathParameters(
  url: string | PostmanUrl | undefined
): { name: string; in: string; required: boolean; schema: { type: string } }[] {
  if (!url || typeof url === 'string') return [];
  const u = url as PostmanUrl;
  const query = u.query;
  if (!Array.isArray(query) || query.length === 0) return [];
  return query
    .filter((q) => q && !q.disabled && q.key)
    .map((q) => ({
      name: q.key!,
      in: 'query' as const,
      required: false,
      schema: { type: 'string' as const }
    }));
}

function inferRequestBodySchema(body: PostmanBody | undefined): any {
  if (!body || body.mode !== 'raw' || !body.raw) return undefined;
  const raw = body.raw.trim();
  if (!raw) return undefined;
  if (raw.startsWith('{') || raw.startsWith('[')) {
    try {
      JSON.parse(raw);
      return { type: 'object', description: 'Inferred from Postman request body' };
    } catch {
      return { type: 'string', description: 'JSON body' };
    }
  }
  return { type: 'string', description: 'Request body' };
}

function collectOperations(
  items: PostmanItem[] | undefined,
  tags: string[],
  pathToOps: Map<string, Map<string, any>>
): void {
  if (!items) return;
  for (const it of items) {
    if (it.request) {
      const path = normalizePath(it.request.url);
      const method = normalizeMethod(it.request.method);
      const pathParams = buildOpenApiPathParameters(it.request.url);
      const op: any = {
        summary: it.name || `${method} ${path}`,
        description: it.request.description || it.description,
        tags: tags.length ? tags : undefined,
        parameters: pathParams.length ? pathParams : undefined
      };
      const bodySchema = inferRequestBodySchema(it.request.body);
      if (bodySchema && ['POST', 'PUT', 'PATCH'].includes(method)) {
        op.requestBody = {
          content: {
            'application/json': {
              schema: bodySchema
            }
          }
        };
      }
      if (!pathToOps.has(path)) pathToOps.set(path, new Map());
      pathToOps.get(path)!.set(method, op);
    } else if (Array.isArray(it.item)) {
      const nextTags = it.name ? [...tags, it.name] : tags;
      collectOperations(it.item, nextTags, pathToOps);
    }
  }
}

/**
 * Convert a Postman Collection v2.1 JSON object to OpenAPI 3.1.0 document.
 */
export function convertPostmanToOpenAPI(
  collection: PostmanCollection,
  options?: { baseUrl?: string }
): PostmanConversionResult {
  const warnings: string[] = [];

  if (!collection || typeof collection !== 'object') {
    return {
      success: false,
      document: null,
      error: 'Invalid collection: expected an object',
      warnings: []
    };
  }

  const info = collection.info || {};
  const pathToOps = new Map<string, Map<string, any>>();
  collectOperations(collection.item, [], pathToOps);

  const paths: Record<string, any> = {};
  for (const [path, opsByMethod] of pathToOps) {
    const pathKey = path || '/';
    const pathItem: any = {};
    for (const [method, op] of opsByMethod) {
      pathItem[method.toLowerCase()] = { ...op, responses: op.responses || { '200': { description: 'OK' } } };
    }
    paths[pathKey] = pathItem;
  }

  const servers = options?.baseUrl
    ? [{ url: options.baseUrl }]
    : [{ url: '/', description: 'Base URL from Postman (configure in your environment)' }];

  const document = {
    openapi: '3.1.0',
    info: {
      title: info.name || 'Imported from Postman Collection',
      description:
        info.description ||
        'Converted from Postman Collection v2.1. Paths and operations were extracted from requests.',
      version: '1.0.0'
    },
    servers,
    paths: Object.keys(paths).length ? paths : { '/': { get: { summary: 'Placeholder', responses: { '200': { description: 'OK' } } } } }
  };

  return {
    success: true,
    document,
    warnings
  };
}

/**
 * Check if a parsed JSON object is a Postman Collection v2.1 (or v2.0).
 */
export function isPostmanCollectionDoc(doc: any): boolean {
  return isPostmanCollection(doc);
}

/**
 * Convert Postman Collection JSON string to OpenAPI 3.1 JSON string.
 * Use this from the import panel after loading/pasting a collection.
 */
export function convertPostmanJsonToOpenAPIString(
  postmanJson: string,
  options?: { baseUrl?: string }
): PostmanConversionResult {
  let doc: PostmanCollection;
  try {
    doc = JSON.parse(postmanJson);
  } catch (e) {
    return {
      success: false,
      document: null,
      error: `Invalid JSON: ${e instanceof Error ? e.message : 'Parse error'}`,
      warnings: []
    };
  }

  if (!isPostmanCollection(doc)) {
    return {
      success: false,
      document: null,
      error:
        'Not a Postman Collection. Expected "info" and "item" with schema containing "postman.com" and "collection".',
      warnings: []
    };
  }

  const result = convertPostmanToOpenAPI(doc, options);
  return result;
}
