import { describe, it, expect } from '@jest/globals';
import { projectHeadRevisionId } from '@/app/utils/project-head-revision';

describe('projectHeadRevisionId', () => {
  it('returns null for empty list', () => {
    expect(projectHeadRevisionId([])).toBeNull();
  });

  it('returns the id with the latest created_at', () => {
    const rows = [
      { id: 'a', created_at: '2020-01-01T00:00:00.000Z' },
      { id: 'b', created_at: '2024-06-15T12:00:00.000Z' },
      { id: 'c', created_at: '2022-01-01T00:00:00.000Z' },
    ];
    expect(projectHeadRevisionId(rows)).toBe('b');
  });

  it('breaks ties with first occurrence when timestamps are equal', () => {
    const t = '2024-01-01T00:00:00.000Z';
    const rows = [
      { id: 'first', created_at: t },
      { id: 'second', created_at: t },
    ];
    expect(projectHeadRevisionId(rows)).toBe('first');
  });
});
