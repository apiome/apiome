'use client';

import { useEffect, useState, useTransition } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { AppShell } from '../../components/AppShell';
import { sanitizeSearchInput } from '../../utils/searchValidation';
import { MCP_SORT_LABELS, type McpSortMode } from '../../../../lib/mcpSort';
import type { McpPublicSearchHit } from '../../../../lib/types';
import {
  mcpSearchHref,
  type McpFederatedRegistryResult,
  type McpRegistryHit,
} from '../../../../lib/mcp/registrySearch';
import { GradeBadge } from '../McpShared';

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function Spinner({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg className={`${className} animate-spin text-[var(--brand)]`} fill="none" viewBox="0 0 24 24" aria-hidden>
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

function HighlightMatches({ text, query }: { text: string; query: string }) {
  const q = query.trim();
  if (!q || !text) return <>{text}</>;
  const parts = text.split(new RegExp(`(${escapeRegExp(q)})`, 'gi'));
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === q.toLowerCase() ? (
          <mark key={i} className="rounded-sm bg-sky-500/20 px-0.5 text-inherit dark:bg-sky-400/35">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}

/** Provenance badge: the published Apiome catalog, or an MCP registry (V2-MCP-26.4). */
function ProvenanceBadge({ source, title }: { source: 'catalog' | 'registry'; title?: string }) {
  return (
    <span className={`provenance-badge provenance-badge-${source}`} title={title}>
      {source === 'catalog' ? 'Catalog' : 'MCP Registry'}
    </span>
  );
}

/** One MCP registry entry the federated search found (not in the catalog). */
function RegistryEntryCard({ entry, query }: { entry: McpRegistryHit; query: string }) {
  const body = (
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
        <ProvenanceBadge source="registry" />
        {entry.status && entry.status !== 'active' ? (
          <span className="provenance-badge provenance-badge-deprecated">{entry.status}</span>
        ) : null}
        <span className="truncate">
          {entry.host ?? 'Runs locally (package)'}
          {entry.version ? ` · v${entry.version}` : ''}
          {entry.transport ? ` · ${entry.transport.replace(/_/g, ' ')}` : ''}
        </span>
      </div>
      <h3 className="mt-1 font-mono text-[15px] font-semibold text-zinc-900 dark:text-zinc-50">
        <HighlightMatches text={entry.serverName} query={query} />
      </h3>
      {entry.title ? <p className="text-sm text-zinc-700 dark:text-zinc-200">{entry.title}</p> : null}
      {entry.description ? (
        <p className="mt-1 line-clamp-2 text-sm text-zinc-600 dark:text-zinc-300">
          <HighlightMatches text={entry.description} query={query} />
        </p>
      ) : null}
    </div>
  );
  const cardClass =
    'block rounded-lg border border-dashed border-zinc-300 bg-white p-4 dark:border-zinc-700 dark:bg-zinc-900';
  return entry.websiteUrl ? (
    <a
      href={entry.websiteUrl}
      target="_blank"
      rel="noopener noreferrer"
      className={`${cardClass} transition-colors hover:border-sky-300 dark:hover:border-sky-700`}
    >
      {body}
    </a>
  ) : (
    <div className={cardClass}>{body}</div>
  );
}

/** Registry dedupe summary, or why the registry results are missing. */
function FederationNotice({ result }: { result: McpFederatedRegistryResult }) {
  if (result.error) {
    return (
      <p className="federation-notice mb-3" role="status">
        {result.error} Showing catalog results only.
      </p>
    );
  }
  return (
    <p className="federation-notice mb-3" role="status">
      {result.entries.length} more from the MCP Registry
      {result.duplicates > 0
        ? ` · ${result.duplicates} registry match${result.duplicates === 1 ? ' is' : 'es are'} already in the catalog and shown once`
        : ''}
      .
    </p>
  );
}

/**
 * Public MCP capability search (MCAT-9.7). Ordering is computed server-side in SQL, so the query box
 * and the Sort control both drive navigation: submitting a query lands relevance-first (the default
 * while searching), and the Sort control lets the user pin "Top graded" (grade-led) instead. The
 * control reflects the active mode; both are carried in the URL so SSR and the control agree.
 *
 * Federated search (V2-MCP-26.4): the **Include MCP Registry** toggle (`registry=1`) adds the MCP
 * registry's matching servers after the catalog results. Every result carries a provenance badge
 * (**Catalog** / **MCP Registry**); a registry entry a published server already is appears once, as
 * the catalog result with an **In MCP Registry** badge.
 */
export function McpSearchClient({
  initialQuery,
  initialSort,
  initialResults,
  includeRegistry = false,
  registryResult = null,
}: {
  initialQuery: string;
  initialSort: McpSortMode;
  initialResults: McpPublicSearchHit[];
  includeRegistry?: boolean;
  registryResult?: McpFederatedRegistryResult | null;
}) {
  const router = useRouter();
  // Results (and their ordering) are computed server-side, so both the query box and the Sort
  // control navigate and refetch. A transition surfaces a spinner while that runs, rather than
  // leaving the user staring at stale or empty results with no indication anything is happening.
  const [isSearching, startSearch] = useTransition();
  const [query, setQuery] = useState(initialQuery);

  useEffect(() => {
    setQuery(initialQuery);
  }, [initialQuery]);

  const navigate = (q: string, sort: McpSortMode | null, registry: boolean) => {
    if (!q.trim()) return;
    startSearch(() => router.push(mcpSearchHref(q, sort, registry)));
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    // A fresh query resets to the query-default mode (relevance): omit the sort param.
    navigate(query, null, includeRegistry);
  };

  const handleSortChange = (mode: McpSortMode) => {
    navigate(initialQuery, mode, includeRegistry);
  };

  const handleRegistryToggle = (checked: boolean) => {
    navigate(initialQuery, initialSort, checked);
  };

  const registryEntries = registryResult?.entries ?? [];
  const registryNames = registryResult?.serverNameByEndpoint ?? {};
  const totalResults = initialResults.length + registryEntries.length;

  return (
    <AppShell containerSize="wide">
      <header className="border-b border-zinc-200 bg-white py-6 dark:border-zinc-800 dark:bg-zinc-900">
        <p className="mb-3 text-[13px] text-zinc-500 dark:text-zinc-400">
          Search published public MCP servers only — private servers never appear here. Turn on{' '}
          <span className="font-semibold">Include MCP Registry</span> to add servers listed in the MCP
          Registry.
        </p>
        <form onSubmit={handleSearch} className="relative">
          <svg
            className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-zinc-400"
            fill="none"
            stroke="currentColor"
            strokeWidth={1.75}
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="search"
            name="q"
            enterKeyHint="search"
            value={query}
            onChange={(e) => setQuery(sanitizeSearchInput(e.target.value))}
            placeholder="Search tools, resources, and prompts…"
            className="w-full rounded-lg border border-zinc-200 bg-zinc-50 py-3.5 pl-12 pr-28 text-[15px] text-zinc-900 placeholder-zinc-400 shadow-xs transition-colors focus-visible:border-[var(--brand)] focus-visible:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100 dark:placeholder-zinc-500"
            autoFocus
          />
          <button
            type="submit"
            disabled={isSearching}
            className="absolute right-3 top-1/2 inline-flex -translate-y-1/2 items-center gap-1.5 rounded-md bg-[var(--brand)] px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[var(--brand-hover)] disabled:opacity-80"
          >
            {isSearching && <Spinner className="h-3.5 w-3.5 text-white" />}
            {isSearching ? 'Searching…' : 'Search'}
          </button>
        </form>
      </header>

      <div className="py-6">
        {isSearching ? (
          <div
            className="flex flex-col items-center justify-center rounded-xl border border-zinc-200 bg-white p-12 text-center dark:border-zinc-800 dark:bg-zinc-900"
            role="status"
            aria-live="polite"
          >
            <Spinner className="h-7 w-7" />
            <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-300">
              Searching the MCP catalog
              {query.trim() && (
                <>
                  {' for '}
                  <span className="font-mono text-sky-600 dark:text-sky-400">&ldquo;{query.trim()}&rdquo;</span>
                </>
              )}
              …
            </p>
          </div>
        ) : !initialQuery ? (
          <div className="rounded-xl border border-dashed border-zinc-300 bg-white/50 p-10 text-center dark:border-zinc-700 dark:bg-zinc-900/40">
            <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Search the MCP catalog</h2>
            <p className="mx-auto mt-2 max-w-lg text-[14px] text-zinc-600 dark:text-zinc-400">
              Match tool, resource, and prompt names and descriptions across every published public
              server. Or{' '}
              <Link href="/mcp" className="font-medium text-sky-600 dark:text-sky-400">
                browse by site
              </Link>
              .
            </p>
          </div>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-zinc-600 dark:text-zinc-300">
                <span className="font-semibold text-zinc-900 dark:text-zinc-50">
                  {totalResults} result{totalResults === 1 ? '' : 's'}
                </span>
                <span className="text-zinc-400"> for </span>
                <span className="font-mono text-sky-600 dark:text-sky-400">
                  &ldquo;{initialQuery}&rdquo;
                </span>
              </p>
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-1.5 text-xs text-zinc-600 dark:text-zinc-300">
                  <input
                    type="checkbox"
                    checked={includeRegistry}
                    onChange={(e) => handleRegistryToggle(e.target.checked)}
                    className="h-3.5 w-3.5 accent-[var(--brand)]"
                  />
                  Include MCP Registry
                </label>
                <div className="flex items-center gap-2">
                  <label htmlFor="mcp-sort" className="text-[11px] text-zinc-500">
                    Sort
                  </label>
                  <select
                    id="mcp-sort"
                    value={initialSort}
                    onChange={(e) => handleSortChange(e.target.value as McpSortMode)}
                    className="rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs text-zinc-800 shadow-xs dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
                  >
                    <option value="relevance">{MCP_SORT_LABELS.relevance}</option>
                    <option value="top_graded">{MCP_SORT_LABELS.top_graded}</option>
                  </select>
                </div>
              </div>
            </div>

            {registryResult ? <FederationNotice result={registryResult} /> : null}

            {totalResults === 0 ? (
              <div className="rounded-xl border border-zinc-200 bg-white p-10 text-center dark:border-zinc-800 dark:bg-zinc-900">
                <p className="text-zinc-600 dark:text-zinc-400">
                  No public capabilities{includeRegistry ? ' or registry servers' : ''} match{' '}
                  <span className="font-medium text-zinc-900 dark:text-zinc-50">
                    &ldquo;{initialQuery}&rdquo;
                  </span>
                  .
                </p>
                <Link href="/mcp" className="mt-4 inline-block text-sm font-medium text-sky-600 dark:text-sky-400">
                  Browse the catalog
                </Link>
              </div>
            ) : (
              <ul className="flex flex-col gap-3">
                {initialResults.length === 0 ? (
                  <li className="text-sm text-zinc-600 dark:text-zinc-400">
                    No public capabilities match &ldquo;{initialQuery}&rdquo;.
                  </li>
                ) : null}
                {initialResults.map((hit) => (
                  <li key={`${hit.item_id}`}>
                    <Link
                      href={`/mcp/${hit.tenant_slug}/${hit.endpoint_slug}`}
                      className="block rounded-lg border border-zinc-200 bg-white p-4 transition-colors hover:border-sky-300 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-sky-700"
                    >
                      <div className="flex items-start gap-3">
                        <GradeBadge grade={hit.grade} score={hit.score} size="sm" />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
                            <span className="truncate">
                              {hit.endpoint_name} · {hit.host ?? 'Unknown host'}
                            </span>
                            <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                              {hit.item_type.replace(/_/g, ' ')}
                            </span>
                            {registryResult ? <ProvenanceBadge source="catalog" /> : null}
                            {registryNames[hit.endpoint_id] ? (
                              <span
                                className="provenance-badge provenance-badge-registry"
                                title={`Listed in the MCP Registry as ${registryNames[hit.endpoint_id]}`}
                              >
                                In MCP Registry
                              </span>
                            ) : null}
                          </div>
                          <h3 className="mt-1 font-mono text-[15px] font-semibold text-zinc-900 dark:text-zinc-50">
                            <HighlightMatches text={hit.item_title || hit.item_name} query={initialQuery} />
                          </h3>
                          {hit.description ? (
                            <p className="mt-1 line-clamp-2 text-sm text-zinc-600 dark:text-zinc-300">
                              <HighlightMatches text={hit.description} query={initialQuery} />
                            </p>
                          ) : null}
                        </div>
                      </div>
                    </Link>
                  </li>
                ))}
                {registryEntries.map((entry) => (
                  <li key={`registry:${entry.serverName}`}>
                    <RegistryEntryCard entry={entry} query={initialQuery} />
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
