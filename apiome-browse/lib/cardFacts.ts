/**
 * Card facts — the "retail questions" a Browse card answers (BDX-2.2, #6294).
 *
 * A visitor deciding whether to open a project wants to know how big it is, whether it is any good,
 * whether they can call a mock or take an SDK, what format it is in and whether it is still being
 * kept up. All of that is stored — operation and schema counts in the normalized model,
 * `versions.quality_grade` / `quality_score`, `versions.mock_enabled`, the public-SDK opt-in in
 * `sdk_generation_settings`, `versions.source_format` and `published_at` — and this module turns it
 * into one compact *facts line*:
 *
 * `42 operations · 18 schemas · Grade B · Mock · SDK · OpenAPI 3.1 · updated 3d ago`
 *
 * It holds three framework-free pieces, so each is unit-tested without React or a database
 * (`lib/__tests__/cardFacts.test.ts`):
 *
 * - **SQL fragments** ({@link cardFactsJoinSql}, {@link latestPublicVersionJoinSql}) that the
 *   queries in `lib/db/helper.ts` and `lib/search/sql.ts` splice in, so the facts come back in the
 *   *same* statement as the rows (no N+1, nothing cached).
 * - **The facts line** ({@link factsLine}): which facts to show, in which order, with which words.
 * - **The sorts** ({@link sortProjectsByFacts}, {@link projectRailOrderSql}): most operations and
 *   best grade, for the organization page and the home rail.
 */

import { formatLabel } from './browseFacets';
import { relativeTime } from './relativeTime';

/**
 * The facts of one published version, exactly as the SQL fragment projects them (snake_case, as
 * every other row in this app arrives). Every field is nullable: a row joined to no version (a
 * project whose latest version vanished between reads) carries nulls, and the line simply shows
 * less.
 */
export interface CardFacts {
  /** Operations (`path_operation` rows) in the version. */
  operation_count: number | null;
  /** Schemas (`classes` rows, not deleted) in the version. */
  schema_count: number | null;
  /** Captured A–F grade, or null when the version has not been scored. */
  quality_grade: string | null;
  /** Captured 0–100 score behind the grade, or null when not scored. */
  quality_score: number | null;
  /** Whether the version's public mock is switched on. */
  mock_enabled: boolean | null;
  /** Whether the project offers its SDK to anonymous visitors (the public *Get SDK* panel). */
  sdk_available: boolean | null;
  /** The version's source format key (`openapi-3.1`), lower-cased; null when unknown. */
  facts_format: string | null;
  /** When the version was published. */
  facts_published_at: string | Date | null;
}

/** The SELECT-list names of {@link CardFacts}, in projection order. */
export const CARD_FACT_COLUMNS: readonly (keyof CardFacts)[] = [
  'operation_count',
  'schema_count',
  'quality_grade',
  'quality_score',
  'mock_enabled',
  'sdk_available',
  'facts_format',
  'facts_published_at',
] as const;

/**
 * The `alias.column` list for a SELECT that joined {@link cardFactsJoinSql} as `alias`.
 *
 * @param alias - The alias the join was given.
 * @returns A comma-separated column list.
 */
export function cardFactsSelectSql(alias = 'cf'): string {
  return CARD_FACT_COLUMNS.map((column) => `${alias}.${column}`).join(', ');
}

/**
 * A `LEFT JOIN LATERAL` that computes the facts of one version, for the row it is joined to.
 *
 * The counts are read from `versions.operation_count` / `versions.schema_count`, which the database
 * records when a version is published (V424, DBP-1.16). A version whose counts are not recorded —
 * NULL: it was edited after publishing, or inserted already published — is counted by a correlated
 * sub-select instead, which `COALESCE` only runs for that row. So a stored count costs nothing, and
 * a missing one costs a small index lookup, never another round trip and never a wrong number.
 *
 * The SDK flag mirrors `app.sdk_generation_settings_store.public_sdk_enabled_from` in apiome-rest:
 * the tenant-wide row and the project's row are merged key by key, the most specific row that
 * *names* `publicSdkEnabled` wins (an explicit `null` there means off), and anything else — no
 * row, no key — is off. The column has a CHECK that it is a JSON object, so the REST side's
 * "degraded" case cannot occur here.
 *
 * @param versionPkExpr - A SQL expression for the version's primary key. It is spliced in as SQL,
 *   so it must be a column reference written in code (`v.id`, `lv.id`) — never user input.
 * @param alias - The alias the joined row gets.
 * @returns The join clause.
 */
export function cardFactsJoinSql(versionPkExpr: string, alias = 'cf'): string {
  return `LEFT JOIN LATERAL (
         SELECT
           COALESCE(f_v.operation_count,
             (SELECT COUNT(*)::int
                FROM apiome.version_path f_vp
                JOIN apiome.path_operation f_po ON f_po.version_path_id = f_vp.id
               WHERE f_vp.version_id = f_v.id)) AS operation_count,
           COALESCE(f_v.schema_count,
             (SELECT COUNT(*)::int
                FROM apiome.classes f_c
               WHERE f_c.version_id = f_v.id AND f_c.deleted_at IS NULL)) AS schema_count,
           NULLIF(TRIM(f_v.quality_grade), '') AS quality_grade,
           f_v.quality_score::int AS quality_score,
           COALESCE(f_v.mock_enabled, false) AS mock_enabled,
           COALESCE((
             SELECT f_s.settings -> 'publicSdkEnabled' = 'true'::jsonb
               FROM apiome.sdk_generation_settings f_s
              WHERE f_s.tenant_id = f_p.tenant_id
                AND (f_s.project_id = f_p.id OR f_s.project_id IS NULL)
                AND f_s.settings ? 'publicSdkEnabled'
              ORDER BY f_s.project_id NULLS LAST
              LIMIT 1
           ), false) AS sdk_available,
           NULLIF(LOWER(TRIM(COALESCE(f_v.source_format, ''))), '') AS facts_format,
           f_v.published_at AS facts_published_at
         FROM apiome.versions f_v
         JOIN apiome.projects f_p ON f_p.id = f_v.project_id
         WHERE f_v.id = ${versionPkExpr}
       ) ${alias} ON TRUE`;
}

/**
 * A `LEFT JOIN LATERAL` that picks a project's latest published public version — the version the
 * project's card describes. "Latest" is the order every other Browse surface uses: newest
 * `published_at`, then newest `created_at`.
 *
 * @param projectPkExpr - A SQL expression for the project's primary key (a column reference written
 *   in code, never user input).
 * @param alias - The alias; the version's id is `alias.id`.
 * @returns The join clause.
 */
export function latestPublicVersionJoinSql(projectPkExpr: string, alias = 'lv'): string {
  return `LEFT JOIN LATERAL (
         SELECT l_v.id
         FROM apiome.versions l_v
         WHERE l_v.project_id = ${projectPkExpr}
           AND l_v.published = true
           AND l_v.visibility = 'public'
           AND l_v.deleted_at IS NULL
         ORDER BY l_v.published_at DESC NULLS LAST, l_v.created_at DESC
         LIMIT 1
       ) ${alias} ON TRUE`;
}

/**
 * Lift the fact columns out of a query row.
 *
 * `pg` returns `::int` columns as numbers but a driver or a JSON round trip can hand back strings,
 * so numbers are coerced; anything that is not a finite number becomes null.
 *
 * @param row - A row that selected {@link CARD_FACT_COLUMNS}.
 * @returns The facts, or null when the row carries none of them (it was joined to no version).
 */
export function pickCardFacts(row: Partial<Record<keyof CardFacts, unknown>> | null | undefined): CardFacts | null {
  if (!row) return null;
  const toNumber = (value: unknown): number | null => {
    if (value === null || value === undefined || value === '') return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  };
  const toText = (value: unknown): string | null =>
    typeof value === 'string' && value.trim() ? value.trim() : null;
  const facts: CardFacts = {
    operation_count: toNumber(row.operation_count),
    schema_count: toNumber(row.schema_count),
    quality_grade: toText(row.quality_grade)?.toUpperCase() ?? null,
    quality_score: toNumber(row.quality_score),
    mock_enabled: typeof row.mock_enabled === 'boolean' ? row.mock_enabled : null,
    sdk_available: typeof row.sdk_available === 'boolean' ? row.sdk_available : null,
    facts_format: toText(row.facts_format),
    facts_published_at:
      row.facts_published_at instanceof Date || typeof row.facts_published_at === 'string'
        ? row.facts_published_at
        : null,
  };
  const empty = CARD_FACT_COLUMNS.every((column) => facts[column] === null);
  return empty ? null : facts;
}

/** Which fact a {@link FactItem} is; the component styles by it. */
export type FactKind = 'operations' | 'schemas' | 'grade' | 'mock' | 'sdk' | 'format' | 'updated';

/** One fact on the line. */
export interface FactItem {
  kind: FactKind;
  /** What the line says (`42 operations`, `Grade B`, `Mock`). */
  label: string;
  /** A longer sentence for the tooltip and screen readers. */
  title: string;
  /** The grade letter, on `grade` items only (for its tone). */
  grade?: string;
}

/** Options for {@link factsLine}. */
export interface FactsLineOptions {
  /** Facts to leave out, because the surface already says them another way. */
  omit?: readonly FactKind[];
  /** The reference time for "updated …", in epoch milliseconds; injectable for tests. */
  now?: number;
}

/** `1 operation`, `42 operations`. */
function counted(n: number, one: string, many: string): string {
  return `${n.toLocaleString('en-US')} ${n === 1 ? one : many}`;
}

/**
 * The facts line for one card, in the fixed order
 * `operations · schemas · grade · Mock · SDK · format · updated`.
 *
 * A fact is shown only when it is known and worth saying: a zero count, an unscored version, a mock
 * that is off and an SDK that is not offered are left out rather than shown as "0" or "No".
 *
 * @param facts - The version's facts, or nothing.
 * @param options - What to omit, and the reference time.
 * @returns The items to render; empty when there is nothing to say.
 */
export function factsLine(facts: CardFacts | null | undefined, options: FactsLineOptions = {}): FactItem[] {
  if (!facts) return [];
  const omit = new Set(options.omit ?? []);
  const items: FactItem[] = [];

  const ops = facts.operation_count ?? 0;
  if (ops > 0) {
    items.push({
      kind: 'operations',
      label: counted(ops, 'operation', 'operations'),
      title: `${counted(ops, 'operation', 'operations')} in the latest version`,
    });
  }
  const schemas = facts.schema_count ?? 0;
  if (schemas > 0) {
    items.push({
      kind: 'schemas',
      label: counted(schemas, 'schema', 'schemas'),
      title: `${counted(schemas, 'schema', 'schemas')} in the latest version`,
    });
  }
  if (facts.quality_grade) {
    const grade = facts.quality_grade.toUpperCase();
    items.push({
      kind: 'grade',
      label: `Grade ${grade}`,
      title:
        facts.quality_score !== null
          ? `Quality grade ${grade} (score ${facts.quality_score} of 100)`
          : `Quality grade ${grade}`,
      grade,
    });
  }
  if (facts.mock_enabled) {
    items.push({ kind: 'mock', label: 'Mock', title: 'A public mock server answers this API' });
  }
  if (facts.sdk_available) {
    items.push({ kind: 'sdk', label: 'SDK', title: 'An SDK and code snippets can be downloaded' });
  }
  if (facts.facts_format) {
    const label = formatLabel(facts.facts_format);
    items.push({ kind: 'format', label, title: `Described in ${label}` });
  }
  const updated = relativeTime(facts.facts_published_at, options.now);
  if (updated) {
    items.push({
      kind: 'updated',
      label: `updated ${updated}`,
      title: `Latest version published ${updated}`,
    });
  }
  return items.filter((item) => !omit.has(item.kind));
}

/**
 * The facts line as plain text (`42 operations · Grade B · …`), for a tooltip or a test.
 *
 * @param items - The items from {@link factsLine}.
 * @returns The labels joined with a middle dot.
 */
export function factsLineText(items: readonly FactItem[]): string {
  return items.map((item) => item.label).join(' · ');
}

// ---------------------------------------------------------------------------------------------------
// Sorting
// ---------------------------------------------------------------------------------------------------

/** How the organization page orders its projects. */
export type ProjectSort = 'name' | 'updated' | 'operations' | 'grade';

/** The organization page's sort options, in menu order. */
export const PROJECT_SORT_OPTIONS: readonly { value: ProjectSort; label: string }[] = [
  { value: 'name', label: 'Name' },
  { value: 'updated', label: 'Recently updated' },
  { value: 'operations', label: 'Most operations' },
  { value: 'grade', label: 'Best grade' },
];

/**
 * Read a sort value from a URL or a select, falling back to name order.
 *
 * @param raw - The raw value.
 * @returns A valid {@link ProjectSort}.
 */
export function parseProjectSort(raw: string | null | undefined): ProjectSort {
  return PROJECT_SORT_OPTIONS.some((o) => o.value === raw) ? (raw as ProjectSort) : 'name';
}

/** A row the sorts can order: a name and (optionally) its facts. */
export type SortableProject = { name: string } & Partial<CardFacts>;

/** Epoch milliseconds of a timestamp, or null. */
function epoch(value: string | Date | null | undefined): number | null {
  if (!value) return null;
  const t = new Date(value).getTime();
  return Number.isNaN(t) ? null : t;
}

/**
 * Compare two rows best grade first: grade A before F, then the higher score within a grade, and
 * unscored rows last.
 *
 * @returns Negative when `a` sorts first.
 */
export function compareByGrade(a: SortableProject, b: SortableProject): number {
  const ga = a.quality_grade ? a.quality_grade.toUpperCase() : null;
  const gb = b.quality_grade ? b.quality_grade.toUpperCase() : null;
  if (ga === null && gb === null) return 0;
  if (ga === null) return 1;
  if (gb === null) return -1;
  if (ga !== gb) return ga < gb ? -1 : 1;
  return (b.quality_score ?? -1) - (a.quality_score ?? -1);
}

/**
 * Order projects for the organization page. Every mode breaks ties by name, so the order is stable
 * across renders.
 *
 * @param rows - The projects (not mutated).
 * @param mode - The sort.
 * @returns A new, sorted array.
 */
export function sortProjectsByFacts<T extends SortableProject>(rows: readonly T[], mode: ProjectSort): T[] {
  const byName = (a: T, b: T) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
  const compare = (a: T, b: T): number => {
    switch (mode) {
      case 'operations':
        return (b.operation_count ?? -1) - (a.operation_count ?? -1);
      case 'grade':
        return compareByGrade(a, b);
      case 'updated':
        return (epoch(b.facts_published_at) ?? -Infinity) - (epoch(a.facts_published_at) ?? -Infinity) || 0;
      case 'name':
      default:
        return 0;
    }
  };
  return [...rows].sort((a, b) => compare(a, b) || byName(a, b));
}

/** How the home page's project rail is ordered. */
export type ProjectRailSort = 'versions' | 'operations' | 'grade';

/** The home rail's sort options, each with the rail title and description it implies. */
export const PROJECT_RAIL_SORTS: readonly {
  value: ProjectRailSort;
  label: string;
  title: string;
  description: string;
}[] = [
  {
    value: 'versions',
    label: 'Most versions',
    title: 'Most active projects',
    description: 'Projects with the largest published version history.',
  },
  {
    value: 'operations',
    label: 'Most operations',
    title: 'Largest APIs',
    description: 'Projects whose latest version has the most operations.',
  },
  {
    value: 'grade',
    label: 'Best grade',
    title: 'Best graded APIs',
    description: 'Projects whose latest version scored best on quality.',
  },
];

/** The URL parameter the home page reads the rail sort from. */
export const PROJECT_RAIL_SORT_PARAM = 'projects';

/**
 * Read the home rail's sort from the URL, falling back to most versions.
 *
 * @param raw - The raw `?projects=` value (a string, an array of them, or nothing).
 * @returns A valid {@link ProjectRailSort}.
 */
export function parseProjectRailSort(raw: string | string[] | null | undefined): ProjectRailSort {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return PROJECT_RAIL_SORTS.some((o) => o.value === value) ? (value as ProjectRailSort) : 'versions';
}

/**
 * The ORDER BY of the home rail query, per sort. It names `version_count`, `latest_published_at`
 * and the {@link cardFactsJoinSql} alias `cf`, which `getMostVersionedProjects` selects.
 *
 * @param mode - The sort (already validated by {@link parseProjectRailSort}).
 * @returns The ORDER BY expression list.
 */
export function projectRailOrderSql(mode: ProjectRailSort): string {
  switch (mode) {
    case 'operations':
      return 'cf.operation_count DESC NULLS LAST, version_count DESC, latest_published_at DESC NULLS LAST';
    case 'grade':
      return 'cf.quality_grade ASC NULLS LAST, cf.quality_score DESC NULLS LAST, latest_published_at DESC NULLS LAST';
    case 'versions':
    default:
      return 'version_count DESC, latest_published_at DESC NULLS LAST';
  }
}
