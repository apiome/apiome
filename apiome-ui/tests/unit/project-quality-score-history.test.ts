import { describe, it, expect, beforeEach, jest } from '@jest/globals';
import {
  buildQualityTrendPoints,
  buildPortfolioQualitySeries,
  buildQualitySnapshotReportExtras,
} from '@/app/utils/project-quality-score-history';

describe('project-quality-score-history', () => {
  beforeEach(() => {
    localStorage.clear();
    jest.resetModules();
  });

  describe('buildQualityTrendPoints', () => {
    it('maps a single value to a flat line across the viewBox', () => {
      const pts = buildQualityTrendPoints([72]);
      expect(pts).toHaveLength(2);
      expect(pts[0].overall).toBe(72);
      expect(pts[1].overall).toBe(72);
      expect(pts[0].y).toBe(100 - 72);
    });

    it('maps multiple values across x', () => {
      const pts = buildQualityTrendPoints([0, 50, 100]);
      expect(pts).toHaveLength(3);
      expect(pts[0].x).toBe(0);
      expect(pts[2].x).toBe(100);
      expect(pts[2].y).toBe(0);
    });
  });

  describe('buildPortfolioQualitySeries', () => {
    it('returns an empty array when there is no history', () => {
      expect(buildPortfolioQualitySeries({})).toEqual([]);
      expect(buildPortfolioQualitySeries({ a: [] })).toEqual([]);
    });

    it('tracks running averages across projects in timestamp order', () => {
      const series = buildPortfolioQualitySeries({
        p1: [
          { recordedAt: '2025-01-01T00:00:00.000Z', overall: 80, grade: 'B' },
          { recordedAt: '2025-01-03T00:00:00.000Z', overall: 90, grade: 'A' },
        ],
        p2: [{ recordedAt: '2025-01-02T00:00:00.000Z', overall: 60, grade: 'C' }],
      });
      expect(series).toHaveLength(3);
      expect(series[0].avgOverall).toBe(80);
      expect(series[1].avgOverall).toBe(70);
      expect(series[2].avgOverall).toBe(75);
    });
  });

  describe('appendProjectQualitySnapshot', () => {
    it('stores and reads snapshots per project', async () => {
      const { appendProjectQualitySnapshot, getProjectQualityHistory } = await import(
        '@/app/utils/project-quality-score-history'
      );
      appendProjectQualitySnapshot('p1', { overall: 80, grade: 'B', importJobId: 'job-a' });
      expect(getProjectQualityHistory('p1')).toHaveLength(1);
      expect(getProjectQualityHistory('p1')[0].overall).toBe(80);
      expect(getProjectQualityHistory('p1')[0].grade).toBe('B');
    });

    it('dedupes the same import job id', async () => {
      const { appendProjectQualitySnapshot, getProjectQualityHistory } = await import(
        '@/app/utils/project-quality-score-history'
      );
      appendProjectQualitySnapshot('p1', { overall: 80, grade: 'B', importJobId: 'job-x' });
      appendProjectQualitySnapshot('p1', { overall: 81, grade: 'B', importJobId: 'job-x' });
      expect(getProjectQualityHistory('p1')).toHaveLength(1);
    });
  });

  describe('buildQualitySnapshotReportExtras', () => {
    it('stores categories, quality issues, and lint findings', () => {
      const extras = buildQualitySnapshotReportExtras({
        qualityScore: {
          overall: 72,
          grade: 'B',
          categories: {
            designQuality: {
              id: 'designQuality',
              label: 'Design Quality',
              description: 'Naming',
              percent: 80,
              maxPoints: 30,
              points: 24,
            },
            documentation: {
              id: 'documentation',
              label: 'Documentation',
              description: 'Docs',
              percent: 50,
              maxPoints: 20,
              points: 10,
            },
            apiBestPractices: {
              id: 'apiBestPractices',
              label: 'API Best Practices',
              description: 'Best',
              percent: 60,
              maxPoints: 25,
              points: 15,
            },
            security: {
              id: 'security',
              label: 'Security',
              description: 'Sec',
              percent: 70,
              maxPoints: 15,
              points: 10,
            },
            performance: {
              id: 'performance',
              label: 'Performance',
              description: 'Perf',
              percent: 40,
              maxPoints: 10,
              points: 4,
            },
          },
          completeness: 50,
          consistency: 80,
          bestPractices: 60,
          security: 70,
          performance: 40,
          issues: [
            {
              category: 'documentation',
              message: 'Missing description',
              suggestion: 'Add a description',
              path: 'info.title',
              severity: 'medium',
            },
          ],
        },
        errors: [{ type: 'error', message: 'Invalid ref', path: '#/components/schemas/Foo', severity: 'high' }],
        warnings: [{ type: 'warning', message: 'No servers', severity: 'low' }],
      });

      expect(extras.categories).toHaveLength(5);
      expect(extras.issues).toHaveLength(1);
      expect(extras.lintFindings).toHaveLength(2);
      expect(extras.lintFindings?.[0].type).toBe('error');
      expect(extras.lintFindings?.[1].type).toBe('warning');
    });
  });
});
