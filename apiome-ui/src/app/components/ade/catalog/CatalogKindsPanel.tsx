'use client';

/**
 * The catalog home's kinds and callouts — CDG-5.1 (#5979).
 *
 * * **Kind** — one tile per entity kind in the registry (Projects, Catalog items, MCP servers,
 *   Consumers, Connectors, Teams, and any kind added later), each with its count, plus **All
 *   kinds**. The tiles *are* the Kind facet: pressing one shows that kind below. The list of kinds
 *   comes from apiome-rest, so a new kind needs no change here.
 * * **Callouts** — **Unowned**, **Stale** and **Shadow**, each with its count and a link to the page
 *   that acts on it. A count the reader may not see is left out.
 */

import * as React from 'react';
import Link from 'next/link';
import {
  ALL_CATALOG_KINDS,
  isCatalogKindReleased,
  releasedCatalogCallouts,
  type CatalogEntitySummary,
} from '@lib/catalog-entities';

/** Props for {@link CatalogKindsPanel}. */
export interface CatalogKindsPanelProps {
  /** The kinds and callouts. */
  summary: CatalogEntitySummary;
  /** The selected facet value: a kind key or {@link ALL_CATALOG_KINDS}. */
  selected: string;
  /** Called with the facet value a tile selects. */
  onSelect: (kind: string) => void;
}

/**
 * The tiles and callouts.
 *
 * @param props - See {@link CatalogKindsPanelProps}.
 * @returns The panel.
 */
export function CatalogKindsPanel({ summary, selected, onSelect }: CatalogKindsPanelProps) {
  // Kinds and callouts whose pages are held back (lib/feature-release.ts) are left out.
  const kinds = summary.kinds.filter((entry) => isCatalogKindReleased(entry.kind));
  const total = kinds.reduce((sum, entry) => sum + entry.count, 0);
  const tiles = [
    { kind: ALL_CATALOG_KINDS, label: 'All kinds', count: total },
    ...kinds.map((entry) => ({ kind: entry.kind, label: entry.pluralLabel, count: entry.count })),
  ];
  const callouts = releasedCatalogCallouts().filter((callout) => summary.callouts[callout.key] !== null);

  return (
    <section className="cat-kinds" aria-label="Catalog kinds" data-testid="catalog-kinds">
      <div className="cat-kinds__tiles" role="group" aria-label="Kind">
        {tiles.map((tile) => (
          <button
            key={tile.kind}
            type="button"
            className="cat-kinds__tile"
            aria-pressed={selected === tile.kind}
            onClick={() => onSelect(tile.kind)}
            data-testid={`catalog-kind-${tile.kind}`}
          >
            <span className="cat-kinds__count">{tile.count.toLocaleString()}</span>
            <span className="cat-kinds__label">{tile.label}</span>
          </button>
        ))}
      </div>
      {callouts.length > 0 ? (
        <ul className="cat-kinds__callouts" aria-label="Needs attention">
          {callouts.map((callout) => {
            const count = summary.callouts[callout.key] ?? 0;
            return (
              <li key={callout.key}>
                <Link
                  href={callout.href}
                  className="cat-kinds__callout"
                  data-attention={count > 0 ? '' : undefined}
                  title={callout.description}
                  data-testid={`catalog-callout-${callout.key}`}
                >
                  <span className="cat-kinds__callout-count">{count.toLocaleString()}</span>
                  <span>{callout.label}</span>
                  <span className="sr-only">: {callout.description}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      ) : null}
    </section>
  );
}
