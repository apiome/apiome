/**
 * Render tests for the Discovery health & availability panel (V2-MCP-31.1 / MCAT-17.1).
 *
 * Covers the acceptance criteria that live in the component (the pure `mcpDiscoveryHealthTimeline`
 * projection is unit-tested in `mcp-reliability-ui.test.ts`): loading / error / no-history states;
 * the availability figure and outcome tallies; the timeline status strip and its legend; the
 * per-code failure breakdown; and the prominent quarantine banner.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { DiscoveryHealthPanel } from '../src/app/components/ui/mcp/DiscoveryHealthPanel';
import {
  mcpReliabilityHealthFromPayload,
  type McpDiscoveryHealth,
} from '../src/app/components/ade/dashboard/mcp/mcpReliabilityUi';

function job(
  jobId: string,
  state: string,
  outcome: string,
  createdAt: string,
  errorCode: string | null = null,
) {
  return {
    job_id: jobId,
    state,
    trigger: 'sweep',
    outcome,
    error_code: errorCode,
    created_at: createdAt,
    started_at: createdAt,
    finished_at: createdAt,
    duration_ms: state === 'failed' ? null : 100,
  };
}

function health(raw: Record<string, unknown>): McpDiscoveryHealth {
  return mcpReliabilityHealthFromPayload({ health: raw })!;
}

const HEALTHY = health({
  timeline: [
    job('j4', 'completed', 'ok', '2026-07-06T12:00:00Z'),
    job('j3', 'failed', 'auth_required', '2026-07-06T06:00:00Z', 'auth_required'),
    job('j2', 'completed', 'ok', '2026-07-06T00:00:00Z'),
    job('j1', 'completed', 'ok', '2026-07-05T18:00:00Z'),
  ],
  window: 50,
  last_status: 'unchanged',
  last_discovered_at: '2026-07-06T12:00:00Z',
});

describe('DiscoveryHealthPanel', () => {
  it('shows a loading state before the first payload', () => {
    render(<DiscoveryHealthPanel health={null} loading error={null} />);
    expect(screen.getByText(/Loading discovery health/i)).toBeInTheDocument();
  });

  it('shows an error state', () => {
    render(<DiscoveryHealthPanel health={null} loading={false} error="Upstream 502" />);
    expect(screen.getByText('Discovery health unavailable')).toBeInTheDocument();
    expect(screen.getByText('Upstream 502')).toBeInTheDocument();
  });

  it('shows the empty state for a never-discovered endpoint', () => {
    const empty = health({ timeline: [], window: 50 });
    render(<DiscoveryHealthPanel health={empty} loading={false} error={null} />);
    expect(screen.getByText('No discovery history yet')).toBeInTheDocument();
  });

  it('renders availability, tallies, and the failure breakdown', () => {
    render(<DiscoveryHealthPanel health={HEALTHY} loading={false} error={null} />);
    // 3 ok / (3 ok + 1 failed) = 75%
    expect(screen.getByText('75%')).toBeInTheDocument();
    expect(screen.getByText('Availability')).toBeInTheDocument();
    // The "over N completed attempts" line reflects the 4 terminal jobs.
    expect(
      screen.getByText((_, el) => /^over\s+4\s+completed attempts$/i.test((el?.textContent || '').trim())),
    ).toBeInTheDocument();
    // The failed job's code surfaces in the breakdown.
    expect(screen.getByText('Failure breakdown')).toBeInTheDocument();
    expect(screen.getByText('Auth error')).toBeInTheDocument();
    // The last-attempt footnote reflects the last status.
    expect(screen.getByText(/Last discovery/i)).toBeInTheDocument();
  });

  it('renders the timeline legend (OK / Failed) as a status strip', () => {
    render(<DiscoveryHealthPanel health={HEALTHY} loading={false} error={null} />);
    // "OK" / "Failed" appear both in the legend and the chart's tabular fallback.
    expect(screen.getAllByText('OK').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Failed').length).toBeGreaterThan(0);
  });

  it('flags a quarantined endpoint with a prominent banner', () => {
    const quarantined = health({
      timeline: [job('q1', 'failed', 'connect_error', '2026-07-06T12:00:00Z', 'connect_error')],
      window: 50,
      quarantined: true,
      quarantined_at: '2026-07-06T12:00:00Z',
      quarantine_reason: 'connect_error: connection refused',
      consecutive_failures: 5,
      last_status: 'connect_error',
      last_discovered_at: '2026-07-06T12:00:00Z',
    });
    render(<DiscoveryHealthPanel health={quarantined} loading={false} error={null} />);
    expect(screen.getByText(/Quarantined — auto-excluded/i)).toBeInTheDocument();
    expect(screen.getByText(/connection refused/)).toBeInTheDocument();
    // The consecutive-failure count is split across a span; assert on the whole line.
    expect(
      screen.getByText((_, el) => el?.tagName === 'P' && /5 consecutive failures/i.test(el.textContent || '')),
    ).toBeInTheDocument();
    // 0% availability (the one terminal job failed) with the "poor" tone.
    expect(screen.getByText('0%')).toBeInTheDocument();
  });
});
