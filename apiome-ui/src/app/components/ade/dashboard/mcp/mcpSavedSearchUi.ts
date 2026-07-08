/**
 * Saved catalog searches — types and pure helpers (V2-MCP-35.3 / MCAT-21.3, #4662).
 *
 * Persists named filter bundles per user/tenant so operators can save, recall, and re-run catalog
 * searches; pinned searches surface as quick-access catalog "views".
 */

import {
  MCP_CATALOG_DEFAULT_SORT,
  MCP_CATALOG_EMPTY_FILTERS,
  mcpNormalizeSortKey,
  type McpCatalogFilters,
  type McpCatalogSortKey,
} from './mcpCatalogUi';

/** One saved catalog search returned by the REST API. */
export interface McpSavedSearch {
  id: string;
  name: string;
  filters: McpCatalogFilters;
  query: string;
  sort: McpCatalogSortKey;
  isPinned: boolean;
  createdAt: string;
  updatedAt: string;
}

/** Parse a saved-search filters object defensively. */
export function mcpSavedSearchFiltersFromPayload(raw: unknown): McpCatalogFilters {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return { ...MCP_CATALOG_EMPTY_FILTERS };
  }
  const obj = raw as Record<string, unknown>;
  const list = (key: keyof McpCatalogFilters): string[] => {
    const value = obj[key];
    if (!Array.isArray(value)) return [];
    return value.filter((v): v is string => typeof v === 'string' && v.trim().length > 0);
  };
  return {
    hosts: list('hosts'),
    grades: list('grades'),
    transports: list('transports'),
    visibilities: list('visibilities'),
    auths: list('auths'),
    categories: list('categories'),
    safeties: list('safeties'),
    complexities: list('complexities'),
    protocols: list('protocols'),
    healths: list('healths'),
  };
}

/** Parse one saved search from the REST payload. */
export function mcpSavedSearchFromPayload(raw: unknown): McpSavedSearch | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const obj = raw as Record<string, unknown>;
  const id = typeof obj.id === 'string' ? obj.id : '';
  const name = typeof obj.name === 'string' ? obj.name.trim() : '';
  if (!id || !name) return null;
  return {
    id,
    name,
    filters: mcpSavedSearchFiltersFromPayload(obj.filters),
    query: typeof obj.query === 'string' ? obj.query : '',
    sort: mcpNormalizeSortKey(typeof obj.sort === 'string' ? obj.sort : null),
    isPinned: obj.isPinned === true || obj.is_pinned === true,
    createdAt: typeof obj.createdAt === 'string' ? obj.createdAt : '',
    updatedAt: typeof obj.updatedAt === 'string' ? obj.updatedAt : '',
  };
}

/** Parse a list response envelope. */
export function mcpSavedSearchesFromPayload(raw: unknown): McpSavedSearch[] {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return [];
  const searches = (raw as { searches?: unknown }).searches;
  if (!Array.isArray(searches)) return [];
  return searches
    .map((item) => mcpSavedSearchFromPayload(item))
    .filter((item): item is McpSavedSearch => item !== null);
}

/** Build a create payload from the current catalog control state. */
export function mcpSavedSearchCreateBody(
  name: string,
  filters: McpCatalogFilters,
  query: string,
  sort: McpCatalogSortKey,
  isPinned: boolean,
): Record<string, unknown> {
  return {
    name: name.trim(),
    filters,
    query,
    sort: sort || MCP_CATALOG_DEFAULT_SORT,
    isPinned,
  };
}

/** Apply a saved search onto catalog control state. */
export function mcpApplySavedSearch(search: McpSavedSearch): {
  filters: McpCatalogFilters;
  query: string;
  sort: McpCatalogSortKey;
} {
  return {
    filters: { ...search.filters },
    query: search.query,
    sort: search.sort,
  };
}

/** Pinned saved searches for the catalog views strip. */
export function mcpPinnedSavedSearches(searches: McpSavedSearch[]): McpSavedSearch[] {
  return searches.filter((s) => s.isPinned);
}
