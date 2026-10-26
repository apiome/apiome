/**
 * OpenAPI 3.2.0 sequential & streaming media types (OA3, #3500).
 *
 * OpenAPI 3.2 lets a Media Type Object carry `itemSchema` to describe each element
 * of a stream (JSON Lines, JSON text sequences, Server-Sent Events, ...). The OA2
 * normalization layer ({@link ./openapi32-converter.ts}) stashes that field on
 * `x-apiome-item-schema`; this module consumes the stash (or a raw `itemSchema`,
 * for documents that were not normalized) so the importer can treat the element
 * schema as a first-class schema source:
 *
 *  - {@link getStreamKind} classifies a media type into a stream family.
 *  - {@link collectStreamMediaTypes} lists every streaming media type in a document
 *    (used by the analyzer's feature report).
 *  - {@link applyStreamItemSchemas} returns a copy of the document in which every
 *    object-shaped inline element schema is hoisted into `components.schemas` (so it
 *    imports as a class), and every element class is tagged with
 *    {@link STREAM_KIND_EXTENSION} provenance metadata.
 */

/** OpenAPI documents are walked untyped, like the other OpenAPI import utilities. */
/* eslint-disable @typescript-eslint/no-explicit-any */

import { listPathItemOperations } from './openapi-path-operations';

/**
 * Stream family of a sequential media type.
 *
 * - `jsonl` — JSON Lines (`application/jsonl`, `+jsonl`).
 * - `json-seq` — JSON text sequences, RFC 7464 (`application/json-seq`, `+json-seq`).
 * - `sse` — Server-Sent Events (`text/event-stream`).
 * - `sequential` — any other media type that declares an `itemSchema`
 *   (e.g. a stream of `application/problem+json` documents), and the kind used when
 *   one class is the element of streams of different families.
 */
export type StreamKind = 'jsonl' | 'json-seq' | 'sse' | 'sequential';

/** Extension that marks an imported class as the element of a stream. */
export const STREAM_KIND_EXTENSION = 'x-apiome-stream-kind';

/** Extension the OA2 normalization layer stashes `itemSchema` on. */
export const STASHED_ITEM_SCHEMA_EXTENSION = 'x-apiome-item-schema';

/** Human-readable names for each stream kind (analyzer report). */
export const STREAM_KIND_LABELS: Record<StreamKind, string> = {
  jsonl: 'JSON Lines',
  'json-seq': 'JSON text sequence',
  sse: 'Server-Sent Events',
  sequential: 'sequential media type',
};

/** One streaming media type found in a document. */
export interface StreamMediaTypeOccurrence {
  /** Location of the Media Type Object, e.g. `paths./logs.get.responses.200`. */
  location: string;
  /** The media type key as written in the document. */
  mediaType: string;
  /** Stream family of the media type. */
  kind: StreamKind;
  /** Whether the Media Type Object declares an element schema (`itemSchema`). */
  hasItemSchema: boolean;
}

const COMPONENT_SCHEMA_REF = /^#\/components\/schemas\/(.+)$/;

/**
 * Classify a media type into its stream family.
 *
 * Parameters (`; charset=utf-8`) and case are ignored.
 *
 * @param mediaType - media type key, e.g. `text/event-stream`.
 * @param hasItemSchema - whether the Media Type Object declares an `itemSchema`;
 *   an unrecognized media type with an `itemSchema` is still a stream (`sequential`).
 * @returns the stream kind, or `null` when the media type is not a stream.
 */
export function getStreamKind(mediaType: string, hasItemSchema = false): StreamKind | null {
  const base = String(mediaType ?? '').split(';')[0].trim().toLowerCase();
  if (base === 'application/jsonl' || base.endsWith('+jsonl')) return 'jsonl';
  if (base === 'application/json-seq' || base.endsWith('+json-seq')) return 'json-seq';
  if (base === 'text/event-stream') return 'sse';
  return hasItemSchema ? 'sequential' : null;
}

/**
 * Read the element schema of a Media Type Object.
 *
 * @param mediaObj - a Media Type Object.
 * @returns the raw `itemSchema`, else the OA2 stash `x-apiome-item-schema`, else `undefined`.
 */
export function getMediaTypeItemSchema(mediaObj: any): any {
  if (!mediaObj || typeof mediaObj !== 'object') return undefined;
  if (mediaObj.itemSchema !== undefined) return mediaObj.itemSchema;
  return mediaObj[STASHED_ITEM_SCHEMA_EXTENSION];
}

/** A Media Type Object visited by {@link forEachMediaType}. */
interface MediaTypeVisit {
  /** The Media Type Object (mutable when walking a cloned document). */
  mediaObj: any;
  mediaType: string;
  /** Location of the content map's owner (operation response / request body / component). */
  location: string;
  /** Base used to name a hoisted inline element schema. */
  nameBase: string;
}

/**
 * Turn an arbitrary string into PascalCase (`list-logs` → `ListLogs`).
 *
 * @param value - source text.
 * @returns the PascalCase identifier; empty when `value` has no letters or digits.
 */
function toPascalCase(value: string): string {
  return String(value)
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('');
}

/**
 * Visit every Media Type Object of a content map.
 */
function visitContent(content: any, location: string, nameBase: string, visit: (v: MediaTypeVisit) => void): void {
  if (!content || typeof content !== 'object') return;
  for (const [mediaType, mediaObj] of Object.entries<any>(content)) {
    if (!mediaObj || typeof mediaObj !== 'object') continue;
    visit({ mediaObj, mediaType, location, nameBase });
  }
}

/**
 * Visit the request-body and response media types of one operation.
 */
function visitOperation(op: any, location: string, nameBase: string, visit: (v: MediaTypeVisit) => void): void {
  if (!op || typeof op !== 'object') return;
  if (op.requestBody && typeof op.requestBody === 'object' && !op.requestBody.$ref) {
    visitContent(op.requestBody.content, `${location}.requestBody`, `${nameBase}Request`, visit);
  }
  if (op.responses && typeof op.responses === 'object') {
    for (const [status, res] of Object.entries<any>(op.responses)) {
      if (!res || typeof res !== 'object' || res.$ref) continue;
      visitContent(res.content, `${location}.responses.${status}`, nameBase, visit);
    }
  }
}

/**
 * Walk every request-body and response Media Type Object of a document: path
 * operations (including the 3.2 `query` method and `additionalOperations`, raw or as
 * stashed by OA2) and `components.requestBodies` / `components.responses`.
 *
 * @param doc - an OpenAPI document.
 * @param visit - called once per Media Type Object.
 */
function forEachMediaType(doc: any, visit: (v: MediaTypeVisit) => void): void {
  if (!doc || typeof doc !== 'object') return;

  const paths = doc.paths;
  if (paths && typeof paths === 'object') {
    for (const [pathName, pathItem] of Object.entries<any>(paths)) {
      if (!pathItem || typeof pathItem !== 'object') continue;
      for (const { key, operation: op } of listPathItemOperations(pathItem).operations) {
        const nameBase =
          (typeof op.operationId === 'string' && toPascalCase(op.operationId)) ||
          toPascalCase(`${key} ${pathName}`);
        visitOperation(op, `paths.${pathName}.${key}`, nameBase, visit);
      }
    }
  }

  const components = doc.components;
  if (components && typeof components === 'object') {
    for (const key of ['requestBodies', 'responses'] as const) {
      const map = components[key];
      if (!map || typeof map !== 'object') continue;
      for (const [name, entry] of Object.entries<any>(map)) {
        if (!entry || typeof entry !== 'object' || entry.$ref) continue;
        visitContent(entry.content, `components.${key}.${name}`, toPascalCase(name), visit);
      }
    }
  }
}

/**
 * List every streaming media type in a document: media types of a known stream
 * family (with or without `itemSchema`) and any media type that declares an
 * `itemSchema`.
 *
 * @param doc - an OpenAPI document (raw 3.2, or normalized by OA2).
 * @returns the occurrences in document order.
 */
export function collectStreamMediaTypes(doc: any): StreamMediaTypeOccurrence[] {
  const result: StreamMediaTypeOccurrence[] = [];
  forEachMediaType(doc, ({ mediaObj, mediaType, location }) => {
    const hasItemSchema = getMediaTypeItemSchema(mediaObj) !== undefined;
    const kind = getStreamKind(mediaType, hasItemSchema);
    if (kind) result.push({ location, mediaType, kind, hasItemSchema });
  });
  return result;
}

/**
 * Whether an inline element schema is object-shaped and therefore worth a class.
 * Primitive elements (e.g. a `string` SSE `data` field) stay inline.
 */
function isClassLikeSchema(schema: any): boolean {
  if (!schema || typeof schema !== 'object' || Array.isArray(schema) || schema.$ref) return false;
  const hasProperties = schema.properties && typeof schema.properties === 'object' && Object.keys(schema.properties).length > 0;
  return Boolean(hasProperties || Array.isArray(schema.allOf));
}

/**
 * Record the stream kind of an element class. A class that is the element of
 * streams of different families is tagged with the generic `sequential` kind.
 */
function tagStreamKind(schema: any, kind: StreamKind): void {
  if (!schema || typeof schema !== 'object') return;
  const existing = schema[STREAM_KIND_EXTENSION];
  schema[STREAM_KIND_EXTENSION] = existing && existing !== kind ? 'sequential' : kind;
}

/**
 * Prepare a document's stream element schemas for import.
 *
 * The input is never mutated. In the returned copy:
 *  - an object-shaped inline `itemSchema` is moved to `components.schemas` under a
 *    generated name (`<OperationId>StreamItem`, de-duplicated with a numeric suffix)
 *    and replaced with a `$ref`, so it imports as a class like any component;
 *  - every component schema used as a stream element (by `$ref` or hoisted) carries
 *    `x-apiome-stream-kind` (see {@link StreamKind}).
 *
 * Deterministic: the same document always yields the same names, so the class and
 * path importers can each call it and agree.
 *
 * @param doc - an OpenAPI document (raw 3.2, or normalized by OA2).
 * @returns the original document when it has no element schemas, else the prepared copy.
 */
export function applyStreamItemSchemas(doc: any): any {
  let hasElementSchemas = false;
  forEachMediaType(doc, ({ mediaObj }) => {
    if (getMediaTypeItemSchema(mediaObj) !== undefined) hasElementSchemas = true;
  });
  if (!hasElementSchemas) return doc;

  const out = JSON.parse(JSON.stringify(doc));
  if (!out.components || typeof out.components !== 'object') out.components = {};
  if (!out.components.schemas || typeof out.components.schemas !== 'object') out.components.schemas = {};
  const schemas = out.components.schemas;

  forEachMediaType(out, ({ mediaObj, mediaType, nameBase }) => {
    const itemKey = mediaObj.itemSchema !== undefined ? 'itemSchema' : STASHED_ITEM_SCHEMA_EXTENSION;
    const itemSchema = mediaObj[itemKey];
    if (itemSchema === undefined) return;
    const kind = getStreamKind(mediaType, true) as StreamKind;

    if (itemSchema && typeof itemSchema === 'object' && typeof itemSchema.$ref === 'string') {
      const match = itemSchema.$ref.match(COMPONENT_SCHEMA_REF);
      if (match && schemas[match[1]]) tagStreamKind(schemas[match[1]], kind);
      return;
    }

    if (!isClassLikeSchema(itemSchema)) return;

    const base = `${nameBase || 'Stream'}StreamItem`;
    let name = base;
    for (let n = 2; schemas[name] !== undefined; n++) name = `${base}${n}`;
    schemas[name] = { ...itemSchema };
    tagStreamKind(schemas[name], kind);
    mediaObj[itemKey] = { $ref: `#/components/schemas/${name}` };
  });

  return out;
}
