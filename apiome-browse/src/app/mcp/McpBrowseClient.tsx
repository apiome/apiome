'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { AppShell } from '../components/AppShell';
import { sanitizeSearchInput } from '../utils/searchValidation';
import type { McpPublicHostGroup } from '../../../lib/types';
import { McpEndpointCard } from './McpShared';

/**
 * Public MCP catalog index (MCAT-9.6). Endpoints are grouped by host and grade-led within each
 * group (the idle, query-empty ordering). The search box hands off to /mcp/search, where results
 * switch to relevance-first ordering (MCAT-9.7).
 */
export function McpBrowseClient({ groups }: { groups: McpPublicHostGroup[] }) {
  const router = useRouter();
  const [query, setQuery] = useState('');

  const endpointCount = groups.reduce((n, g) => n + g.endpoints.length, 0);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    if (q) router.push(`/mcp/search?q=${encodeURIComponent(q)}`);
  };

  return (
    <AppShell containerSize="wide">
      <header className="border-b border-zinc-200 py-8 dark:border-zinc-800">
        <p className="text-[13px] font-semibold uppercase tracking-wider text-[var(--brand)]">MCP Catalog</p>
        <h1 className="mt-1 text-2xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
          Browse public MCP servers
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-zinc-600 dark:text-zinc-400">
          Published, public Model Context Protocol servers grouped by site and ranked by quality
          grade. Private servers never appear here.
        </p>

        <Link
          href="/mcp/analytics"
          className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-[var(--brand)] hover:underline"
        >
          View catalog analytics →
        </Link>

        <form onSubmit={handleSearch} className="relative mt-5 max-w-2xl">
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
            className="w-full rounded-lg border border-zinc-200 bg-zinc-50 py-3 pl-12 pr-28 text-[15px] text-zinc-900 placeholder-zinc-400 shadow-xs transition-colors focus-visible:border-[var(--brand)] focus-visible:outline-none dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-100 dark:placeholder-zinc-500"
          />
          <button
            type="submit"
            className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md bg-[var(--brand)] px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-[var(--brand-hover)]"
          >
            Search
          </button>
        </form>
      </header>

      {groups.length === 0 ? (
        <div className="my-10 rounded-xl border border-dashed border-zinc-300 bg-white/50 p-10 text-center dark:border-zinc-700 dark:bg-zinc-900/40">
          <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">No public MCP servers yet</h2>
          <p className="mx-auto mt-2 max-w-lg text-sm text-zinc-600 dark:text-zinc-400">
            Published, public servers will appear here grouped by site once they are available.
          </p>
        </div>
      ) : (
        <div className="space-y-8 py-8">
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            <span className="font-semibold text-zinc-900 dark:text-zinc-50">{endpointCount}</span>{' '}
            server{endpointCount === 1 ? '' : 's'} across{' '}
            <span className="font-semibold text-zinc-900 dark:text-zinc-50">{groups.length}</span>{' '}
            site{groups.length === 1 ? '' : 's'}
          </p>
          {groups.map((group) => (
            <section key={group.host}>
              <div className="mb-3 flex items-center gap-2">
                <svg className="h-4 w-4 text-zinc-400" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z M3 12h18 M12 3a15 15 0 010 18 M12 3a15 15 0 000 18" />
                </svg>
                <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">{group.host}</h2>
                <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                  {group.endpoints.length}
                </span>
              </div>
              <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {group.endpoints.map((endpoint) => (
                  <li key={endpoint.id}>
                    <McpEndpointCard endpoint={endpoint} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </AppShell>
  );
}
