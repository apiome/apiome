/**
 * The MCP endpoint uptime badge — V2-MCP-27.3 / MCAT-13.3 (#3713).
 *
 * `mcpUptimeUi` parses the `/uptime` payload defensively and turns its summary into the badge's
 * status, text and tooltip; `<UptimeBadge>` fetches it and renders a status-vocabulary pill.
 */

import * as React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import {
  mcpFormatUptimePct,
  mcpUptimeBadge,
  mcpUptimeSummaryFromPayload,
} from '../src/app/components/ade/dashboard/mcp/mcpUptimeUi';
import { UptimeBadge } from '../src/app/components/ui/mcp/UptimeBadge';

const EP = '11111111-1111-4111-8111-111111111111';

function payload(summary: Record<string, unknown>) {
  return {
    success: true,
    endpoint_id: EP,
    summary: {
      status: 'up',
      window_hours: 24,
      checks: 288,
      up: 288,
      down: 0,
      uptime_pct: 100,
      latency_p50_ms: 120,
      latency_p95_ms: 410,
      last_checked_at: '2026-11-08T12:00:00Z',
      last_status: 'up',
      last_error_code: null,
      ...summary,
    },
    checks: [],
  };
}

describe('mcpUptimeSummaryFromPayload', () => {
  it('parses the summary block', () => {
    expect(mcpUptimeSummaryFromPayload(payload({}))).toEqual({
      status: 'up',
      windowHours: 24,
      checks: 288,
      up: 288,
      down: 0,
      uptimePct: 100,
      latencyP50Ms: 120,
      latencyP95Ms: 410,
      lastCheckedAt: '2026-11-08T12:00:00Z',
      lastErrorCode: null,
    });
  });

  it('returns null without a summary and reads an unknown status as unknown', () => {
    expect(mcpUptimeSummaryFromPayload(null)).toBeNull();
    expect(mcpUptimeSummaryFromPayload({ success: false })).toBeNull();
    expect(mcpUptimeSummaryFromPayload(payload({ status: 'sideways' }))?.status).toBe('unknown');
  });

  it('ignores malformed numbers', () => {
    const s = mcpUptimeSummaryFromPayload(payload({ uptime_pct: 'lots', checks: -3, up: 'x' }));
    expect(s?.uptimePct).toBeNull();
    expect(s?.checks).toBe(0);
    expect(s?.up).toBe(0);
  });
});

describe('mcpFormatUptimePct', () => {
  it('floors to one decimal so a gap never reads 100%', () => {
    expect(mcpFormatUptimePct(null)).toBe('');
    expect(mcpFormatUptimePct(100)).toBe('100%');
    expect(mcpFormatUptimePct(99.96)).toBe('99.9%');
    expect(mcpFormatUptimePct(80)).toBe('80.0%');
  });
});

describe('mcpUptimeBadge', () => {
  it('prints status, uptime and median latency', () => {
    const badge = mcpUptimeBadge(mcpUptimeSummaryFromPayload(payload({})));
    expect(badge.vocabulary).toBe('healthy');
    expect(badge.text).toBe('Up · 100% · 120 ms');
    expect(badge.title).toBe(
      '288 of 288 probes answered in the last 24 hours; median 120 ms, p95 410 ms.',
    );
  });

  it('reads degraded with its uptime', () => {
    const badge = mcpUptimeBadge(
      mcpUptimeSummaryFromPayload(payload({ status: 'degraded', uptime_pct: 97.25, up: 280, down: 8 })),
    );
    expect(badge.vocabulary).toBe('degraded');
    expect(badge.text).toBe('Degraded · 97.2% · 120 ms');
  });

  it('names the last failure when down', () => {
    const badge = mcpUptimeBadge(
      mcpUptimeSummaryFromPayload(
        payload({ status: 'down', uptime_pct: 80, latency_p50_ms: null, latency_p95_ms: null, up: 4, checks: 5, down: 1, last_error_code: 'connect_error' }),
      ),
    );
    expect(badge.vocabulary).toBe('down');
    expect(badge.text).toBe('Down · 80.0%');
    expect(badge.title).toBe(
      '4 of 5 probes answered in the last 24 hours. Last probe failed: connect_error.',
    );
  });

  it('reads unknown without a summary or without probes', () => {
    expect(mcpUptimeBadge(null)).toEqual({
      vocabulary: 'unknown',
      text: 'Uptime unknown',
      title: 'No reachability probes in the last 24 hours.',
    });
    const empty = mcpUptimeBadge(
      mcpUptimeSummaryFromPayload(payload({ status: 'unknown', checks: 0, up: 0, uptime_pct: null })),
    );
    expect(empty.text).toBe('Uptime unknown');
  });
});

describe('<UptimeBadge>', () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  function mockFetch(ok: boolean, body: unknown) {
    const fn = jest.fn(async () => ({ ok, json: async () => body }));
    global.fetch = fn as unknown as typeof fetch;
    return fn;
  }

  it('fetches the last probe and renders the summary', async () => {
    const fn = mockFetch(true, payload({ status: 'degraded', uptime_pct: 98.5 }));
    render(<UptimeBadge endpointId={EP} />);
    const badge = screen.getByTestId('mcp-uptime-badge');
    expect(badge).toHaveTextContent('Uptime unknown');
    await waitFor(() => expect(badge).toHaveTextContent('Degraded · 98.5% · 120 ms'));
    expect(badge).toHaveAttribute('data-status', 'degraded');
    expect(badge.getAttribute('title')).toContain('probes answered');
    expect(fn).toHaveBeenCalledWith(`/api/mcp/endpoints/${EP}/uptime?limit=1`, {
      credentials: 'include',
    });
  });

  it('stays unknown when the read fails', async () => {
    const fn = mockFetch(false, { success: false });
    render(<UptimeBadge endpointId={EP} />);
    await waitFor(() => expect(fn).toHaveBeenCalled());
    expect(screen.getByTestId('mcp-uptime-badge')).toHaveTextContent('Uptime unknown');
    expect(screen.getByTestId('mcp-uptime-badge')).toHaveAttribute('data-status', 'unknown');
  });
});
