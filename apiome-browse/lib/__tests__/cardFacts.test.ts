import { describe, expect, it } from 'vitest';
import {
  CARD_FACT_COLUMNS,
  PROJECT_RAIL_SORTS,
  PROJECT_SORT_OPTIONS,
  cardFactsJoinSql,
  cardFactsSelectSql,
  compareByGrade,
  factsLine,
  factsLineText,
  parseProjectRailSort,
  parseProjectSort,
  pickCardFacts,
  projectRailOrderSql,
  sortProjectsByFacts,
  summaryRailOrderSql,
  type CardFacts,
} from '../cardFacts';

const NOW = Date.parse('2026-11-16T12:00:00Z');
const THREE_DAYS_AGO = '2026-11-13T12:00:00Z';

/** A fully populated facts row, overridable per test. */
function facts(overrides: Partial<CardFacts> = {}): CardFacts {
  return {
    operation_count: 42,
    schema_count: 18,
    quality_grade: 'B',
    quality_score: 84,
    mock_enabled: true,
    sdk_available: true,
    facts_format: 'openapi-3.1',
    facts_published_at: THREE_DAYS_AGO,
    ...overrides,
  };
}

describe('factsLine', () => {
  it('reads the issue example in the fixed order', () => {
    const items = factsLine(facts(), { now: NOW });
    expect(factsLineText(items)).toBe(
      '42 operations · 18 schemas · Grade B · Mock · SDK · OpenAPI 3.1 · updated 3d ago'
    );
    expect(items.map((i) => i.kind)).toEqual([
      'operations',
      'schemas',
      'grade',
      'mock',
      'sdk',
      'format',
      'updated',
    ]);
  });

  it('uses the singular for one operation and one schema, and groups thousands', () => {
    expect(factsLineText(factsLine(facts({ operation_count: 1, schema_count: 1 }), { omit: ['grade', 'mock', 'sdk', 'format', 'updated'] }))).toBe(
      '1 operation · 1 schema'
    );
    expect(factsLine(facts({ operation_count: 1234 }))[0].label).toBe('1,234 operations');
  });

  it('leaves out what is unknown, zero, off or not offered', () => {
    const items = factsLine(
      facts({
        operation_count: 0,
        schema_count: null,
        quality_grade: null,
        quality_score: null,
        mock_enabled: false,
        sdk_available: false,
        facts_format: null,
        facts_published_at: null,
      }),
      { now: NOW }
    );
    expect(items).toEqual([]);
  });

  it('shows the grade only when scored, with the score in the tooltip', () => {
    const [grade] = factsLine(facts({ operation_count: 0, schema_count: 0 }), { now: NOW });
    expect(grade).toMatchObject({ kind: 'grade', label: 'Grade B', grade: 'B' });
    expect(grade.title).toBe('Quality grade B (score 84 of 100)');
    const noScore = factsLine(facts({ operation_count: 0, schema_count: 0, quality_score: null }))[0];
    expect(noScore.title).toBe('Quality grade B');
  });

  it('honours omit', () => {
    const kinds = factsLine(facts(), { now: NOW, omit: ['mock', 'updated'] }).map((i) => i.kind);
    expect(kinds).not.toContain('mock');
    expect(kinds).not.toContain('updated');
    expect(kinds).toContain('sdk');
  });

  it('returns nothing for no facts', () => {
    expect(factsLine(null)).toEqual([]);
    expect(factsLine(undefined)).toEqual([]);
  });
});

describe('pickCardFacts', () => {
  it('lifts the fact columns out of a wider row and coerces numbers', () => {
    const row = { id: 'p1', name: 'Payments', ...facts(), operation_count: '42', quality_grade: 'b' };
    expect(pickCardFacts(row as never)).toEqual(facts());
  });

  it('returns null for a row joined to no version', () => {
    expect(pickCardFacts({})).toBeNull();
    expect(pickCardFacts(null)).toBeNull();
    expect(
      pickCardFacts(Object.fromEntries(CARD_FACT_COLUMNS.map((c) => [c, null])) as never)
    ).toBeNull();
  });

  it('drops values of the wrong type instead of trusting them', () => {
    const picked = pickCardFacts({
      operation_count: 'many',
      schema_count: 3,
      mock_enabled: 'yes',
      sdk_available: 1,
      quality_grade: '  ',
      facts_published_at: 12,
    } as never);
    expect(picked).toMatchObject({
      operation_count: null,
      schema_count: 3,
      mock_enabled: null,
      sdk_available: null,
      quality_grade: null,
      facts_published_at: null,
    });
  });
});

describe('SQL fragments', () => {
  it('selects every fact column from the alias', () => {
    expect(cardFactsSelectSql('cf')).toBe(CARD_FACT_COLUMNS.map((c) => `cf.${c}`).join(', '));
  });

  it('computes the counts and flags for the given version inside one lateral join', () => {
    const sql = cardFactsJoinSql('lv.id', 'cf');
    expect(sql).toMatch(/^LEFT JOIN LATERAL \(/);
    expect(sql).toMatch(/\) cf ON TRUE$/);
    expect(sql).toContain('WHERE f_v.id = lv.id');
    expect(sql).toContain('apiome.path_operation');
    expect(sql).toContain('f_c.deleted_at IS NULL');
    for (const column of CARD_FACT_COLUMNS) expect(sql).toContain(`AS ${column}`);
  });

  it('reads the counts stored at publish and only counts a version that has none (DBP-1.16)', () => {
    const sql = cardFactsJoinSql('lv.id', 'cf');
    expect(sql).toMatch(/COALESCE\(f_v\.operation_count,\s*\(SELECT COUNT\(\*\)::int[\s\S]*?apiome\.path_operation[\s\S]*?\)\) AS operation_count/);
    expect(sql).toMatch(/COALESCE\(f_v\.schema_count,\s*\(SELECT COUNT\(\*\)::int[\s\S]*?apiome\.classes[\s\S]*?\)\) AS schema_count/);
  });

  it('reads the public SDK opt-in the way REST merges it: most specific row naming the key wins, default off', () => {
    const sql = cardFactsJoinSql('v.id');
    expect(sql).toContain("f_s.settings ? 'publicSdkEnabled'");
    expect(sql).toContain('(f_s.project_id = f_p.id OR f_s.project_id IS NULL)');
    expect(sql).toContain('ORDER BY f_s.project_id NULLS LAST');
    expect(sql).toMatch(/COALESCE\(\(\s*SELECT f_s\.settings -> 'publicSdkEnabled' = 'true'::jsonb[\s\S]*\), false\) AS sdk_available/);
  });
});

describe('summaryRailOrderSql', () => {
  it('orders each rail by the column list of its summary index (DBP-1.27)', () => {
    expect(summaryRailOrderSql('versions', 'b')).toBe('b.version_count DESC, b.latest_published_at DESC NULLS LAST');
    expect(summaryRailOrderSql('operations', 'b')).toBe(
      'b.operation_count DESC, b.version_count DESC, b.latest_published_at DESC NULLS LAST'
    );
    expect(summaryRailOrderSql('grade', 'b')).toBe(
      'b.quality_grade ASC NULLS LAST, b.quality_score DESC NULLS LAST, b.latest_published_at DESC NULLS LAST'
    );
  });

  it('ranks in the same order as the rail renders', () => {
    for (const mode of ['versions', 'operations', 'grade'] as const) {
      const stored = summaryRailOrderSql(mode, 'b').replace(/b\./g, '').replace(/ NULLS LAST/g, '');
      const shown = projectRailOrderSql(mode).replace(/cf\./g, '').replace(/ NULLS LAST/g, '');
      expect(stored).toBe(shown);
    }
  });
});

describe('sorting', () => {
  const rows = [
    { name: 'Billing', ...facts({ operation_count: 10, quality_grade: 'C', quality_score: 71, facts_published_at: '2026-11-01T00:00:00Z' }) },
    { name: 'accounts', ...facts({ operation_count: 50, quality_grade: null, quality_score: null, facts_published_at: null }) },
    { name: 'Catalog', ...facts({ operation_count: 50, quality_grade: 'A', quality_score: 93, facts_published_at: '2026-11-10T00:00:00Z' }) },
    { name: 'Docs', ...facts({ operation_count: null, quality_grade: 'A', quality_score: 97, facts_published_at: '2026-11-15T00:00:00Z' }) },
  ];
  const names = (sorted: { name: string }[]) => sorted.map((r) => r.name);

  it('orders by name, case-insensitively, by default', () => {
    expect(names(sortProjectsByFacts(rows, 'name'))).toEqual(['accounts', 'Billing', 'Catalog', 'Docs']);
  });

  it('orders by most operations, ties by name, unknown counts last', () => {
    expect(names(sortProjectsByFacts(rows, 'operations'))).toEqual(['accounts', 'Catalog', 'Billing', 'Docs']);
  });

  it('orders by best grade, then score, ungraded last', () => {
    expect(names(sortProjectsByFacts(rows, 'grade'))).toEqual(['Docs', 'Catalog', 'Billing', 'accounts']);
  });

  it('orders by most recently updated, undated last', () => {
    expect(names(sortProjectsByFacts(rows, 'updated'))).toEqual(['Docs', 'Catalog', 'Billing', 'accounts']);
  });

  it('does not mutate its input', () => {
    const copy = [...rows];
    sortProjectsByFacts(rows, 'grade');
    expect(rows).toEqual(copy);
  });

  it('compareByGrade treats grades case-insensitively and ties equal rows', () => {
    expect(compareByGrade({ name: 'a', quality_grade: 'a' }, { name: 'b', quality_grade: 'B' })).toBeLessThan(0);
    expect(compareByGrade({ name: 'a' }, { name: 'b' })).toBe(0);
  });

  it('parses sort values and falls back to the default', () => {
    for (const o of PROJECT_SORT_OPTIONS) expect(parseProjectSort(o.value)).toBe(o.value);
    expect(parseProjectSort('bogus')).toBe('name');
    expect(parseProjectSort(null)).toBe('name');
    for (const o of PROJECT_RAIL_SORTS) expect(parseProjectRailSort(o.value)).toBe(o.value);
    expect(parseProjectRailSort(['grade', 'operations'])).toBe('grade');
    expect(parseProjectRailSort('DROP TABLE')).toBe('versions');
    expect(parseProjectRailSort(undefined)).toBe('versions');
  });

  it('builds a fixed ORDER BY per rail sort (never from input)', () => {
    expect(projectRailOrderSql('versions')).toBe('version_count DESC, latest_published_at DESC NULLS LAST');
    expect(projectRailOrderSql('operations')).toMatch(/^cf\.operation_count DESC NULLS LAST/);
    expect(projectRailOrderSql('grade')).toMatch(/^cf\.quality_grade ASC NULLS LAST, cf\.quality_score DESC NULLS LAST/);
  });
});
