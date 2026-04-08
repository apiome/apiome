import { describe, it, expect, beforeEach, jest } from '@jest/globals';
import { buildQualityTrendPoints } from '@/app/utils/project-quality-score-history';

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
});
