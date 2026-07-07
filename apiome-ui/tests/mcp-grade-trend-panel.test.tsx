/**
 * Render/interaction tests for the Grade & surface-size trend panel (V2-MCP-30.4 / MCAT-16.4).
 *
 * Covers the acceptance criteria that live in the component (the pure {@link mcpGradeSurfaceTrend}
 * projection is unit-tested in `mcp-evolution-ui.test.ts`): loading / error / no-history states; the
 * score and surface-size trend charts render from the series; an unscored snapshot is gapped (a "no
 * data" cell) rather than zeroed; and the breaking-change releases surface as chips that deep-link to
 * their diff via `onSelectVersion`.
 */
import React from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { GradeSurfaceTrendPanel } from '../src/app/components/ui/mcp/GradeSurfaceTrendPanel';
import type { McpEvolutionPoint } from '../src/app/components/ade/dashboard/mcp/mcpEvolutionUi';

function point(overrides: Partial<McpEvolutionPoint> = {}): McpEvolutionPoint {
  return {
    version_id: overrides.version_id ?? 'v-1',
    version_seq: overrides.version_seq ?? 1,
    version_tag: overrides.version_tag ?? null,
    discovered_at: overrides.discovered_at ?? '2026-07-01T10:00:00Z',
    is_current: overrides.is_current ?? false,
    type_counts: overrides.type_counts ?? {
      tools: 2,
      resources: 1,
      resource_templates: 0,
      prompts: 0,
      total: 3,
    },
    score: overrides.score === undefined ? 90 : overrides.score,
    grade: overrides.grade === undefined ? 'A' : overrides.grade,
    change_counts: overrides.change_counts ?? { added: 0, removed: 0, modified: 0, total: 0 },
    severity_counts:
      overrides.severity_counts ?? { breaking: 0, additive: 0, review: 0, total: 0 },
  };
}

// A four-snapshot series: rising scores with one unscored gap (v3) and one breaking release (v4).
const SERIES: McpEvolutionPoint[] = [
  point({
    version_id: 'a',
    version_seq: 1,
    score: 60,
    grade: 'D',
    type_counts: { tools: 5, resources: 0, resource_templates: 0, prompts: 0, total: 5 },
  }),
  point({
    version_id: 'b',
    version_seq: 2,
    score: 72,
    grade: 'C',
    type_counts: { tools: 6, resources: 1, resource_templates: 0, prompts: 0, total: 7 },
  }),
  point({
    version_id: 'c',
    version_seq: 3,
    score: null,
    grade: null,
    type_counts: { tools: 6, resources: 1, resource_templates: 0, prompts: 0, total: 7 },
  }),
  point({
    version_id: 'd',
    version_seq: 4,
    is_current: true,
    score: 88,
    grade: 'B',
    type_counts: { tools: 8, resources: 2, resource_templates: 0, prompts: 1, total: 11 },
    severity_counts: { breaking: 2, additive: 1, review: 0, total: 3 },
  }),
];

describe('GradeSurfaceTrendPanel', () => {
  it('shows a loading state before the series arrives', () => {
    render(<GradeSurfaceTrendPanel series={null} loading error={null} onSelectVersion={jest.fn()} />);
    expect(screen.getByText(/Loading trend/i)).toBeInTheDocument();
  });

  it('shows an error state (not a crash) on failure', () => {
    render(
      <GradeSurfaceTrendPanel
        series={null}
        loading={false}
        error="evolution engine down"
        onSelectVersion={jest.fn()}
      />,
    );
    expect(screen.getByText('Trend unavailable')).toBeInTheDocument();
    expect(screen.getByText('evolution engine down')).toBeInTheDocument();
  });

  it('shows a no-history empty state for an endpoint with no snapshots', () => {
    render(
      <GradeSurfaceTrendPanel series={[]} loading={false} error={null} onSelectVersion={jest.fn()} />,
    );
    expect(screen.getByText('No history yet')).toBeInTheDocument();
  });

  it('renders both trend charts and the latest grade headline', () => {
    render(
      <GradeSurfaceTrendPanel series={SERIES} loading={false} error={null} onSelectVersion={jest.fn()} />,
    );
    expect(screen.getByText('Quality score')).toBeInTheDocument();
    expect(screen.getByText('Surface size')).toBeInTheDocument();
    // The latest scored snapshot (v4, B / 88) leads the headline via the grade glyph.
    expect(screen.getByRole('img', { name: /Grade B, score 88/ })).toBeInTheDocument();
    // Latest capability total (11).
    expect(screen.getByText('11')).toBeInTheDocument();
  });

  it('gaps an unscored snapshot in the score chart rather than plotting a zero', () => {
    render(
      <GradeSurfaceTrendPanel series={SERIES} loading={false} error={null} onSelectVersion={jest.fn()} />,
    );
    // The score chart's sr-only data table records v3 as "unscored" (a gap), never 0.
    const scoreFigure = screen.getByRole('img', { name: /Quality score per snapshot/ });
    const table = within(scoreFigure.closest('figure') as HTMLElement).getByRole('table');
    expect(within(table).getByText(/unscored/)).toBeInTheDocument();
  });

  it('lists breaking-change releases as chips and deep-links a chip to its diff', () => {
    const onSelect = jest.fn();
    render(
      <GradeSurfaceTrendPanel series={SERIES} loading={false} error={null} onSelectVersion={onSelect} />,
    );
    // v4 introduced 2 breaking changes → a clickable chip.
    const chip = screen.getByRole('button', { name: /v4.*2 breaking/ });
    expect(chip).toBeInTheDocument();
    fireEvent.click(chip);
    expect(onSelect).toHaveBeenCalledWith('d');
  });

  it('reports no breaking changes when none were recorded', () => {
    const clean = [
      point({ version_id: 'a', version_seq: 1, score: 70, grade: 'C' }),
      point({ version_id: 'b', version_seq: 2, score: 80, grade: 'B' }),
    ];
    render(
      <GradeSurfaceTrendPanel series={clean} loading={false} error={null} onSelectVersion={jest.fn()} />,
    );
    expect(screen.getByText(/No breaking changes recorded/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /breaking/ })).not.toBeInTheDocument();
  });

  it('shows a "not yet scored" note when no snapshot is scored, but still charts the surface size', () => {
    const unscored = [
      point({ version_id: 'a', version_seq: 1, score: null, grade: null }),
      point({ version_id: 'b', version_seq: 2, score: null, grade: null }),
    ];
    render(
      <GradeSurfaceTrendPanel series={unscored} loading={false} error={null} onSelectVersion={jest.fn()} />,
    );
    expect(screen.getByText(/No snapshot has been scored yet/i)).toBeInTheDocument();
    // The surface-size trend still renders.
    expect(screen.getByRole('img', { name: /Capability count per snapshot/ })).toBeInTheDocument();
  });
});
