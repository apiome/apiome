/**
 * Integration tests for McpTrustPosturePanel (CLX-3.2, #4856).
 *
 * The panel's job is to render the trust-posture report honestly. These tests assert the two
 * guarantees that honesty depends on: the "signal, not a demonstrated exploit" banner and per-
 * finding label are present, and skipped rules / uncovered OWASP risks are shown as visible gaps.
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { McpTrustPosturePanel } from '@/app/components/ade/dashboard/mcp/McpTrustPosturePanel';

const REPORT = {
  success: true,
  endpointId: 'ep',
  versionId: 'v',
  profile: 'mcp-trust-posture',
  owaspRevision: '2025',
  score: 40,
  grade: 'F',
  findings: [
    {
      id: 'f1',
      path: 'tools.read_file',
      rule: 'metadata.hidden-instruction',
      severity: 'error',
      message: 'The tool text addresses the model as an instruction.',
      origin: 'metadata',
      origin_label: 'Advertised metadata',
      owasp_ids: ['MCP01'],
      exploitability: 'static_signal',
      exploitability_label: 'Signal — not proven exploitable',
      confidence: 'high',
    },
  ],
  severity_counts: { error: 1, warning: 0, info: 0 },
  origin_counts: { metadata: 1 },
  owasp_counts: { MCP01: 1 },
  owasp_coverage: { covered: ['MCP01'], uncovered: ['MCP05'] },
  report_fingerprint: 'fp',
  evaluated_rules: ['metadata.hidden-instruction'],
  skipped_rules: ['dependency.known-vulnerability'],
  skip_reasons: { 'dependency.known-vulnerability': 'Vulnerability lookup did not run.' },
  proven_count: 0,
  gate: { passed: false, fail_on: 'error', min_score: null, require_full_coverage: false, reasons: ['1 error'] },
};

describe('McpTrustPosturePanel', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  function mockReport(report: unknown) {
    global.fetch = jest.fn(async () => ({ ok: true, json: async () => report }) as Response);
  }

  it('shows the "signal, not proven exploitable" banner and label', async () => {
    mockReport(REPORT);
    render(<McpTrustPosturePanel endpointId="ep" versionId="v" />);

    await waitFor(() => expect(screen.getByText(/signal to review/i)).toBeInTheDocument());
    // Every finding carries the explicit not-proven label.
    expect(screen.getByText('Signal — not proven exploitable')).toBeInTheDocument();
    expect(screen.getByText(/Gate failed/i)).toBeInTheDocument();
  });

  it('shows skipped rules as an unverified coverage gap, not a pass', async () => {
    mockReport(REPORT);
    render(<McpTrustPosturePanel endpointId="ep" versionId="v" />);

    await waitFor(() => expect(screen.getByText(/Not evaluated/i)).toBeInTheDocument());
    expect(screen.getByText(/dependency.known-vulnerability/)).toBeInTheDocument();
    expect(screen.getByText(/not passing/i)).toBeInTheDocument();
  });

  it('names uncovered OWASP risks so an unmentioned risk is not read as absent', async () => {
    mockReport(REPORT);
    render(<McpTrustPosturePanel endpointId="ep" versionId="v" />);

    await waitFor(() => expect(screen.getByText(/OWASP coverage/i)).toBeInTheDocument());
    expect(screen.getByText(/MCP05/)).toBeInTheDocument();
  });

  it('renders an error state when the scan cannot be loaded', async () => {
    global.fetch = jest.fn(async () => ({ ok: false, status: 500, json: async () => ({ error: 'boom' }) }) as Response);
    render(<McpTrustPosturePanel endpointId="ep" versionId="v" />);
    await waitFor(() => expect(screen.getByText(/unavailable/i)).toBeInTheDocument());
  });
});
