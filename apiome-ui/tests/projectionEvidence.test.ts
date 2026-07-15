/**
 * projectionEvidence — evidence-page contract + integrity guards (EFP-2.1, #4813).
 *
 * Covers the guard the projection graph (EFP-2.2) and evidence drawer (EFP-2.3) run
 * before trusting a page from `POST /api/export/projection-evidence`: canonical status
 * vocabulary, canonical + required reason codes, node-reference closure, and snapshot
 * identity.
 */

import {
  evidencePageIssues,
  isKnownProjectionStatus,
  PROJECTION_STATUSES,
  type ProjectionEdge,
  type ProjectionEvidencePage,
  type ProjectionNode,
} from '../src/app/components/ade/dashboard/export/projectionEvidence';

function node(overrides: Partial<ProjectionNode>): ProjectionNode {
  return {
    id: 'canonical:User.email',
    kind: 'canonical',
    label: 'User.email',
    construct_key: 'User.email',
    canonical_kind: 'field',
    ...overrides,
  };
}

function edge(overrides: Partial<ProjectionEdge>): ProjectionEdge {
  return {
    id: 'projects:User.email#0',
    relation: 'projects',
    source: 'canonical:User.email',
    target: null,
    status: 'dropped',
    reason: 'destination_unsupported',
    severity: 'warn',
    detail: 'the destination cannot represent this field',
    ...overrides,
  };
}

function page(overrides: Partial<ProjectionEvidencePage>): ProjectionEvidencePage {
  return {
    manifest_hash: 'abc123',
    edges: [edge({})],
    nodes: [node({})],
    next_cursor: null,
    total: 1,
    ...overrides,
  };
}

describe('isKnownProjectionStatus', () => {
  it('accepts the seven canonical statuses', () => {
    expect(PROJECTION_STATUSES).toHaveLength(7);
    for (const status of PROJECTION_STATUSES) {
      expect(isKnownProjectionStatus(status)).toBe(true);
    }
  });

  it('rejects unknown statuses', () => {
    expect(isKnownProjectionStatus('vanished')).toBe(false);
    expect(isKnownProjectionStatus('')).toBe(false);
  });
});

describe('evidencePageIssues', () => {
  it('accepts a consistent page', () => {
    expect(evidencePageIssues(page({}))).toEqual([]);
  });

  it('accepts a retained edge without a reason', () => {
    const clean = page({ edges: [edge({ status: 'retained', reason: null })] });
    expect(evidencePageIssues(clean)).toEqual([]);
  });

  it('flags a missing snapshot id', () => {
    const issues = evidencePageIssues(page({ manifest_hash: '' }));
    expect(issues.some((issue) => issue.includes('manifest_hash'))).toBe(true);
  });

  it('flags an unknown status', () => {
    const issues = evidencePageIssues(
      page({ edges: [edge({ status: 'vanished' as never, reason: null })] }),
    );
    expect(issues.some((issue) => issue.includes("unknown status 'vanished'"))).toBe(true);
  });

  it('flags an unknown reason code', () => {
    const issues = evidencePageIssues(page({ edges: [edge({ reason: 'destination_broken' })] }));
    expect(issues.some((issue) => issue.includes("unknown reason code 'destination_broken'"))).toBe(
      true,
    );
  });

  it('flags a reason-required status without a reason', () => {
    for (const status of ['approximated', 'synthesized', 'dropped', 'unavailable'] as const) {
      const issues = evidencePageIssues(page({ edges: [edge({ status, reason: null })] }));
      expect(issues.some((issue) => issue.includes('missing its reason code'))).toBe(true);
    }
  });

  it('flags edges referencing nodes the page did not bundle', () => {
    const orphanSource = page({ edges: [edge({ source: 'canonical:Missing' })] });
    expect(
      evidencePageIssues(orphanSource).some((issue) => issue.includes("source node 'canonical:Missing'")),
    ).toBe(true);

    const orphanTarget = page({ edges: [edge({ target: 'target:Missing' })] });
    expect(
      evidencePageIssues(orphanTarget).some((issue) => issue.includes("target node 'target:Missing'")),
    ).toBe(true);
  });

  it('accepts a projects edge with a bundled target node', () => {
    const withTarget = page({
      nodes: [
        node({}),
        node({ id: 'target:User.email', kind: 'target', target: { json_pointer: '/x' } }),
      ],
      edges: [edge({ status: 'retained', reason: null, target: 'target:User.email' })],
    });
    expect(evidencePageIssues(withTarget)).toEqual([]);
  });

  it('flags a page carrying more edges than its claimed total', () => {
    const overfull = page({ total: 0 });
    expect(evidencePageIssues(overfull).some((issue) => issue.includes('claims a total'))).toBe(true);
  });
});
