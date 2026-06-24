/**
 * Unit tests for version lint report helpers (#3609).
 */
import {
  fetchVersionLintReport,
  gradeChipClass,
  severityBadgeClass,
  sortLintFindings,
  type VersionLintFinding,
} from '@/app/utils/version-lint-report';

describe('version-lint-report helpers', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('maps each grade to a distinct chip class and falls back for unknown', () => {
    const a = gradeChipClass('A');
    const f = gradeChipClass('F');
    expect(a).not.toBe(f);
    expect(gradeChipClass('a')).toBe(a); // case-insensitive
    expect(gradeChipClass('Z')).toBe(gradeChipClass('?')); // fallback shared
  });

  it('maps severities to classes with a fallback', () => {
    expect(severityBadgeClass('error')).toContain('rose');
    expect(severityBadgeClass('warning')).toContain('amber');
    expect(severityBadgeClass('info')).toContain('sky');
    expect(severityBadgeClass('mystery')).toContain('gray');
  });

  it('sorts findings most-severe first, then by path and rule', () => {
    const findings: VersionLintFinding[] = [
      { id: '1', path: 'b', category: 'c', rule: 'r2', severity: 'info', message: '' },
      { id: '2', path: 'a', category: 'c', rule: 'r1', severity: 'error', message: '' },
      { id: '3', path: 'a', category: 'c', rule: 'r2', severity: 'warning', message: '' },
    ];
    const sorted = sortLintFindings(findings);
    expect(sorted.map((f) => f.id)).toEqual(['2', '3', '1']);
    // input not mutated
    expect(findings[0].id).toBe('1');
  });

  it('fetches a report through the proxy and returns the body', async () => {
    const body = { success: true, score: 88, grade: 'B', findings: [] };
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(body) });
    const report = await fetchVersionLintReport('p1', 'v1');
    expect(report.score).toBe(88);
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/projects/p1/versions/v1/lint',
      expect.objectContaining({ method: 'GET' })
    );
  });

  it('appends baseRevisionId to the request when provided', async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({ success: true, score: 1, grade: 'F', findings: [] }) });
    await fetchVersionLintReport('p1', 'v1', { baseRevisionId: 'base-9' });
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/projects/p1/versions/v1/lint?baseRevisionId=base-9',
      expect.objectContaining({ method: 'GET' })
    );
  });

  it('throws with the server message on failure', async () => {
    global.fetch = jest
      .fn()
      .mockResolvedValue({ ok: false, status: 404, json: () => Promise.resolve({ success: false, error: 'nope' }) });
    await expect(fetchVersionLintReport('p1', 'v1')).rejects.toThrow('nope');
  });
});
