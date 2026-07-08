'use client';

import Link from 'next/link';
import type { McpPublicCollection } from '../../../../../../lib/types';
import { McpEndpointCard } from '../../../McpShared';

export function McpCollectionClient({
  collection,
}: {
  collection: McpPublicCollection;
}) {
  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
      <nav className="mb-6 text-sm text-zinc-500 dark:text-zinc-400">
        <Link href="/mcp" className="hover:text-[var(--brand)]">
          MCP Catalog
        </Link>
        <span className="mx-2">/</span>
        <span className="text-zinc-700 dark:text-zinc-200">{collection.tenant_name}</span>
        <span className="mx-2">/</span>
        <span className="text-zinc-700 dark:text-zinc-200">{collection.name}</span>
      </nav>

      <header className="mb-8">
        <p className="text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
          Curated collection
        </p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
          {collection.name}
        </h1>
        {collection.description ? (
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
            {collection.description}
          </p>
        ) : null}
        <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-400">
          {collection.endpoints.length} public endpoint
          {collection.endpoints.length === 1 ? '' : 's'} in this collection.
        </p>
      </header>

      {collection.endpoints.length === 0 ? (
        <div className="rounded-xl border border-dashed border-zinc-300 bg-zinc-50 p-8 text-center dark:border-zinc-700 dark:bg-zinc-900/40">
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            This collection has no published public endpoints to show yet.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {collection.endpoints.map((endpoint) => (
            <McpEndpointCard key={endpoint.id} endpoint={endpoint} />
          ))}
        </div>
      )}
    </div>
  );
}
