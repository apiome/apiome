/**
 * Render/interaction tests for the MCP endpoint-detail "Insight" tab (V2-MCP-28.4 / MCAT-14.4).
 *
 * Covers the scaffold's contract: lazy data fetch (versions + surface) on mount, the never-discovered
 * empty state, a surface-fetch error state, the live baseline rendered from the 14.2 metrics, and the
 * version selector re-fetching insight for a different snapshot.
 */
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

import McpEndpointInsight from '../src/app/ade/dashboard/mcp/[endpointId]/McpEndpointInsight';

const ENDPOINT_ID = '11111111-1111-4111-8111-111111111111';
const V3 = '33333333-3333-4333-8333-333333333333';
const V2 = '22222222-2222-4222-8222-222222222222';

/** Two-snapshot version-history payload (newest first), v3 current. */
function versionsPayload() {
  return {
    success: true,
    versions: [
      {
        id: V3,
        endpoint_id: ENDPOINT_ID,
        version_seq: 3,
        version_tag: '2026-07-06',
        is_current: true,
        score: 90,
        grade: 'A',
        change_counts: { added: 1, removed: 0, modified: 0 },
      },
      {
        id: V2,
        endpoint_id: ENDPOINT_ID,
        version_seq: 2,
        version_tag: '2026-06-01',
        is_current: false,
        score: 80,
        grade: 'B',
        change_counts: { added: 2, removed: 1, modified: 0 },
      },
    ],
  };
}

/** A surface payload with the given tool count, so different snapshots render distinguishably. */
function surfacePayload(versionId: string, versionSeq: number, tools: number) {
  return {
    success: true,
    endpoint_id: ENDPOINT_ID,
    version_id: versionId,
    version_seq: versionSeq,
    version_tag: null,
    is_current: versionSeq === 3,
    metrics: {
      type_counts: {
        tools,
        resources: 2,
        resource_templates: 0,
        prompts: 1,
        total: tools + 3,
      },
      tool_complexity: [],
      output_schema_count: tools,
      annotation_coverage: {
        tool_count: tools,
        annotated_tools: tools,
        read_only_hint: tools,
        destructive_hint: 0,
        idempotent_hint: 0,
        open_world_hint: 0,
      },
      documentation_coverage: {
        item_count: tools + 3,
        described_items: tools + 3,
        titled_items: tools,
        description_pct: 100,
        title_pct: 60,
        tool_param_count: 4,
        documented_tool_params: 4,
        tool_param_description_pct: 100,
      },
      metrics_fingerprint: `fp-${versionSeq}`,
    },
  };
}

/**
 * Match the baseline headline span whose (whitespace-normalized) text is exactly
 * "<total> capabilities in this snapshot" — the number and phrase live in separate text nodes, so a
 * plain string/regex matcher can't span them.
 */
function headlineMatcher(total: number) {
  return (_content: string, el: Element | null) =>
    !!el &&
    el.tagName === 'SPAN' &&
    (el.textContent ?? '').replace(/\s+/g, ' ').trim() === `${total} capabilities in this snapshot`;
}

function jsonResponse(body: unknown, ok = true, status = 200) {
  return {
    ok,
    status,
    statusText: ok ? 'OK' : 'Error',
    json: async () => body,
  } as Response;
}

/**
 * Route the mocked `fetch` by URL so the two lazy requests (versions, then surface) resolve
 * independently regardless of call order. The `surface` handler receives the requested version id.
 */
function routeFetch(handlers: {
  versions: () => Response;
  surface: (versionId: string | null) => Response;
}) {
  (global.fetch as jest.Mock).mockImplementation(async (url: string) => {
    if (url.includes('/insight/surface')) {
      const versionId = new URL(url, 'http://test').searchParams.get('version_id');
      return handlers.surface(versionId);
    }
    if (url.includes('/versions')) {
      return handlers.versions();
    }
    throw new Error(`unexpected fetch: ${url}`);
  });
}

beforeEach(() => {
  global.fetch = jest.fn();
});

afterEach(() => {
  jest.clearAllMocks();
});

describe('McpEndpointInsight — scaffold', () => {
  it('lazy-loads versions + surface and renders the capability baseline', async () => {
    routeFetch({
      versions: () => jsonResponse(versionsPayload()),
      surface: (vid) => jsonResponse(surfacePayload(vid ?? V3, 3, 4)),
    });

    render(<McpEndpointInsight endpointId={ENDPOINT_ID} currentVersionId={V3} />);

    // Baseline headline reflects the current snapshot's total (4 tools + 2 resources + 1 prompt = 7).
    await waitFor(() =>
      expect(screen.getByText(headlineMatcher(7))).toBeInTheDocument(),
    );

    // The three section headers that later epics fill are present.
    expect(screen.getByText('Capability surface')).toBeInTheDocument();
    expect(screen.getByText('Surface evolution')).toBeInTheDocument();
    expect(screen.getByText('Reliability & trust')).toBeInTheDocument();

    // Reserved placeholder panels are laid out.
    expect(screen.getAllByText('Coming soon').length).toBeGreaterThan(0);

    // Surface was fetched for the current version by default.
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining(`/insight/surface?version_id=${V3}`),
      expect.anything(),
    );
  });

  it('shows a helpful empty state for a never-discovered endpoint', async () => {
    routeFetch({
      versions: () => jsonResponse({ success: true, versions: [] }),
      surface: () => jsonResponse({}, false, 404),
    });

    render(<McpEndpointInsight endpointId={ENDPOINT_ID} currentVersionId={null} />);

    await waitFor(() => expect(screen.getByText('No insight yet')).toBeInTheDocument());
    expect(screen.getByText(/never been discovered/i)).toBeInTheDocument();
    // No surface request when there is no snapshot to summarize.
    expect(global.fetch).not.toHaveBeenCalledWith(
      expect.stringContaining('/insight/surface'),
      expect.anything(),
    );
  });

  it('surfaces an insight-fetch error without blanking the tab', async () => {
    routeFetch({
      versions: () => jsonResponse(versionsPayload()),
      surface: () => jsonResponse({ error: 'metrics engine down' }, false, 502),
    });

    render(<McpEndpointInsight endpointId={ENDPOINT_ID} currentVersionId={V3} />);

    await waitFor(() => expect(screen.getByText('Insight unavailable')).toBeInTheDocument());
    expect(screen.getByText('metrics engine down')).toBeInTheDocument();
    // The section framework still renders around the error.
    expect(screen.getByText('Capability surface')).toBeInTheDocument();
  });

  it('re-fetches insight when the version selector changes snapshot', async () => {
    routeFetch({
      versions: () => jsonResponse(versionsPayload()),
      // v3 → 4 tools (total 7); v2 → 9 tools (total 12) so the baseline visibly changes.
      surface: (vid) =>
        vid === V2 ? jsonResponse(surfacePayload(V2, 2, 9)) : jsonResponse(surfacePayload(V3, 3, 4)),
    });

    render(<McpEndpointInsight endpointId={ENDPOINT_ID} currentVersionId={V3} />);

    await waitFor(() =>
      expect(screen.getByText(headlineMatcher(7))).toBeInTheDocument(),
    );

    const select = screen.getByLabelText('Snapshot') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: V2 } });

    // The older snapshot's larger surface (total 12) is fetched and rendered.
    await waitFor(() =>
      expect(screen.getByText(headlineMatcher(12))).toBeInTheDocument(),
    );
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining(`/insight/surface?version_id=${V2}`),
      expect.anything(),
    );
  });
});
