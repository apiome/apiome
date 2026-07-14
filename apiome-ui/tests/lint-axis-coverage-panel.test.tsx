/**
 * Integration-ish render tests for LintAxisCoveragePanel (CLX-1.2, #4849).
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import { LintAxisCoveragePanel } from '../src/app/components/ade/dashboard/lint/LintAxisCoveragePanel';
import type { LintAxisEvaluation } from '../src/app/utils/lint-axis-ui';

const evaluation: LintAxisEvaluation = {
  algorithmId: 'clx-axis-v1',
  algorithmVersion: '1',
  compositeScore: 90,
  compositeGrade: 'A',
  requiredCoverageMet: true,
  sourceReportFingerprint: 'fp',
  axes: [
    {
      key: 'quality',
      label: 'Quality',
      weight: 1,
      assessed: true,
      score: 90,
      grade: 'A',
      severityCounts: { error: 0, warning: 0, info: 0 },
      coverageState: 'full',
      notAssessedReason: null,
    },
    {
      key: 'security',
      label: 'Security',
      weight: 1,
      assessed: true,
      score: 100,
      grade: 'A',
      severityCounts: { error: 0, warning: 0, info: 0 },
      coverageState: 'full',
      notAssessedReason: null,
    },
    {
      key: 'protocol',
      label: 'Protocol',
      weight: 1,
      assessed: false,
      score: null,
      grade: null,
      severityCounts: { error: 0, warning: 0, info: 0 },
      coverageState: 'none',
      notAssessedReason: 'No protocol-conformance scanner evidence yet',
    },
  ],
};

describe('LintAxisCoveragePanel', () => {
  it('shows Not assessed for gaps and No findings for clean scored axes', () => {
    render(<LintAxisCoveragePanel evaluation={evaluation} />);
    expect(screen.getByTestId('lint-axis-coverage-panel')).toBeInTheDocument();
    expect(screen.getByTestId('lint-axis-row-protocol')).toHaveTextContent('Not assessed');
    expect(screen.getByTestId('lint-axis-row-security')).toHaveTextContent('No findings');
    expect(screen.getByTestId('lint-axis-row-quality')).toHaveTextContent('90/100');
    expect(screen.getByText(/composite/i)).toBeInTheDocument();
  });
});
