/**
 * Public MCP catalog sort ordering (V2-MCP-23.7 / MCAT-9.7).
 *
 * The public MCP browse pages resolve to **grade-led** ranking when idle (no query) but foreground
 * **relevance** while a search term is present, with service grade as the tiebreaker. This module
 * is the single source of truth for that decision so the SQL helper and the UI sort control stay in
 * lock-step. It is deliberately pure (no DB, no React, no Next imports) and therefore unit-testable.
 */

/** The two ranking modes the public catalog offers. */
export type McpSortMode = 'top_graded' | 'relevance';

/** Default label shown by the sort control for each mode. */
export const MCP_SORT_LABELS: Record<McpSortMode, string> = {
  top_graded: 'Top graded',
  relevance: 'Relevance',
};

/**
 * The mode a fresh view should default to for a given query:
 * - grade-led (`top_graded`) when the query is empty/whitespace (idle browse), and
 * - relevance-first (`relevance`) while a search term is present.
 *
 * Callers pass the user's raw query; only emptiness matters here, so trimming is sufficient (the
 * pages sanitize input upstream via `sanitizeSearchInput`).
 */
export function resolveDefaultSortMode(query: string | null | undefined): McpSortMode {
  return query && query.trim().length > 0 ? 'relevance' : 'top_graded';
}

/**
 * Coerce an arbitrary string (e.g. a URL search param) to a valid {@link McpSortMode}, falling back
 * to the query-derived default when it is missing or unrecognized.
 */
export function coerceSortMode(raw: string | null | undefined, query: string): McpSortMode {
  if (raw === 'top_graded' || raw === 'relevance') return raw;
  return resolveDefaultSortMode(query);
}

/**
 * The `ORDER BY` tail for a catalog query in the given mode. The grade glyph (A–F) is the lead
 * signal, so grade ascends (A first) with ungraded endpoints last; `score` then breaks ties within
 * a grade and the endpoint name gives a stable final order. In `relevance` mode the full-text
 * `relevance` rank (the `ts_rank(...) AS relevance` column produced by the search query) leads, with
 * grade as the tiebreaker — exactly the 9.7 acceptance wording.
 *
 * `nameColumn` names the (already-aliased) endpoint-name column to use as the final tiebreak; it
 * differs between queries (`name` for browse, `endpoint_name` for search, where a bare `name` would
 * be ambiguous against `mcp_capability_items.name`). It is only ever an internal constant, never
 * user input, so — like the per-mode constants — the result is always safe to splice into SQL.
 */
export function mcpSortOrderSql(mode: McpSortMode, nameColumn = 'name'): string {
  const gradeLed = `grade ASC NULLS LAST, score DESC NULLS LAST, ${nameColumn} ASC`;
  return mode === 'relevance' ? `relevance DESC, ${gradeLed}` : gradeLed;
}
