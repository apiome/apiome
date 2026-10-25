'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from 'react';
import { formatLabel, paradigmLabel } from '../../../lib/browseFacets';
import { groupHitsByKind, hitHref, type CatalogSearchResponse } from '../../../lib/search/hits';
import {
  HIT_KIND_LABELS,
  SCOPE_KINDS,
  SEARCH_SCOPES,
  SEARCH_SCOPE_LABELS,
  type HitKind,
  type SearchScope,
} from '../../../lib/search/kinds';
import {
  SEARCH_SORTS,
  SEARCH_SORT_LABELS,
  patchSearchRequest,
  toSearchParams,
  toUrlState,
  toggleUrlValue,
  type SearchRequest,
  type SearchSort,
  type SearchUrlState,
} from '../../../lib/search/params';
import {
  FILTER_KEY_LABELS,
  stringifyQuery,
  textNeedles,
  withFilter,
  type FilterKey,
} from '../../../lib/search/query';
import type { McpPublicSearchHit } from '../../../lib/types';
import { AppShell } from '../components/AppShell';
import { GradeBadge } from '../mcp/McpShared';
import { FacetRail, type FacetRailActions } from '../components/search/FacetRail';
import { Highlight } from '../components/search/Highlight';
import { HitRow } from '../components/search/HitRow';
import { SearchBox } from '../components/search/SearchBox';
import { OperatorChips, SyntaxHelpCard } from '../components/search/SyntaxHelp';
import { RECENT_SEARCHES_KEY, clearRecentSearches, pushRecentSearch } from '../components/search/searchPaletteBus';
import { useStoredPref } from '../components/search/useStoredPref';

const GROUP_KEY = 'apiome-browse:search-grouped';
const parseGrouped = (raw: string) => raw !== '0';
const serializeGrouped = (value: boolean) => (value ? '1' : '0');
const parseRecent = (raw: string): string[] => {
  const parsed = JSON.parse(raw) as unknown;
  return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : [];
};
const NO_RECENT: string[] = [];

const EXAMPLE_QUERIES = [
  { label: 'POST operations', q: 'method:POST' },
  { label: 'Order schemas', q: 'type:schema order' },
  { label: 'Anything about payments', q: 'payments' },
  { label: '"webhook" phrases', q: '"webhook"' },
  { label: 'Published this year', q: 'after:2026' },
];

const BROWSE_TILES: { title: string; hint: string; state: SearchUrlState }[] = [
  { title: 'Operations', hint: 'Every operation in the latest versions', state: { type: 'operation' } },
  { title: 'Schemas', hint: 'Every data model', state: { type: 'schema' } },
  { title: 'Projects', hint: 'Every public project', state: { scope: 'catalog', type: 'project' } },
  { title: 'Organizations', hint: 'Every publisher', state: { scope: 'catalog', type: 'organization' } },
  { title: 'Recent versions', hint: 'Newest published first', state: { scope: 'catalog', type: 'version', all: '1' } },
];

interface ActiveChip {
  key: string;
  label: string;
  value: string;
  remove: () => SearchUrlState;
}

function Spinner({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg className={`${className} animate-spin text-[var(--brand)]`} fill="none" viewBox="0 0 24 24" aria-hidden>
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

/**
 * The results page. The URL is the state: every control navigates, the server re-runs the
 * engine, and this component renders what came back. Local state is limited to the text in the
 * box, the keyboard cursor, the group toggle and the mobile filter drawer.
 */
export function SearchClient({
  request,
  response,
  mcpHits,
  mcpQuery,
}: {
  request: SearchRequest;
  response: CatalogSearchResponse;
  mcpHits: McpPublicSearchHit[];
  mcpQuery: string;
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  // The box's text follows the URL's `q` until the visitor types; keying the draft on the
  // request's `q` resets it on navigation without an effect.
  const [draft, setDraft] = useState<{ base: string; value: string }>({ base: request.q, value: request.q });
  const query = draft.base === request.q ? draft.value : request.q;
  const setQuery = useCallback((value: string) => setDraft({ base: request.q, value }), [request.q]);
  const [grouped, setGrouped] = useStoredPref<boolean>(GROUP_KEY, true, parseGrouped, serializeGrouped);
  const [recent] = useStoredPref<string[]>(RECENT_SEARCHES_KEY, NO_RECENT, parseRecent);
  // The keyboard cursor belongs to one response; a new response starts with no row selected.
  const [cursorState, setCursorState] = useState<{ response: CatalogSearchResponse; index: number } | null>(null);
  const cursor = cursorState && cursorState.response === response ? cursorState.index : -1;
  const setCursor = useCallback(
    (update: number | ((current: number) => number)) =>
      setCursorState((prev) => {
        const current = prev && prev.response === response ? prev.index : -1;
        return { response, index: typeof update === 'function' ? update(current) : update };
      }),
    [response]
  );
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const needles = useMemo(() => textNeedles(request.parsed), [request.parsed]);
  const hasText = request.parsed.terms.length > 0 || request.parsed.phrases.length > 0;
  const isLanding = response.total === 0 && response.totalAllKinds === 0 && !hasText && activeFilterCount(request) === 0;

  const go = useCallback(
    (state: SearchUrlState) => {
      const qs = toSearchParams(state);
      startTransition(() => router.push(qs ? `/search?${qs}` : '/search'));
    },
    [router]
  );

  const submit = useCallback(() => {
    const q = query.trim();
    if (q) pushRecentSearch(q);
    setFiltersOpen(false);
    go(patchSearchRequest(request, { q: q || null }));
  }, [go, query, request]);

  const insertOperator = (operator: string) => {
    const base = query.trimEnd();
    const next = operator === '"phrase"' ? `${base} ""`.trimStart() : operator === '-word' ? `${base} -`.trimStart() : `${base} ${operator}`.trimStart();
    setQuery(next);
    requestAnimationFrame(() => {
      const el = inputRef.current;
      if (!el) return;
      el.focus();
      const pos = operator === '"phrase"' ? next.length - 1 : next.length;
      el.setSelectionRange(pos, pos);
    });
  };

  // Rewrite q without one inline filter.
  const removeInline = useCallback(
    (key: FilterKey, value: string): SearchUrlState => {
      const nextParsed = withFilter(request.parsed, key, value, 'remove');
      return patchSearchRequest(request, { q: stringifyQuery(nextParsed) || null });
    },
    [request]
  );

  const rail: FacetRailActions = {
    toggleOrg: (slug) => go(inlineHas(request, 'org', slug) ? removeInline('org', slug) : toggleUrlValue(request, 'org', slug)),
    toggleMethod: (m) => go(inlineHas(request, 'method', m) ? removeInline('method', m) : toggleUrlValue(request, 'method', m)),
    toggleType: (kind) => go(inlineHas(request, 'type', kind) ? removeInline('type', kind) : toggleUrlValue(request, 'type', kind)),
    toggleFormat: (f) => go(inlineHas(request, 'format', f) ? removeInline('format', f) : toggleUrlValue(request, 'format', f)),
    toggleParadigm: (p) => go(inlineHas(request, 'paradigm', p) ? removeInline('paradigm', p) : toggleUrlValue(request, 'paradigm', p)),
    setDates: (after, before) => {
      let parsed = request.parsed;
      if (parsed.filters.after) parsed = { ...parsed, filters: { ...parsed.filters, after: undefined } };
      if (parsed.filters.before) parsed = { ...parsed, filters: { ...parsed.filters, before: undefined } };
      const q = stringifyQuery(parsed);
      go({ ...patchSearchRequest(request, { q: q || null }), after: after ?? undefined, before: before ?? undefined });
    },
    setAllVersions: (all) => go(patchSearchRequest(request, { all: all ? '1' : null })),
    clearAll: () => go({ q: stringifyQuery({ ...request.parsed, filters: {} }) || undefined, scope: request.scope === 'all' ? undefined : request.scope }),
  };

  const chips = useMemo<ActiveChip[]>(() => activeChips(request, removeInline), [request, removeInline]);

  // Keyboard: j/k or arrows walk the results, Enter opens, `/` focuses the box.
  const rows = response.rows;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const typing = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable);
      if (typing) return;
      if (e.key === 'j' || e.key === 'ArrowDown') {
        if (rows.length === 0) return;
        e.preventDefault();
        setCursor((c) => Math.min(rows.length - 1, c + 1));
      } else if (e.key === 'k' || e.key === 'ArrowUp') {
        if (rows.length === 0) return;
        e.preventDefault();
        setCursor((c) => Math.max(0, c - 1));
      } else if (e.key === 'Enter' && cursor >= 0 && rows[cursor]) {
        e.preventDefault();
        router.push(hitHref(rows[cursor]));
      } else if (e.key === 'Escape') {
        setCursor(-1);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [rows, cursor, router, setCursor]);

  useEffect(() => {
    if (cursor < 0) return;
    document.getElementById(`hit-${cursor}`)?.scrollIntoView({ block: 'nearest' });
  }, [cursor]);

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  const scopeCounts = useMemo(() => {
    const byKind = new Map(response.facets.kinds.map((k) => [k.value as HitKind, k.count]));
    const sum = (kinds: readonly HitKind[]) => kinds.reduce((n, k) => n + (byKind.get(k) ?? 0), 0);
    return {
      all: response.totalAllKinds,
      operations: sum(SCOPE_KINDS.operations),
      schemas: sum(SCOPE_KINDS.schemas),
      catalog: sum(SCOPE_KINDS.catalog),
      mcp: mcpHits.length,
    } satisfies Record<SearchScope, number>;
  }, [response, mcpHits.length]);

  const activeCount = activeFilterCount(request);
  const groups = useMemo(() => (grouped ? groupHitsByKind(rows) : [{ kind: null, rows }]), [grouped, rows]);
  const pageStart = response.total === 0 ? 0 : (response.page - 1) * response.perPage + 1;
  const pageEnd = Math.min(response.page * response.perPage, response.total);

  return (
    <>
      {/* Search band */}
      <section className="border-b border-zinc-200/80 bg-white dark:border-zinc-800/80 dark:bg-zinc-950">
        <AppShell containerSize="wide">
          <div className="space-y-3 py-6">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h1 className="text-[1.5rem]! font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
                Search the public catalog
              </h1>
              <p className="text-[12px] text-zinc-500 dark:text-zinc-400">
                Published public specifications only — private projects never appear here.
              </p>
            </div>
            <SearchBox
              ref={inputRef}
              id="catalog-search"
              primary
              value={query}
              onChange={setQuery}
              onSubmit={submit}
              busy={isPending}
              autoFocus={isLanding}
              shortcutHint={false}
              placeholder="Search operations, schemas, projects, organizations… try method:POST path:/orders"
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <OperatorChips onInsert={insertOperator} compact />
              <span className="hidden text-[11px] text-zinc-400 lg:inline">
                <kbd className="rounded border border-zinc-200 px-1 font-mono dark:border-zinc-700">/</kbd> focus ·{' '}
                <kbd className="rounded border border-zinc-200 px-1 font-mono dark:border-zinc-700">j</kbd>/<kbd className="rounded border border-zinc-200 px-1 font-mono dark:border-zinc-700">k</kbd> move ·{' '}
                <kbd className="rounded border border-zinc-200 px-1 font-mono dark:border-zinc-700">↵</kbd> open
              </span>
            </div>

            {chips.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5" aria-label="Active filters">
                {chips.map((chip) => (
                  <button
                    key={`${chip.key}:${chip.value}`}
                    type="button"
                    onClick={() => go(chip.remove())}
                    className="inline-flex items-center gap-1 rounded-full border border-[var(--brand)]/40 bg-[var(--brand-soft)] py-0.5 pl-2.5 pr-1.5 text-[12px] font-medium text-[var(--brand-soft-text)] transition-colors hover:bg-[var(--brand-soft-hover)]"
                    title={`Remove ${chip.label}: ${chip.value}`}
                  >
                    <span className="opacity-70">{chip.label}</span>
                    <span>{chip.value}</span>
                    <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24" aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                ))}
                <button type="button" onClick={rail.clearAll} className="ml-1 text-[12px] text-zinc-500 hover:underline dark:text-zinc-400">
                  Clear all
                </button>
              </div>
            )}
          </div>

          {!isLanding && (
            <nav aria-label="Result scope" className="-mb-px flex gap-1 overflow-x-auto">
              {SEARCH_SCOPES.map((scope) => {
                const active = request.scope === scope;
                const count = scopeCounts[scope];
                const disabled = scope === 'mcp' && !hasText;
                return (
                  <button
                    key={scope}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    disabled={disabled}
                    onClick={() => go(patchSearchRequest(request, { scope: scope === 'all' ? null : scope, type: null }))}
                    className={`inline-flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-[13px] font-medium transition-colors ${
                      active
                        ? 'border-[var(--brand)] text-[var(--brand)]'
                        : 'border-transparent text-zinc-500 hover:border-zinc-300 hover:text-zinc-900 disabled:opacity-40 dark:text-zinc-400 dark:hover:text-zinc-100'
                    }`}
                    title={disabled ? 'Type a word to search MCP servers' : undefined}
                  >
                    {SEARCH_SCOPE_LABELS[scope]}
                    <span className={`rounded-full px-1.5 text-[10.5px] tabular-nums ${active ? 'bg-[var(--brand-soft)] text-[var(--brand-soft-text)]' : 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400'}`}>
                      {count.toLocaleString()}
                      {scope === 'all' && response.truncated ? '+' : ''}
                    </span>
                  </button>
                );
              })}
            </nav>
          )}
        </AppShell>
      </section>

      <AppShell containerSize="wide">
        {isLanding ? (
          <Landing
            recent={recent}
            onClearRecent={clearRecentSearches}
            onPick={(q) => {
              setQuery(q);
              pushRecentSearch(q);
              go({ q });
            }}
            onBrowse={(state) => go(state)}
          />
        ) : (
          <div className="grid gap-6 py-6 lg:grid-cols-[260px_minmax(0,1fr)] xl:grid-cols-[260px_minmax(0,1fr)_280px]">
            {/* Filters: rail on desktop, drawer on mobile */}
            <div className="lg:hidden">
              <button
                type="button"
                onClick={() => setFiltersOpen(true)}
                className="inline-flex items-center gap-2 rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-sm font-medium text-zinc-700 shadow-xs dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300"
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 4h18l-7 8v6l-4 2v-8L3 4z" />
                </svg>
                Filters{activeCount > 0 ? ` (${activeCount})` : ''}
              </button>
              {filtersOpen && (
                <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Filters">
                  <div className="absolute inset-0 bg-zinc-900/50 backdrop-blur-sm" onClick={() => setFiltersOpen(false)} />
                  <div className="absolute inset-y-0 left-0 w-[320px] max-w-[90vw] overflow-y-auto bg-[var(--background)] p-4 shadow-lg">
                    <div className="mb-3 flex items-center justify-between">
                      <span className="text-sm font-semibold">Filters</span>
                      <button type="button" onClick={() => setFiltersOpen(false)} aria-label="Close filters" className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800">
                        <svg className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden="true">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                        </svg>
                      </button>
                    </div>
                    <FacetRail request={request} response={response} actions={rail} activeCount={activeCount} />
                  </div>
                </div>
              )}
            </div>
            <aside className="hidden lg:block">
              <div className="sticky top-20 max-h-[calc(100vh-6rem)] overflow-y-auto pb-6">
                <FacetRail request={request} response={response} actions={rail} activeCount={activeCount} />
              </div>
            </aside>

            {/* Results */}
            <section className="min-w-0 space-y-3" aria-live="polite" aria-busy={isPending}>
              {request.scope === 'mcp' ? (
                <McpResults hits={mcpHits} query={mcpQuery} needles={needles} />
              ) : (
                <>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-[13px] text-zinc-600 dark:text-zinc-300">
                      {isPending ? (
                        <span className="inline-flex items-center gap-2"><Spinner className="h-4 w-4" /> Searching…</span>
                      ) : (
                        <>
                          <span className="font-semibold text-zinc-900 dark:text-zinc-50">
                            {response.truncated && request.scope === 'all' ? 'More than ' : ''}
                            {response.total.toLocaleString()} {response.total === 1 ? 'result' : 'results'}
                          </span>
                          {hasText && (
                            <>
                              <span className="text-zinc-400"> for </span>
                              <span className="font-mono text-[var(--brand-soft-text)]">&ldquo;{needles.join(' ')}&rdquo;</span>
                            </>
                          )}
                          {response.total > 0 && (
                            <span className="text-zinc-400"> · {pageStart.toLocaleString()}–{pageEnd.toLocaleString()}</span>
                          )}
                          {response.tookMs > 0 && <span className="text-zinc-400"> · {response.tookMs} ms</span>}
                          {!request.allVersions && <span className="text-zinc-400"> · latest versions</span>}
                        </>
                      )}
                    </p>
                    <div className="flex flex-wrap items-center gap-2">
                      <label className="flex items-center gap-1.5 text-[11px] text-zinc-500">
                        Sort
                        <select
                          value={request.sort}
                          onChange={(e) => go(patchSearchRequest(request, { sort: e.target.value as SearchSort }))}
                          className="rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs text-zinc-800 shadow-xs dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
                        >
                          {SEARCH_SORTS.map((s) => (
                            <option key={s} value={s} disabled={s === 'relevance' && !hasText}>
                              {SEARCH_SORT_LABELS[s]}
                            </option>
                          ))}
                        </select>
                      </label>
                      <div className="inline-flex overflow-hidden rounded-md border border-zinc-200 text-[11px] font-medium dark:border-zinc-700" role="group" aria-label="Layout">
                        {[
                          { value: true, label: 'Grouped' },
                          { value: false, label: 'Flat' },
                        ].map((opt, i) => (
                          <button
                            key={opt.label}
                            type="button"
                            aria-pressed={grouped === opt.value}
                            onClick={() => setGrouped(opt.value)}
                            className={`px-2 py-1 ${i > 0 ? 'border-l border-zinc-200 dark:border-zinc-700' : ''} ${
                              grouped === opt.value ? 'bg-[var(--brand)] text-white' : 'text-zinc-600 hover:bg-zinc-50 dark:text-zinc-300 dark:hover:bg-zinc-800'
                            }`}
                          >
                            {opt.label}
                          </button>
                        ))}
                      </div>
                      <button
                        type="button"
                        onClick={copyLink}
                        className="rounded-md border border-zinc-200 bg-white px-2 py-1 text-[11px] font-medium text-zinc-600 shadow-xs hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
                        title="Copy a link to this search"
                      >
                        {copied ? 'Copied' : 'Copy link'}
                      </button>
                    </div>
                  </div>

                  {rows.length === 0 && !isPending ? (
                    <NoResults request={request} chips={chips} mcpCount={mcpHits.length} onGo={go} />
                  ) : (
                    <div className={`space-y-5 ${isPending ? 'opacity-60 transition-opacity' : ''}`}>
                      {groups.map((group) => {
                        let offset = 0;
                        for (const g of groups) {
                          if (g === group) break;
                          offset += g.rows.length;
                        }
                        return (
                          <div key={group.kind ?? 'flat'}>
                            {group.kind && (
                              <div className="mb-2 flex items-center gap-2">
                                <h2 className="text-[11px]! font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                                  {HIT_KIND_LABELS[group.kind].many}
                                </h2>
                                <span className="text-[11px] tabular-nums text-zinc-400">{group.rows.length} on this page</span>
                                {!request.types.includes(group.kind) && (
                                  <button
                                    type="button"
                                    onClick={() => go(toggleUrlValue(request, 'type', group.kind as string))}
                                    className="ml-auto text-[11px] font-medium text-[var(--brand)] hover:underline"
                                  >
                                    Only {HIT_KIND_LABELS[group.kind].many.toLowerCase()}
                                  </button>
                                )}
                              </div>
                            )}
                            <ul className="flex flex-col gap-2">
                              {group.rows.map((hit, i) => (
                                <HitRow key={hit.hit_id} id={`hit-${offset + i}`} hit={hit} needles={needles} active={cursor === offset + i} />
                              ))}
                            </ul>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {response.pageCount > 1 && (
                    <Pagination page={response.page} pageCount={response.pageCount} onPage={(p) => go(patchSearchRequest(request, { page: p > 1 ? String(p) : null }))} />
                  )}
                </>
              )}
            </section>

            {/* Right rail */}
            <aside className="hidden xl:block">
              <div className="sticky top-20 space-y-4">
                {response.facets.projects.length > 0 && request.scope !== 'mcp' && (
                  <div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
                    <div className="border-b border-zinc-200 px-4 py-2.5 dark:border-zinc-800">
                      <h3 className="text-[13px]! font-semibold text-zinc-900 dark:text-zinc-50">Top projects</h3>
                      <p className="mt-0.5 text-[12px] text-zinc-500 dark:text-zinc-400">Where the matches concentrate.</p>
                    </div>
                    <ul className="divide-y divide-zinc-100 dark:divide-zinc-800/80">
                      {response.facets.projects.map((p) => (
                        <li key={`${p.tenant_slug}/${p.project_slug}`}>
                          <Link
                            href={`/tenant/${encodeURIComponent(p.tenant_slug)}/${encodeURIComponent(p.project_slug)}`}
                            className="flex items-center gap-3 px-4 py-2 transition-colors hover:bg-zinc-50 dark:hover:bg-zinc-900"
                          >
                            <div className="min-w-0 flex-1">
                              <div className="truncate text-[13px] font-medium text-zinc-900 dark:text-zinc-50">{p.project_name}</div>
                              <div className="truncate text-[11px] text-zinc-500 dark:text-zinc-400">{p.tenant_name}</div>
                            </div>
                            <span className="font-mono text-[11px] tabular-nums text-zinc-400">{p.count}</span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                <SyntaxHelpCard
                  onTry={(example) => {
                    setQuery(example);
                    go({ q: example });
                  }}
                />
              </div>
            </aside>
          </div>
        )}
      </AppShell>
    </>
  );
}

/* ----------------------------------------------------------------------------------------------- */

function inlineHas(request: SearchRequest, key: FilterKey, value: string): boolean {
  const values = request.parsed.filters[key] ?? [];
  return values.includes(key === 'method' ? value.toUpperCase() : value.toLowerCase());
}

/** How many filter dimensions are narrowing the request (for badges and "Clear all"). */
function activeFilterCount(request: SearchRequest): number {
  return (
    request.types.length +
    request.orgs.length +
    request.projects.length +
    request.versions.length +
    request.methods.length +
    request.paths.length +
    request.formats.length +
    request.paradigms.length +
    request.tags.length +
    (request.after ? 1 : 0) +
    (request.before ? 1 : 0)
  );
}

/** The removable chips for every active filter, inline or rail. */
function activeChips(request: SearchRequest, removeInline: (key: FilterKey, value: string) => SearchUrlState): ActiveChip[] {
  const chips: ActiveChip[] = [];
  const add = (key: FilterKey, value: string, label: string, display: string, urlKey?: 'org' | 'method' | 'type' | 'format' | 'paradigm') => {
    chips.push({
      key,
      label,
      value: display,
      remove: () => (inlineHas(request, key, value) ? removeInline(key, value) : urlKey ? toggleUrlValue(request, urlKey, value) : patchSearchRequest(request, {})),
    });
  };
  for (const kind of request.types) add('type', kind, FILTER_KEY_LABELS.type, HIT_KIND_LABELS[kind].many, 'type');
  for (const m of request.methods) add('method', m, FILTER_KEY_LABELS.method, m, 'method');
  for (const p of request.paths) add('path', p, FILTER_KEY_LABELS.path, p);
  for (const o of request.orgs) add('org', o, FILTER_KEY_LABELS.org, o, 'org');
  for (const p of request.projects) add('project', p, FILTER_KEY_LABELS.project, p);
  for (const v of request.versions) add('version', v, FILTER_KEY_LABELS.version, v);
  for (const f of request.formats) add('format', f, FILTER_KEY_LABELS.format, formatLabel(f), 'format');
  for (const p of request.paradigms) add('paradigm', p, FILTER_KEY_LABELS.paradigm, paradigmLabel(p), 'paradigm');
  for (const t of request.tags) add('tag', t, FILTER_KEY_LABELS.tag, t);
  if (request.after) {
    chips.push({
      key: 'after',
      label: FILTER_KEY_LABELS.after,
      value: request.after,
      remove: () =>
        request.parsed.filters.after
          ? patchSearchRequest(request, { q: stringifyQuery({ ...request.parsed, filters: { ...request.parsed.filters, after: undefined } }) || null })
          : patchSearchRequest(request, { after: null }),
    });
  }
  if (request.before) {
    chips.push({
      key: 'before',
      label: FILTER_KEY_LABELS.before,
      value: request.before,
      remove: () =>
        request.parsed.filters.before
          ? patchSearchRequest(request, { q: stringifyQuery({ ...request.parsed, filters: { ...request.parsed.filters, before: undefined } }) || null })
          : patchSearchRequest(request, { before: null }),
    });
  }
  return chips;
}

function Landing({
  recent,
  onClearRecent,
  onPick,
  onBrowse,
}: {
  recent: string[];
  onClearRecent: () => void;
  onPick: (q: string) => void;
  onBrowse: (state: SearchUrlState) => void;
}) {
  return (
    <div className="grid gap-8 py-8 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-8">
        <section>
          <h2 className="text-[12px]! font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">Try a search</h2>
          <div className="mt-3 flex flex-wrap gap-2">
            {EXAMPLE_QUERIES.map((ex) => (
              <button
                key={ex.q}
                type="button"
                onClick={() => onPick(ex.q)}
                className="group rounded-full border border-zinc-200 bg-white px-3 py-1.5 text-[12.5px] text-zinc-700 shadow-xs transition-colors hover:border-[var(--brand)] hover:text-[var(--brand)] dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
              >
                {ex.label} <code className="ml-1 font-mono text-[11px] text-zinc-400 group-hover:text-[var(--brand)]">{ex.q}</code>
              </button>
            ))}
          </div>
        </section>

        <section>
          <h2 className="text-[12px]! font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">Browse everything</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {BROWSE_TILES.map((tile) => (
              <button
                key={tile.title}
                type="button"
                onClick={() => onBrowse(tile.state)}
                className="group flex flex-col items-start gap-1 rounded-xl border border-zinc-200 bg-white p-4 text-left shadow-xs transition-all hover:-translate-y-0.5 hover:border-sky-300 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-950 dark:hover:border-sky-800"
              >
                <span className="text-[14px] font-semibold text-zinc-900 group-hover:text-[var(--brand)] dark:text-zinc-50">{tile.title}</span>
                <span className="text-[12px] text-zinc-500 dark:text-zinc-400">{tile.hint}</span>
              </button>
            ))}
          </div>
        </section>

        {recent.length > 0 && (
          <section>
            <div className="flex items-center justify-between">
              <h2 className="text-[12px]! font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">Recent searches</h2>
              <button type="button" onClick={onClearRecent} className="text-[12px] text-[var(--brand)] hover:underline">
                Clear
              </button>
            </div>
            <ul className="mt-3 flex flex-wrap gap-2">
              {recent.map((r) => (
                <li key={r}>
                  <button
                    type="button"
                    onClick={() => onPick(r)}
                    className="rounded-full border border-zinc-200 bg-white px-3 py-1.5 font-mono text-[12px] text-zinc-700 shadow-xs hover:border-[var(--brand)] hover:text-[var(--brand)] dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
                  >
                    {r}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
      <SyntaxHelpCard onTry={onPick} />
    </div>
  );
}

function NoResults({
  request,
  chips,
  mcpCount,
  onGo,
}: {
  request: SearchRequest;
  chips: ActiveChip[];
  mcpCount: number;
  onGo: (state: SearchUrlState) => void;
}) {
  const needles = textNeedles(request.parsed);
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-8 dark:border-zinc-800 dark:bg-zinc-950">
      <h2 className="text-[15px]! font-semibold text-zinc-900 dark:text-zinc-50">
        No {request.scope === 'all' ? 'results' : SEARCH_SCOPE_LABELS[request.scope].toLowerCase()}
        {needles.length > 0 && (
          <>
            {' '}for <span className="font-mono text-[var(--brand-soft-text)]">&ldquo;{needles.join(' ')}&rdquo;</span>
          </>
        )}
        {!request.allVersions && ' in the latest versions'}
      </h2>
      <ul className="mt-4 space-y-2 text-[13px] text-zinc-600 dark:text-zinc-300">
        {!request.allVersions && (
          <li>
            <button type="button" onClick={() => onGo(patchSearchRequest(request, { all: '1' }))} className="font-medium text-[var(--brand)] hover:underline">
              Search every published version
            </button>{' '}
            — older versions may still mention it.
          </li>
        )}
        {request.scope !== 'all' && response_hint(request, onGo)}
        {chips.map((chip) => (
          <li key={`${chip.key}:${chip.value}`}>
            <button type="button" onClick={() => onGo(chip.remove())} className="font-medium text-[var(--brand)] hover:underline">
              Drop {chip.label.toLowerCase()} {chip.value}
            </button>
          </li>
        ))}
        {needles.length > 1 && <li>Try fewer words — every word must match.</li>}
        {needles.length > 0 && mcpCount > 0 && (
          <li>
            <button type="button" onClick={() => onGo(patchSearchRequest(request, { scope: 'mcp', type: null }))} className="font-medium text-[var(--brand)] hover:underline">
              {mcpCount} MCP server {mcpCount === 1 ? 'capability matches' : 'capabilities match'}
            </button>{' '}
            in the MCP catalog.
          </li>
        )}
        <li>
          <Link href="/" className="font-medium text-[var(--brand)] hover:underline">
            Browse the directory
          </Link>{' '}
          by organization instead.
        </li>
      </ul>
    </div>
  );
}

function response_hint(request: SearchRequest, onGo: (state: SearchUrlState) => void) {
  return (
    <li>
      <button type="button" onClick={() => onGo(patchSearchRequest(request, { scope: null, type: null }))} className="font-medium text-[var(--brand)] hover:underline">
        Search all kinds
      </button>{' '}
      — the match may be a different kind of item.
    </li>
  );
}

function McpResults({ hits, query, needles }: { hits: McpPublicSearchHit[]; query: string; needles: string[] }) {
  if (hits.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-200 bg-white p-8 text-[13px] text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
        No public MCP server capability matches <span className="font-mono">&ldquo;{query}&rdquo;</span>.{' '}
        <Link href="/mcp" className="font-medium text-[var(--brand)] hover:underline">
          Browse the MCP catalog
        </Link>
        .
      </div>
    );
  }
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] text-zinc-600 dark:text-zinc-300">
          <span className="font-semibold text-zinc-900 dark:text-zinc-50">{hits.length} {hits.length === 1 ? 'capability' : 'capabilities'}</span>
          <span className="text-zinc-400"> across public MCP servers for </span>
          <span className="font-mono text-[var(--brand-soft-text)]">&ldquo;{query}&rdquo;</span>
        </p>
        <Link href={`/mcp/search?q=${encodeURIComponent(query)}`} className="text-[12px] font-medium text-[var(--brand)] hover:underline">
          Open in the MCP catalog →
        </Link>
      </div>
      <ul className="flex flex-col gap-2">
        {hits.map((hit) => (
          <li key={hit.item_id} className="list-none">
            <Link
              href={`/mcp/${hit.tenant_slug}/${hit.endpoint_slug}`}
              className="group block rounded-xl border border-zinc-200 bg-white p-4 transition-colors hover:border-sky-300 dark:border-zinc-800 dark:bg-zinc-950 dark:hover:border-sky-700"
            >
              <div className="flex items-start gap-3">
                <GradeBadge grade={hit.grade} score={hit.score} size="sm" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2 text-[11px] text-zinc-500 dark:text-zinc-400">
                    <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                      {hit.item_type.replace(/_/g, ' ')}
                    </span>
                    <span className="truncate">{hit.endpoint_name}{hit.host ? ` · ${hit.host}` : ''}</span>
                  </div>
                  <h3 className="mt-1 truncate text-[15px]! font-semibold text-zinc-900 group-hover:text-[var(--brand)] dark:text-zinc-50">
                    <Highlight text={hit.item_title || hit.item_name} needles={needles} />
                  </h3>
                  {hit.description && (
                    <p className="mt-1 line-clamp-2 text-[13px] text-zinc-600 dark:text-zinc-400">
                      <Highlight text={hit.description} needles={needles} />
                    </p>
                  )}
                </div>
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

function Pagination({ page, pageCount, onPage }: { page: number; pageCount: number; onPage: (p: number) => void }) {
  const window = 2;
  const pages: (number | '…')[] = [];
  for (let p = 1; p <= pageCount; p++) {
    if (p === 1 || p === pageCount || Math.abs(p - page) <= window) pages.push(p);
    else if (pages[pages.length - 1] !== '…') pages.push('…');
  }
  const btn = 'inline-flex h-8 min-w-8 items-center justify-center rounded-md border px-2 text-[12px] font-medium transition-colors';
  return (
    <nav className="flex flex-wrap items-center justify-between gap-2 border-t border-zinc-200 pt-4 dark:border-zinc-800" aria-label="Pagination">
      <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)} className={`${btn} border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50 disabled:opacity-40 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300`}>
        ← Previous
      </button>
      <div className="flex items-center gap-1">
        {pages.map((p, i) =>
          p === '…' ? (
            <span key={`gap-${i}`} className="px-1 text-zinc-400">…</span>
          ) : (
            <button
              key={p}
              type="button"
              aria-current={p === page ? 'page' : undefined}
              onClick={() => onPage(p)}
              className={`${btn} ${p === page ? 'border-[var(--brand)] bg-[var(--brand)] text-white' : 'border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300'}`}
            >
              {p}
            </button>
          )
        )}
      </div>
      <button type="button" disabled={page >= pageCount} onClick={() => onPage(page + 1)} className={`${btn} border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50 disabled:opacity-40 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300`}>
        Next →
      </button>
    </nav>
  );
}

// `toUrlState` is re-exported for the landing tiles so a tile can describe itself as URL state.
export { toUrlState };
