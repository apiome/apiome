'use client';

/**
 * The catalog's entities of one kind, or of every kind — CDG-5.1 (#5979).
 *
 * Shown on the catalog home when the Kind facet is anything but Catalog items (which keep their
 * cards and table). One table for every kind: the name (linked to the page that renders it), its
 * kind, its owner team and when it last changed. Rows come from `GET …/catalog/{t}/entities` in
 * name order; **Load more** reads the next page with the cursor. The search box and the owner
 * filter (`?team=`) narrow it on the server.
 */

import * as React from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';
import { Badge, Button, EmptyState, LoadingState } from '@/app/components/ui';
import { DataTableSearch } from '@/app/components/ui/DataTable';
import { OwnerCell } from '@/app/components/ade/owners/OwnerCell';
import {
  ALL_CATALOG_KINDS,
  kindLabel,
  type CatalogEntity,
  type EntityKindSummary,
} from '@lib/catalog-entities';
import type { OwnerEntityKind } from '@lib/owners';
import { fetchEntityPage } from './catalogEntitiesApi';

/** Rows per page. */
const PAGE_SIZE = 50;

/** How long the search box waits after the last keystroke. */
const SEARCH_DELAY_MS = 250;

/** Props for {@link CatalogEntityList}. */
export interface CatalogEntityListProps {
  /** A kind key, or {@link ALL_CATALOG_KINDS}. */
  kind: string;
  /** The owner team filter (`?team=`). */
  team: string | null;
  /** The registry's kinds, for labels. */
  kinds: readonly EntityKindSummary[];
}

/** The list's read state. */
interface ListState {
  items: CatalogEntity[];
  nextCursor: string | null;
  loading: boolean;
  error: string | null;
}

/**
 * The entity table.
 *
 * @param props - See {@link CatalogEntityListProps}.
 * @returns The list.
 */
export function CatalogEntityList({ kind, team, kinds }: CatalogEntityListProps) {
  const [query, setQuery] = React.useState('');
  const [search, setSearch] = React.useState('');
  const [state, setState] = React.useState<ListState>({ items: [], nextCursor: null, loading: true, error: null });
  const apiKind = kind === ALL_CATALOG_KINDS ? null : kind;
  const title = kind === ALL_CATALOG_KINDS ? 'All kinds' : kindLabel(kinds, kind, true);

  React.useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query), SEARCH_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [query]);

  const load = React.useCallback(
    async (cursor: string | null) => {
      setState((current) => ({ ...current, loading: true, error: null }));
      try {
        const page = await fetchEntityPage({ kind: apiKind, team, q: search, cursor, limit: PAGE_SIZE });
        setState((current) => ({
          items: cursor ? [...current.items, ...page.items] : page.items,
          nextCursor: page.pagination.nextCursor,
          loading: false,
          error: null,
        }));
      } catch (caught) {
        setState((current) => ({
          ...current,
          loading: false,
          error: caught instanceof Error ? caught.message : 'Could not load the catalog',
        }));
      }
    },
    [apiKind, team, search],
  );

  React.useEffect(() => {
    void load(null);
  }, [load]);

  const { items, nextCursor, loading, error } = state;

  return (
    <section className="cat-entities" aria-labelledby="cat-entities-title" data-testid="catalog-entity-list">
      <div className="cat-entities__head">
        <h2 id="cat-entities-title" className="cat-entities__title">
          {title}
        </h2>
        <DataTableSearch
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Filter by name, slug or description"
          aria-label={`Filter ${title.toLowerCase()}`}
          data-testid="catalog-entity-search"
        />
      </div>
      {error && items.length === 0 ? (
        <EmptyState
          variant="compact"
          surface={false}
          tone="danger"
          title="The catalog could not be read"
          description={error}
          action={
            <Button variant="soft" onClick={() => void load(null)}>
              <RefreshCw aria-hidden />
              Try again
            </Button>
          }
        />
      ) : loading && items.length === 0 ? (
        <LoadingState message="Reading the catalog…" minHeightClassName="min-h-[8rem]" />
      ) : items.length === 0 ? (
        <EmptyState
          variant="compact"
          surface={false}
          title="Nothing matches"
          description="Clear the filter or the owner team to see more."
        />
      ) : (
        <>
          <div className="cat-entities__wrap">
            <table className="cat-entities__table" data-testid="catalog-entity-table">
              <caption className="sr-only">{title} in this workspace</caption>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Owner</th>
                  <th scope="col">Updated</th>
                </tr>
              </thead>
              <tbody>
                {items.map((entity) => (
                  <tr key={`${entity.kind}:${entity.id}`} data-testid={`catalog-entity-${entity.kind}-${entity.id}`}>
                    <td>
                      <Link className="cat-entities__name" href={entity.href}>
                        {entity.name}
                      </Link>
                      {entity.slug ? <span className="cat-entities__sub mono">{entity.slug}</span> : null}
                      {entity.description ? <span className="cat-entities__sub">{entity.description}</span> : null}
                    </td>
                    <td>
                      <Badge variant="neutral" square>
                        {kindLabel(kinds, entity.kind)}
                      </Badge>
                    </td>
                    <td>
                      {entity.owner && entity.graphNode ? (
                        <OwnerCell
                          owner={entity.owner}
                          kind={entity.graphNode.kind as OwnerEntityKind}
                          entityId={entity.id}
                          readOnly
                        />
                      ) : (
                        <span className="cat-entities__muted">—</span>
                      )}
                    </td>
                    <td className="cat-entities__date">
                      {entity.updatedAt ? new Date(entity.updatedAt).toLocaleDateString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {error ? <p className="cat-entities__muted" role="alert">{error}</p> : null}
          {nextCursor ? (
            <div className="cat-entities__more">
              <Button
                variant="outline"
                size="sm"
                disabled={loading}
                onClick={() => void load(nextCursor)}
                data-testid="catalog-entity-more"
              >
                {loading ? 'Loading…' : 'Load more'}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
