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
      <nav className="mb-6 text-base text-fg-muted">
        <Link href="/mcp" className="hover:text-accent-fg">
          MCP Catalog
        </Link>
        <span className="mx-2">/</span>
        <span className="text-fg-muted">{collection.tenant_name}</span>
        <span className="mx-2">/</span>
        <span className="text-fg-muted">{collection.name}</span>
      </nav>

      <header className="mb-8">
        <p className="text-xs font-medium uppercase tracking-wide text-fg-muted">
          Curated collection
        </p>
        <h1 className="mt-1 text-4xl font-bold tracking-tight text-fg">
          {collection.name}
        </h1>
        {collection.description ? (
          <p className="mt-2 max-w-3xl text-base leading-relaxed text-fg-muted">
            {collection.description}
          </p>
        ) : null}
        <p className="mt-3 text-base text-fg-muted">
          {collection.endpoints.length} public endpoint
          {collection.endpoints.length === 1 ? '' : 's'} in this collection.
        </p>
      </header>

      {collection.endpoints.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border-strong bg-subtle p-8 text-center">
          <p className="text-base text-fg-muted">
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
