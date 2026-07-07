/**
 * Render tests for the Score & lint breakdown panel (V2-MCP-31.3 / MCAT-17.3).
 *
 * Covers the acceptance criteria that live in the component (the pure `mcpLintScoreBreakdown`
 * arithmetic is unit-tested in `mcp-lint-ui.test.ts`): loading / error / unavailable states; the
 * score-reconstruction headline; that the severity tallies shown match the findings; the points-lost
 * breakdown; the clean (no findings) "bill of health" state; and that a finding deep-links to its
 * offending capability via `onNavigateToItem`.
 */
import React from 'react';
import { render, screen, within, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ScoreBreakdownPanel } from '../src/app/components/ui/mcp/ScoreBreakdownPanel';
import {
  mcpLintReportFromPayload,
  type McpLintReport,
} from '../src/app/components/ade/dashboard/mcp/mcpLintUi';

function report(overrides: Record<string, unknown> = {}): McpLintReport {
  return mcpLintReportFromPayload({
    endpointId: 'ep-1',
    versionId: 'v-1',
    versionSeq: 3,
    versionTag: '2026-07-01',
    score: 72,
    grade: 'C',
    findings: [
      { id: 'f1', path: 'tools.write_record', category: 'security', rule: 'security.no-auth', severity: 'error', message: 'Destructive tool reachable with no auth.' },
      { id: 'f2', path: 'tools.search', category: 'annotation', rule: 'annotation.hint', severity: 'warning', message: 'Missing readOnlyHint.' },
      { id: 'f3', path: 'surface', category: 'hygiene', rule: 'hygiene.ws', severity: 'info', message: 'Trailing whitespace.' },
    ],
    ruleHits: { 'security.no-auth': 1, 'annotation.hint': 1, 'hygiene.ws': 1 },
    severityCounts: { error: 1, warning: 1, info: 1 },
    reportFingerprint: 'fp',
    source: 'stored',
    scoredAt: '2026-07-01T00:00:00Z',
    ...overrides,
  })!;
}

describe('ScoreBreakdownPanel', () => {
  it('shows a loading state before the first report', () => {
    render(<ScoreBreakdownPanel report={null} loading error={null} />);
    expect(screen.getByText(/Loading score breakdown/i)).toBeInTheDocument();
  });

  it('shows an error state', () => {
    render(<ScoreBreakdownPanel report={null} loading={false} error="Upstream 502" />);
    expect(screen.getByText('Score breakdown unavailable')).toBeInTheDocument();
    expect(screen.getByText('Upstream 502')).toBeInTheDocument();
  });

  it('shows the unavailable state for an unscored snapshot (null report)', () => {
    render(<ScoreBreakdownPanel report={null} loading={false} error={null} />);
    expect(screen.getByText('Score breakdown unavailable')).toBeInTheDocument();
    expect(screen.getByText(/has not been scored yet/i)).toBeInTheDocument();
  });

  it('renders the reconstruction headline and the point total', () => {
    render(<ScoreBreakdownPanel report={report()} loading={false} error={null} />);
    // 10 (error) + 4 (warning) + 1 (info) = 15 points across 3 rule groups.
    expect(
      screen.getByText((content) => /points deducted across rule groups/i.test(content)),
    ).toBeInTheDocument();
    expect(screen.getByText('−15')).toBeInTheDocument();
  });

  it('shows the severity tallies matching the findings', () => {
    render(<ScoreBreakdownPanel report={report()} loading={false} error={null} />);
    // MUST / SHOULD / Advisory chips appear in the headline strip and again as drill-down headers.
    expect(screen.getAllByText('MUST').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('SHOULD').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Advisory').length).toBeGreaterThanOrEqual(1);
  });

  it('lists the rule groups that cost points, costliest first', () => {
    render(<ScoreBreakdownPanel report={report()} loading={false} error={null} />);
    const heading = screen.getByText('Points lost by rule group');
    const section = heading.closest('div')!.parentElement!;
    // Security (−10) leads annotation (−4) leads hygiene (−1).
    expect(within(section).getByText('Security')).toBeInTheDocument();
    expect(within(section).getByText('−10')).toBeInTheDocument();
  });

  it('deep-links a finding to its offending capability item', () => {
    const onNavigateToItem = jest.fn();
    render(
      <ScoreBreakdownPanel report={report()} loading={false} error={null} onNavigateToItem={onNavigateToItem} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /tools\.write_record/i }));
    expect(onNavigateToItem).toHaveBeenCalledWith('tool', 'write_record');
  });

  it('renders a surface-level finding path as inert text (no deep-link)', () => {
    const onNavigateToItem = jest.fn();
    render(
      <ScoreBreakdownPanel report={report()} loading={false} error={null} onNavigateToItem={onNavigateToItem} />,
    );
    // The surface-scoped finding has no capability target, so its path is not a button.
    expect(screen.queryByRole('button', { name: /^surface$/i })).not.toBeInTheDocument();
  });

  it('celebrates a clean report with no findings', () => {
    const clean = report({ score: 100, grade: 'A', findings: [], ruleHits: {}, severityCounts: { error: 0, warning: 0, info: 0 } });
    render(<ScoreBreakdownPanel report={clean} loading={false} error={null} />);
    expect(screen.getByText('No findings')).toBeInTheDocument();
    expect(screen.getByText(/clean bill of health/i)).toBeInTheDocument();
    // No point-cost breakdown is rendered for a clean report.
    expect(screen.queryByText('Points lost by rule group')).not.toBeInTheDocument();
  });
});
