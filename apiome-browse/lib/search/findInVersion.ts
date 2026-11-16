/**
 * Find inside one version (BDX-1.3).
 *
 * The catalog search (`./sql.ts`) answers "where in the directory is X"; this module answers
 * "where on *this* page is X" — over the spec the version page already loaded, in the browser, with
 * no server round trip. It reads the same query language (`./query.ts`), so `method:DELETE pets`
 * means the same thing in the find box as it does in the catalog box.
 *
 * ### What is searched
 *
 * - **Operations** (OpenAPI): method, path, summary, description, operationId, tags, parameter
 *   names and response codes.
 * - **Schemas** (OpenAPI `components.schemas` / `definitions`, JSON Schema `$defs` /
 *   `definitions`): name, title, description and property names.
 * - **Workflows** (Arazzo): workflow id, summary and description.
 *
 * ### How a query matches an item
 *
 * - Every word and every phrase must appear somewhere in the item (case-insensitive substring).
 * - No negated word may appear.
 * - `method:` keeps operations with one of the methods; items without a method drop out.
 * - `path:` keeps operations whose path contains one of the values; items without a path drop out.
 * - `type:` keeps items of one of the kinds (`operation`, `schema`, `workflow`, or an alias the
 *   catalog accepts, such as `op`, `endpoint`, `model`, `class`).
 * - Filters that only make sense across the catalog (`org:`, `project:`, `version:`, …) are
 *   ignored here — every item on the page is already in that org, project and version.
 *
 * Pure: no React, no DOM. Unit-tested in `lib/search/__tests__/findInVersion.test.ts`.
 */

import { operationAnchorId, schemaAnchorId } from './anchors';
import { resolveHitKind } from './kinds';
import { textNeedles, type ParsedQuery } from './query';

/** The kinds of item the find box can match on a version page. */
export type FindItemKind = 'operation' | 'schema' | 'workflow';

/** The spec formats the version page renders. */
export type FindSpecFormat = 'openapi' | 'arazzo' | 'jsonschema';

/** One searchable item on the version page. */
export interface FindItem {
  /** What the item is. */
  kind: FindItemKind;
  /** The element id the page renders the item under (`op-get-pets`, `schema-Pet`, `wf-…`). */
  anchorId: string;
  /** Upper-cased HTTP method, operations only. */
  method?: string;
  /** The path template, operations only. */
  path?: string;
  /** Every searchable string of the item, lower-cased and joined with newlines. */
  haystack: string;
}

/** What the find box needs to render a result. */
export interface FindResult {
  /** Whether the query has anything to search for. When false, nothing is filtered. */
  active: boolean;
  /** Anchor ids of the matching items, in page order (operations, then schemas / workflows). */
  anchors: string[];
  /** The same anchor ids as a set, for O(1) "is this row a match" checks while rendering. */
  matched: ReadonlySet<string>;
  /** How many items the page has in total (the "of 42" in "3 of 42"). */
  total: number;
  /** The words and phrases to highlight, longest first. */
  needles: string[];
}

/** HTTP methods an OpenAPI path item may declare, in the order the page lists them. */
const HTTP_METHODS = ['get', 'post', 'put', 'patch', 'delete', 'options', 'head', 'trace'] as const;

/** `type:` values that mean "workflow" (the catalog has no workflow kind, so these live here). */
const WORKFLOW_KIND_ALIASES = new Set(['workflow', 'workflows', 'wf', 'arazzo']);

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** The strings among `values`, skipping anything else. */
function strings(values: readonly unknown[]): string[] {
  return values.filter((v): v is string => typeof v === 'string' && v.length > 0);
}

/** Lower-case and join the searchable strings of one item. */
function haystackOf(parts: readonly (string | undefined)[]): string {
  return parts
    .filter((p): p is string => typeof p === 'string' && p.length > 0)
    .join('\n')
    .toLowerCase();
}

/**
 * Property names of a schema: its own `properties`, plus those of its direct `allOf` / `oneOf` /
 * `anyOf` members — the shapes a reader sees as "the fields of this schema".
 */
function propertyNames(schema: Record<string, unknown>): string[] {
  const names: string[] = [];
  const collect = (node: unknown) => {
    if (isObject(node) && isObject(node.properties)) names.push(...Object.keys(node.properties));
  };
  collect(schema);
  for (const key of ['allOf', 'oneOf', 'anyOf'] as const) {
    const members = schema[key];
    if (Array.isArray(members)) members.forEach(collect);
  }
  return names;
}

/** One schema item from its name and (possibly missing) definition. */
function schemaItem(name: string, raw: unknown, anchorId: string): FindItem {
  const schema = isObject(raw) ? raw : {};
  return {
    kind: 'schema',
    anchorId,
    haystack: haystackOf([
      name,
      typeof schema.title === 'string' ? schema.title : undefined,
      typeof schema.description === 'string' ? schema.description : undefined,
      ...propertyNames(schema),
    ]),
  };
}

/** Operations and schemas of an OpenAPI (or Swagger 2) document, in page order. */
function openApiItems(spec: Record<string, unknown>): FindItem[] {
  const items: FindItem[] = [];
  const paths = isObject(spec.paths) ? spec.paths : {};

  for (const [path, pathItemRaw] of Object.entries(paths)) {
    if (!isObject(pathItemRaw)) continue;
    // Path-level parameters apply to every operation under the path.
    const sharedParams = Array.isArray(pathItemRaw.parameters) ? pathItemRaw.parameters : [];
    for (const method of HTTP_METHODS) {
      const op = pathItemRaw[method];
      if (!isObject(op)) continue;
      const params = [...sharedParams, ...(Array.isArray(op.parameters) ? op.parameters : [])];
      const paramNames = params.map((p) => (isObject(p) && typeof p.name === 'string' ? p.name : undefined));
      const responseCodes = isObject(op.responses) ? Object.keys(op.responses) : [];
      items.push({
        kind: 'operation',
        anchorId: operationAnchorId(method, path),
        method: method.toUpperCase(),
        path,
        haystack: haystackOf([
          method.toUpperCase(),
          path,
          typeof op.summary === 'string' ? op.summary : undefined,
          typeof op.description === 'string' ? op.description : undefined,
          typeof op.operationId === 'string' ? op.operationId : undefined,
          ...strings(Array.isArray(op.tags) ? op.tags : []),
          ...paramNames,
          ...responseCodes,
        ]),
      });
    }
  }

  const components = isObject(spec.components) ? spec.components : null;
  const componentSchemas = components && isObject(components.schemas) ? components.schemas : {};
  const legacyDefinitions = isObject(spec.definitions) ? spec.definitions : {};
  const names = [
    ...new Set([...Object.keys(componentSchemas), ...Object.keys(legacyDefinitions)]),
  ].sort((a, b) => a.localeCompare(b));
  for (const name of names) {
    const raw = isObject(componentSchemas[name]) ? componentSchemas[name] : legacyDefinitions[name];
    items.push(schemaItem(name, raw, schemaAnchorId(name)));
  }
  return items;
}

/** Workflows of an Arazzo document. Anchor ids match `SpecViewer` / `SpecSidebar` (`wf-<id>`). */
function arazzoItems(spec: Record<string, unknown>): FindItem[] {
  const workflows = Array.isArray(spec.workflows) ? spec.workflows : [];
  return workflows.flatMap((w, idx) => {
    if (!isObject(w)) return [];
    const id = typeof w.workflowId === 'string' ? w.workflowId : `workflow-${idx}`;
    return [
      {
        kind: 'workflow' as const,
        anchorId: `wf-${id}`,
        haystack: haystackOf([
          id,
          typeof w.summary === 'string' ? w.summary : undefined,
          typeof w.description === 'string' ? w.description : undefined,
        ]),
      },
    ];
  });
}

/** Top-level definitions of a JSON Schema document. Anchor ids match the page (`def-<name>`). */
function jsonSchemaItems(spec: Record<string, unknown>): FindItem[] {
  const defs =
    (isObject(spec.$defs) && spec.$defs) || (isObject(spec.definitions) && spec.definitions) || null;
  if (!defs) return [];
  return Object.entries(defs).map(([name, raw]) =>
    schemaItem(name, raw, `def-${name.replace(/[^a-z0-9]+/gi, '-')}`)
  );
}

/**
 * Project a loaded spec into the flat list of items the find box searches.
 *
 * @param spec The spec object the page loaded; anything that is not an object yields no items.
 * @param format Which document the page is showing.
 * @returns The items in the order the page renders them.
 */
export function buildFindItems(spec: unknown, format: FindSpecFormat): FindItem[] {
  if (!isObject(spec)) return [];
  if (format === 'openapi') return openApiItems(spec);
  if (format === 'arazzo') return arazzoItems(spec);
  return jsonSchemaItems(spec);
}

/**
 * Resolve the `type:` values of a query to item kinds. Unknown values resolve to nothing, so
 * `type:banana` matches no item rather than being silently ignored.
 */
function wantedKinds(values: readonly string[]): Set<FindItemKind> {
  const kinds = new Set<FindItemKind>();
  for (const value of values) {
    if (WORKFLOW_KIND_ALIASES.has(value.trim().toLowerCase())) {
      kinds.add('workflow');
      continue;
    }
    const kind = resolveHitKind(value);
    // The catalog's finer kinds (parameter, response, property) live inside an operation or a
    // schema on this page, so they narrow to the item that holds them.
    if (kind === 'operation' || kind === 'parameter' || kind === 'request_body' || kind === 'response') {
      kinds.add('operation');
    } else if (kind === 'schema' || kind === 'property') {
      kinds.add('schema');
    }
  }
  return kinds;
}

/**
 * Whether the query has anything this page can filter on: a word, a phrase, a negated word, or
 * one of the `method:` / `path:` / `type:` filters. Catalog-only filters on their own do not
 * count, so `org:acme` alone leaves the page unfiltered.
 */
export function isFindActive(parsed: ParsedQuery): boolean {
  return (
    parsed.terms.length > 0 ||
    parsed.phrases.length > 0 ||
    parsed.negated.length > 0 ||
    (parsed.filters.method?.length ?? 0) > 0 ||
    (parsed.filters.path?.length ?? 0) > 0 ||
    (parsed.filters.type?.length ?? 0) > 0
  );
}

/**
 * Whether one item matches a parsed query. See the module comment for the rules.
 *
 * @param item The item to test.
 * @param parsed The parsed find query.
 * @returns True when the item satisfies every word, phrase and filter and no negation.
 */
export function matchesFindItem(item: FindItem, parsed: ParsedQuery): boolean {
  const has = (needle: string) => item.haystack.includes(needle.toLowerCase());
  if (!parsed.terms.every(has)) return false;
  if (!parsed.phrases.every(has)) return false;
  if (parsed.negated.some(has)) return false;

  const methods = parsed.filters.method ?? [];
  if (methods.length > 0 && (!item.method || !methods.includes(item.method.toUpperCase()))) return false;

  const paths = parsed.filters.path ?? [];
  if (paths.length > 0) {
    const path = item.path?.toLowerCase();
    if (!path || !paths.some((p) => path.includes(p.toLowerCase()))) return false;
  }

  const types = parsed.filters.type ?? [];
  if (types.length > 0 && !wantedKinds(types).has(item.kind)) return false;

  return true;
}

/**
 * Run a find query over the page's items.
 *
 * @param items The page's items, from {@link buildFindItems}.
 * @param parsed The parsed query (`parseQuery(find)`).
 * @returns The matches in page order, the total, and the needles to highlight. An inactive query
 *   returns every item as matched, so callers can filter unconditionally.
 */
export function findInVersion(items: readonly FindItem[], parsed: ParsedQuery): FindResult {
  const active = isFindActive(parsed);
  // Anchors repeat when the same operation is listed under several tags — count each once.
  const anchors = [
    ...new Set((active ? items.filter((i) => matchesFindItem(i, parsed)) : items).map((i) => i.anchorId)),
  ];
  return {
    active,
    anchors,
    matched: new Set(anchors),
    total: new Set(items.map((i) => i.anchorId)).size,
    needles: active ? textNeedles(parsed) : [],
  };
}

/**
 * The anchor the `↵` key should jump to next.
 *
 * @param anchors Matching anchors in page order.
 * @param current The anchor last jumped to (or the active one), if any.
 * @param direction `1` for next (`↵`), `-1` for previous (`⇧↵`).
 * @returns The anchor to jump to, wrapping around at either end; null when nothing matches.
 */
export function nextFindAnchor(
  anchors: readonly string[],
  current: string | null | undefined,
  direction: 1 | -1 = 1
): string | null {
  if (anchors.length === 0) return null;
  const at = current ? anchors.indexOf(current) : -1;
  if (at < 0) return direction === 1 ? anchors[0] : anchors[anchors.length - 1];
  return anchors[(at + direction + anchors.length) % anchors.length];
}

/** The URL parameter that carries the find query (`?find=method:DELETE%20pets`). */
export const FIND_PARAM = 'find';

/**
 * Rewrite a URL so its `?find=` matches the query, keeping every other parameter and the hash.
 *
 * @param href The current URL (absolute or relative to `base`).
 * @param find The query text; blank removes the parameter.
 * @param base The base for relative hrefs (defaults to a dummy origin; only path, query and hash
 *   are returned).
 * @returns The path, query string and hash of the rewritten URL.
 */
export function withFindParam(href: string, find: string, base = 'http://localhost'): string {
  const url = new URL(href, base);
  const value = find.trim();
  if (value) url.searchParams.set(FIND_PARAM, value);
  else url.searchParams.delete(FIND_PARAM);
  return `${url.pathname}${url.search}${url.hash}`;
}
