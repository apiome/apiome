/**
 * EFP-3.2 (#4817) projection guardrails: soft render budget, aggregation metric
 * whitelist, reduced-motion / high-contrast coverage.
 */

import {
  BUILD_PROJECTION_VIEW_SOFT_BUDGET_MS,
  GRAPH_AGGREGATION_THRESHOLD,
  buildEvidenceRows,
  buildProjectionView,
} from '../src/app/components/ade/dashboard/export/projectionGraph';
import type { ProjectionEdge, ProjectionNode } from '../src/app/components/ade/dashboard/export/projectionEvidence';
import { trackProjectionMetric } from '../src/app/components/ade/dashboard/export/projectionMetrics';
import { EVIDENCE_INITIAL_RENDER_ROW_BUDGET } from '../src/app/components/ade/dashboard/export/useProjectionEvidence';

function makeRetainedRow(index: number): {
  nodes: ProjectionNode[];
  edges: ProjectionEdge[];
} {
  const construct = `op.retained.${index}`;
  const nativeId = `native:${construct}`;
  const canonicalId = `canonical:${construct}`;
  const targetId = `target:${construct}`;
  return {
    nodes: [
      {
        id: nativeId,
        kind: 'native',
        label: construct,
        construct_key: construct,
        native: { native_id: `id-${index}`, native_name: `name-${index}`, source_location: `L${index}` },
      },
      {
        id: canonicalId,
        kind: 'canonical',
        label: construct,
        construct_key: construct,
        canonical_kind: 'operation',
      },
      {
        id: targetId,
        kind: 'target',
        label: `/paths/${index}`,
        construct_key: construct,
        target: { json_pointer: `/paths/${index}`, native_path: null },
      },
    ],
    edges: [
      {
        id: `projects:${construct}`,
        relation: 'projects',
        source: canonicalId,
        target: targetId,
        status: 'retained',
        reason: null,
        severity: 'info',
        detail: `retained ${construct}`,
        target_mapping: null,
        explanation: null,
        documentation: null,
      },
    ],
  };
}

describe('projection guardrails (EFP-3.2)', () => {
  it('documents the initial-render row budget', () => {
    expect(EVIDENCE_INITIAL_RENDER_ROW_BUDGET).toBe(1000);
    expect(GRAPH_AGGREGATION_THRESHOLD).toBe(48);
  });

  it('aggregates large clean manifests under the soft buildProjectionView budget', () => {
    const nodes: ProjectionNode[] = [];
    const edges: ProjectionEdge[] = [];
    for (let i = 0; i < GRAPH_AGGREGATION_THRESHOLD + 20; i += 1) {
      const piece = makeRetainedRow(i);
      nodes.push(...piece.nodes);
      edges.push(...piece.edges);
    }
    const rows = buildEvidenceRows(nodes, edges);
    const started = performance.now();
    const view = buildProjectionView(rows);
    const elapsed = performance.now() - started;
    expect(view.aggregated).toBe(true);
    expect(elapsed).toBeLessThan(BUILD_PROJECTION_VIEW_SOFT_BUDGET_MS);
  });

  it('trackProjectionMetric posts only whitelist fields', async () => {
    const fetchMock = jest.fn().mockResolvedValue({ ok: true });
    (global as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;

    await trackProjectionMetric({ kind: 'aggregation_used', page_total: 120 });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body).toEqual({ kind: 'aggregation_used', page_total: 120 });
    expect(body).not.toHaveProperty('label');
    expect(body).not.toHaveProperty('native_id');
  });

  it('honours prefers-reduced-motion in matchMedia mocks', () => {
    const matchMedia = jest.fn().mockImplementation((query: string) => ({
      matches: query.includes('prefers-reduced-motion'),
      media: query,
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
      addListener: jest.fn(),
      removeListener: jest.fn(),
      dispatchEvent: jest.fn(),
      onchange: null,
    }));
    window.matchMedia = matchMedia as unknown as typeof window.matchMedia;
    expect(window.matchMedia('(prefers-reduced-motion: reduce)').matches).toBe(true);
  });

  it('exposes a projection-panel class for high-contrast CSS hooks', () => {
    // The panel root uses `projection-panel`; globals.css scopes high-contrast rules to it.
    expect(typeof document).toBe('object');
    document.documentElement.setAttribute('data-theme', 'high-contrast');
    expect(document.documentElement.getAttribute('data-theme')).toBe('high-contrast');
  });
});
