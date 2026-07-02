import {
  getNumericScoreTier,
  letterGradeFromOverallPercent,
  NUMERIC_SCORE_TIER_LEGEND,
} from '@/app/utils/numeric-score-tier';

describe('numeric-score-tier', () => {
  describe('getNumericScoreTier', () => {
    it('maps 90–100 to excellent (green)', () => {
      expect(getNumericScoreTier(90).band).toBe('excellent');
      expect(getNumericScoreTier(100).band).toBe('excellent');
    });

    it('maps 70–89 to good (yellow)', () => {
      expect(getNumericScoreTier(70).band).toBe('good');
      expect(getNumericScoreTier(89).band).toBe('good');
    });

    it('rounds near thresholds before mapping bands', () => {
      expect(getNumericScoreTier(89.6).band).toBe('excellent');
      expect(getNumericScoreTier(69.5).band).toBe('good');
    });

    it('maps 50–69 to fair (orange)', () => {
      expect(getNumericScoreTier(50).band).toBe('fair');
      expect(getNumericScoreTier(69).band).toBe('fair');
    });

    it('maps 0–49 to poor (red)', () => {
      expect(getNumericScoreTier(0).band).toBe('poor');
      expect(getNumericScoreTier(49).band).toBe('poor');
    });

    it('clamps out-of-range inputs', () => {
      expect(getNumericScoreTier(-5).band).toBe('poor');
      expect(getNumericScoreTier(150).band).toBe('excellent');
    });

    it('includes expected labels on excellent tier', () => {
      const t = getNumericScoreTier(95);
      expect(t.shortLabel).toBe('Excellent');
      expect(t.detailLabel).toBe('Production ready');
      expect(t.progressGradientClass).toContain('green');
    });
  });

  describe('letterGradeFromOverallPercent', () => {
    it('aligns A/B/C with tier bands', () => {
      expect(letterGradeFromOverallPercent(90)).toBe('A');
      expect(letterGradeFromOverallPercent(70)).toBe('B');
      expect(letterGradeFromOverallPercent(50)).toBe('C');
    });

    it('splits poor band into D and F', () => {
      expect(letterGradeFromOverallPercent(45)).toBe('D');
      expect(letterGradeFromOverallPercent(39)).toBe('F');
    });
  });

  it('legend lists four bands', () => {
    expect(NUMERIC_SCORE_TIER_LEGEND).toHaveLength(4);
    expect(NUMERIC_SCORE_TIER_LEGEND.map((x) => x.band).sort()).toEqual(
      ['excellent', 'fair', 'good', 'poor'].sort()
    );
  });
});
