/**
 * Render tests for the workspace posture summary header (CLX-4.1, #4859): the acceptance
 * criterion 1 callouts (unwaived security errors, missing required coverage), waiver
 * counts, grade distribution, and the drill-down callbacks.
 */

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import LintWorkspaceSummaryHeader from '../src/app/components/ade/dashboard/lint/workspace/LintWorkspaceSummaryHeader';
import type { LintWorkspaceSummary } from '../src/app/utils/lint-workspace';

const SUMMARY: LintWorkspaceSummary = {
  subjects: { catalog_revisions: 4, mcp_endpoint_versions: 2 },
  gradeDistribution: { A: 2, B: 1, C: 0, D: 0, F: 1, ungraded: 2 },
  axes: [
    {
      key: 'quality',
      label: 'Quality',
      assessedCount: 4,
      notAssessedCount: 2,
      averageScore: 82,
      gradeDistribution: { A: 2 },
      severityCounts: { error: 3, warning: 5, info: 1 },
    },
    {
      key: 'security',
      label: 'Security',
      assessedCount: 0,
      notAssessedCount: 6,
      averageScore: null,
      gradeDistribution: {},
      severityCounts: { error: 0, warning: 0, info: 0 },
    },
  ],
  coverage: {
    missingCount: 3,
    subjects: [
      {
        subjectType: 'catalog_revision',
        subjectId: 'v1',
        projectId: 'p1',
        subjectLabel: '1.0.0',
        missingAxes: ['quality'],
      },
    ],
  },
  findings: {
    open: 5,
    acknowledged: 1,
    waiver_requested: 2,
    waived: 1,
    fixed: 0,
    false_positive: 0,
    new_count: 4,
    unwaived_errors: 3,
    unwaived_security_errors: 2,
  },
  waivers: { active: 1, requested: 2, expiring_soon: 1 },
};

describe('LintWorkspaceSummaryHeader', () => {
  it('renders the acceptance-criterion callouts and waiver counts', () => {
    render(<LintWorkspaceSummaryHeader summary={SUMMARY} />);
    expect(screen.getByTestId('summary-security-errors')).toHaveTextContent('2');
    expect(screen.getByTestId('summary-missing-coverage')).toHaveTextContent('3');
    expect(screen.getByTestId('summary-missing-coverage')).toHaveTextContent('of 6 subjects');
    expect(screen.getByTestId('summary-new-findings')).toHaveTextContent('4');
    expect(screen.getByTestId('summary-waivers')).toHaveTextContent(
      '2 requested · 1 expiring soon',
    );
  });

  it('renders grade chips (skipping zero counts) and axis chips', () => {
    render(<LintWorkspaceSummaryHeader summary={SUMMARY} />);
    const grades = screen.getByTestId('summary-grades');
    expect(grades).toHaveTextContent('A');
    expect(grades).toHaveTextContent('Ungraded');
    expect(grades).not.toHaveTextContent('C');
    const axes = screen.getByTestId('summary-axes');
    expect(axes).toHaveTextContent('Quality');
    expect(axes).toHaveTextContent('82');
    expect(axes).toHaveTextContent('Security');
  });

  it('drills down through the callout tiles', () => {
    const onDrillDown = jest.fn();
    render(<LintWorkspaceSummaryHeader summary={SUMMARY} onDrillDown={onDrillDown} />);
    fireEvent.click(screen.getByTestId('summary-security-errors'));
    expect(onDrillDown).toHaveBeenCalledWith('security-errors');
    fireEvent.click(screen.getByTestId('summary-new-findings'));
    expect(onDrillDown).toHaveBeenCalledWith('new');
    fireEvent.click(screen.getByTestId('summary-waivers'));
    expect(onDrillDown).toHaveBeenCalledWith('waiver-requests');
  });
});
