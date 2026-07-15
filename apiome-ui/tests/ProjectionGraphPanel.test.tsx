/**
 * ProjectionGraphPanel — the destination-aware projection map (EFP-2.2, #4814).
 *
 * Covers the ticket's acceptance criteria at the component level:
 *  1. The graph and the table expose identical counts, statuses, and evidence rows
 *     (they render from one shared view model).
 *  2. Keyboard-only interaction: nodes are focusable buttons; Enter selects; Escape
 *     resets the view; zoom/reset are plain buttons.
 *  3. Screen-reader labels carry source construct, status, target location, and reason.
 *  4. Colour is supplemental: every status renders a text label and symbol.
 *  5. Untrusted labels render as inert text — never as markup (no injected elements).
 *  6. Integrity failures refuse the evidence outright; fetch failures degrade quietly.
 *  7. The cursor walk pages evidence in, exposes Load more past the window budget, and
 *     warns when the evidence snapshot differs from the fidelity envelope's snapshot.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { ProjectionGraphPanel } from '../src/app/components/ade/dashboard/export/ProjectionGraphPanel';
import {
  EVIDENCE_PAGES_PER_WINDOW,
} from '../src/app/components/ade/dashboard/export/useProjectionEvidence';
import type {
  ExportProjectionEvidenceResponse,
  ProjectionEdge,
  ProjectionNode,
} from '../src/app/components/ade/dashboard/export/projectionEvidence';
import type { ProjectionManifestSummary } from '../src/app/components/ade/dashboard/export/exportFidelityPreview';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

// Mirrors the real evidence-page shape (EFP-2.1): outcome edges only; the native
// provenance node rides in `nodes` and links to its canonical node via `construct_key`.
const NODES: ProjectionNode[] = [
  { id: 'n1', kind: 'native', label: 'userEmail', construct_key: 'User.email', native: { native_id: 'n1', native_name: 'userEmail', source_location: 'schema.graphql:12' } },
  { id: 'c1', kind: 'canonical', label: 'User.email', construct_key: 'User.email', canonical_kind: 'field' },
  { id: 'c2', kind: 'canonical', label: 'User.tags', construct_key: 'User.tags', canonical_kind: 'field' },
  { id: 'c3', kind: 'canonical', label: 'Sub.onUserCreated', construct_key: 'Sub.onUserCreated', canonical_kind: 'operation' },
  { id: 'c4', kind: 'canonical', label: 'User.avatar', construct_key: 'User.avatar', canonical_kind: 'field' },
  { id: 't1', kind: 'target', label: 'email', target: { json_pointer: '/components/schemas/User/properties/email' } },
  { id: 't2', kind: 'target', label: 'tags', target: { json_pointer: '/components/schemas/User/properties/tags' } },
];

const EDGES: ProjectionEdge[] = [
  { id: 'e1', relation: 'projects', source: 'c1', target: 't1', status: 'retained', severity: 'info', detail: 'Carried faithfully.' },
  { id: 'e2', relation: 'projects', source: 'c2', target: 't2', status: 'approximated', severity: 'warn', reason: 'destination_unsupported', detail: 'List constraint approximated.', explanation: 'The uniqueness constraint becomes a description note.' },
  { id: 'e3', relation: 'projects', source: 'c3', target: null, status: 'dropped', severity: 'critical', reason: 'destination_unsupported', detail: 'Subscriptions cannot be represented.', documentation: { specification: 'OpenAPI 3.1', version: '3.1', url: 'https://spec.openapis.org/oas/v3.1.0', anchor: null, documentation_unavailable: false, note: null } },
  { id: 'e4', relation: 'projects', source: 'c4', target: null, status: 'unavailable', severity: 'info', reason: 'source_parse_limit', detail: 'The source parser did not capture this construct.' },
];

const SUMMARY: ProjectionManifestSummary = {
  manifest_hash: 'hash-aaaaaaaaaaaaaaaa',
  target: { key: 'openapi' },
  status_counts: { retained: 1, transformed: 0, approximated: 1, synthesized: 0, dropped: 1, unavailable: 1, 'not-applicable': 0 },
  reason_counts: { destination_unsupported: 2, source_parse_limit: 1 },
  total_constructs: 4,
  node_count: NODES.length,
  edge_count: EDGES.length,
  evidence_count: 4,
  is_lossless: false,
  worst_severity: 'critical',
  truncated: false,
};

function evidenceResponse(
  overrides: Partial<ExportProjectionEvidenceResponse> = {},
  page: Partial<ExportProjectionEvidenceResponse['page']> = {},
): ExportProjectionEvidenceResponse {
  return {
    artifact: 'proj-petstore',
    version: null,
    version_record_id: 'rev-1',
    version_label: '1.2.0',
    summary: SUMMARY,
    page: {
      manifest_hash: SUMMARY.manifest_hash,
      edges: EDGES,
      nodes: NODES,
      next_cursor: null,
      total: 4,
      ...page,
    },
    redacted: false,
    ...overrides,
  };
}

/** Mock fetch answering /api/export/projection-evidence with the queued responses in order. */
function mockEvidenceFetch(responses: Array<ExportProjectionEvidenceResponse | { error: string }>): jest.Mock {
  let call = 0;
  const fetchMock = jest.fn(() => {
    const response = responses[Math.min(call, responses.length - 1)];
    call += 1;
    if ('error' in response) {
      return Promise.resolve({ ok: false, json: () => Promise.resolve({ success: false, error: response.error }) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, ...response }) });
  }) as unknown as jest.Mock;
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

function renderPanel(props: Partial<React.ComponentProps<typeof ProjectionGraphPanel>> = {}) {
  return render(
    <ProjectionGraphPanel
      artifact="proj-petstore"
      version={null}
      target="openapi"
      targetLabel="OpenAPI 3.1"
      options={null}
      envelopeProjection={SUMMARY}
      enabled
      {...props}
    />,
  );
}

async function renderLoadedPanel(props: Partial<React.ComponentProps<typeof ProjectionGraphPanel>> = {}) {
  const utils = renderPanel(props);
  await waitFor(() => expect(screen.getByTestId('projection-table')).toBeInTheDocument());
  return utils;
}

afterEach(() => {
  jest.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// 1. Graph/table parity
// ---------------------------------------------------------------------------

describe('ProjectionGraphPanel — graph/table parity (EFP-2.2 AC 1)', () => {
  it('renders the graph and the table with identical entries and statuses', async () => {
    mockEvidenceFetch([evidenceResponse()]);
    const { container } = await renderLoadedPanel();

    const graphNodes = Array.from(container.querySelectorAll('[data-testid^="projection-node-"]'));
    const tableRows = Array.from(container.querySelectorAll('[data-testid^="projection-row-e"]'));
    expect(graphNodes).toHaveLength(4);
    expect(tableRows).toHaveLength(4);

    // Same entry keys in the same order on both surfaces.
    const graphKeys = graphNodes.map((el) => el.getAttribute('data-testid')?.replace('projection-node-', ''));
    const tableKeys = tableRows.map((el) => el.getAttribute('data-testid')?.replace('projection-row-', ''));
    expect(tableKeys).toEqual(graphKeys);

    // Same per-status counts on both surfaces.
    const graphStatuses = graphNodes.map((el) => el.getAttribute('data-status')).sort();
    expect(graphStatuses).toEqual(['approximated', 'dropped', 'retained', 'unavailable']);
    for (const status of ['Approximated', 'Dropped', 'Retained', 'Unavailable']) {
      expect(within(screen.getByTestId('projection-table')).getAllByText(status)).toHaveLength(1);
    }
  });

  it('shows full-manifest status count chips with text labels and symbols', async () => {
    mockEvidenceFetch([evidenceResponse()]);
    await renderLoadedPanel();
    expect(screen.getByTestId('projection-chip-retained')).toHaveTextContent('1 retained');
    expect(screen.getByTestId('projection-chip-approximated')).toHaveTextContent('1 approximated');
    expect(screen.getByTestId('projection-chip-dropped')).toHaveTextContent('1 dropped');
    expect(screen.getByTestId('projection-chip-unavailable')).toHaveTextContent('1 unavailable');
    expect(screen.queryByTestId('projection-chip-synthesized')).not.toBeInTheDocument();
  });

  it('shows the snapshot hash from the evidence summary', async () => {
    mockEvidenceFetch([evidenceResponse()]);
    await renderLoadedPanel();
    expect(screen.getByTestId('projection-snapshot')).toHaveTextContent('snapshot hash-aaaaaaa');
  });
});

// ---------------------------------------------------------------------------
// 2. Selection-to-evidence + keyboard
// ---------------------------------------------------------------------------

describe('ProjectionGraphPanel — selection and keyboard access (EFP-2.2 AC 2)', () => {
  it('selecting a table row opens the evidence detail with reason, location, and documentation', async () => {
    mockEvidenceFetch([evidenceResponse()]);
    await renderLoadedPanel();

    fireEvent.click(screen.getByTestId('projection-row-select-e3'));
    const detail = screen.getByTestId('projection-detail');
    expect(detail).toHaveTextContent('Sub.onUserCreated');
    expect(detail).toHaveTextContent('Dropped');
    expect(detail).toHaveTextContent('critical');
    expect(detail).toHaveTextContent('destination_unsupported');
    expect(detail).toHaveTextContent('Subscriptions cannot be represented.');
    const link = within(detail).getByRole('link', { name: /openapi 3\.1/i });
    expect(link).toHaveAttribute('href', 'https://spec.openapis.org/oas/v3.1.0');

    // The same selection is reflected on the graph node.
    expect(screen.getByTestId('projection-node-e3')).toHaveAttribute('aria-pressed', 'true');
  });

  it('selecting a graph node with Enter opens the same evidence as the table row', async () => {
    mockEvidenceFetch([evidenceResponse()]);
    await renderLoadedPanel();

    fireEvent.keyDown(screen.getByTestId('projection-node-e2'), { key: 'Enter' });
    const detail = screen.getByTestId('projection-detail');
    expect(detail).toHaveTextContent('User.tags');
    expect(detail).toHaveTextContent('The uniqueness constraint becomes a description note.');
    expect(detail).toHaveTextContent('/components/schemas/User/properties/tags');
  });

  it('Escape resets the view: selection cleared and zoom back to 1', async () => {
    mockEvidenceFetch([evidenceResponse()]);
    await renderLoadedPanel();

    fireEvent.click(screen.getByTestId('projection-row-select-e1'));
    expect(screen.getByTestId('projection-detail')).toBeInTheDocument();

    const svg = screen.getByTestId('projection-graph');
    const baseWidth = svg.getAttribute('width');
    fireEvent.click(screen.getByTestId('projection-zoom-in'));
    expect(svg.getAttribute('width')).not.toBe(baseWidth);

    fireEvent.keyDown(screen.getByTestId('projection-panel'), { key: 'Escape' });
    expect(screen.queryByTestId('projection-detail')).not.toBeInTheDocument();
    expect(svg.getAttribute('width')).toBe(baseWidth);
  });

  it('the reset-view button restores zoom and clears the selection', async () => {
    mockEvidenceFetch([evidenceResponse()]);
    await renderLoadedPanel();
    const svg = screen.getByTestId('projection-graph');
    const baseWidth = svg.getAttribute('width');
    fireEvent.click(screen.getByTestId('projection-zoom-out'));
    fireEvent.click(screen.getByTestId('projection-row-select-e1'));
    fireEvent.click(screen.getByTestId('projection-reset-view'));
    expect(svg.getAttribute('width')).toBe(baseWidth);
    expect(screen.queryByTestId('projection-detail')).not.toBeInTheDocument();
  });

  it('graph nodes form a roving-tabindex list navigable with arrow keys', async () => {
    mockEvidenceFetch([evidenceResponse()]);
    await renderLoadedPanel();

    const first = screen.getByTestId('projection-node-e2'); // worst-first: approximated/warn leads the target lane
    expect(first).toHaveAttribute('tabindex', '0');
    expect(screen.getByTestId('projection-node-e1')).toHaveAttribute('tabindex', '-1');

    fireEvent.keyDown(first, { key: 'ArrowDown' });
    await waitFor(() =>
      expect(screen.getByTestId('projection-node-e1')).toHaveAttribute('tabindex', '0'),
    );
    expect(first).toHaveAttribute('tabindex', '-1');
  });

  it('closing the detail card returns the panel to its unselected state', async () => {
    mockEvidenceFetch([evidenceResponse()]);
    await renderLoadedPanel();
    fireEvent.click(screen.getByTestId('projection-row-select-e1'));
    fireEvent.click(screen.getByTestId('projection-detail-close'));
    expect(screen.queryByTestId('projection-detail')).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// 3. Screen-reader labels
// ---------------------------------------------------------------------------

describe('ProjectionGraphPanel — screen-reader labels (EFP-2.2 AC 3)', () => {
  it('labels every graph node with construct, status, target location, and reason summary', async () => {
    mockEvidenceFetch([evidenceResponse()]);
    await renderLoadedPanel();

    const label = screen.getByTestId('projection-node-e2').getAttribute('aria-label') ?? '';
    expect(label).toContain('User.tags');
    expect(label).toContain('approximated');
    expect(label).toContain('lands at /components/schemas/User/properties/tags');
    expect(label).toContain('The uniqueness constraint becomes a description note.');

    const droppedLabel = screen.getByTestId('projection-node-e3').getAttribute('aria-label') ?? '';
    expect(droppedLabel).toContain('no destination location');
    expect(droppedLabel).toContain('severity critical');
  });

  it('gives the table a caption naming it the accessible equivalent of the graph', async () => {
    mockEvidenceFetch([evidenceResponse()]);
    await renderLoadedPanel();
    expect(screen.getByTestId('projection-table')).toHaveAccessibleName(/accessible equivalent of the projection graph/i);
  });
});

// ---------------------------------------------------------------------------
// 4/5. Safe rendering
// ---------------------------------------------------------------------------

describe('ProjectionGraphPanel — safe rendering of untrusted labels (EFP-2.2)', () => {
  it('renders a hostile source label as inert text, never as markup', async () => {
    const hostile = '<img src=x onerror=window.__pwned=1> "quoted" `tick`';
    const response = evidenceResponse();
    response.page = {
      ...response.page,
      nodes: [
        { id: 'c1', kind: 'canonical', label: hostile, construct_key: hostile },
        { id: 't1', kind: 'target', label: hostile, target: { json_pointer: '/x' } },
      ],
      edges: [
        { id: 'e1', relation: 'projects', source: 'c1', target: 't1', status: 'retained', severity: 'info', detail: hostile },
      ],
      total: 1,
    };
    mockEvidenceFetch([response]);
    const { container } = await renderLoadedPanel();

    // No element was injected anywhere — the label stayed a text node.
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('foreignObject')).toBeNull();
    expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
    expect(screen.getByTestId('projection-row-select-e1').textContent).toContain('<img src=x onerror=');
  });
});

// ---------------------------------------------------------------------------
// 6. Integrity refusal + degraded fetch
// ---------------------------------------------------------------------------

describe('ProjectionGraphPanel — integrity and failure handling', () => {
  it('refuses to render evidence that fails its integrity check', async () => {
    const response = evidenceResponse();
    response.page = {
      ...response.page,
      edges: [{ ...EDGES[1], status: 'exploded' as ProjectionEdge['status'] }],
      total: 1,
    };
    mockEvidenceFetch([response]);
    renderPanel();

    await waitFor(() =>
      expect(screen.getByTestId('projection-integrity-error')).toBeInTheDocument(),
    );
    expect(screen.queryByTestId('projection-table')).not.toBeInTheDocument();
    expect(screen.queryByTestId('projection-graph')).not.toBeInTheDocument();
  });

  it('degrades quietly when the evidence fetch fails', async () => {
    mockEvidenceFetch([{ error: 'boom' }]);
    renderPanel();
    await waitFor(() => expect(screen.getByTestId('projection-error')).toBeInTheDocument());
    expect(screen.getByTestId('projection-error')).toHaveTextContent(/could not be loaded/i);
    expect(screen.getByTestId('projection-error')).toHaveTextContent('boom');
  });

  it('does not fetch while disabled and renders nothing', () => {
    const fetchMock = mockEvidenceFetch([evidenceResponse()]);
    renderPanel({ enabled: false });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByTestId('projection-panel')).not.toBeInTheDocument();
  });

  it('notes when source-native evidence values were redacted', async () => {
    mockEvidenceFetch([evidenceResponse({ redacted: true })]);
    await renderLoadedPanel();
    expect(screen.getByTestId('projection-redacted')).toHaveTextContent(/redacted/i);
  });
});

// ---------------------------------------------------------------------------
// 7. Pagination + snapshot identity
// ---------------------------------------------------------------------------

describe('ProjectionGraphPanel — evidence paging and snapshot identity', () => {
  it('walks cursor pages within one window and merges the evidence', async () => {
    const pageOne = evidenceResponse({}, {
      edges: EDGES.slice(0, 3),
      nodes: NODES,
      next_cursor: 'cursor-2',
      total: 4,
    });
    const pageTwo = evidenceResponse({}, {
      edges: EDGES.slice(3),
      nodes: NODES,
      next_cursor: null,
      total: 4,
    });
    const fetchMock = mockEvidenceFetch([pageOne, pageTwo]);
    await renderLoadedPanel();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const secondInit = (fetchMock.mock.calls[1] as [unknown, { body?: string }])[1];
    const secondBody = JSON.parse(secondInit?.body ?? '{}');
    expect(secondBody.cursor).toBe('cursor-2');
    await waitFor(() =>
      expect(document.querySelectorAll('[data-testid^="projection-row-e"]')).toHaveLength(4),
    );
    expect(screen.queryByTestId('projection-load-more')).not.toBeInTheDocument();
  });

  it('stops at the window budget and continues on Load more', async () => {
    // Every page returns one edge and a next cursor, so the first window exhausts its budget.
    const pages: ExportProjectionEvidenceResponse[] = [];
    const walkSummary = { ...SUMMARY, evidence_count: EVIDENCE_PAGES_PER_WINDOW + 1 };
    for (let i = 0; i <= EVIDENCE_PAGES_PER_WINDOW; i += 1) {
      pages.push(
        evidenceResponse({ summary: walkSummary }, {
          edges: [{ ...EDGES[1], id: `page-edge-${i}`, source: 'c1', target: 't1' }],
          nodes: NODES,
          next_cursor: i < EVIDENCE_PAGES_PER_WINDOW ? `cursor-${i + 1}` : null,
          total: EVIDENCE_PAGES_PER_WINDOW + 1,
        }),
      );
    }
    const fetchMock = mockEvidenceFetch(pages);
    await renderLoadedPanel();

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(EVIDENCE_PAGES_PER_WINDOW));
    const loadMore = await screen.findByTestId('projection-load-more');
    expect(screen.getByText(new RegExp(`first ${EVIDENCE_PAGES_PER_WINDOW} of ${EVIDENCE_PAGES_PER_WINDOW + 1} evidence rows`))).toBeInTheDocument();

    fireEvent.click(loadMore);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(EVIDENCE_PAGES_PER_WINDOW + 1));
    await waitFor(() =>
      expect(screen.queryByTestId('projection-load-more')).not.toBeInTheDocument(),
    );
  });

  it('warns when the evidence snapshot differs from the fidelity envelope snapshot', async () => {
    mockEvidenceFetch([evidenceResponse()]);
    await renderLoadedPanel({
      envelopeProjection: { ...SUMMARY, manifest_hash: 'hash-bbbbbbbbbbbbbbbb' },
    });
    const warning = screen.getByTestId('projection-mismatch');
    expect(warning).toHaveTextContent('hash-aaaaaaa');
    expect(warning).toHaveTextContent('hash-bbbbbbb');
  });

  it('refuses evidence whose pages span two different snapshots', async () => {
    const pageOne = evidenceResponse({}, { edges: EDGES.slice(0, 2), next_cursor: 'cursor-2', total: 4 });
    const pageTwo = evidenceResponse({}, {
      manifest_hash: 'hash-cccccccccccccccc',
      edges: EDGES.slice(2),
      next_cursor: null,
      total: 4,
    });
    mockEvidenceFetch([pageOne, pageTwo]);
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId('projection-integrity-error')).toBeInTheDocument(),
    );
  });
});

// ---------------------------------------------------------------------------
// Aggregation in the rendered table
// ---------------------------------------------------------------------------

describe('ProjectionGraphPanel — aggregate rows stay explorable', () => {
  it('renders an aggregate row that expands to list every member construct', async () => {
    // 60 retained rows (over the 48 threshold) + one critical drop that must stay individual.
    const nodes: ProjectionNode[] = [
      { id: 'cx', kind: 'canonical', label: 'Sub.critical', construct_key: 'Sub.critical' },
    ];
    const edges: ProjectionEdge[] = [
      { id: 'ex', relation: 'projects', source: 'cx', target: null, status: 'dropped', severity: 'critical', reason: 'destination_unsupported', detail: 'Cannot represent.' },
    ];
    for (let i = 0; i < 60; i += 1) {
      nodes.push({ id: `c${i}`, kind: 'canonical', label: `Type.f${String(i).padStart(2, '0')}`, construct_key: `Type.f${i}` });
      nodes.push({ id: `t${i}`, kind: 'target', label: `f${i}`, target: { json_pointer: `/t/${i}` } });
      edges.push({ id: `e${i}`, relation: 'projects', source: `c${i}`, target: `t${i}`, status: 'retained', severity: 'info', detail: 'Carried faithfully.' });
    }
    const summary: ProjectionManifestSummary = {
      ...SUMMARY,
      status_counts: { ...SUMMARY.status_counts, retained: 60, approximated: 0, unavailable: 0, dropped: 1 },
      evidence_count: 61,
    };
    mockEvidenceFetch([evidenceResponse({ summary }, { nodes, edges, total: 61 })]);
    await renderLoadedPanel();

    expect(screen.getByTestId('projection-aggregated-note')).toBeInTheDocument();
    // The critical drop is individually present.
    expect(screen.getByTestId('projection-row-ex')).toBeInTheDocument();

    const toggle = screen.getByTestId('projection-aggregate-toggle-retained');
    expect(toggle).toHaveTextContent('60 constructs retained (aggregated)');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('Type.f00')).toBeInTheDocument();
    expect(screen.getByText('Type.f59')).toBeInTheDocument();
  });
});
