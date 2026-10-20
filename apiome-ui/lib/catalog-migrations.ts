/**
 * Backstage and Compass import — CDG-5.5 (#5983): wire types, the proxy's path rules and the view
 * helpers shared by the import report, the **Import to catalog** wizard's Compass source and the
 * component page.
 *
 * An import report is what a repository's `catalog-info.yaml` files (re-read by every scan) or one
 * uploaded Compass export produced: suggested teams and components waiting for a click, and every
 * field that has no Apiome equivalent. Nothing becomes a team, a component or a confirmed owner
 * until someone accepts it.
 */

import type { EntityOwner } from '@lib/owners';

/** Where a report came from. */
export type MigrationSource = 'backstage' | 'compass';

/** What a suggestion would become. */
export type SuggestionKind = 'component' | 'team';

/** Where a suggestion stands. */
export type SuggestionStatus = 'suggested' | 'accepted' | 'dismissed';

/** A component's category: Backstage's entity kinds (a Compass component is a `component`). */
export type ComponentCategory = 'component' | 'system' | 'domain';

/** The kinds of link a component keeps. */
export type ComponentLinkType = 'chat' | 'on_call' | 'document' | 'repository' | 'dashboard' | 'other';

/** One link. */
export interface ComponentLink {
  type: ComponentLinkType;
  url: string;
  title?: string | null;
}

/** A field an import read but could not map (its value is never stored). */
export interface UnmappedField {
  entity: string;
  field: string;
  reason: string;
}

/** One staged team or component. */
export interface MigrationSuggestion {
  id: string;
  kind: SuggestionKind;
  source: MigrationSource;
  externalRef: string;
  name: string;
  slug: string;
  status: SuggestionStatus;
  payload: Record<string, unknown>;
  /** The Project or catalog item the component already is. */
  match: { kind: 'project' | 'catalog_item'; id: string; name: string | null; slug: string | null } | null;
  /** What accepting made or applied to. */
  entity: { kind: string; id: string; slug: string | null } | null;
  decidedAt: string | null;
}

/** One import report. */
export interface MigrationRun {
  id: string;
  source: MigrationSource;
  label: string;
  repositoryId: string | null;
  branch: string | null;
  counts: Record<string, number>;
  unmapped: UnmappedField[];
  unmappedTotal: number;
  pending: number;
  suggestions: MigrationSuggestion[] | null;
  createdAt: string | null;
  updatedAt: string | null;
}

/** An accepted component. */
export interface CatalogComponent {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  category: ComponentCategory;
  componentType: string | null;
  lifecycle: string | null;
  parentRef: string | null;
  links: ComponentLink[];
  source: MigrationSource;
  externalRef: string;
  owner: EntityOwner | null;
  createdAt: string | null;
  updatedAt: string | null;
}

/** Overrides sent when accepting. */
export interface AcceptSuggestionInput {
  name?: string;
  slug?: string;
  asComponent?: boolean;
}

export const MIGRATION_SOURCE_LABELS: Readonly<Record<MigrationSource, string>> = {
  backstage: 'Backstage',
  compass: 'Compass',
};

export const COMPONENT_CATEGORY_LABELS: Readonly<Record<ComponentCategory, string>> = {
  component: 'Component',
  system: 'System',
  domain: 'Domain',
};

export const LINK_TYPE_LABELS: Readonly<Record<ComponentLinkType, string>> = {
  chat: 'Chat',
  on_call: 'On-call',
  document: 'Docs',
  repository: 'Repository',
  dashboard: 'Dashboard',
  other: 'Link',
};

export const SUGGESTION_STATUS_LABELS: Readonly<Record<SuggestionStatus, string>> = {
  suggested: 'Waiting',
  accepted: 'Accepted',
  dismissed: 'Dismissed',
};

/** Largest Compass export the upload takes (apiome-rest refuses anything bigger). */
export const COMPASS_MAX_BYTES = 5 * 1024 * 1024;

/** The import reports page. */
export const IMPORT_REPORTS_ROUTE = '/ade/dashboard/catalog/imports';

/** One report's page. */
export function importReportHref(id: string): string {
  return `${IMPORT_REPORTS_ROUTE}/${encodeURIComponent(id)}`;
}

/** One component's page. */
export function componentHref(slug: string): string {
  return `/ade/dashboard/catalog/components/${encodeURIComponent(slug)}`;
}

/** Where an accepted suggestion's entity lives, or `null`. */
export function suggestionEntityHref(suggestion: Pick<MigrationSuggestion, 'entity'>): string | null {
  const entity = suggestion.entity;
  if (!entity) return null;
  switch (entity.kind) {
    case 'component':
      return componentHref(entity.slug ?? entity.id);
    case 'team':
      return `/ade/dashboard/teams/${encodeURIComponent(entity.slug ?? entity.id)}`;
    case 'project':
      return `/ade/dashboard/versions?projectId=${encodeURIComponent(entity.id)}`;
    case 'catalog_item':
      return `/ade/dashboard/catalog/${encodeURIComponent(entity.id)}`;
    default:
      return null;
  }
}

/**
 * The one-line summary of a report's counts, in the words the report page uses.
 *
 * @param run - The report.
 * @returns e.g. `3 entities · 2 components · 1 team · 1 API imported · 4 unmapped fields`.
 */
export function migrationCountsLine(run: Pick<MigrationRun, 'counts' | 'unmappedTotal'>): string {
  const counts = run.counts ?? {};
  const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  const parts = [plural(counts.entities ?? 0, 'entity', 'entities')];
  parts.push(plural(counts.components ?? 0, 'component', 'components'));
  const teams = (counts.teams ?? 0) + (counts.teamsMatched ?? 0);
  parts.push(plural(teams, 'team', 'teams'));
  if (counts.apisImported) parts.push(plural(counts.apisImported, 'API imported', 'APIs imported'));
  parts.push(plural(run.unmappedTotal ?? 0, 'unmapped field', 'unmapped fields'));
  return parts.join(' · ');
}

/**
 * What a suggestion is, in one line: its category or the team's contact, and its owner.
 *
 * @param suggestion - The suggestion.
 * @returns The detail line (may be empty).
 */
export function suggestionDetail(suggestion: MigrationSuggestion): string {
  const payload = suggestion.payload ?? {};
  const text = (key: string) => (typeof payload[key] === 'string' ? (payload[key] as string) : '');
  if (suggestion.kind === 'team') {
    const parts = [text('contactEmail'), payload.existingTeam ? `Team ${suggestion.slug} already exists` : ''];
    return parts.filter(Boolean).join(' · ');
  }
  const category = COMPONENT_CATEGORY_LABELS[(text('category') || 'component') as ComponentCategory] ?? 'Component';
  const parts = [text('componentType') ? `${category} · ${text('componentType')}` : category];
  if (text('ownerRef')) parts.push(`Owner ${text('ownerRef')}`);
  const links = Array.isArray(payload.links) ? payload.links.length : 0;
  if (links) parts.push(`${links} ${links === 1 ? 'link' : 'links'}`);
  const references = Array.isArray(payload.references) ? payload.references.length : 0;
  if (references) parts.push(`${references} ${references === 1 ? 'dependency' : 'dependencies'}`);
  return parts.join(' · ');
}

/**
 * The verb on a waiting suggestion's accept button.
 *
 * @param suggestion - The suggestion.
 * @returns `Create team`, `Use team`, `Apply to <name>` or `Register component`.
 */
export function acceptLabel(suggestion: MigrationSuggestion): string {
  if (suggestion.kind === 'team') return suggestion.payload?.existingTeam ? 'Use team' : 'Create team';
  if (suggestion.match) return `Apply to ${suggestion.match.name ?? suggestion.match.slug ?? 'match'}`;
  return 'Register component';
}

/**
 * Unmapped fields grouped by the entity they belong to, in first-seen order.
 *
 * @param unmapped - The report's unmapped fields.
 * @returns `[entity, fields]` pairs.
 */
export function groupUnmapped(unmapped: readonly UnmappedField[]): Array<[string, UnmappedField[]]> {
  const groups = new Map<string, UnmappedField[]>();
  for (const field of unmapped) {
    const list = groups.get(field.entity) ?? [];
    list.push(field);
    groups.set(field.entity, list);
  }
  return Array.from(groups.entries());
}

/** Whether a file looks like a Compass export (`.json`) and fits the upload limit. */
export function compassFileProblem(file: { name: string; size: number }): string | null {
  if (!/\.json$/i.test(file.name)) return 'Choose the JSON file Compass exported.';
  if (file.size > COMPASS_MAX_BYTES) return 'The export is larger than 5 MB.';
  return null;
}

// ---------------------------------------------------------------------------------------------
// The proxy
// ---------------------------------------------------------------------------------------------

/** HTTP methods the proxy forwards. */
export type CatalogMigrationMethod = 'GET' | 'POST';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const SLUG = /^[a-z0-9][a-z0-9-]{0,127}$/i;

/**
 * The apiome-rest path (under `/v1/tenants/{t}/`) a browser request maps to, or `null` when the
 * proxy does not forward it.
 *
 * | Browser (`/api/catalog-migrations/…`) | apiome-rest |
 * | --- | --- |
 * | `GET` (none) | `catalog-migrations` |
 * | `POST compass` | `catalog-migrations/compass` |
 * | `GET <run id>` | `catalog-migrations/<run id>` |
 * | `POST suggestions/<id>/accept` · `…/dismiss` | `catalog-migration-suggestions/<id>/…` |
 * | `GET components/<slug>` | `catalog-components/<slug>` |
 *
 * @param segments - The path segments after `/api/catalog-migrations`.
 * @param method - The HTTP method.
 */
export function catalogMigrationProxyPath(segments: readonly string[], method: CatalogMigrationMethod): string | null {
  const [first, second, third, ...rest] = segments;
  if (rest.length > 0) return null;
  if (segments.length === 0) return method === 'GET' ? 'catalog-migrations' : null;
  if (segments.length === 1 && first === 'compass') return method === 'POST' ? 'catalog-migrations/compass' : null;
  if (segments.length === 1 && UUID.test(first)) return method === 'GET' ? `catalog-migrations/${first}` : null;
  if (first === 'suggestions' && segments.length === 3 && UUID.test(second) && (third === 'accept' || third === 'dismiss')) {
    return method === 'POST' ? `catalog-migration-suggestions/${second}/${third}` : null;
  }
  if (first === 'components' && segments.length === 2 && (SLUG.test(second) || UUID.test(second))) {
    return method === 'GET' ? `catalog-components/${encodeURIComponent(second)}` : null;
  }
  return null;
}

/**
 * The body a write forwards: only the fields its path takes.
 *
 * @param path - The apiome-rest path from {@link catalogMigrationProxyPath}.
 * @param raw - The parsed request body.
 */
export function catalogMigrationProxyBody(path: string, raw: unknown): Record<string, unknown> {
  const source = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const body: Record<string, unknown> = {};
  if (path === 'catalog-migrations/compass') {
    if (typeof source.filename === 'string') body.filename = source.filename.slice(0, 255);
    if (typeof source.content === 'string') body.content = source.content;
    return body;
  }
  if (path.endsWith('/accept')) {
    if (typeof source.name === 'string' && source.name.trim()) body.name = source.name.trim().slice(0, 200);
    if (typeof source.slug === 'string' && source.slug.trim()) body.slug = source.slug.trim().slice(0, 128);
    if (source.asComponent === true) body.asComponent = true;
  }
  return body;
}
