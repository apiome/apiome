/**
 * Unit tests for the public MCP catalog sort logic (V2-MCP-23.7 / MCAT-9.7).
 *
 * These cover the two acceptance-critical behaviours without a database: idle browse is grade-led,
 * an active query defaults to relevance-first, the mode can be overridden, and the emitted ORDER BY
 * puts relevance ahead of grade (with grade as the tiebreaker) only in relevance mode.
 */

import { describe, expect, it } from 'vitest';

import {
  coerceSortMode,
  mcpSortOrderSql,
  resolveDefaultSortMode,
  MCP_SORT_LABELS,
} from '../mcpSort';

describe('resolveDefaultSortMode', () => {
  it('is grade-led (top_graded) when the query is empty — idle browse', () => {
    expect(resolveDefaultSortMode('')).toBe('top_graded');
  });

  it('is grade-led for whitespace-only or nullish queries', () => {
    expect(resolveDefaultSortMode('   ')).toBe('top_graded');
    expect(resolveDefaultSortMode(null)).toBe('top_graded');
    expect(resolveDefaultSortMode(undefined)).toBe('top_graded');
  });

  it('is relevance-first when a search term is present', () => {
    expect(resolveDefaultSortMode('payments')).toBe('relevance');
    expect(resolveDefaultSortMode('  webhook ')).toBe('relevance');
  });
});

describe('coerceSortMode', () => {
  it('honours an explicit, valid mode regardless of the query', () => {
    expect(coerceSortMode('top_graded', 'payments')).toBe('top_graded');
    expect(coerceSortMode('relevance', '')).toBe('relevance');
  });

  it('falls back to the query-derived default for missing/unknown values', () => {
    expect(coerceSortMode(undefined, 'payments')).toBe('relevance');
    expect(coerceSortMode(null, '')).toBe('top_graded');
    expect(coerceSortMode('garbage', 'payments')).toBe('relevance');
    expect(coerceSortMode('garbage', '')).toBe('top_graded');
  });
});

describe('mcpSortOrderSql', () => {
  it('grade-led mode orders by grade then score then name, with no relevance term', () => {
    const sql = mcpSortOrderSql('top_graded');
    expect(sql).toBe('grade ASC NULLS LAST, score DESC NULLS LAST, name ASC');
    expect(sql).not.toContain('relevance');
  });

  it('relevance mode leads with relevance, then grade as the tiebreaker', () => {
    const sql = mcpSortOrderSql('relevance');
    expect(sql).toBe('relevance DESC, grade ASC NULLS LAST, score DESC NULLS LAST, name ASC');
    expect(sql.indexOf('relevance')).toBeLessThan(sql.indexOf('grade'));
  });

  it('uses the supplied tiebreak column (e.g. endpoint_name to avoid ambiguity in the search join)', () => {
    expect(mcpSortOrderSql('relevance', 'endpoint_name')).toBe(
      'relevance DESC, grade ASC NULLS LAST, score DESC NULLS LAST, endpoint_name ASC'
    );
    expect(mcpSortOrderSql('top_graded', 'endpoint_name')).toBe(
      'grade ASC NULLS LAST, score DESC NULLS LAST, endpoint_name ASC'
    );
  });
});

describe('MCP_SORT_LABELS', () => {
  it('labels both modes for the sort control', () => {
    expect(MCP_SORT_LABELS.top_graded).toBe('Top graded');
    expect(MCP_SORT_LABELS.relevance).toBe('Relevance');
  });
});
