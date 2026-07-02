'use client';

import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { AppShell } from '../components/AppShell';
import { sanitizeSearchInput } from '../utils/searchValidation';
import type { PublishedCatalogSearchHit } from '../../../lib/db/helper';

const SUGGESTED_QUERIES = ['payments', 'POST /', 'webhooks', 'schema', 'inventory'];
const RECENT_KEY = 'apiome-browse-search-recent';
const RECENT_MAX = 8;

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
          <mark
            key={i}
            className="rounded-sm bg-indigo-500/20 px-0.5 text-inherit dark:bg-indigo-400/35"
          >
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}

function readRecent(): string[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

function pushRecent(q: string) {
  if (typeof window === 'undefined' || !q.trim()) return;
  const prev = readRecent().filter((x) => x.toLowerCase() !== q.trim().toLowerCase());
  prev.unshift(q.trim());
  window.localStorage.setItem(RECENT_KEY, JSON.stringify(prev.slice(0, RECENT_MAX)));
}

function hitIcon(hitType: string) {
  const common = 'h-5 w-5';
  switch (hitType) {
    case 'path':
      return (
        <svg className={common} fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
        </svg>
      );
    case 'schema':
      return (
        <svg className={common} fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
        </svg>
      );
    case 'project':
      return (
        <svg className={common} fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
        </svg>
      );
    default:
      return (
        <svg className={common} fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h7" />
        </svg>
      );
  }
}

function hitTone(hitType: string): string {
  switch (hitType) {
    case 'path':
      return 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300';
    case 'schema':
    case 'property':
      return 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300';
    case 'project':
      return 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300';
    case 'request_body':
    case 'response':
      return 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300';
    default:
      return 'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300';
  }
}

export function SearchClient({
  initialQuery,
  initialResults,
}: {
  initialQuery: string;
  initialResults: PublishedCatalogSearchHit[];
}) {
  const router = useRouter();
  // Search results are server-rendered, so submitting navigates and refetches. Wrapping the
  // navigation in a transition lets us show a spinner while the new results compute, instead of
  // leaving the user on stale/empty content with no feedback.
  const [isSearching, startSearch] = useTransition();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState(initialQuery);
  const [panelOpen, setPanelOpen] = useState(false);
  const [recent, setRecent] = useState<string[]>([]);
  const [sortKey, setSortKey] = useState<'relevance' | 'newest'>('relevance');
  const [view, setView] = useState<'list' | 'grid'>('list');
  const [allowedTenants, setAllowedTenants] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    setQuery(initialQuery);
  }, [initialQuery]);

  useEffect(() => {
    setRecent(readRecent());
  }, []);

  const tenantOptions = useMemo(() => {
    const m = new Map<string, string>();
    for (const r of initialResults) {
      if (!m.has(r.tenant_slug)) m.set(r.tenant_slug, r.tenant_name);
    }
    return [...m.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [initialResults]);

  useEffect(() => {
    setAllowedTenants(new Set(initialResults.map((r) => r.tenant_slug)));
  }, [initialResults]);

  const filtered = useMemo(() => {
    let rows = initialResults.filter((r) => allowedTenants.has(r.tenant_slug));
    if (sortKey === 'newest') {
      rows = [...rows].sort((a, b) => {
        const ta = a.published_at ? new Date(a.published_at).getTime() : 0;
        const tb = b.published_at ? new Date(b.published_at).getTime() : 0;
        return tb - ta;
      });
    }
    return rows;
  }, [initialResults, allowedTenants, sortKey]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    setPanelOpen(false);
    if (q) {
      pushRecent(q);
      setRecent(readRecent());
      startSearch(() => router.push(`/search?q=${encodeURIComponent(q)}`));
    }
  };

  const applyQuery = useCallback(
    (q: string) => {
      const t = q.trim();
      if (!t) return;
      pushRecent(t);
      setRecent(readRecent());
      setPanelOpen(false);
      setQuery(t);
      startSearch(() => router.push(`/search?q=${encodeURIComponent(t)}`));
    },
    [router]
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
        setPanelOpen(true);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const toggleTenant = (slug: string) => {
    setAllowedTenants((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) {
        if (next.size <= 1) return next;
        next.delete(slug);
      } else {
        next.add(slug);
      }
      return next;
    });
  };

  const resetTenants = () => {
    setAllowedTenants(new Set(initialResults.map((r) => r.tenant_slug)));
  };

  const formatPublished = (iso: string | null) => {
    if (!iso) return null;
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  };

  const started = useRef<number | null>(null);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);

  useEffect(() => {
    if (initialQuery) {
      started.current = performance.now();
      const id = requestAnimationFrame(() => {
        if (started.current != null) setElapsedMs(Math.round(performance.now() - started.current));
      });
      return () => cancelAnimationFrame(id);
    }
    setElapsedMs(null);
    return undefined;
  }, [initialQuery, initialResults]);

  return (
    <AppShell containerSize="full">
      <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
          <p className="mb-3 text-[13px] text-zinc-500 dark:text-zinc-400">
            Search published public specifications only — private projects never appear here.
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
              ref={inputRef}
              type="search"
              name="q"
              enterKeyHint="search"
              value={query}
              onChange={(e) => setQuery(sanitizeSearchInput(e.target.value))}
              onFocus={() => setPanelOpen(true)}
              onBlur={() => setTimeout(() => setPanelOpen(false), 120)}
              placeholder="Search paths, schemas, parameters, and descriptions…"
              className="w-full rounded-lg border border-zinc-200 bg-zinc-50 py-3.5 pl-12 pr-36 text-[15px] text-zinc-900 placeholder-zinc-400 shadow-xs transition-colors focus-visible:border-[var(--brand)] focus-visible:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100 dark:placeholder-zinc-500"
              autoFocus
            />
            <div className="absolute right-3 top-1/2 flex -translate-y-1/2 items-center gap-2">
              <span className="hidden items-center gap-1 font-mono text-[11px] text-zinc-500 sm:flex">
                <kbd className="rounded border border-zinc-200 bg-white px-1.5 py-0.5 dark:border-zinc-600 dark:bg-zinc-800">
                  ⌘K
                </kbd>
              </span>
              <button
                type="submit"
                disabled={isSearching}
                className="inline-flex items-center gap-1.5 rounded-md bg-[var(--brand)] px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[var(--brand-hover)] disabled:opacity-80"
              >
                {isSearching && <Spinner className="h-3.5 w-3.5 text-white" />}
                {isSearching ? 'Searching…' : 'Search'}
              </button>
            </div>

            {panelOpen && (
              <div className="absolute left-0 right-0 top-full z-30 mt-2 overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-xl dark:border-zinc-700 dark:bg-zinc-900">
                <div className="flex items-center gap-2 border-b border-zinc-200 bg-zinc-50 px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-400">
                  Suggestions
                  <span className="ml-auto font-normal normal-case text-[10px] text-zinc-400">
                    Public catalog only
                  </span>
                </div>
                <ul className="max-h-48 divide-y divide-zinc-100 overflow-y-auto text-sm dark:divide-zinc-800">
                  {SUGGESTED_QUERIES.map((s) => (
                    <li key={s}>
                      <button
                        type="button"
                        className="flex w-full items-center gap-2 px-3 py-2 text-left text-zinc-700 hover:bg-zinc-50 dark:text-zinc-200 dark:hover:bg-zinc-800/80"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => applyQuery(s)}
                      >
                        <span className="text-indigo-500">↵</span>
                        {s}
                      </button>
                    </li>
                  ))}
                </ul>
                {recent.length > 0 && (
                  <>
                    <div className="flex items-center justify-between border-t border-zinc-200 bg-zinc-50 px-3 py-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-400">
                      Recent
                      <button
                        type="button"
                        className="normal-case font-normal text-indigo-600 hover:underline dark:text-indigo-400"
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => {
                          localStorage.removeItem(RECENT_KEY);
                          setRecent([]);
                        }}
                      >
                        Clear
                      </button>
                    </div>
                    <ul className="max-h-40 divide-y divide-zinc-100 overflow-y-auto text-sm dark:divide-zinc-800">
                      {recent.map((r) => (
                        <li key={r}>
                          <button
                            type="button"
                            className="flex w-full items-center gap-2 px-3 py-2 text-left text-zinc-600 hover:bg-zinc-50 dark:text-zinc-300 dark:hover:bg-zinc-800/80"
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => applyQuery(r)}
                          >
                            {r}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            )}
          </form>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl grid-cols-12 gap-6 px-4 py-6 sm:px-6">
        <aside className="col-span-12 lg:col-span-3">
          <div className="rounded-lg border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
            <div className="flex items-center gap-2 rounded-t-lg border-b border-zinc-200 bg-zinc-50 px-4 py-3 dark:border-zinc-800 dark:bg-zinc-950">
              <svg className="h-4 w-4 text-indigo-500" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
              </svg>
              <h3 className="flex-1 text-sm font-semibold text-zinc-900 dark:text-zinc-50">Filters</h3>
              <button
                type="button"
                onClick={resetTenants}
                className="text-[11px] text-indigo-600 hover:underline dark:text-indigo-400"
              >
                Reset
              </button>
            </div>
            <div className="space-y-5 p-4 text-xs text-zinc-700 dark:text-zinc-300">
              <div>
                <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                  Organization
                </p>
                {initialQuery && tenantOptions.length === 0 ? (
                  <p className="text-zinc-500 dark:text-zinc-400">No facets for this query.</p>
                ) : (
                  <ul className="max-h-60 space-y-1.5 overflow-y-auto">
                    {tenantOptions.map(([slug, name]) => (
                      <li key={slug} className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          id={`t-${slug}`}
                          checked={allowedTenants.has(slug)}
                          onChange={() => toggleTenant(slug)}
                          className="accent-indigo-600"
                        />
                        <label htmlFor={`t-${slug}`} className="flex-1 cursor-pointer truncate">
                          {name}
                        </label>
                        <span className="font-mono text-zinc-400">
                          {initialResults.filter((r) => r.tenant_slug === slug).length}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <p className="border-t border-zinc-100 pt-3 text-[10px] text-zinc-500 dark:border-zinc-800 dark:text-zinc-400">
                Results include operations, models, and docs from every published public version that matches
                your terms.
              </p>
            </div>
          </div>
        </aside>

        <section className="col-span-12 space-y-3 lg:col-span-9">
          {isSearching && (
            <div
              className="flex flex-col items-center justify-center rounded-xl border border-zinc-200 bg-white p-12 text-center dark:border-zinc-800 dark:bg-zinc-900"
              role="status"
              aria-live="polite"
            >
              <Spinner className="h-7 w-7" />
              <p className="mt-4 text-sm text-zinc-600 dark:text-zinc-300">
                Searching the catalog
                {query.trim() && (
                  <>
                    {' for '}
                    <span className="font-mono text-indigo-600 dark:text-indigo-400">&ldquo;{query.trim()}&rdquo;</span>
                  </>
                )}
                …
              </p>
            </div>
          )}

          {!isSearching && !initialQuery && (
            <div className="rounded-xl border border-dashed border-zinc-300 bg-white/50 p-10 text-center dark:border-zinc-700 dark:bg-zinc-900/40">
              <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">Search the public catalog</h2>
              <p className="mx-auto mt-2 max-w-lg text-[14px] text-zinc-600 dark:text-zinc-400">
                Enter plain text to match organization names, project slugs, OpenAPI paths, schemas, parameters,
                and other published documentation.
              </p>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {SUGGESTED_QUERIES.map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => applyQuery(s)}
                    className="rounded-full border border-zinc-200 bg-white px-3 py-1 text-[12px] font-medium text-zinc-700 shadow-xs hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {!isSearching && initialQuery && (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-zinc-600 dark:text-zinc-300">
                  <span className="font-semibold text-zinc-900 dark:text-zinc-50">{filtered.length} results</span>
                  <span className="text-zinc-400"> for </span>
                  <span className="font-mono text-indigo-600 dark:text-indigo-400">&ldquo;{initialQuery}&rdquo;</span>
                  {elapsedMs != null && (
                    <span className="text-zinc-400">
                      {' '}
                      in {elapsedMs}ms
                    </span>
                  )}
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[11px] text-zinc-500">Sort</span>
                  <select
                    value={sortKey}
                    onChange={(e) => setSortKey(e.target.value as 'relevance' | 'newest')}
                    className="rounded-md border border-zinc-200 bg-white px-2 py-1 text-xs text-zinc-800 shadow-xs dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
                  >
                    <option value="relevance">Relevance</option>
                    <option value="newest">Newest published</option>
                  </select>
                  <span className="hidden h-5 w-px bg-zinc-200 sm:inline dark:bg-zinc-700" />
                  <div className="inline-flex overflow-hidden rounded-md border border-zinc-200 dark:border-zinc-700">
                    <button
                      type="button"
                      title="List view"
                      onClick={() => setView('list')}
                      className={`px-2 py-1 text-[11px] font-semibold ${
                        view === 'list'
                          ? 'bg-[var(--brand)] text-white'
                          : 'text-zinc-600 hover:bg-zinc-50 dark:text-zinc-300 dark:hover:bg-zinc-800'
                      }`}
                    >
                      List
                    </button>
                    <button
                      type="button"
                      title="Grid view"
                      onClick={() => setView('grid')}
                      className={`border-l border-zinc-200 px-2 py-1 text-[11px] font-medium dark:border-zinc-700 ${
                        view === 'grid'
                          ? 'bg-[var(--brand)] text-white'
                          : 'text-zinc-600 hover:bg-zinc-50 dark:text-zinc-300 dark:hover:bg-zinc-800'
                      }`}
                    >
                      Grid
                    </button>
                  </div>
                </div>
              </div>

              {filtered.length === 0 ? (
                <div className="rounded-xl border border-zinc-200 bg-white p-10 text-center dark:border-zinc-800 dark:bg-zinc-900">
                  <p className="text-zinc-600 dark:text-zinc-400">
                    No public published matches for{' '}
                    <span className="font-medium text-zinc-900 dark:text-zinc-50">&ldquo;{initialQuery}&rdquo;</span>.
                  </p>
                  <Link href="/" className="mt-4 inline-block text-sm font-medium text-indigo-600 dark:text-indigo-400">
                    Browse the directory
                  </Link>
                </div>
              ) : (
                <ul
                  className={
                    view === 'grid'
                      ? 'grid gap-3 sm:grid-cols-2'
                      : 'flex flex-col gap-3'
                  }
                >
                  {filtered.map((hit) => {
                    const href = `/tenant/${hit.tenant_slug}/${hit.project_slug}/${hit.version_slug}`;
                    const pub = formatPublished(hit.published_at);
                    return (
                      <li key={hit.hit_id}>
                        <Link
                          href={href}
                          className="block rounded-lg border border-zinc-200 bg-white p-4 transition-colors hover:border-indigo-300 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-indigo-700"
                        >
                          <div className="flex items-start gap-3">
                            <div
                              className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${hitTone(hit.hit_type)}`}
                            >
                              {hitIcon(hit.hit_type)}
                            </div>
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
                                <span>
                                  {hit.tenant_slug} · {hit.project_slug}
                                </span>
                                <span className="rounded bg-indigo-500/10 px-1.5 py-0.5 font-mono text-[10px] text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300">
                                  v{hit.version_slug}
                                </span>
                                <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                                  {hit.hit_type.replace(/_/g, ' ')}
                                </span>
                              </div>
                              <h3 className="mt-1 text-base font-semibold text-zinc-900 dark:text-zinc-50">
                                <HighlightMatches text={hit.title} query={initialQuery} />
                              </h3>
                              {hit.snippet ? (
                                <p className="mt-1 line-clamp-3 text-sm text-zinc-600 dark:text-zinc-300">
                                  <HighlightMatches text={hit.snippet} query={initialQuery} />
                                </p>
                              ) : null}
                              <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-zinc-500 dark:text-zinc-400">
                                {hit.subtitle ? (
                                  <span className="flex items-center gap-1">
                                    <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                                      <path strokeLinecap="round" strokeLinejoin="round" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                                    </svg>
                                    {hit.subtitle}
                                  </span>
                                ) : null}
                                {pub ? (
                                  <span className="flex items-center gap-1">
                                    <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                                      <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                                    </svg>
                                    {pub}
                                  </span>
                                ) : null}
                              </div>
                            </div>
                          </div>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              )}
            </>
          )}
        </section>
      </div>
    </AppShell>
  );
}
