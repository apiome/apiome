/**
 * Tests for the changelog grouping/presentation helpers — CTG-3.2 (#4476).
 *
 * Pins the section ordering (breaking → non-breaking → docs-only regardless of input order),
 * pathGroup grouping in input order, empty input, the unknown-severity fallback, and the
 * label/badge vocabularies the Changes tab and feeds render from.
 */

import { describe, expect, it } from 'vitest';
import {
  groupChangelogEntries,
  severityBadgeClasses,
  severityDotClasses,
  severityLabel,
} from '../group';
import type { ChangelogEntry, Severity } from '../types';

function entry(severity: string, pathGroup: string, pointer: string): ChangelogEntry {
  return {
    severity: severity as Severity,
    pathGroup,
    pointer,
    ruleId: 'rule.test',
    changeKind: 'modified',
    summary: `change at ${pointer}`,
  };
}

describe('groupChangelogEntries', () => {
  it('returns an empty array for no entries', () => {
    expect(groupChangelogEntries([])).toEqual([]);
  });

  it('orders sections breaking → non-breaking → docs-only regardless of input order', () => {
    const sections = groupChangelogEntries([
      entry('docs-only', '/info', '/info/description'),
      entry('breaking', '/paths/~1pets', '/paths/~1pets/get'),
      entry('non-breaking', '/paths/~1pets', '/paths/~1pets/post'),
    ]);
    expect(sections.map((s) => s.severity)).toEqual(['breaking', 'non-breaking', 'docs-only']);
  });

  it('omits severities with no entries', () => {
    const sections = groupChangelogEntries([entry('docs-only', '/info', '/info/title')]);
    expect(sections.map((s) => s.severity)).toEqual(['docs-only']);
  });

  it('groups by pathGroup preserving input order of groups and entries', () => {
    const sections = groupChangelogEntries([
      entry('breaking', '/paths/~1pets', '/paths/~1pets/get'),
      entry('breaking', '/components/schemas/Pet', '/components/schemas/Pet/required'),
      entry('breaking', '/paths/~1pets', '/paths/~1pets/delete'),
    ]);
    expect(sections).toHaveLength(1);
    const [section] = sections;
    expect(section.count).toBe(3);
    expect(section.groups.map((g) => g.pathGroup)).toEqual([
      '/paths/~1pets',
      '/components/schemas/Pet',
    ]);
    expect(section.groups[0].entries.map((e) => e.pointer)).toEqual([
      '/paths/~1pets/get',
      '/paths/~1pets/delete',
    ]);
  });

  it('folds unknown severities into the docs-only section', () => {
    const sections = groupChangelogEntries([
      entry('mystery', '/info', '/info/x'),
      entry('breaking', '/paths/~1a', '/paths/~1a/get'),
    ]);
    expect(sections.map((s) => s.severity)).toEqual(['breaking', 'docs-only']);
    expect(sections[1].groups[0].entries[0].pointer).toBe('/info/x');
  });
});

describe('severityLabel', () => {
  it('maps the vocabulary to display labels', () => {
    expect(severityLabel('breaking')).toBe('Breaking');
    expect(severityLabel('non-breaking')).toBe('Non-breaking');
    expect(severityLabel('docs-only')).toBe('Docs-only');
  });

  it('falls back to Docs-only for unknown severities', () => {
    expect(severityLabel('mystery')).toBe('Docs-only');
  });
});

describe('severityBadgeClasses', () => {
  it('uses rose for breaking, amber for non-breaking, sky for docs-only', () => {
    expect(severityBadgeClasses('breaking')).toContain('bg-rose-50');
    expect(severityBadgeClasses('non-breaking')).toContain('bg-amber-50');
    expect(severityBadgeClasses('docs-only')).toContain('bg-sky-50');
  });

  it('always includes dark: variants', () => {
    for (const sev of ['breaking', 'non-breaking', 'docs-only']) {
      expect(severityBadgeClasses(sev)).toMatch(/dark:bg-/);
      expect(severityBadgeClasses(sev)).toMatch(/dark:text-/);
    }
  });

  it('falls back to the docs-only classes for unknown severities', () => {
    expect(severityBadgeClasses('mystery')).toBe(severityBadgeClasses('docs-only'));
  });
});

describe('severityDotClasses', () => {
  it('matches each severity hue', () => {
    expect(severityDotClasses('breaking')).toBe('bg-rose-500');
    expect(severityDotClasses('non-breaking')).toBe('bg-amber-500');
    expect(severityDotClasses('docs-only')).toBe('bg-sky-500');
    expect(severityDotClasses('mystery')).toBe('bg-sky-500');
  });
});
