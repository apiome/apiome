/**
 * Pure helpers over stored `ctg.changelog.v1` changelogs (CTG-3.2, #4476):
 * severity grouping, pointer → class-diff stableId mapping, stored-pair
 * matching, and badge/count formatting.
 */
import {
  breakingStableIds,
  changelogMatchesComparedPair,
  countsSummary,
  decodeJsonPointer,
  groupChangelogEntries,
  severityBadgeVariant,
  severityLabel,
  stableIdForPointer,
  type ChangelogEntry,
} from '../lib/version-changelog';

function entry(overrides: Partial<ChangelogEntry>): ChangelogEntry {
  return {
    severity: 'non-breaking',
    pathGroup: '/pets',
    pointer: '/paths/~1pets/get',
    ruleId: 'rule',
    changeKind: 'modified',
    summary: 'Changed',
    ...overrides,
  };
}

describe('groupChangelogEntries', () => {
  it('orders sections breaking → non-breaking → docs-only regardless of input order', () => {
    const sections = groupChangelogEntries([
      entry({ severity: 'docs-only', pathGroup: 'a' }),
      entry({ severity: 'non-breaking', pathGroup: 'b' }),
      entry({ severity: 'breaking', pathGroup: 'c' }),
    ]);
    expect(sections.map((s) => s.severity)).toEqual(['breaking', 'non-breaking', 'docs-only']);
  });

  it('omits severities with no entries', () => {
    const sections = groupChangelogEntries([entry({ severity: 'breaking' })]);
    expect(sections.map((s) => s.severity)).toEqual(['breaking']);
  });

  it('groups by pathGroup preserving first-seen order and entry order', () => {
    const sections = groupChangelogEntries([
      entry({ severity: 'breaking', pathGroup: '/pets', summary: 'one' }),
      entry({ severity: 'breaking', pathGroup: '/owners', summary: 'two' }),
      entry({ severity: 'breaking', pathGroup: '/pets', summary: 'three' }),
    ]);
    expect(sections).toHaveLength(1);
    expect(sections[0].groups.map((g) => g.pathGroup)).toEqual(['/pets', '/owners']);
    expect(sections[0].groups[0].entries.map((e) => e.summary)).toEqual(['one', 'three']);
  });

  it('returns [] for empty, null, and undefined input', () => {
    expect(groupChangelogEntries([])).toEqual([]);
    expect(groupChangelogEntries(null)).toEqual([]);
    expect(groupChangelogEntries(undefined)).toEqual([]);
  });

  it('coerces unknown severities to docs-only instead of dropping them', () => {
    const weird = entry({ severity: 'catastrophic' as never, summary: 'odd' });
    const sections = groupChangelogEntries([weird]);
    expect(sections).toHaveLength(1);
    expect(sections[0].severity).toBe('docs-only');
    expect(sections[0].entries[0].summary).toBe('odd');
  });

  it('buckets entries with an empty pathGroup under "(other)"', () => {
    const sections = groupChangelogEntries([entry({ pathGroup: '' })]);
    expect(sections[0].groups[0].pathGroup).toBe('(other)');
  });
});

describe('decodeJsonPointer', () => {
  it('splits and unescapes RFC 6901 segments', () => {
    expect(decodeJsonPointer('/paths/~1pets~1{id}/get')).toEqual(['paths', '/pets/{id}', 'get']);
    expect(decodeJsonPointer('/a~0b')).toEqual(['a~b']);
  });

  it('handles root and empty pointers', () => {
    expect(decodeJsonPointer('')).toEqual([]);
    expect(decodeJsonPointer('/')).toEqual([]);
  });
});

describe('stableIdForPointer', () => {
  it('maps components/schemas pointers to the schema name', () => {
    expect(stableIdForPointer('/components/schemas/Pet')).toBe('Pet');
    expect(stableIdForPointer('/components/schemas/Pet/properties/name')).toBe('Pet');
  });

  it('returns null for non-schema pointers', () => {
    expect(stableIdForPointer('/paths/~1pets/get')).toBeNull();
    expect(stableIdForPointer('/info/title')).toBeNull();
    expect(stableIdForPointer('/components/parameters/Limit')).toBeNull();
    expect(stableIdForPointer('')).toBeNull();
  });
});

describe('breakingStableIds', () => {
  it('collects schema ids only from breaking entries', () => {
    const ids = breakingStableIds([
      entry({ severity: 'breaking', pointer: '/components/schemas/Pet/properties/name' }),
      entry({ severity: 'breaking', pointer: '/paths/~1pets/get' }),
      entry({ severity: 'non-breaking', pointer: '/components/schemas/Owner' }),
    ]);
    expect([...ids]).toEqual(['Pet']);
  });

  it('is empty for null/undefined entries', () => {
    expect(breakingStableIds(null).size).toBe(0);
    expect(breakingStableIds(undefined).size).toBe(0);
  });
});

describe('changelogMatchesComparedPair', () => {
  const stored = { publishedRevisionId: 'head-1', baselineRevisionId: 'base-1' };

  it('matches only the exact stored pair', () => {
    expect(changelogMatchesComparedPair(stored, 'base-1', 'head-1')).toBe(true);
    expect(changelogMatchesComparedPair(stored, 'other', 'head-1')).toBe(false);
    expect(changelogMatchesComparedPair(stored, 'base-1', 'other')).toBe(false);
    // Reversed direction must not badge.
    expect(changelogMatchesComparedPair(stored, 'head-1', 'base-1')).toBe(false);
  });

  it('never matches when data is missing', () => {
    expect(changelogMatchesComparedPair(null, 'a', 'b')).toBe(false);
    expect(changelogMatchesComparedPair(stored, null, 'head-1')).toBe(false);
    expect(changelogMatchesComparedPair(stored, 'base-1', undefined)).toBe(false);
    expect(
      changelogMatchesComparedPair(
        { publishedRevisionId: 'head-1', baselineRevisionId: null },
        'base-1',
        'head-1',
      ),
    ).toBe(false);
  });
});

describe('labels and counts', () => {
  it('severityLabel / severityBadgeVariant cover all severities', () => {
    expect(severityLabel('breaking')).toBe('Breaking');
    expect(severityLabel('non-breaking')).toBe('Non-breaking');
    expect(severityLabel('docs-only')).toBe('Docs-only');
    expect(severityBadgeVariant('breaking')).toBe('error');
    expect(severityBadgeVariant('non-breaking')).toBe('warning');
    expect(severityBadgeVariant('docs-only')).toBe('secondary');
  });

  it('countsSummary lists non-zero severities in worst-first order', () => {
    expect(
      countsSummary({ breaking: 1, 'non-breaking': 2, 'docs-only': 0, unclassified: 0, total: 3 }),
    ).toBe('1 breaking · 2 non-breaking');
  });

  it('countsSummary returns null when empty or all-zero', () => {
    expect(countsSummary(null)).toBeNull();
    expect(countsSummary(undefined)).toBeNull();
    expect(countsSummary({ breaking: 0, 'non-breaking': 0, 'docs-only': 0 })).toBeNull();
  });
});
