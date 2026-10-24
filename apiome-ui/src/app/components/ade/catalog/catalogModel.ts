/**
 * The rules the Catalog list runs on (HIVE-7.1, #5318).
 *
 * Authority: `docs/mockups/sources/catalog.html` and its **Notes → Keeps (1:1)** list;
 * `docs/mockups/DESIGN.md` §8 (list page, destructive confirms, keyboard) and §3.1 (status
 * vocabulary).
 *
 * The Catalog is the `publishable = false` slice of projects (MFI-23.1) — the imports whose
 * format does not map 1:1 onto OpenAPI. Before this ticket almost every decision the screen
 * makes lived inside a 1,651-line `page.tsx`: which chip counts what, which of two quality
 * numbers wins, what a facet offers, what the permanent-delete confirm asks. None of it could
 * be tested without rendering the whole screen, and the card and the table each carried their
 * own copy of the score derivation.
 *
 * Everything here is pure and React-free, so the two views import one answer instead of
 * writing two. There is no colour and no class name in this file: a tone is looked up from
 * `ui/statusVocabulary` and `ui/metrics/metricTiers` by the component that paints it, and a
 * format's hue comes from the fixed identity block via `ui/catalog/FormatPill`.
 *
 * @see `./CatalogCard.tsx` and `./CatalogTable.tsx` — the two views these rules serve.
 * @see `@/app/utils/catalog-dashboard-sort` — the comparators, which predate this ticket and
 *   are unchanged; this module only bridges them to `DataTable`'s sort state.
 * @see `@/app/utils/catalog-format-registry` — the format, protocol and source-material
 *   registry the facets are derived from.
 */

import { isFeatureReleased } from '@lib/feature-release';
import { allowEverything, type PermissionCheck } from '../access/permissionCheck';
import type { EntityOwner } from '@lib/owners';
import { dataTableRangeLabel, type DataTableSortState } from '@/app/components/ui/DataTable';
import {
  destructiveConfirm,
  type DestructiveConfirmOptions,
} from '@/app/components/dialogs/destructiveConfirm';
import type { FactsLineFact } from '@/app/components/ui/FactsLine';
import { computeCatalogStats } from '@/app/utils/catalog-dashboard-stats';
import { catalogOrbScores } from '@/app/utils/catalog-card-presentation';
import type { CatalogConversion } from '@/app/utils/catalog-conversion';
import {
  catalogFormatFamilyId,
  catalogFormatFamilyLabel,
  catalogFormatSearchTokens,
  resolveCatalogProtocol,
  resolveCatalogSource,
  type CatalogSource,
  type CatalogSourceKind,
} from '@/app/utils/catalog-format-registry';
import {
  sortCatalogDashboardRows,
  type CatalogDashboardSortColumn,
  type CatalogDashboardSortDirection,
} from '@/app/utils/catalog-dashboard-sort';
import type { ProjectQualitySnapshot } from '@/app/utils/project-quality-score-history';
import { PROJECT_DOMAIN_CATEGORIES } from '@/app/utils/project-domain-categories';

// ---------------------------------------------------------------------------------------
// The row
// ---------------------------------------------------------------------------------------

/**
 * One catalog item, as `/api/catalog` returns it (REST `CatalogItemSchema`, MFI-23.2).
 *
 * A catalog item's `id` **is** a project id — the Catalog is a projection over the same
 * `projects` table — which is why the delete, undelete and permanent-delete writes are the
 * project server actions and the quality dialogs are the project ones.
 */
export interface CatalogItem {
  id: string;
  tenant_id: string;
  creator_id?: string | null;
  name: string;
  slug?: string | null;
  description?: string | null;
  enabled: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  creator_name?: string | null;
  creator_email?: string | null;
  metadata?: ({ summary?: string } & Record<string, unknown>) | null;
  qualityScore?: number | null;
  qualityGrade?: string | null;
  /** Live revision count (parity with the projects list cards). */
  versionsCount?: number;
  /** Always false for a catalog item (the non-publishable invariant, MFI-23.1). */
  publishable?: boolean;
  /** Imported source format + paradigm/protocol off the latest revision (MFI-7.1/7.2). */
  sourceFormat?: string | null;
  protocol?: string | null;
  /** Format-specific metadata off the latest revision; carries source provenance (MFI-7.x). */
  formatMetadata?: Record<string, unknown> | null;
  /** Cross-format identity group when filtering representations (MFI-6.4). */
  identityGroupId?: string | null;
  /** The convert-to-OpenAPI back-link (MFI-23.11): present once the item has been converted. */
  conversion?: CatalogConversion | null;
  /** Auto-derived paradigm — the latest revision's protocol (MFI-6.3). */
  paradigm?: string | null;
  /** Manual domain id (`finance`, `iot`, …), or null when none is set (MFI-6.3). */
  domain?: string | null;
  /** Free-form tags, lower-cased and alphabetical (MFI-6.3). */
  tags?: readonly string[];
  /** The owner team: confirmed, else suggested; null when none (CDG-2.2/2.4). */
  owner?: EntityOwner | null;
  /**
   * The schema-registry subjects this item backs, by name (CDG-4.5); filled in by the list after a
   * second read, so it is absent until then and empty for an item that backs none.
   */
  registrySubjects?: readonly string[];
}

/** The quality history of every item on screen, keyed by item id. */
export type CatalogQualityHistoryMap = Readonly<
  Record<string, readonly ProjectQualitySnapshot[]>
>;

// ---------------------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------------------

/**
 * What state a catalog item is in, as one word.
 *
 * Three states, not two flags: `enabled` and `deleted_at` are independent in the database,
 * but a deleted item's enabled flag is *remembered* rather than *meaningful* — undelete
 * restores it — so a reader should only ever be shown the outer one.
 */
export type CatalogLifecycle = 'active' | 'disabled' | 'deleted';

/**
 * The state an item is in.
 *
 * @param item The row.
 * @returns `deleted` when it is soft-deleted, otherwise `active` or `disabled`.
 */
export function catalogLifecycle(item: CatalogItem): CatalogLifecycle {
  if (item.deleted_at) return 'deleted';
  return item.enabled ? 'active' : 'disabled';
}

/** The label for each lifecycle state — the shared vocabulary's spelling, sentence case. */
export const CATALOG_LIFECYCLE_LABEL: Readonly<Record<CatalogLifecycle, string>> = {
  active: 'Active',
  disabled: 'Disabled',
  deleted: 'Deleted',
};

/**
 * Whether a row or card opens its detail view.
 *
 * A deleted item has nothing to open — its revisions are hidden with it — so the whole hit
 * area goes inert rather than routing to a page that would say "not found".
 *
 * @param item The row.
 * @returns True when clicking it should route to the item detail.
 */
export function isCatalogItemOpenable(item: CatalogItem): boolean {
  return !item.deleted_at;
}

/** Where a catalog item's detail lives (MFI-23.9). */
export function catalogItemHref(item: CatalogItem): string {
  return `/ade/dashboard/catalog/${encodeURIComponent(item.id)}`;
}

/** Where a catalog item's revisions live (its id is a project id). */
export function catalogVersionsHref(item: CatalogItem): string {
  return `/ade/dashboard/versions?projectId=${encodeURIComponent(item.id)}`;
}

// ---------------------------------------------------------------------------------------
// The view chips
// ---------------------------------------------------------------------------------------

/** The four view chips of the mockup's toolbar. */
export type CatalogFacet = 'all' | 'active' | 'attention' | 'deleted';

/** Every facet, in the order the toolbar draws them. */
export const CATALOG_FACETS: readonly CatalogFacet[] = [
  'all',
  'active',
  'attention',
  'deleted',
] as const;

/** What each chip says. */
export const CATALOG_FACET_LABELS: Readonly<Record<CatalogFacet, string>> = {
  all: 'All',
  active: 'Active',
  attention: 'Needs attention',
  deleted: 'Deleted',
};

/**
 * Whether an item belongs to a facet.
 *
 * "Needs attention" is *disabled or deleted* — the two states that stop an item being usable —
 * which is why a deleted item is counted by two chips rather than one. That is deliberate and
 * matches the mockup's counts: the chips narrow the list, they do not partition it.
 *
 * @param item The row.
 * @param facet The chip.
 * @returns True when the chip should keep this row.
 */
export function matchesCatalogFacet(item: CatalogItem, facet: CatalogFacet): boolean {
  switch (facet) {
    case 'active':
      return item.enabled && !item.deleted_at;
    case 'attention':
      return !item.enabled || Boolean(item.deleted_at);
    case 'deleted':
      return Boolean(item.deleted_at);
    case 'all':
    default:
      return true;
  }
}

/**
 * How many rows each chip would leave.
 *
 * Counted over the rows every *other* control has already narrowed, so the chips describe
 * what pressing them would actually show rather than the unfiltered total — the ticket's
 * "facet counts reflect the active filter set".
 *
 * @param items The rows the search, the format facet and the three selects left.
 * @returns One count per facet.
 */
export function catalogFacetCounts(
  items: readonly CatalogItem[]
): Readonly<Record<CatalogFacet, number>> {
  return {
    all: items.length,
    active: items.filter((item) => matchesCatalogFacet(item, 'active')).length,
    attention: items.filter((item) => matchesCatalogFacet(item, 'attention')).length,
    deleted: items.filter((item) => matchesCatalogFacet(item, 'deleted')).length,
  };
}

// ---------------------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------------------

/**
 * The free-text filter behind the toolbar's search box.
 *
 * Matches the name, the slug, the description, the raw format and protocol tokens, and every
 * *alias* the format registry knows — so typing `grpc` finds an item stored as `protobuf`,
 * which is the one search a reader of this list is most likely to try.
 *
 * @param items The rows.
 * @param query What was typed. Blank returns a copy of the input.
 * @returns The rows that match, in their original order.
 */
export function searchCatalog<T extends CatalogItem>(items: readonly T[], query: string): T[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...items];
  return items.filter((item) => {
    const tokens = catalogFormatSearchTokens(item.sourceFormat ?? null);
    return (
      [
        item.name,
        item.slug ?? '',
        item.description ?? '',
        item.sourceFormat ?? '',
        item.protocol ?? '',
        ...(item.tags ?? []),
      ]
        .join(' ')
        .toLowerCase()
        .includes(needle) || tokens.some((token) => token.includes(needle))
    );
  });
}

// ---------------------------------------------------------------------------------------
// The quick filters
// ---------------------------------------------------------------------------------------

/** The sentinel every quick-filter select starts on — "do not narrow by this axis". */
export const CATALOG_FILTER_ANY = 'any';

/**
 * The three quick-filter selects beside the format facet, plus the format facet itself.
 *
 * `formats` is a *set* because a format facet is multi-select (an empty array means "every
 * format"); the other three are single-choice, and `CATALOG_FILTER_ANY` is their neutral.
 */
export interface CatalogFilterState {
  /** Selected format-family ids. Empty means every format. */
  formats: readonly string[];
  /** A protocol id from the registry, or {@link CATALOG_FILTER_ANY}. */
  protocol: string;
  /** A {@link CatalogSourceKind}, or {@link CATALOG_FILTER_ANY}. */
  source: string;
  /** An A–F letter, `unscored`, or {@link CATALOG_FILTER_ANY}. */
  grade: string;
  /** A domain id, {@link CATALOG_UNCATEGORIZED}, or {@link CATALOG_FILTER_ANY} (MFI-6.3). */
  domain: string;
  /** A tag, {@link CATALOG_UNCATEGORIZED}, or {@link CATALOG_FILTER_ANY} (MFI-6.3). */
  tag: string;
}

/** The neutral state of every quick filter — what "Clear all filters" restores. */
export const EMPTY_CATALOG_FILTERS: CatalogFilterState = {
  formats: [],
  protocol: CATALOG_FILTER_ANY,
  source: CATALOG_FILTER_ANY,
  grade: CATALOG_FILTER_ANY,
  domain: CATALOG_FILTER_ANY,
  tag: CATALOG_FILTER_ANY,
};

/**
 * The value the Domain and Tag selects use for "has none" — the same `uncategorized` bucket
 * the REST facets (`GET /v1/catalog/{tenant}/facets`) use, so a URL or a CLI filter means the
 * same thing here.
 */
export const CATALOG_UNCATEGORIZED = 'uncategorized';

/**
 * The display name of a domain id — the Projects pickers' label without its parenthesised
 * examples ("Finance (Account, Transaction, …)" → "Finance"), short enough for a card pill and
 * a filter menu; or the id itself for a free-text domain an older import recorded.
 */
export function catalogDomainLabel(domain: string): string {
  const label = PROJECT_DOMAIN_CATEGORIES.find((entry) => entry.id === domain)?.label;
  return label ? label.split(' (')[0] : domain;
}

/**
 * The Domain select (MFI-6.3): every domain at least one item is in — plus the current choice,
 * so a selection never vanishes from its own menu — in label order, then **No domain**.
 *
 * @param items Every row on screen (before the quick filters).
 * @param selected The current Domain value.
 * @returns The select's options.
 */
export function catalogDomainOptions(
  items: readonly CatalogItem[],
  selected: string = CATALOG_FILTER_ANY
): CatalogFilterOption[] {
  const present = new Set(items.map((item) => item.domain).filter((d): d is string => Boolean(d)));
  if (selected !== CATALOG_FILTER_ANY && selected !== CATALOG_UNCATEGORIZED) present.add(selected);
  const domains = [...present]
    .map((value) => ({ value, label: catalogDomainLabel(value) }))
    .sort((a, b) => a.label.localeCompare(b.label));
  return [
    { value: CATALOG_FILTER_ANY, label: 'All domains' },
    ...domains,
    { value: CATALOG_UNCATEGORIZED, label: 'No domain' },
  ];
}

/** Most tags one catalog item may carry — the REST API's limit (MFI-6.3). */
export const CATALOG_MAX_TAGS = 20;

/** Longest tag the REST API accepts. */
export const CATALOG_MAX_TAG_LENGTH = 64;

/**
 * A tag as the API will store it, or why it cannot be one (MFI-6.3).
 *
 * The same rule as the server's `normalize_tag`: inner whitespace collapsed, trimmed,
 * lower-cased, 1–64 characters, no control characters, and never the reserved
 * {@link CATALOG_UNCATEGORIZED} bucket name. Checking it here lets the editor refuse a tag as
 * it is typed instead of after a round trip.
 *
 * @param raw What was typed.
 * @returns `{ tag }` when it is acceptable, otherwise `{ error }`.
 */
export function normalizeCatalogTag(raw: string): { tag: string } | { error: string } {
  const tag = raw.replace(/\s+/g, ' ').trim().toLowerCase();
  if (!tag) return { error: 'A tag cannot be empty.' };
  if (tag.length > CATALOG_MAX_TAG_LENGTH) {
    return { error: `A tag can be at most ${CATALOG_MAX_TAG_LENGTH} characters.` };
  }
  if (/[\x00-\x1f\x7f]/.test(tag)) return { error: 'A tag cannot contain control characters.' };
  if (tag === CATALOG_UNCATEGORIZED) {
    return { error: `“${CATALOG_UNCATEGORIZED}” is reserved for items with no tags.` };
  }
  return { tag };
}

/**
 * The Tag select (MFI-6.3): every tag in use (plus the current choice), alphabetical, then
 * **No tags**.
 *
 * @param items Every row on screen (before the quick filters).
 * @param selected The current Tag value.
 * @returns The select's options.
 */
export function catalogTagOptions(
  items: readonly CatalogItem[],
  selected: string = CATALOG_FILTER_ANY
): CatalogFilterOption[] {
  const present = new Set(items.flatMap((item) => item.tags ?? []));
  if (selected !== CATALOG_FILTER_ANY && selected !== CATALOG_UNCATEGORIZED) present.add(selected);
  return [
    { value: CATALOG_FILTER_ANY, label: 'All tags' },
    ...[...present].sort((a, b) => a.localeCompare(b)).map((value) => ({ value, label: value })),
    { value: CATALOG_UNCATEGORIZED, label: 'No tags' },
  ];
}

/** One entry of a quick-filter select. */
export interface CatalogFilterOption {
  /** The `<option>` value — an id, or {@link CATALOG_FILTER_ANY}. */
  value: string;
  /** What the row says. */
  label: string;
}

/** The Protocol select, in the mockup's order: every paradigm the registry knows. */
export const CATALOG_PROTOCOL_OPTIONS: readonly CatalogFilterOption[] = [
  { value: CATALOG_FILTER_ANY, label: 'All protocols' },
  { value: 'rest', label: 'REST' },
  { value: 'rpc', label: 'RPC' },
  { value: 'event', label: 'Event' },
  { value: 'graph', label: 'Graph' },
  { value: 'dataschema', label: 'Data Schema' },
  { value: 'agent', label: 'Agent' },
] as const;

/** Every Source the select knows — the five input kinds an import can have come through. */
const ALL_CATALOG_SOURCE_OPTIONS: readonly CatalogFilterOption[] = [
  { value: CATALOG_FILTER_ANY, label: 'All sources' },
  { value: 'file', label: 'Uploaded file' },
  { value: 'url', label: 'Source URL' },
  { value: 'paste', label: 'Pasted content' },
  { value: 'discovery', label: 'Live discovery' },
  { value: 'connector', label: 'Catalog connector' },
] as const;

/**
 * The Source select's options. **Catalog connector** is offered only while connectors are released
 * (`lib/feature-release.ts`): until then nothing can sync an item in, so the option would filter to
 * an empty list (RC6-H8, #6215).
 *
 * @returns The options, in order.
 */
export function catalogSourceOptions(): readonly CatalogFilterOption[] {
  return isFeatureReleased('connectors')
    ? ALL_CATALOG_SOURCE_OPTIONS
    : ALL_CATALOG_SOURCE_OPTIONS.filter((option) => option.value !== 'connector');
}

/** The value the Grade select uses for "has no score at all". */
export const CATALOG_GRADE_UNSCORED = 'unscored';

/** The Grade select — the five letters plus the unscored bucket. */
export const CATALOG_GRADE_OPTIONS: readonly CatalogFilterOption[] = [
  { value: CATALOG_FILTER_ANY, label: 'Any grade' },
  { value: 'A', label: 'A' },
  { value: 'B', label: 'B' },
  { value: 'C', label: 'C' },
  { value: 'D', label: 'D' },
  { value: 'F', label: 'F' },
  { value: CATALOG_GRADE_UNSCORED, label: 'Unscored' },
] as const;

/** The item's source material, resolved from either metadata bag. */
export function catalogItemSource(item: CatalogItem): CatalogSource | undefined {
  return resolveCatalogSource(item.formatMetadata, item.metadata);
}

/** The item's source *kind*, for the Source select. */
export function catalogItemSourceKind(item: CatalogItem): CatalogSourceKind | undefined {
  return catalogItemSource(item)?.kind;
}

/** The item's protocol id, resolved through the registry so aliases match the select. */
export function catalogItemProtocolId(item: CatalogItem): string | undefined {
  return resolveCatalogProtocol(item.protocol)?.id;
}

/**
 * The letter the Grade select matches on.
 *
 * The same ladder the orbs draw: a captured grade wins, otherwise one is derived from the
 * score, otherwise there is none. Deriving here rather than reading `qualityGrade` alone is
 * what stops "Grade: B" hiding an item whose orb is showing a B.
 *
 * @param item The row.
 * @param history Its browser-local snapshots, oldest first.
 * @returns The A–F letter, or `null` when nothing has scored it.
 */
export function catalogItemGradeLetter(
  item: CatalogItem,
  history: readonly ProjectQualitySnapshot[] = []
): string | null {
  const { lintLetter } = catalogOrbScores(item, [...history]);
  return lintLetter ?? null;
}

/**
 * Whether a row survives the format facet and the three selects.
 *
 * Each axis is independent and each is skipped when it is on its neutral value, so the four
 * compose without any of them having to know about the others.
 *
 * @param item The row.
 * @param filters The current quick-filter state.
 * @param history The item's browser-local snapshots (the grade axis needs them).
 * @returns True when every active axis keeps the row.
 */
export function matchesCatalogFilters(
  item: CatalogItem,
  filters: CatalogFilterState,
  history: readonly ProjectQualitySnapshot[] = []
): boolean {
  if (filters.formats.length > 0) {
    const familyId = catalogFormatFamilyId(item.sourceFormat);
    if (!familyId || !filters.formats.includes(familyId)) return false;
  }
  if (filters.protocol !== CATALOG_FILTER_ANY && catalogItemProtocolId(item) !== filters.protocol) {
    return false;
  }
  if (filters.source !== CATALOG_FILTER_ANY && catalogItemSourceKind(item) !== filters.source) {
    return false;
  }
  if (filters.grade !== CATALOG_FILTER_ANY) {
    const letter = catalogItemGradeLetter(item, history);
    if (filters.grade === CATALOG_GRADE_UNSCORED) {
      if (letter !== null) return false;
    } else if (letter !== filters.grade) {
      return false;
    }
  }
  // Domain and Tag (MFI-6.3): the `uncategorized` value keeps the rows with none.
  const domain = filters.domain ?? CATALOG_FILTER_ANY;
  if (domain !== CATALOG_FILTER_ANY) {
    if (domain === CATALOG_UNCATEGORIZED ? Boolean(item.domain) : item.domain !== domain) {
      return false;
    }
  }
  const tag = filters.tag ?? CATALOG_FILTER_ANY;
  if (tag !== CATALOG_FILTER_ANY) {
    const tags = item.tags ?? [];
    if (tag === CATALOG_UNCATEGORIZED ? tags.length > 0 : !tags.includes(tag)) return false;
  }
  return true;
}

/** Whether anything is narrowing the list — what decides which empty state is shown. */
export function isCatalogNarrowed(
  query: string,
  facet: CatalogFacet,
  filters: CatalogFilterState
): boolean {
  return (
    query.trim().length > 0 ||
    facet !== 'all' ||
    filters.formats.length > 0 ||
    filters.protocol !== CATALOG_FILTER_ANY ||
    filters.source !== CATALOG_FILTER_ANY ||
    filters.grade !== CATALOG_FILTER_ANY ||
    (filters.domain ?? CATALOG_FILTER_ANY) !== CATALOG_FILTER_ANY ||
    (filters.tag ?? CATALOG_FILTER_ANY) !== CATALOG_FILTER_ANY
  );
}

// ---------------------------------------------------------------------------------------
// The format facet
// ---------------------------------------------------------------------------------------

/** One entry of the format facet's menu: a family, its label, and how many rows carry it. */
export interface CatalogFormatFacetOption {
  /** The format-family id (`protobuf` covers both gRPC and Protobuf). */
  id: string;
  /** Its display label. */
  label: string;
  /** How many of the rows this facet was built from carry it. */
  count: number;
}

/**
 * The format facet's menu.
 *
 * Two rules, and both are the ticket's acceptance criteria:
 *
 * 1. **It is derived from the rows, not from the registry.** Offering all 44 importable
 *    formats on a catalog holding three would make the facet a catalogue of the product
 *    rather than a filter over the list.
 * 2. **The counts come from the rows the *other* controls left.** So they answer "how many
 *    would I see if I ticked this", which is the only question a count beside a checkbox is
 *    ever asked.
 *
 * A family already ticked is always listed even when the current narrowing leaves it at
 * zero — otherwise the control that produced the empty list would vanish from the menu that
 * has to un-tick it.
 *
 * @param rows The rows every control except the format facet has left.
 * @param selected The currently ticked family ids.
 * @returns One option per family, alphabetical by label.
 */
export function catalogFormatFacetOptions(
  rows: readonly CatalogItem[],
  selected: readonly string[] = []
): CatalogFormatFacetOption[] {
  const counts = new Map<string, number>();
  for (const item of rows) {
    const familyId = catalogFormatFamilyId(item.sourceFormat);
    if (!familyId) continue;
    counts.set(familyId, (counts.get(familyId) ?? 0) + 1);
  }
  for (const id of selected) if (!counts.has(id)) counts.set(id, 0);
  return [...counts.entries()]
    .map(([id, count]) => ({ id, label: catalogFormatFamilyLabel(id), count }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

// ---------------------------------------------------------------------------------------
// Scores
// ---------------------------------------------------------------------------------------

/** What an item's three orbs and its two table cells have to draw. */
export interface CatalogScores {
  /** Revisions the server summary counted. */
  versionsCount: number;
  /** The overall quality score, 0–100, or `null` when nothing has scored it. */
  quality: number | null;
  /** The A–F letter the Lint orb prints, or `null` when there is no score behind it. */
  grade: string | null;
}

/**
 * The one derivation both views use.
 *
 * Unlike a project, a catalog item is *server*-imported far more often than it is imported in
 * this browser, so the ladder is the reverse of `projectScores`': the server-captured score
 * (MFI-23.2) is preferred and browser-local history is the fallback. That is
 * {@link catalogOrbScores}, which predates this ticket and which the detail screen shares —
 * this only adds the revision count so a card and a row cannot disagree about either figure.
 *
 * @param item The row.
 * @param history Its browser-local snapshots, oldest first.
 * @returns The figures both views print. See {@link CatalogScores}.
 */
export function catalogScores(
  item: CatalogItem,
  history: readonly ProjectQualitySnapshot[] = []
): CatalogScores {
  const { qualityValue, lintLetter } = catalogOrbScores(item, [...history]);
  return {
    versionsCount: typeof item.versionsCount === 'number' ? item.versionsCount : 0,
    quality: qualityValue,
    grade: lintLetter ?? null,
  };
}

/** `3 versions`, `1 version`, `0 versions`. */
export function catalogVersionsLabel(count: number): string {
  return `${count} ${count === 1 ? 'version' : 'versions'}`;
}

/**
 * The two-line blurb on a card.
 *
 * The OpenAPI-style summary first, then the description, then a statement that there is
 * neither. Never an empty paragraph: the card's body has a minimum height so a grid keeps its
 * rhythm, and an empty one would read as a rendering fault.
 */
export function catalogSummaryText(item: CatalogItem): string {
  return item.metadata?.summary?.trim() || item.description?.trim() || 'No description yet.';
}

/**
 * The short, stable id the card and the row print beside the slug.
 *
 * Six hex characters of the uuid, as `sources/catalog.html` prints them (`cat_4d1e9a`). It is
 * a *label*, never an identifier to look anything up by — the uuid is what the API takes.
 *
 * @param id The item's uuid.
 * @returns `cat_` plus the first six characters with the dashes removed.
 */
export function catalogShortId(id: string): string {
  return `cat_${id.replace(/-/g, '').slice(0, 6)}`;
}

/** How many format pills the facts line draws before the count alone speaks for the rest. */
export const CATALOG_FACT_FORMAT_PILLS = 4;

/**
 * The facts line under the page header (HIVE-11.6, #5602):
 * `3 items · 3 formats [pills] · avg quality B · 83 · 1 converted to OpenAPI · 2 active · 1 disabled`.
 *
 * It is the four-figure stat strip (`CatalogStatsRow`) folded into one sentence, so **every
 * figure the strip draws is here**, from the same {@link computeCatalogStats} — the live
 * catalog only. The strip itself stays one click away behind **Show stats**. The deleted count
 * is added only when the switch that reveals deleted rows is on: a count of rows the reader
 * cannot see is a count they cannot act on.
 *
 * Each format pill carries the first raw `sourceFormat` seen for its family, which is what
 * `FormatPill` resolves to an identity hue; at most {@link CATALOG_FACT_FORMAT_PILLS} are drawn.
 *
 * @param items Every row currently loaded.
 * @param showDeleted Whether the Show-deleted switch is on.
 * @returns The facts, in reading order, for `FactsLine`.
 */
export function catalogFacts(
  items: readonly CatalogItem[],
  showDeleted: boolean
): FactsLineFact[] {
  const stats = computeCatalogStats(items);

  const formats: string[] = [];
  const families = new Set<string>();
  for (const item of items) {
    if (item.deleted_at) continue;
    const raw = item.sourceFormat?.trim();
    if (!raw) continue;
    const family = catalogFormatFamilyId(raw) ?? raw.toLowerCase();
    if (families.has(family)) continue;
    families.add(family);
    formats.push(raw);
  }

  const status = [`${stats.active} active`, `${stats.disabled} disabled`];
  if (showDeleted) {
    const deleted = items.filter((item) => item.deleted_at).length;
    if (deleted > 0) status.push(`${deleted} deleted`);
  }

  return [
    { id: 'items', value: stats.total, label: stats.total === 1 ? 'item' : 'items' },
    {
      id: 'formats',
      value: stats.formatCount,
      label: stats.formatCount === 1 ? 'format' : 'formats',
      formats: formats.slice(0, CATALOG_FACT_FORMAT_PILLS),
    },
    {
      id: 'quality',
      label: 'avg quality',
      value: stats.avgScore != null ? `${stats.avgGrade} · ${stats.avgScore}` : '—',
      labelFirst: true,
    },
    { id: 'converted', value: stats.converted, label: 'converted to OpenAPI' },
    { id: 'status', label: status.join(' · '), muted: true },
  ];
}

/** The identity-group chip's label — `Identity group idg_7c21e9…`, the mockup's spelling. */
export function catalogIdentityGroupLabel(identityGroupId: string): string {
  return `Identity group ${identityGroupId.slice(0, 8)}…`;
}

// ---------------------------------------------------------------------------------------
// Sorting
// ---------------------------------------------------------------------------------------

/** One entry of the toolbar's sort menu. */
export interface CatalogSortOption {
  /** The comparator this option runs. */
  id: CatalogDashboardSortColumn;
  /** What the menu row says. */
  label: string;
}

/**
 * The sort menu, in the order it lists.
 *
 * The mockup's six. Every table column is also sortable — Protocol, Source and Status have
 * comparators too — but they are reached by clicking their header rather than by a menu row,
 * because a menu that lists nine ways to order seven items is longer than the list.
 */
export const CATALOG_SORT_OPTIONS: readonly CatalogSortOption[] = [
  { id: 'name', label: 'Name' },
  { id: 'created', label: 'Created' },
  { id: 'updated', label: 'Updated' },
  { id: 'quality', label: 'Quality' },
  { id: 'grade', label: 'Grade' },
  { id: 'format', label: 'Format' },
] as const;

/**
 * Display label per sortable column — the menu's six plus the ones only the table headers
 * offer. Keeps the "Sorted by …" summary honest whichever control was used.
 */
export const CATALOG_SORT_COLUMN_LABELS: Readonly<Record<CatalogDashboardSortColumn, string>> = {
  name: 'Artifact',
  description: 'Description',
  quality: 'Quality',
  grade: 'Grade',
  format: 'Format',
  protocol: 'Protocol',
  source: 'Source',
  status: 'Status',
  creator: 'Creator',
  created: 'Created',
  updated: 'Updated',
};

/** The sort a fresh page starts on — the mockup's `Sorted by name ↑`. */
export const DEFAULT_CATALOG_SORT: DataTableSortState = { column: 'name', direction: 'asc' };

/** Whether a string names a sortable catalog column. */
export function isCatalogSortColumn(id: string): id is CatalogDashboardSortColumn {
  return id in CATALOG_SORT_COLUMN_LABELS;
}

/**
 * `DataTable`'s sort state as the comparator's pair.
 *
 * `DataTable` speaks `{column, direction}` over arbitrary column ids and allows `null` for
 * "unsorted"; the comparators speak a closed union. This is the only place the two meet, so a
 * column id that is not sortable — or a cleared sort — falls back to the default rather than
 * reaching a comparator that has no case for it.
 *
 * @param sort The table's state, or `null`.
 * @returns The column and direction to compare by.
 */
export function catalogSortKey(sort: DataTableSortState | null | undefined): {
  column: CatalogDashboardSortColumn;
  direction: CatalogDashboardSortDirection;
} {
  if (!sort || !isCatalogSortColumn(sort.column)) {
    return {
      column: DEFAULT_CATALOG_SORT.column as CatalogDashboardSortColumn,
      direction: DEFAULT_CATALOG_SORT.direction,
    };
  }
  return { column: sort.column, direction: sort.direction };
}

/**
 * Order the rows.
 *
 * @param items The rows the search, the chip and the quick filters left.
 * @param sort The table's sort state.
 * @returns A new, sorted array.
 */
export function sortCatalog<T extends CatalogItem>(
  items: readonly T[],
  sort: DataTableSortState | null | undefined
): T[] {
  const { column, direction } = catalogSortKey(sort);
  return sortCatalogDashboardRows(items, column, direction);
}

/** `name ↑` — the phrase the toolbar button and the table foot both end with. */
export function catalogSortLabel(sort: DataTableSortState | null | undefined): string {
  const { column, direction } = catalogSortKey(sort);
  return `${CATALOG_SORT_COLUMN_LABELS[column].toLowerCase()} ${direction === 'asc' ? '↑' : '↓'}`;
}

/**
 * How many items one page of the Catalog draws, in either view (RC6-H6, #6213).
 *
 * A thousand cards or rows take seconds to mount, and every keystroke in the filter re-draws them
 * all; fifty keep the first row and each filter well inside budget, and are more than a 1440 × 900
 * screen shows at once.
 */
export const CATALOG_PAGE_SIZE = 50;

/**
 * The table foot: `7 items · sorted by artifact ↑`, or — once the list needs more than one page —
 * `Showing 51–100 of 1000 items · sorted by artifact ↑`.
 *
 * @param count How many items matched.
 * @param sort The table's sort.
 * @param page The 1-based page shown (ignored for a one-page list).
 * @param pageSize Items per page.
 * @returns The sentence.
 */
export function catalogFootLabel(
  count: number,
  sort: DataTableSortState | null | undefined,
  page = 1,
  pageSize = CATALOG_PAGE_SIZE
): string {
  const counted =
    count > pageSize
      ? dataTableRangeLabel(page, pageSize, count, 'item')
      : `${count} ${count === 1 ? 'item' : 'items'}`;
  return `${counted} · sorted by ${catalogSortLabel(sort)}`;
}

// ---------------------------------------------------------------------------------------
// Row actions
// ---------------------------------------------------------------------------------------

/** Which verbs a row's overflow menu offers. */
export interface CatalogRowActions {
  /** Open the item's detail view. */
  details: boolean;
  /** Open its revisions. */
  versions: boolean;
  /** Open the server lint report. */
  lint: boolean;
  /** Open the Export Studio scoped to it (MFX-41.2). */
  export: boolean;
  /** Open the conversion preview (MFI-22.4). */
  convert: boolean;
  /** Soft-delete it. */
  delete: boolean;
  /** Restore it. */
  undelete: boolean;
  /** Destroy it — offered on both kinds of row. */
  permanentDelete: boolean;
  /** Edit its categories. */
  categorize: boolean;
}

/**
 * The single gate on what a row may do.
 *
 * Stated once, here, rather than re-derived as `item.deleted_at ? … : …` in each of the two
 * views: a deleted item has no detail page, no revisions, no lint report, nothing to export
 * and nothing to convert — the only two things left are putting it back and finishing the
 * job. There is deliberately **no Publish and no Edit**: the catalog is the non-publishable
 * slice (MFI-23.1) and its items are minted by the import routing (MFI-23.7), not here.
 *
 * The writes are also gated on the viewer's role (RC6-H5, #6212), with the permission apiome-rest
 * checks for each — `docs/catalog-projects-permission-matrix.json`: converting creates a project
 * (`projects:create`), categorizing and undeleting edit one (`projects:edit`), and deleting either
 * way needs `projects:delete`. Reading, linting and exporting need only membership.
 *
 * @param item The row.
 * @param can The viewer's grants (`useMyPermissions().can`); omitted, every write is allowed.
 * @returns One flag per verb. See {@link CatalogRowActions}.
 */
export function catalogRowActions(item: CatalogItem, can: PermissionCheck = allowEverything): CatalogRowActions {
  const deleted = Boolean(item.deleted_at);
  return {
    details: !deleted,
    versions: !deleted,
    lint: !deleted,
    export: !deleted,
    convert: !deleted && can('projects:create'),
    delete: !deleted && can('projects:delete'),
    undelete: deleted && can('projects:edit'),
    permanentDelete: can('projects:delete'),
    categorize: !deleted && can('projects:edit'),
  };
}

// ---------------------------------------------------------------------------------------
// Destructive confirms
// ---------------------------------------------------------------------------------------

/**
 * Soft delete — reversible, so no gate.
 *
 * DESIGN.md §8 reserves type-to-confirm for what cannot be undone; a soft delete says how to
 * get the item back instead, which is the more useful sentence.
 */
export function softDeleteCatalogItemConfirm(item: CatalogItem): DestructiveConfirmOptions {
  return destructiveConfirm({
    action: 'Delete',
    noun: 'catalog item',
    name: item.name,
    consequence:
      'The item is hidden from the catalog and its pickers. Turn on "Show deleted" to undelete it.',
  });
}

/**
 * Permanent delete — the one gate on this screen.
 *
 * What this replaces was **two** `window.confirm`s in a row, the second a restatement of the
 * first: a delay dressed as a check, which teaches a reader to click twice without reading.
 * It is one dialog now, gated on the item's **slug** — unique within the workspace and
 * printed on the very card the click came from, so the gate cannot be passed for the wrong
 * item by a reader who is looking at the right one. An item with no slug falls back to its
 * name rather than opening an ungated confirm.
 */
export function permanentDeleteCatalogItemConfirm(item: CatalogItem): DestructiveConfirmOptions {
  return destructiveConfirm({
    action: 'Permanently delete',
    noun: 'catalog item',
    name: item.name,
    consequence:
      'Every revision of this item, its stored source material and its lint history are destroyed. A conversion already made into an OpenAPI project is left alone.',
    typeToConfirm: true,
    confirmLabel: 'Delete everything',
    confirmPhrase: item.slug?.trim() || item.name,
  });
}

/** Undelete — not destructive, but it changes what other pickers show, so it is confirmed. */
export function undeleteCatalogItemConfirm(item: CatalogItem): {
  title: string;
  message: string;
  variant: 'info';
  confirmLabel: string;
  cancelLabel: string;
} {
  return {
    title: `Undelete catalog item "${item.name}"?`,
    message:
      'It returns to the catalog with the enabled or disabled state it had before deletion.',
    variant: 'info',
    confirmLabel: 'Undelete item',
    cancelLabel: 'Cancel',
  };
}

// ---------------------------------------------------------------------------------------
// Selection
// ---------------------------------------------------------------------------------------

/** What a bulk action may do to the current selection. */
export interface CatalogBulkPlan {
  /** Selected rows that are live and can be soft-deleted. */
  deletable: CatalogItem[];
  /** Selected rows that are deleted and can be restored. */
  restorable: CatalogItem[];
  /** Selected rows the row menu would offer Convert for (MFI-28.5) — the live ones. */
  convertible: CatalogItem[];
}

/**
 * Split a selection into the two things a bulk action can do to it.
 *
 * The bulk bar offers Delete and Undelete at once because a selection can hold both kinds of
 * row, and hiding the verb that applies to *some* of the selection would leave the reader
 * clearing and re-selecting. Each button states its own count, so neither can be pressed
 * without knowing how many rows it reaches.
 *
 * Convert is a bulk verb too (MFI-28.5), but it does not *write*: it opens the bulk convert
 * review, where every item still has its own fidelity preview and its own low-tier
 * acknowledgement (or one explicit "apply the warning to all"). Which rows reach it is
 * {@link catalogRowActions}'s `convert` gate, so the bar and the row menu cannot disagree.
 *
 * Every verb follows {@link catalogRowActions}, role gate included, so a role that cannot delete
 * sees no Delete button however many rows it selects.
 *
 * @param items Every row currently on screen.
 * @param selectedIds The ids the table reports as selected.
 * @param can The viewer's grants; omitted, every write is allowed.
 * @returns The rows each verb applies to. See {@link CatalogBulkPlan}.
 */
export function catalogBulkPlan(
  items: readonly CatalogItem[],
  selectedIds: readonly string[],
  can: PermissionCheck = allowEverything
): CatalogBulkPlan {
  const chosen = new Set(selectedIds);
  const selected = items.filter((item) => chosen.has(item.id));
  const actions = (item: CatalogItem) => catalogRowActions(item, can);
  return {
    deletable: selected.filter((item) => actions(item).delete),
    restorable: selected.filter((item) => actions(item).undelete),
    convertible: selected.filter((item) => actions(item).convert),
  };
}

/** One item a bulk write could not apply to, and why (MFI-28.5). */
export interface CatalogBulkFailure {
  /** The item's id. */
  id: string;
  /** Its name, as the report prints it. */
  name: string;
  /** The server's refusal, or the write's fallback sentence. */
  reason: string;
}

/**
 * The title of the per-item failure report a partial bulk write opens (MFI-28.5).
 *
 * The toast says the split; this dialog says *which* items and *why*, one line each, which
 * is what lets a reader retry the right ones rather than guess.
 *
 * @param verb The bare verb, lower case — `delete`, `undelete`, `convert`.
 * @param failures The items the write refused.
 * @returns e.g. `2 catalog items could not be deleted`.
 */
export function catalogBulkFailureTitle(
  verb: 'delete' | 'undelete' | 'convert',
  failures: readonly CatalogBulkFailure[]
): string {
  const count = failures.length;
  const noun = count === 1 ? 'catalog item' : 'catalog items';
  const participle = verb === 'convert' ? 'converted' : `${verb}d`;
  return `${count} ${noun} could not be ${participle}`;
}

/**
 * What a bulk write says once it has finished.
 *
 * States the split rather than only the successes: "Deleted 3 of 5 catalog items" with the
 * first refusal named is the sentence a reader can act on, and a bare success count after a
 * partial failure reads as a complete success.
 *
 * @param verb Past tense, capitalised — `Deleted`, `Undeleted`.
 * @param applied How many writes succeeded.
 * @param total How many were attempted.
 * @param firstError The first failure's message, if any.
 * @returns The toast's text.
 */
export function catalogBulkResultMessage(
  verb: string,
  applied: number,
  total: number,
  firstError?: string | null
): string {
  const noun = total === 1 ? 'catalog item' : 'catalog items';
  if (applied === total) return `${verb} ${applied} ${noun}.`;
  const reason = firstError?.trim();
  return `${verb} ${applied} of ${total} ${noun} · ${total - applied} refused${
    reason ? ` — ${reason}` : ''
  }`;
}
