import { describe, it, expect } from '@jest/globals';
import { groupCompatibilityFindings } from '../lib/compatibility-report-group';

describe('groupCompatibilityFindings', () => {
  it('groups by severity then entity path', () => {
    const g = groupCompatibilityFindings([
      { category: 'safe', rule: 'r1', path: '/z', message: 'm1' },
      { category: 'breaking', rule: 'r2', path: '/a', message: 'm2' },
      { category: 'breaking', rule: 'r3', path: '/a', message: 'm3' },
      { category: 'unknown', rule: 'r4', path: '/b', message: 'm4' },
    ]);
    expect(g.map((s) => s.severity)).toEqual(['breaking', 'unknown', 'safe']);
    expect(g[0].paths.map((p) => p.path)).toEqual(['/a']);
    expect(g[0].paths[0].findings).toHaveLength(2);
    expect(g[1].paths[0].path).toBe('/b');
    expect(g[2].paths[0].path).toBe('/z');
  });

  it('treats missing category as unknown', () => {
    const g = groupCompatibilityFindings([{ rule: 'r', path: '/p', message: 'm' }]);
    expect(g[0]?.severity).toBe('unknown');
  });
});
