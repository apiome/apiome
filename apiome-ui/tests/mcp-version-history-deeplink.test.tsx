/**
 * Deep-link behaviour of the MCP Versions tab (V2-MCP-30.1 / MCAT-16.1 → MCAT-10.3).
 *
 * When the churn timeline asks to open a specific snapshot's diff, the version history should — once
 * its history has loaded — select that version against its immediate predecessor (not the default
 * two-newest pair), run that compare, and clear the request so a later manual visit is not hijacked.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

import McpVersionHistory from '../src/app/ade/dashboard/mcp/[endpointId]/McpVersionHistory';

const ENDPOINT_ID = '11111111-1111-4111-8111-111111111111';
const V3 = '33333333-3333-4333-8333-333333333333';
const V2 = '22222222-2222-4222-8222-222222222222';
const V1 = '11111111-1111-4111-8111-000000000001';

/** Three snapshots, newest-first, as the history route serves them. */
function versionsPayload() {
  const base = {
    endpoint_id: ENDPOINT_ID,
    server_name: 'acme',
    server_title: null,
    server_version: '1.0.0',
    protocol_version: '2025-06-18',
  };
  return {
    success: true,
    versions: [
      { ...base, id: V3, version_seq: 3, version_tag: '2026-07-06', is_current: true, score: 90, grade: 'A', change_counts: { added: 1, removed: 0, modified: 3 } },
      { ...base, id: V2, version_seq: 2, version_tag: '2026-06-01', is_current: false, score: 80, grade: 'B', change_counts: { added: 2, removed: 1, modified: 0 } },
      { ...base, id: V1, version_seq: 1, version_tag: '2026-05-01', is_current: false, score: 70, grade: 'C', change_counts: { added: 3, removed: 0, modified: 0 } },
    ],
  };
}

/** A compare payload for a base→target pair (older→newer), with no item-level changes. */
function comparePayload(baseSeq: number, targetSeq: number) {
  return {
    success: true,
    base: { id: `v-${baseSeq}`, version_seq: baseSeq, version_tag: null, surface_fingerprint: `fp${baseSeq}` },
    target: { id: `v-${targetSeq}`, version_seq: targetSeq, version_tag: null, surface_fingerprint: `fp${targetSeq}` },
    fingerprint_changed: true,
    counts: { added: 2, removed: 1, modified: 0 },
    changes: [],
  };
}

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, statusText: ok ? 'OK' : 'Error', json: async () => body } as Response;
}

let lastCompareUrl: string | null = null;

beforeEach(() => {
  lastCompareUrl = null;
  global.fetch = jest.fn(async (url: string) => {
    if (url.includes('/versions/compare')) {
      lastCompareUrl = url;
      const params = new URL(url, 'http://test').searchParams;
      // Map the requested ids back to their sequence numbers for the header.
      const seqOf = (id: string | null) => (id === V1 ? 1 : id === V2 ? 2 : 3);
      return jsonResponse(comparePayload(seqOf(params.get('base')), seqOf(params.get('target'))));
    }
    if (url.includes('/versions')) return jsonResponse(versionsPayload());
    throw new Error(`unexpected fetch: ${url}`);
  }) as jest.Mock;
});

afterEach(() => jest.clearAllMocks());

describe('McpVersionHistory — churn-timeline deep-link', () => {
  it('opens the requested version against its predecessor and clears the request', async () => {
    const onConsumed = jest.fn();
    render(
      <McpVersionHistory
        endpointId={ENDPOINT_ID}
        requestedDiffVersionId={V2}
        onDiffRequestConsumed={onConsumed}
      />,
    );

    // The diff opens on v1 → v2 (the change v2 introduced), not the default v3 → v2 (two newest).
    // Generous timeout: the default 1s flakes under CI's coverage-instrumented full-suite run.
    await waitFor(
      () => expect(screen.getByRole('heading', { name: 'v1 → v2' })).toBeInTheDocument(),
      { timeout: 3000 },
    );
    expect(lastCompareUrl).toContain(`base=${V1}`);
    expect(lastCompareUrl).toContain(`target=${V2}`);
    // The request is consumed so a later manual visit is not forced back to this diff.
    expect(onConsumed).toHaveBeenCalledTimes(1);
  });

  it('defaults to the two newest snapshots when no diff is requested', async () => {
    render(<McpVersionHistory endpointId={ENDPOINT_ID} />);
    // Default selection is the two newest → v2 → v3.
    await waitFor(
      () => expect(screen.getByRole('heading', { name: 'v2 → v3' })).toBeInTheDocument(),
      { timeout: 3000 },
    );
  });

  it('selects the first snapshot alone when its diff is requested (no predecessor)', async () => {
    const onConsumed = jest.fn();
    render(
      <McpVersionHistory
        endpointId={ENDPOINT_ID}
        requestedDiffVersionId={V1}
        onDiffRequestConsumed={onConsumed}
      />,
    );
    // v1 has no predecessor, so it compares to itself — an "identical surface" read.
    await waitFor(() => expect(onConsumed).toHaveBeenCalledTimes(1), { timeout: 3000 });
    await waitFor(
      () => expect(screen.getByRole('heading', { name: 'v1 → v1' })).toBeInTheDocument(),
      { timeout: 3000 },
    );
  });
});
