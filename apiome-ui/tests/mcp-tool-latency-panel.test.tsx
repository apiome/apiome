/**
 * Render tests for the Tool latency & error-rate panel (V2-MCP-31.2 / MCAT-17.2).
 *
 * Covers the acceptance criteria that live in the component (the pure ranking/formatting helpers are
 * unit-tested in `mcp-reliability-ui.test.ts`): loading / error / no-data states; the error-rate
 * headline and call/tool totals; the latency distribution; the slowest (by p95) and flakiest (by
 * error rate) rankings; and that a single-call tool renders its one sample as all three percentiles
 * without crashing.
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ToolLatencyPanel } from '../src/app/components/ui/mcp/ToolLatencyPanel';
import {
  mcpToolReliabilityFromPayload,
  type McpToolReliability,
} from '../src/app/components/ade/dashboard/mcp/mcpReliabilityUi';

function tool(
  name: string,
  callCount: number,
  errorCount: number,
  latency: Partial<{ count: number; p50_ms: number; p95_ms: number; p99_ms: number }> = {},
) {
  return {
    tool_name: name,
    call_count: callCount,
    error_count: errorCount,
    success_count: callCount - errorCount,
    error_rate: 0,
    latency: {
      count: latency.count ?? callCount,
      avg_ms: null,
      min_ms: null,
      max_ms: null,
      p50_ms: latency.p50_ms ?? null,
      p95_ms: latency.p95_ms ?? null,
      p99_ms: latency.p99_ms ?? null,
    },
  };
}

function reliability(raw: Record<string, unknown>): McpToolReliability {
  return mcpToolReliabilityFromPayload({ tools: raw })!;
}

const POPULATED = reliability({
  tools: [
    tool('search', 4, 1, { p50_ms: 25, p95_ms: 40, p99_ms: 40 }),
    tool('write', 2, 2, { p50_ms: 200, p95_ms: 300, p99_ms: 300 }),
    tool('ping', 3, 0, { p50_ms: 5, p95_ms: 9, p99_ms: 9 }),
  ],
  latency_distribution: [
    { label: '0–50 ms', upper_ms: 50, count: 7 },
    { label: '250–500 ms', upper_ms: 500, count: 2 },
  ],
  window_days: 30,
});

describe('ToolLatencyPanel', () => {
  it('shows a loading state before the first payload', () => {
    render(<ToolLatencyPanel reliability={null} loading error={null} />);
    expect(screen.getByText(/Loading tool latency/i)).toBeInTheDocument();
  });

  it('shows an error state', () => {
    render(<ToolLatencyPanel reliability={null} loading={false} error="Upstream 502" />);
    expect(screen.getByText('Tool latency unavailable')).toBeInTheDocument();
    expect(screen.getByText('Upstream 502')).toBeInTheDocument();
  });

  it('shows the no-data state for a never-tested endpoint', () => {
    const empty = reliability({ tools: [], latency_distribution: [], window_days: 30 });
    render(<ToolLatencyPanel reliability={empty} loading={false} error={null} />);
    expect(screen.getByText('No tool calls yet')).toBeInTheDocument();
  });

  it('renders the error-rate headline and call/tool totals', () => {
    render(<ToolLatencyPanel reliability={POPULATED} loading={false} error={null} />);
    // 3 errored / 9 calls = 33.3%
    expect(screen.getByText('33.3%')).toBeInTheDocument();
    expect(screen.getByText('Error rate')).toBeInTheDocument();
    // The caption's numbers live in spans (excluded from a node's direct text), so match the prose.
    expect(
      screen.getByText((content) => /tool calls across tools · last 30 days/i.test(content)),
    ).toBeInTheDocument();
  });

  it('ranks the slowest tools by p95 and the flakiest by error rate', () => {
    render(<ToolLatencyPanel reliability={POPULATED} loading={false} error={null} />);
    const slowest = screen.getByText('Slowest tools').closest('div')!.parentElement!;
    const slowestList = within(slowest).getByRole('list');
    const slowestNames = within(slowestList)
      .getAllByRole('listitem')
      .map((li) => li.querySelector('.font-medium')?.textContent);
    expect(slowestNames).toEqual(['write', 'search', 'ping']);

    const flakiest = screen.getByText('Flakiest tools').closest('div')!.parentElement!;
    const flakiestList = within(flakiest).getByRole('list');
    const flakiestNames = within(flakiestList)
      .getAllByRole('listitem')
      .map((li) => li.querySelector('.font-medium')?.textContent);
    // ping (0% error) is excluded; write (100%) leads search (25%).
    expect(flakiestNames).toEqual(['write', 'search']);
  });

  it('celebrates a clean server with no flaky tools', () => {
    const clean = reliability({
      tools: [tool('search', 3, 0, { p50_ms: 10, p95_ms: 20, p99_ms: 20 })],
      latency_distribution: [{ label: '0–50 ms', upper_ms: 50, count: 3 }],
      window_days: 30,
    });
    render(<ToolLatencyPanel reliability={clean} loading={false} error={null} />);
    expect(screen.getByText('No tool has errored in this window.')).toBeInTheDocument();
  });

  it('renders a single-call tool as all three percentiles without dividing by zero', () => {
    const single = reliability({
      tools: [tool('solo', 1, 0, { p50_ms: 42, p95_ms: 42, p99_ms: 42 })],
      latency_distribution: [{ label: '0–50 ms', upper_ms: 50, count: 1 }],
      window_days: 30,
    });
    render(<ToolLatencyPanel reliability={single} loading={false} error={null} />);
    // 0% error rate, and its one sample shows up as the p50/p95/p99 value.
    expect(screen.getByText('0%')).toBeInTheDocument();
    expect(screen.getAllByText('42 ms').length).toBeGreaterThanOrEqual(3);
    expect(
      screen.getByText((content) => /tool call across tool · last 30 days/i.test(content)),
    ).toBeInTheDocument();
  });
});
