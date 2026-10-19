/**
 * The catalog's entity kinds in the UI — CDG-5.1 (#5979).
 *
 * The kinds themselves (their labels, counts and pages) come from apiome-rest's registry
 * (`GET /v1/catalog/{tenant}/entities/summary`), never from a constant here: a kind added to the
 * registry shows up as a tile, in the Kind facet and in the entity list with no UI change. This
 * module holds the wire shapes, the URL parameter, the three home callouts and the proxy's
 * query-parameter allowlist.
 */

import type { EntityOwner } from '@lib/owners';

/** The kind the catalog home shows by default: catalog items, in today's cards and table. */
export const DEFAULT_CATALOG_KIND = 'spec';

/** The Kind facet's "every kind" value. */
export const ALL_CATALOG_KINDS = 'all';

/** The URL parameter holding the Kind facet. */
export const KIND_PARAM = 'kind';

/** One registry kind with its count (`EntityKindSummary`). */
export interface EntityKindSummary {
  kind: string;
  label: string;
  pluralLabel: string;
  count: number;
  /** Whether entities of the kind can have an owner team. */
  ownerSupport: boolean;
  /** The graph node kind, or `null`. */
  graphKind: string | null;
  /** The kind's own list page, when it has one. */
  listHref: string | null;
}

/** The home callouts; a count the caller may not see is `null`. */
export interface CatalogCallouts {
  unowned: number | null;
  stale: number | null;
  shadow: number | null;
}

/** `GET …/entities/summary`. */
export interface CatalogEntitySummary {
  kinds: EntityKindSummary[];
  callouts: CatalogCallouts;
}

/** One entity in the common envelope. */
export interface CatalogEntity {
  kind: string;
  id: string;
  slug: string | null;
  name: string;
  description: string | null;
  owner: EntityOwner | null;
  updatedAt: string | null;
  /** The page that renders it. */
  href: string;
  graphNode: { kind: string; id: string } | null;
}

/** `GET …/entities`. */
export interface CatalogEntityPage {
  items: CatalogEntity[];
  pagination: { nextCursor: string | null };
}

/** One home callout: what it counts and the report it opens. */
export interface CalloutDefinition {
  key: keyof CatalogCallouts;
  label: string;
  /** What the count means, for the tooltip and screen readers. */
  description: string;
  href: string;
}

/** The three callouts, in order. Unowned and Stale open the existing pages that act on them. */
export const CATALOG_CALLOUTS: readonly CalloutDefinition[] = [
  {
    key: 'unowned',
    label: 'Unowned',
    description: 'Entities with no confirmed owner team',
    href: '/ade/dashboard/teams#tm-drift',
  },
  {
    key: 'stale',
    label: 'Stale',
    description: 'Connectors and MCP servers not refreshed within twice their cadence',
    href: '/ade/dashboard/connectors',
  },
  {
    key: 'shadow',
    label: 'Shadow',
    description: 'Gateway APIs with no catalog entry',
    href: '/ade/dashboard/connectors/shadow',
  },
];

/** A kind key as the registry spells one. */
const KIND_KEY = /^[a-z][a-z0-9_]{0,39}$/;

/**
 * The Kind facet named by the URL.
 *
 * @param value - The raw `?kind=` value.
 * @returns A kind key, {@link ALL_CATALOG_KINDS}, or {@link DEFAULT_CATALOG_KIND} for anything else.
 */
export function catalogKindParam(value: string | null | undefined): string {
  const raw = (value ?? '').trim();
  if (raw === ALL_CATALOG_KINDS) return raw;
  return KIND_KEY.test(raw) ? raw : DEFAULT_CATALOG_KIND;
}

/**
 * The query string for one facet value, keeping every other parameter.
 *
 * @param search - The current query string.
 * @param kind - The facet value; the default kind is spelled by no `?kind=` at all.
 * @returns The new query string with its leading `?`, or `?` when nothing is left.
 */
export function withKindParam(search: string, kind: string): string {
  const params = new URLSearchParams(search);
  if (kind === DEFAULT_CATALOG_KIND) params.delete(KIND_PARAM);
  else params.set(KIND_PARAM, kind);
  const query = params.toString();
  return query ? `?${query}` : '?';
}

/**
 * The label of a kind, from the summary, falling back to the key.
 *
 * @param kinds - The summary's kinds.
 * @param kind - A kind key.
 * @param plural - The plural label.
 */
export function kindLabel(kinds: readonly EntityKindSummary[], kind: string, plural = false): string {
  const entry = kinds.find((candidate) => candidate.kind === kind);
  if (!entry) return kind;
  return plural ? entry.pluralLabel : entry.label;
}

/** Query parameters the entity-list proxy forwards, and how many of each. */
const FORWARDED: Readonly<Record<string, 'single' | 'repeat'>> = {
  kind: 'repeat',
  team: 'single',
  q: 'single',
  cursor: 'single',
  limit: 'single',
};

/**
 * The allowed, well-formed query parameters of an entity-list or summary request.
 *
 * @param params - The browser's query parameters.
 * @param allowed - Parameter names to keep (default: every entity-list parameter).
 * @returns The query string to forward, with its leading `?`, or `''`.
 */
export function entityQuery(params: URLSearchParams, allowed: readonly string[] = Object.keys(FORWARDED)): string {
  const out = new URLSearchParams();
  for (const name of allowed) {
    const mode = FORWARDED[name];
    if (!mode) continue;
    const values = mode === 'repeat' ? params.getAll(name) : [params.get(name)].filter((v): v is string => v !== null);
    for (const value of values) {
      if (!value || value.length > 2000) continue;
      if (name === 'kind' && !KIND_KEY.test(value)) continue;
      if (name === 'limit' && !/^[1-9][0-9]{0,2}$/.test(value)) continue;
      out.append(name, value);
    }
  }
  const query = out.toString();
  return query ? `?${query}` : '';
}
