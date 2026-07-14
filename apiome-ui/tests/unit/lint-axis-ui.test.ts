/**
 * Unit tests for multi-axis score/coverage presentation helpers (CLX-1.2, #4849).
 */

import {
  lintAxisBand,
  lintAxisEvaluationFromLintReport,
  lintAxisEvaluationFromPayload,
  lintAxisFromPayload,
  lintAxisScoreLabel,
} from '../../src/app/utils/lint-axis-ui';

describe('lintAxisUi', () => {
  it('forces a gap when assessed is false even if a score sneaks through', () => {
    const axis = lintAxisFromPayload({
      key: 'protocol',
      label: 'Protocol',
      assessed: false,
      score: 0,
      grade: 'F',
      coverage: { state: 'none' },
      notAssessedReason: 'No protocol scanner yet',
    });
    expect(axis).not.toBeNull();
    expect(axis!.assessed).toBe(false);
    expect(axis!.score).toBeNull();
    expect(axis!.grade).toBeNull();
    expect(lintAxisBand(axis!)).toBe('gap');
    expect(lintAxisScoreLabel(axis!)).toBe('Not assessed');
  });

  it('treats assessed empty findings as clean, not a gap', () => {
    const axis = lintAxisFromPayload({
      key: 'security',
      label: 'Security',
      assessed: true,
      score: 100,
      grade: 'A',
      severityCounts: { error: 0, warning: 0, info: 0 },
      coverage: { state: 'full' },
    });
    expect(axis!.assessed).toBe(true);
    expect(axis!.score).toBe(100);
    expect(lintAxisScoreLabel(axis!)).toContain('No findings');
    expect(lintAxisBand(axis!)).toBe('strong');
  });

  it('parses a lint report nested evaluation', () => {
    const evaluation = lintAxisEvaluationFromLintReport({
      algorithmId: 'clx-axis-v1',
      requiredCoverageMet: true,
      compositeScore: 90,
      compositeGrade: 'A',
      axes: [
        {
          key: 'quality',
          label: 'Quality',
          assessed: true,
          score: 90,
          grade: 'A',
          severityCounts: { error: 0, warning: 0, info: 0 },
          coverage: { state: 'full' },
        },
        {
          key: 'protocol',
          label: 'Protocol',
          assessed: false,
          score: null,
          coverage: { state: 'none' },
          notAssessedReason: 'pending',
        },
      ],
    });
    expect(evaluation).not.toBeNull();
    expect(evaluation!.algorithmId).toBe('clx-axis-v1');
    expect(evaluation!.compositeScore).toBe(90);
    expect(evaluation!.axes[1].assessed).toBe(false);
    expect(evaluation!.axes[1].score).toBeNull();
  });

  it('withholds composite when required coverage is incomplete', () => {
    const evaluation = lintAxisEvaluationFromPayload({
      algorithm_id: 'clx-axis-v1',
      required_coverage_met: false,
      composite_score: 50,
      composite_grade: 'F',
      axes: [
        {
          key: 'quality',
          label: 'Quality',
          assessed: false,
          coverage: { state: 'none' },
          not_assessed_reason: 'missing',
        },
      ],
    });
    expect(evaluation!.requiredCoverageMet).toBe(false);
    expect(evaluation!.compositeScore).toBeNull();
    expect(evaluation!.compositeGrade).toBeNull();
  });
});
