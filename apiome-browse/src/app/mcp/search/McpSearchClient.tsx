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
    <svg className={`${className} animate-spin text-accent-fg`} fill="none" viewBox="0 0 24 24" aria-hidden>
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
          <mark key={i} className="rounded-sm bg-accent/20 px-0.5 text-inherit">
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
      <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
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
      <h3 className="mt-1 font-mono text-lg font-semibold text-fg">
        <HighlightMatches text={entry.serverName} query={query} />
      </h3>
      {entry.title ? <p className="text-base text-fg-muted">{entry.title}</p> : null}
      {entry.description ? (
        <p className="mt-1 line-clamp-2 text-base text-fg-muted">
          <HighlightMatches text={entry.description} query={query} />
        </p>
      ) : null}
    </div>
  );
  const cardClass =
    'block rounded-lg border border-dashed border-border-strong bg-surface p-4';
  return entry.websiteUrl ? (
    <a
      href={entry.websiteUrl}
      target="_blank"
      rel="noopener noreferrer"
      className={`${cardClass} transition-colors hover:border-accent/30`}
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
      <header className="border-b border-border bg-surface py-6">
        <p className="mb-3 text-sm text-fg-muted">
          Search published public MCP servers only — private servers never appear here. Turn on{' '}
          <span className="font-semibold">Include MCP Registry</span> to add servers listed in the MCP
          Registry.
        </p>
        <form onSubmit={handleSearch} className="relative">
          <svg
            className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-fg-subtle"
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
            className="control h-12 rounded-lg pl-12 pr-28 text-lg"
            autoFocus
          />
          <button
            type="submit"
            disabled={isSearching}
            className="absolute right-3 top-1/2 inline-flex -translate-y-1/2 items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-fg-on-accent transition-colors hover:bg-accent-hover disabled:opacity-80"
          >
            {isSearching && <Spinner className="h-3.5 w-3.5 text-white" />}
            {isSearching ? 'Searching…' : 'Search'}
          </button>
        </form>
      </header>

      <div className="py-6">
        {isSearching ? (
          <div
            className="flex flex-col items-center justify-center rounded-lg border border-border bg-surface p-12 text-center"
            role="status"
            aria-live="polite"
          >
            <Spinner className="h-7 w-7" />
            <p className="mt-4 text-base text-fg-muted">
              Searching the MCP catalog
              {query.trim() && (
                <>
                  {' for '}
                  <span className="font-mono text-accent-fg">&ldquo;{query.trim()}&rdquo;</span>
                </>
              )}
              …
            </p>
          </div>
        ) : !initialQuery ? (
          <div className="rounded-lg border border-dashed border-border-strong bg-surface/50 p-10 text-center">
            <h2 className="text-xl font-semibold text-fg">Search the MCP catalog</h2>
            <p className="mx-auto mt-2 max-w-lg text-base text-fg-muted">
              Match tool, resource, and prompt names and descriptions across every published public
              server. Or{' '}
              <Link href="/mcp" className="font-medium text-accent-fg">
                browse by site
              </Link>
              .
            </p>
          </div>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <p className="text-base text-fg-muted">
                <span className="font-semibold text-fg">
                  {totalResults} result{totalResults === 1 ? '' : 's'}
                </span>
                <span className="text-fg-subtle"> for </span>
                <span className="font-mono text-accent-fg">
                  &ldquo;{initialQuery}&rdquo;
                </span>
              </p>
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-1.5 text-xs text-fg-muted">
                  <input
                    type="checkbox"
                    checked={includeRegistry}
                    onChange={(e) => handleRegistryToggle(e.target.checked)}
                    className="h-3.5 w-3.5 accent-accent"
                  />
                  Include MCP Registry
                </label>
                <div className="flex items-center gap-2">
                  <label htmlFor="mcp-sort" className="text-2xs text-fg-muted">
                    Sort
                  </label>
                  <select
                    id="mcp-sort"
                    value={initialSort}
                    onChange={(e) => handleSortChange(e.target.value as McpSortMode)}
                    className="control control-sm w-auto"
                  >
                    <option value="relevance">{MCP_SORT_LABELS.relevance}</option>
                    <option value="top_graded">{MCP_SORT_LABELS.top_graded}</option>
                  </select>
                </div>
              </div>
            </div>

            {registryResult ? <FederationNotice result={registryResult} /> : null}

            {totalResults === 0 ? (
              <div className="rounded-lg border border-border bg-surface p-10 text-center">
                <p className="text-fg-muted">
                  No public capabilities{includeRegistry ? ' or registry servers' : ''} match{' '}
                  <span className="font-medium text-fg">
                    &ldquo;{initialQuery}&rdquo;
                  </span>
                  .
                </p>
                <Link href="/mcp" className="mt-4 inline-block text-base font-medium text-accent-fg">
                  Browse the catalog
                </Link>
              </div>
            ) : (
              <ul className="flex flex-col gap-3">
                {initialResults.length === 0 ? (
                  <li className="text-base text-fg-muted">
                    No public capabilities match &ldquo;{initialQuery}&rdquo;.
                  </li>
                ) : null}
                {initialResults.map((hit) => (
                  <li key={`${hit.item_id}`}>
                    <Link
                      href={`/mcp/${hit.tenant_slug}/${hit.endpoint_slug}`}
                      className="block rounded-lg border border-border bg-surface p-4 transition-colors hover:border-accent/30"
                    >
                      <div className="flex items-start gap-3">
                        <GradeBadge grade={hit.grade} score={hit.score} size="sm" />
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2 text-xs text-fg-muted">
                            <span className="truncate">
                              {hit.endpoint_name} · {hit.host ?? 'Unknown host'}
                            </span>
                            <span className="rounded-xs bg-subtle px-1.5 py-0.5 text-2xs font-semibold uppercase tracking-wide text-fg-muted">
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
                          <h3 className="mt-1 font-mono text-lg font-semibold text-fg">
                            <HighlightMatches text={hit.item_title || hit.item_name} query={initialQuery} />
                          </h3>
                          {hit.description ? (
                            <p className="mt-1 line-clamp-2 text-base text-fg-muted">
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
