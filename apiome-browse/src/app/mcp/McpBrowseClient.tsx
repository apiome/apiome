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
      <header className="border-b border-border py-8">
        <p className="text-sm font-semibold uppercase tracking-wider text-accent-fg">MCP Catalog</p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight text-fg">
          Browse public MCP servers
        </h1>
        <p className="mt-2 max-w-2xl text-base text-fg-muted">
          Published, public Model Context Protocol servers grouped by site and ranked by quality
          grade. Private servers never appear here.
        </p>

        <Link
          href="/mcp/analytics"
          className="mt-3 inline-flex items-center gap-1 text-base font-medium text-accent-fg hover:underline"
        >
          View catalog analytics →
        </Link>

        <form onSubmit={handleSearch} className="relative mt-5 max-w-2xl">
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
          />
          <button
            type="submit"
            className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-fg-on-accent transition-colors hover:bg-accent-hover"
          >
            Search
          </button>
        </form>
      </header>

      {groups.length === 0 ? (
        <div className="my-10 rounded-lg border border-dashed border-border-strong bg-surface/50 p-10 text-center">
          <h2 className="text-xl font-semibold text-fg">No public MCP servers yet</h2>
          <p className="mx-auto mt-2 max-w-lg text-base text-fg-muted">
            Published, public servers will appear here grouped by site once they are available.
          </p>
        </div>
      ) : (
        <div className="space-y-8 py-8">
          <p className="text-base text-fg-muted">
            <span className="font-semibold text-fg">{endpointCount}</span>{' '}
            server{endpointCount === 1 ? '' : 's'} across{' '}
            <span className="font-semibold text-fg">{groups.length}</span>{' '}
            site{groups.length === 1 ? '' : 's'}
          </p>
          {groups.map((group) => (
            <section key={group.host}>
              <div className="mb-3 flex items-center gap-2">
                <svg className="h-4 w-4 text-fg-subtle" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z M3 12h18 M12 3a15 15 0 010 18 M12 3a15 15 0 000 18" />
                </svg>
                <h2 className="text-base font-semibold text-fg">{group.host}</h2>
                <span className="rounded-full bg-subtle px-2 py-0.5 text-2xs font-medium text-fg-muted">
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
