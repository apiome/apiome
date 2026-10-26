/**
 * Path Item operation walk, including OpenAPI 3.2.0 `query` and
 * `additionalOperations` (OA4, #3501).
 *
 * OpenAPI 3.2 declares operations two ways the fixed verb list cannot see:
 *  - `query` — the HTTP QUERY method (safe, body-bearing);
 *  - `additionalOperations` — a map of any other HTTP method, keyed by its token
 *    exactly as sent on the wire (e.g. `REPORT`, `LINK`).
 *
 * The OA2 normalization layer ({@link ./openapi32-converter.ts}) stashes them on
 * `x-apiome-query-operation` and `x-apiome-additional-operations`. This module reads
 * the raw 3.2 fields and the stashes alike, so an importer walks every operation of a
 * Path Item in one uniform shape whether or not the document was normalized.
 */

/** OpenAPI documents are walked untyped, like the other OpenAPI import utilities. */
/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * OpenAPI 3.0–3.2 fixed Path Item operation fields, in the order the importer has
 * always walked them (so path import order is unchanged).
 */
export const FIXED_HTTP_METHODS = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'] as const;

/** Extension the OA2 layer stashes a Path Item's `query` operation on. */
export const STASHED_QUERY_OPERATION_EXTENSION = 'x-apiome-query-operation';

/** Extension the OA2 layer stashes a Path Item's `additionalOperations` map on. */
export const STASHED_ADDITIONAL_OPERATIONS_EXTENSION = 'x-apiome-additional-operations';

/**
 * Where an operation was declared on its Path Item.
 *
 * - `fixed` — one of {@link FIXED_HTTP_METHODS}.
 * - `query` — the 3.2 `query` field.
 * - `additionalOperations` — an entry of the 3.2 `additionalOperations` map.
 */
export type PathOperationSource = 'fixed' | 'query' | 'additionalOperations';

/** One operation of a Path Item. */
export interface PathItemOperation {
  /** The key as written in the document (`get`, `query`, `REPORT`); stable for locations. */
  key: string;
  /** The HTTP method token as sent on the wire (`GET`, `QUERY`, `REPORT`). */
  method: string;
  /** Upper-cased method, used to de-duplicate (`GET` and `get` are one operation). */
  normalizedMethod: string;
  /** Where the operation was declared. */
  source: PathOperationSource;
  /** The Operation Object. */
  operation: any;
}

/** Whether a value is a non-array object. */
function isObject(value: unknown): value is Record<string, any> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * List every operation of a Path Item: the fixed verbs, then `query`, then the
 * `additionalOperations` entries (raw fields before their OA2 stashes).
 *
 * A method declared more than once (e.g. `additionalOperations.GET` beside `get`,
 * which the 3.2 spec forbids, or a raw field beside its stash) is listed once: the
 * first declaration wins and the rest are reported in `duplicates`.
 *
 * @param pathItem - an OpenAPI Path Item Object.
 * @returns the operations in walk order, and the method tokens that were skipped as duplicates.
 */
export function listPathItemOperations(pathItem: any): { operations: PathItemOperation[]; duplicates: string[] } {
  const operations: PathItemOperation[] = [];
  const duplicates: string[] = [];
  if (!isObject(pathItem)) return { operations, duplicates };

  const seen = new Set<string>();
  const add = (key: string, method: string, source: PathOperationSource, operation: unknown): void => {
    if (!isObject(operation) || !method.trim()) return;
    const normalizedMethod = method.trim().toUpperCase();
    if (seen.has(normalizedMethod)) {
      duplicates.push(method);
      return;
    }
    seen.add(normalizedMethod);
    operations.push({ key, method: method.trim(), normalizedMethod, source, operation });
  };

  for (const verb of FIXED_HTTP_METHODS) {
    add(verb, verb.toUpperCase(), 'fixed', pathItem[verb]);
  }
  add('query', 'QUERY', 'query', pathItem.query);
  add('query', 'QUERY', 'query', pathItem[STASHED_QUERY_OPERATION_EXTENSION]);
  for (const mapKey of ['additionalOperations', STASHED_ADDITIONAL_OPERATIONS_EXTENSION]) {
    const map = pathItem[mapKey];
    if (!isObject(map)) continue;
    for (const [method, operation] of Object.entries(map)) {
      add(method, method, 'additionalOperations', operation);
    }
  }

  return { operations, duplicates };
}
