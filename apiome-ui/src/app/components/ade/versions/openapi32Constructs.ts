/**
 * The OpenAPI 3.2 constructs in a revision's generated document (COA-2.5, #7048), as the spec
 * viewer lists them above the code.
 *
 * Reads the JSON text the screen builds (`buildOpenApiSpecJsonForVersion`) and lists what a 3.2
 * document adds: operations declared with `query` or `additionalOperations`, the tag hierarchy
 * (`parent` / `summary` / `kind`), streaming media types (`itemSchema`) and `in: querystring`
 * parameters. A document that does not declare `openapi: 3.2.x` has none of them, so the summary is
 * `null` and the viewer shows nothing extra.
 */

/** OpenAPI documents are walked untyped, like the other OpenAPI utilities. */
/* eslint-disable @typescript-eslint/no-explicit-any */

import { listPathItemOperations } from '@/app/utils/openapi-path-operations';
import { collectStreamMediaTypes, STREAM_KIND_LABELS, type StreamKind } from '@/app/utils/openapi-stream-media-types';

/** An operation declared outside the fixed verbs. */
export interface Openapi32Operation {
  path: string;
  /** The method token as sent on the wire (`QUERY`, `REPORT`). */
  method: string;
  /** `query` for the Path Item's `query` field, else `additionalOperations`. */
  source: 'query' | 'additionalOperations';
  operationId?: string;
}

/** A tag carrying any 3.2 field. */
export interface Openapi32Tag {
  name: string;
  summary?: string;
  parent?: string;
  kind?: string;
}

/** A streaming media type. */
export interface Openapi32Stream {
  /** Where the Media Type Object is, e.g. `paths./logs.get.responses.200`. */
  location: string;
  mediaType: string;
  /** Human-readable stream family (`JSON Lines`, `Server-Sent Events`). */
  kindLabel: string;
  hasItemSchema: boolean;
}

/** An `in: querystring` parameter. */
export interface Openapi32Querystring {
  path: string;
  method: string;
  name: string;
  /** The media type of its `content`, when declared. */
  mediaType?: string;
}

/** Everything a 3.2 document adds. */
export interface Openapi32Summary {
  /** The declared version (`3.2.0`). */
  openapi: string;
  operations: Openapi32Operation[];
  tags: Openapi32Tag[];
  streams: Openapi32Stream[];
  querystring: Openapi32Querystring[];
}

/**
 * Parse the spec text, or return null when it is not a JSON object.
 *
 * @param spec - the JSON text.
 * @returns the document, or null.
 */
function parseSpec(spec: string): any | null {
  if (!spec || !spec.trim()) return null;
  try {
    const doc = JSON.parse(spec);
    return doc && typeof doc === 'object' && !Array.isArray(doc) ? doc : null;
  } catch {
    return null;
  }
}

/**
 * The declared OpenAPI version of a spec.
 *
 * @param spec - the JSON text.
 * @returns the `openapi` value (`3.2.0`), or null when it is missing or unreadable.
 */
export function specOpenapiVersion(spec: string): string | null {
  const doc = parseSpec(spec);
  return doc && typeof doc.openapi === 'string' ? doc.openapi : null;
}

/**
 * List the OpenAPI 3.2 constructs of a spec.
 *
 * @param spec - the JSON text.
 * @returns the summary, or null when the document is not OpenAPI 3.2 or declares none of them.
 */
export function summarizeOpenapi32Constructs(spec: string): Openapi32Summary | null {
  const doc = parseSpec(spec);
  if (!doc || typeof doc.openapi !== 'string' || !/^3\.2(\.|$)/.test(doc.openapi)) return null;

  const operations: Openapi32Operation[] = [];
  const querystring: Openapi32Querystring[] = [];
  const paths = doc.paths && typeof doc.paths === 'object' ? doc.paths : {};
  for (const [path, pathItem] of Object.entries<any>(paths)) {
    for (const op of listPathItemOperations(pathItem).operations) {
      if (op.source !== 'fixed') {
        operations.push({
          path,
          method: op.method,
          source: op.source,
          ...(typeof op.operation.operationId === 'string' ? { operationId: op.operation.operationId } : {}),
        });
      }
      const params = [
        ...(Array.isArray(pathItem?.parameters) ? pathItem.parameters : []),
        ...(Array.isArray(op.operation.parameters) ? op.operation.parameters : []),
      ];
      for (const param of params) {
        if (param?.in !== 'querystring') continue;
        const mediaType = param.content && typeof param.content === 'object' ? Object.keys(param.content)[0] : undefined;
        querystring.push({ path, method: op.method, name: String(param.name ?? ''), ...(mediaType ? { mediaType } : {}) });
      }
    }
  }

  const tags: Openapi32Tag[] = (Array.isArray(doc.tags) ? doc.tags : [])
    .filter((tag: any) => tag && typeof tag.name === 'string' && (tag.parent || tag.summary || tag.kind))
    .map((tag: any) => ({
      name: tag.name,
      ...(typeof tag.summary === 'string' ? { summary: tag.summary } : {}),
      ...(typeof tag.parent === 'string' ? { parent: tag.parent } : {}),
      ...(typeof tag.kind === 'string' ? { kind: tag.kind } : {}),
    }));

  const streams: Openapi32Stream[] = collectStreamMediaTypes(doc).map((s) => ({
    location: s.location,
    mediaType: s.mediaType,
    kindLabel: STREAM_KIND_LABELS[s.kind as StreamKind],
    hasItemSchema: s.hasItemSchema,
  }));

  if (operations.length + tags.length + streams.length + querystring.length === 0) return null;
  return { openapi: doc.openapi, operations, tags, streams, querystring };
}
