/**
 * Render tests for the Composite trust profile panel (V2-MCP-31.4 / MCAT-17.4).
 *
 * Covers the acceptance criteria that live in the component (the pure projections are unit-tested in
 * `mcp-trust-ui.test.ts`): loading / error / not-enough-signal states; the overall composite headline
 * and "N of 5 signals measured" caption; that measured axes show their score while missing ones show
 * an explicit "Not measured" gap (never a zero); that each axis exposes its methodology on hover; and
 * that the heuristic-composite disclaimer is present.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { TrustProfilePanel } from '../src/app/components/ui/mcp/TrustProfilePanel';
import {
  mcpTrustProfileFromPayload,
  type McpTrustProfile,
} from '../src/app/components/ade/dashboard/mcp/mcpTrustUi';

function axis(
  key: string,
  label: string,
  value: number | null,
  available: boolean,
  detail: string,
  methodology = `How ${label} is computed.`,
) {
  return { key, label, value, available, detail, methodology };
}

function profile(axes: unknown[], extra: Record<string, unknown> = {}): McpTrustProfile {
  return mcpTrustProfileFromPayload({
    success: true,
    endpoint_id: 'ep',
    version_id: 'v1',
    auth_type: 'none',
    profile: { axes, overall: null, available_count: 0, axis_count: axes.length, ...extra },
  })!;
}

const FULL = () =>
  profile([
    axis('quality', 'Quality', 90, true, 'Grade A · 90/100'),
    axis('safety', 'Safety', 75, true, '2/2 tools annotated · anonymous'),
    axis('documentation', 'Documentation', 50, true, '100% described · 0% titled'),
    axis('stability', 'Stability', null, false, 'Not enough history'),
    axis('responsiveness', 'Responsiveness', null, false, 'Never tested'),
  ]);

describe('TrustProfilePanel', () => {
  it('shows a loading state before the first profile arrives', () => {
    render(<TrustProfilePanel profile={null} loading error={null} />);
    expect(screen.getByText(/loading trust profile/i)).toBeInTheDocument();
  });

  it('shows an error state', () => {
    render(<TrustProfilePanel profile={null} loading={false} error="boom" />);
    expect(screen.getByText('Trust profile unavailable')).toBeInTheDocument();
    expect(screen.getByText('boom')).toBeInTheDocument();
  });

  it('shows a not-enough-signal empty state when no axis is measured', () => {
    const empty = profile([
      axis('quality', 'Quality', null, false, 'Not yet scored'),
      axis('safety', 'Safety', null, false, 'No tools to assess'),
    ]);
    render(<TrustProfilePanel profile={empty} loading={false} error={null} />);
    expect(screen.getByText(/not enough signal to profile yet/i)).toBeInTheDocument();
  });

  it('renders the overall composite headline and the measured-signal count', () => {
    render(<TrustProfilePanel profile={FULL()} loading={false} error={null} />);
    // overall = mean(90, 75, 50) = 71.7 → 72; three of five axes measured.
    expect(screen.getByText('72')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText(/signals measured/i)).toBeInTheDocument();
    // The heuristic-composite disclaimer is present (not an official rating).
    expect(screen.getByText(/heuristic composite/i)).toBeInTheDocument();
  });

  it('shows each measured axis score and renders missing axes as explicit gaps, not zeros', () => {
    render(<TrustProfilePanel profile={FULL()} loading={false} error={null} />);
    // Measured axes: their basis line (labels/values also appear in the radar's sr-only table, so we
    // assert on the uniquely-panel basis text).
    expect(screen.getByText('Grade A · 90/100')).toBeInTheDocument();
    expect(screen.getByText('2/2 tools annotated · anonymous')).toBeInTheDocument();
    // The two missing axes render "Not measured" (a gap), and their basis, never a "0".
    const gaps = screen.getAllByText('Not measured');
    expect(gaps).toHaveLength(2);
    expect(screen.getByText('Never tested')).toBeInTheDocument();
    expect(screen.getByText('Not enough history')).toBeInTheDocument();
    // The gap footnote spells out that gaps are not zeros.
    expect(screen.getByText(/not scored zero/i)).toBeInTheDocument();
  });

  it('exposes each axis methodology on hover via a title attribute', () => {
    render(<TrustProfilePanel profile={FULL()} loading={false} error={null} />);
    const hint = screen.getByLabelText(/How Quality is computed/i);
    expect(hint).toHaveAttribute('title', 'How Quality is computed.');
  });

  it('renders the radar chart figure', () => {
    render(<TrustProfilePanel profile={FULL()} loading={false} error={null} />);
    // The Radar primitive renders an accessible figure titled with the overall.
    expect(screen.getByRole('img', { name: /trust profile radar/i })).toBeInTheDocument();
  });
});
