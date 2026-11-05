/**
 * The Studio half of the OpenAPI test drive (Swagger UI / ReDoc) — MFX-44.2 (#4368).
 *
 * The emitted document is parsed here, in the Studio, and posted into the sandboxed viewer page
 * (`/test-drive/openapi`, see `lib/test-drive/openapi-viewer.ts`) — it never makes a server round-trip.
 * While a test-drive mock (MFX-44.5) is running, the document's servers are pointed at it and Swagger
 * UI's **Try it out** is on: the viewer posts each request here, and only a request under the mock's
 * base URL is sent, through the same authenticated proxy the Mock server tab uses.
 */

import { parse as parseYaml } from 'yaml';

import type { OpenApiViewerKind } from '@lib/test-drive/openapi-viewer';

export type { OpenApiViewerKind } from '@lib/test-drive/openapi-viewer';

/** The prefix of every message the viewer page and the Studio exchange. */
export const TEST_DRIVE_MESSAGE_PREFIX = 'apiome-test-drive:';

/** A document with more operations than this renders collapsed (Swagger UI) or lighter (ReDoc). */
export const LARGE_SPEC_OPERATIONS = 300;

/** A document larger than this, in characters, renders the same way. */
export const LARGE_SPEC_CHARS = 1_000_000;

/** HTTP methods an OpenAPI path item can hold. */
const OPERATION_METHODS = ['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'];

/** A parsed OpenAPI document, ready for a viewer. */
export interface OpenApiTestDriveDocument {
  /** The document as an object. */
  spec: Record<string, unknown>;
  /** `openapi` (3.x) or `swagger` (2.0) version string. */
  version: string;
  /** How many operations it declares. */
  operations: number;
  /** Whether it is large enough to render collapsed. */
  large: boolean;
}

/** The outcome of reading an emitted file as OpenAPI. */
export type OpenApiParseResult = { ok: true; document: OpenApiTestDriveDocument } | { ok: false; error: string };

/**
 * Count a document's operations.
 *
 * @param spec An OpenAPI document.
 * @returns The number of method entries across its `paths`.
 */
export function countOperations(spec: Record<string, unknown>): number {
  const paths = spec.paths;
  if (!paths || typeof paths !== 'object') return 0;
  let count = 0;
  for (const item of Object.values(paths as Record<string, unknown>)) {
    if (!item || typeof item !== 'object') continue;
    count += OPERATION_METHODS.filter((method) => method in (item as Record<string, unknown>)).length;
  }
  return count;
}

/**
 * Read an emitted file as an OpenAPI 2.0 / 3.x document.
 *
 * @param text The file's text (JSON or YAML).
 * @returns The document, or why it cannot be shown.
 */
export function parseOpenApiDocument(text: string): OpenApiParseResult {
  let value: unknown;
  try {
    value = text.trimStart().startsWith('{') ? JSON.parse(text) : parseYaml(text);
  } catch (error) {
    return { ok: false, error: `The file is not valid JSON or YAML: ${error instanceof Error ? error.message : error}` };
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { ok: false, error: 'The file is not an OpenAPI document.' };
  }
  const spec = value as Record<string, unknown>;
  const version = typeof spec.openapi === 'string' ? spec.openapi : typeof spec.swagger === 'string' ? spec.swagger : null;
  if (!version) return { ok: false, error: 'The file has no `openapi` or `swagger` version, so it is not an OpenAPI document.' };
  const operations = countOperations(spec);
  return {
    ok: true,
    document: { spec, version, operations, large: operations > LARGE_SPEC_OPERATIONS || text.length > LARGE_SPEC_CHARS },
  };
}

/**
 * The document with its servers pointed at a running mock, so Try it out reaches it.
 *
 * @param spec The document; not modified.
 * @param baseUrl The mock's base URL.
 * @returns A copy whose only server is the mock (`servers` for 3.x; `schemes`/`host`/`basePath` for 2.0).
 */
export function withMockServer(spec: Record<string, unknown>, baseUrl: string): Record<string, unknown> {
  if (typeof spec.swagger === 'string') {
    const url = new URL(baseUrl);
    return { ...spec, schemes: [url.protocol.replace(':', '')], host: url.host, basePath: url.pathname };
  }
  return { ...spec, servers: [{ url: baseUrl, description: 'Test-drive mock server' }] };
}

/**
 * The request path a viewer's request asks the mock for — only when it is under the mock.
 *
 * @param url The absolute URL the viewer requested.
 * @param baseUrl The running mock's base URL.
 * @returns The path and query relative to the mock (`/pets?limit=1`), or null for anything else.
 */
export function mockRequestPath(url: string, baseUrl: string): string | null {
  let requested: URL;
  let base: URL;
  try {
    requested = new URL(url);
    base = new URL(baseUrl);
  } catch {
    return null;
  }
  const prefix = base.pathname.replace(/\/+$/, '');
  if (requested.origin !== base.origin) return null;
  if (requested.pathname !== prefix && !requested.pathname.startsWith(`${prefix}/`)) return null;
  const path = requested.pathname.slice(prefix.length) || '/';
  return `${path}${requested.search}`;
}

/**
 * The viewer page for one viewer.
 *
 * @param viewer Swagger UI or ReDoc.
 * @returns The iframe's `src`.
 */
export function openApiViewerSrc(viewer: OpenApiViewerKind): string {
  return `/test-drive/openapi?viewer=${viewer}`;
}

/** Whether a message is one of the viewer's, of the given kind. */
export function isTestDriveMessage(data: unknown, kind: string): data is Record<string, unknown> {
  return Boolean(data) && typeof data === 'object' && (data as { type?: unknown }).type === `${TEST_DRIVE_MESSAGE_PREFIX}${kind}`;
}
