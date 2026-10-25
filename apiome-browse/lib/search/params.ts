/**
 * The search request: everything a results page needs, resolved from the URL.
 *
 * Two inputs feed one request. The query text carries inline filters (`method:POST`) and the URL
 * carries rail filters (`?method=POST`); a visitor may use either, or both, and the SQL must see
 * one merged picture. {@link resolveSearchRequest} does that merge once, so the rail, the chips,
 * the pagination and the SQL never disagree about what is being searched.
 *
 * Round-trips: {@link toSearchParams} serializes a request back to a URL, and
 * {@link patchSearchRequest} changes one dimension (a filter, the page, the sort) while keeping the
 * rest, which is how every control on the page navigates.
 *
 * Pure; unit-tested in `lib/search/__tests__/params.test.ts`.
 */

import { HIT_KINDS, SCOPE_KINDS, resolveHitKind, resolveScope, type HitKind, type SearchScope } from './kinds';
import { EMPTY_QUERY, parseQuery, type ParsedQuery } from './query';

export const SEARCH_SORTS = ['relevance', 'newest', 'oldest', 'name'] as const;
export type SearchSort = (typeof SEARCH_SORTS)[number];

export const SEARCH_SORT_LABELS: Readonly<Record<SearchSort, string>> = {
  relevance: 'Relevance',
  newest: 'Newest published',
  oldest: 'Oldest published',
  name: 'Name A–Z',
};

/** Results per page; one size, so page numbers in shared links stay meaningful. */
export const SEARCH_PAGE_SIZE = 25;

/** Hard ceiling on how deep pagination goes; past this the visitor should narrow the query. */
export const SEARCH_MAX_PAGE = 40;

/** The resolved request the SQL builder consumes. */
export interface SearchRequest {
  /** The raw query text as typed (sanitized upstream). */
  q: string;
  /** The parsed query text. */
  parsed: ParsedQuery;
  /** The results tab. */
  scope: SearchScope;
  /** Kinds to return: the explicit `type` selection within the scope, or the whole scope. */
  kinds: HitKind[];
  /** Explicit `type` selection, as the URL carries it (empty = whole scope). */
  types: HitKind[];
  /** Organization slugs (or names) to restrict to; empty = any. */
  orgs: string[];
  /** Project slugs (or names) to restrict to; empty = any. */
  projects: string[];
  /** Version labels (substring) to restrict to; empty = any. */
  versions: string[];
  /** HTTP methods (upper-case) to restrict operations to; empty = any. */
  methods: string[];
  /** Path substrings operations must contain; empty = any. */
  paths: string[];
  /** Source-format keys (lower-case) a version must carry; empty = any. */
  formats: string[];
  /** Paradigm keys (lower-case) a version must carry; empty = any. */
  paradigms: string[];
  /** Tag names a version must carry; empty = any. */
  tags: string[];
  /** ISO date (YYYY-MM-DD) lower bound on `published_at`, inclusive. */
  after: string | null;
  /** ISO date (YYYY-MM-DD) upper bound on `published_at`, exclusive. */
  before: string | null;
  /** Ordering. */
  sort: SearchSort;
  /** 1-based page. */
  page: number;
  /** Page size. */
  perPage: number;
  /** When true, search every published version; otherwise only each project's latest. */
  allVersions: boolean;
}

/** The URL-facing shape: what a page or a link can set. */
export interface SearchUrlState {
  q?: string;
  scope?: string;
  type?: string | string[];
  org?: string | string[];
  method?: string | string[];
  format?: string | string[];
  paradigm?: string | string[];
  after?: string;
  before?: string;
  sort?: string;
  page?: string;
  all?: string;
}

/** Split a repeated-or-comma-separated URL value into clean tokens. */
export function splitParam(value: string | string[] | null | undefined): string[] {
  const raw = Array.isArray(value) ? value : value == null ? [] : [value];
  const out: string[] = [];
  for (const item of raw) {
    for (const piece of String(item).split(',')) {
      const token = piece.trim();
      if (token && !out.includes(token)) out.push(token);
    }
  }
  return out;
}

/**
 * Keep only well-formed ISO dates (YYYY-MM-DD, YYYY-MM, or YYYY) and expand them to a full date.
 *
 * A partial date means the start of its period on either bound: `after:2026-03` is "from 1 March",
 * `before:2026-03` is "before 1 March". Anything else — including an impossible day — is dropped
 * rather than guessed at.
 */
export function normalizeDate(value: string | null | undefined): string | null {
  const text = (value ?? '').trim();
  const match = /^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$/.exec(text);
  if (!match) return null;
  const year = Number(match[1]);
  const month = match[2] ? Number(match[2]) : 1;
  const day = match[3] ? Number(match[3]) : 1;
  if (year < 1970 || year > 2200 || month < 1 || month > 12 || day < 1 || day > 31) return null;
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return date.toISOString().slice(0, 10);
}

function resolveSort(raw: string | null | undefined, hasText: boolean): SearchSort {
  const key = (raw ?? '').trim().toLowerCase();
  if ((SEARCH_SORTS as readonly string[]).includes(key)) return key as SearchSort;
  // Without words to rank by, "relevance" is meaningless; a filter-only browse lists newest first.
  return hasText ? 'relevance' : 'newest';
}

function resolvePage(raw: string | null | undefined): number {
  const n = Number.parseInt((raw ?? '').trim(), 10);
  if (!Number.isFinite(n) || n < 1) return 1;
  return Math.min(n, SEARCH_MAX_PAGE);
}

function union(a: readonly string[], b: readonly string[]): string[] {
  const out: string[] = [];
  for (const v of [...a, ...b]) if (v && !out.includes(v)) out.push(v);
  return out;
}

/**
 * Build the resolved request from URL state.
 *
 * Inline filters in `q` and rail filters in the URL are merged (union per dimension). The kinds
 * are the intersection of the scope and any explicit `type` selection (from the URL *or* from
 * `type:` in the query), so `scope=schemas&type=operation` yields no kinds rather than a
 * contradiction the SQL has to guess at.
 *
 * @param state The URL search params, as Next hands them to a page.
 * @returns The request.
 */
export function resolveSearchRequest(state: SearchUrlState): SearchRequest {
  const q = (state.q ?? '').trim();
  const parsed = q ? parseQuery(q) : EMPTY_QUERY;
  const f = parsed.filters;

  const scope = resolveScope(state.scope);
  const scopeKinds = SCOPE_KINDS[scope];

  const typeTokens = union(splitParam(state.type), f.type ?? []);
  const types = typeTokens.map(resolveHitKind).filter((k): k is HitKind => k != null);
  const kinds = types.length > 0 ? types.filter((k) => scopeKinds.includes(k)) : [...scopeKinds];

  const methods = union(
    splitParam(state.method).map((m) => m.toUpperCase()),
    f.method ?? []
  );

  const hasText = parsed.terms.length > 0 || parsed.phrases.length > 0;

  return {
    q,
    parsed,
    scope,
    kinds,
    types: types.filter((k) => scopeKinds.includes(k)),
    orgs: union(splitParam(state.org).map((s) => s.toLowerCase()), f.org ?? []),
    projects: [...(f.project ?? [])],
    versions: [...(f.version ?? [])],
    methods,
    paths: [...(f.path ?? [])],
    formats: union(splitParam(state.format).map((s) => s.toLowerCase()), f.format ?? []),
    paradigms: union(splitParam(state.paradigm).map((s) => s.toLowerCase()), f.paradigm ?? []),
    tags: [...(f.tag ?? [])],
    after: normalizeDate(state.after ?? f.after?.[f.after.length - 1]),
    before: normalizeDate(state.before ?? f.before?.[f.before.length - 1]),
    sort: resolveSort(state.sort, hasText),
    page: resolvePage(state.page),
    perPage: SEARCH_PAGE_SIZE,
    allVersions: state.all === '1' || state.all === 'true',
  };
}

/**
 * Whether the request asks for anything — words, or at least one filter dimension. An empty
 * request renders the landing state instead of running SQL.
 */
export function isEmptyRequest(request: SearchRequest): boolean {
  const { parsed } = request;
  return (
    parsed.terms.length === 0 &&
    parsed.phrases.length === 0 &&
    request.types.length === 0 &&
    request.orgs.length === 0 &&
    request.projects.length === 0 &&
    request.versions.length === 0 &&
    request.methods.length === 0 &&
    request.paths.length === 0 &&
    request.formats.length === 0 &&
    request.paradigms.length === 0 &&
    request.tags.length === 0 &&
    request.after == null &&
    request.before == null
  );
}

/**
 * The URL state a request serializes to. Only the URL-level dimensions are written; inline
 * filters stay inside `q`. Defaults are omitted so links stay short.
 */
export function toUrlState(request: SearchRequest): SearchUrlState {
  const state: SearchUrlState = {};
  if (request.q) state.q = request.q;
  if (request.scope !== 'all') state.scope = request.scope;
  // Only the rail's own selections go back to the URL: anything that came in via `type:` in the
  // query text is already in `q`.
  const inlineTypes = new Set((request.parsed.filters.type ?? []).map(resolveHitKind));
  const urlTypes = request.types.filter((k) => !inlineTypes.has(k));
  if (urlTypes.length > 0) state.type = urlTypes.join(',');
  const inlineOrgs = new Set(request.parsed.filters.org ?? []);
  const urlOrgs = request.orgs.filter((o) => !inlineOrgs.has(o));
  if (urlOrgs.length > 0) state.org = urlOrgs.join(',');
  const inlineMethods = new Set(request.parsed.filters.method ?? []);
  const urlMethods = request.methods.filter((m) => !inlineMethods.has(m));
  if (urlMethods.length > 0) state.method = urlMethods.join(',');
  const inlineFormats = new Set(request.parsed.filters.format ?? []);
  const urlFormats = request.formats.filter((v) => !inlineFormats.has(v));
  if (urlFormats.length > 0) state.format = urlFormats.join(',');
  const inlineParadigms = new Set(request.parsed.filters.paradigm ?? []);
  const urlParadigms = request.paradigms.filter((v) => !inlineParadigms.has(v));
  if (urlParadigms.length > 0) state.paradigm = urlParadigms.join(',');
  if (request.after && !request.parsed.filters.after) state.after = request.after;
  if (request.before && !request.parsed.filters.before) state.before = request.before;
  const hasText = request.parsed.terms.length > 0 || request.parsed.phrases.length > 0;
  const defaultSort: SearchSort = hasText ? 'relevance' : 'newest';
  if (request.sort !== defaultSort) state.sort = request.sort;
  if (request.page > 1) state.page = String(request.page);
  if (request.allVersions) state.all = '1';
  return state;
}

/** Serialize URL state to a query string (without the leading `?`). */
export function toSearchParams(state: SearchUrlState): string {
  const params = new URLSearchParams();
  const order: (keyof SearchUrlState)[] = [
    'q',
    'scope',
    'type',
    'org',
    'method',
    'format',
    'paradigm',
    'after',
    'before',
    'sort',
    'all',
    'page',
  ];
  for (const key of order) {
    const value = state[key];
    if (value == null) continue;
    const text = Array.isArray(value) ? value.join(',') : String(value);
    if (text) params.set(key, text);
  }
  return params.toString();
}

/** The `/search?…` href for a request. */
export function searchHref(request: SearchRequest): string {
  const qs = toSearchParams(toUrlState(request));
  return qs ? `/search?${qs}` : '/search';
}

/** A patch: any URL-level dimension, with `null` meaning "clear". */
export type SearchPatch = {
  [K in keyof SearchUrlState]?: SearchUrlState[K] | null;
};

/**
 * Apply a patch to a request's URL state. Changing anything but the page resets the page, since a
 * page number only means something against the result set it was counted in.
 *
 * @param request The current request.
 * @param patch The dimensions to change.
 * @returns The next URL state.
 */
export function patchSearchRequest(request: SearchRequest, patch: SearchPatch): SearchUrlState {
  const state = toUrlState(request);
  const keys = Object.keys(patch) as (keyof SearchUrlState)[];
  for (const key of keys) {
    const value = patch[key];
    if (value == null || value === '' || (Array.isArray(value) && value.length === 0)) {
      delete state[key];
    } else {
      (state as Record<string, string | string[]>)[key] = value;
    }
  }
  if (!(keys.length === 1 && keys[0] === 'page')) delete state.page;
  return state;
}

/**
 * Toggle one value in a multi-valued URL dimension (org, method, type, format, paradigm).
 */
export function toggleUrlValue(
  request: SearchRequest,
  key: 'org' | 'method' | 'type' | 'format' | 'paradigm',
  value: string
): SearchUrlState {
  const state = toUrlState(request);
  const current = splitParam(state[key]);
  const normalized = key === 'method' ? value.toUpperCase() : value.toLowerCase();
  const next = current.includes(normalized)
    ? current.filter((v) => v !== normalized)
    : [...current, normalized];
  return patchSearchRequest(request, { [key]: next.length > 0 ? next.join(',') : null });
}

/** All kinds, for callers that want to iterate the vocabulary without importing kinds.ts. */
export const ALL_HIT_KINDS = HIT_KINDS;
