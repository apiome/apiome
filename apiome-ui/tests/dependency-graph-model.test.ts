/**
 * The dependency graph's pure rules — CDG-3.4 (#5969).
 *
 * `lib/graph` (links, grouping, pointers, truncation notices, evidence rows) and the bounded SVG
 * layout (`graphLayoutModel`): centre in the middle, incoming left, outgoing right, expansions one
 * column further out, at most ten a column with the rest counted, never a node twice.
 */

import { describe, expect, it } from '@jest/globals';
import {
  evidenceItem,
  graphNodeHref,
  graphPageHref,
  groupEdges,
  lastSeenLabel,
  mergeEdges,
  neighbourOf,
  nodeDisplayName,
  operationPointer,
  parseEntityParam,
  schemaPointer,
  truncationNotice,
  type GraphEdge,
} from '@lib/graph';
import {
  MAX_NODES_PER_COLUMN,
  caption,
  graphAriaLabel,
  graphLayout,
} from '@/app/components/ade/graph/graphLayoutModel';

const CENTRE = '11111111-1111-4111-8111-111111111111';

function id(n: number): string {
  return `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
}

export function edge(over: Partial<GraphEdge> & { n: number }): GraphEdge {
  const { n, ...rest } = over;
  return {
    id: `e${n}`,
    from_kind: 'consumer',
    from_id: id(n),
    to_kind: 'project',
    to_id: CENTRE,
    edge_kind: 'consumes',
    pointer: null,
    provenance: 'derived',
    source_ref: `consumer_contract:${n}`,
    evidence: {},
    first_seen_at: null,
    last_seen_at: '2026-10-03T10:00:00Z',
    stale_since: null,
    stale: false,
    from_label: { name: `Consumer ${n}`, slug: `c${n}`, owner: null },
    to_label: { name: 'Petstore', slug: 'petstore', owner: null },
    ...rest,
  };
}

describe('links', () => {
  it('sends every node somewhere: its page, else the graph page centred on it', () => {
    expect(graphNodeHref('project', CENTRE)).toBe(`/ade/dashboard/versions?projectId=${CENTRE}`);
    expect(graphNodeHref('catalog_item', CENTRE)).toBe(`/ade/dashboard/catalog/${CENTRE}`);
    expect(graphNodeHref('mcp_endpoint', CENTRE)).toBe(`/ade/dashboard/mcp/${CENTRE}`);
    expect(graphNodeHref('repository', CENTRE)).toBe(`/ade/dashboard/repositories/${CENTRE}`);
    expect(graphNodeHref('consumer', CENTRE)).toBe(graphPageHref('consumer', CENTRE));
    expect(graphPageHref('identity_group', CENTRE)).toBe(
      `/ade/dashboard/graph?entity=${encodeURIComponent(`identity_group:${CENTRE}`)}`
    );
  });

  it('parses ?entity= strictly', () => {
    expect(parseEntityParam(`consumer:${CENTRE}`)).toEqual({ kind: 'consumer', id: CENTRE });
    expect(parseEntityParam('galaxy:x')).toBeNull();
    expect(parseEntityParam(`project:../x`)).toBeNull();
    expect(parseEntityParam(null)).toBeNull();
  });

  it('names a node by name, slug, else kind and short id', () => {
    expect(nodeDisplayName('project', CENTRE, { name: 'Petstore', slug: 'petstore' })).toBe('Petstore');
    expect(nodeDisplayName('project', CENTRE, { name: null, slug: 'petstore' })).toBe('petstore');
    expect(nodeDisplayName('consumer', CENTRE, null)).toBe('Consumer 11111111');
  });
});

describe('grouping', () => {
  it('groups by direction then edge kind, current before stale', () => {
    const edges = [
      edge({ n: 1, stale: true, stale_since: '2026-10-05T00:00:00Z' }),
      edge({ n: 2 }),
      edge({ n: 3, from_kind: 'project', from_id: CENTRE, to_kind: 'project', to_id: id(9), edge_kind: 'depends_on',
             provenance: 'declared', from_label: null, to_label: { name: 'Payments', slug: 'payments', owner: null } }),
    ];
    const groups = groupEdges(edges, CENTRE);
    expect(groups.map((g) => [g.key, g.title, g.neighbours.length, g.staleCount])).toEqual([
      ['out:depends_on', 'Depends on', 1, 0],
      ['in:consumes', 'Consumed by', 2, 1],
    ]);
    expect(groups[1].neighbours.map((n) => n.edge.id)).toEqual(['e2', 'e1']);
    expect(neighbourOf(edges[2], CENTRE)).toMatchObject({ direction: 'out', id: id(9) });
  });

  it('merges pages without duplicates', () => {
    expect(mergeEdges([edge({ n: 1 }), edge({ n: 2 })], [edge({ n: 2 })]).map((e) => e.id)).toEqual(['e1', 'e2']);
  });

  it('says when a stale edge was last seen', () => {
    expect(lastSeenLabel('2026-10-03T10:00:00Z')).toBe('Last seen 3 Oct 2026');
    expect(lastSeenLabel(null)).toBe('Last seen: unknown');
  });
});

describe('pointers and notices', () => {
  it('turns an operation or a schema into a pointer', () => {
    expect(operationPointer('GET /pets/{id}')).toBe('/paths/~1pets~1{id}/get');
    expect(operationPointer('post  /a/b')).toBe('/paths/~1a~1b/post');
    expect(operationPointer('FETCH /pets')).toBeNull();
    expect(operationPointer('GET pets')).toBeNull();
    expect(schemaPointer('Pet')).toBe('/components/schemas/Pet');
    expect(schemaPointer('a/b~c')).toBe('/components/schemas/a~1b~0c');
    expect(schemaPointer('  ')).toBeNull();
  });

  it('says "Showing 2,000 of N" only when cut short', () => {
    expect(truncationNotice(10, 10, false)).toBeNull();
    expect(truncationNotice(2000, 2431, true)).toBe('Showing 2,000 of 2,431. Narrow it down to see the rest.');
    expect(truncationNotice(2000, 2431, true, { atLeast: true })).toContain('of at least 2,431');
    expect(truncationNotice(40, null, true)).toContain('Showing the first 40');
  });

  it('reads every evidence section with a link where one exists', () => {
    expect(evidenceItem('verification_runs', { run_id: 'r1', target: 'staging', outcome: 'passed',
                                               operations: ['GET /pets/{id}'] }, CENTRE)).toEqual({
      key: 'r1', title: 'staging · passed', detail: 'GET /pets/{id}',
      href: `/ade/dashboard/versions?projectId=${CENTRE}`,
    });
    expect(evidenceItem('consumer_contracts', { contract_id: 'k', consumer_id: CENTRE, revision: 2 }, CENTRE).href)
      .toBe(graphPageHref('consumer', CENTRE));
    expect(evidenceItem('deploy_gate_evaluations', { id: 'g', purpose: 'deploy', passed: false }, CENTRE).title)
      .toBe('Deploy gate · failed');
    expect(evidenceItem('sdk_regen_targets', { id: 's', ecosystem: 'npm', delivery_mode: 'registry' }, CENTRE).href)
      .toBe('/ade/dashboard/export/studio?tab=sdk');
    expect(evidenceItem('agent_toolset_tools', { id: 't', tool_name: 'get_pet', operation_key: 'GET /p' }, CENTRE))
      .toMatchObject({ title: 'get_pet', detail: 'GET /p' });
    expect(evidenceItem('mock_fixture_packs', { kind: 'scenario', name: 'slow', operations: ['GET /p'] }, CENTRE))
      .toMatchObject({ title: 'Scenario slow', detail: 'GET /p' });
    expect(evidenceItem('sunset_consumers', { contract_id: 'k', consumer_slug: 'batch', version_label: '0.9.0' }, null))
      .toMatchObject({ title: 'batch on 0.9.0', detail: 'Deprecated', href: '/ade/dashboard/versions/sunset-timeline' });
  });
});

describe('the layout', () => {
  const centre = { kind: 'project' as const, id: CENTRE, label: { name: 'Petstore', slug: 'petstore', owner: null } };

  it('puts what depends on the entity left and what it depends on right', () => {
    const neighbours = [
      neighbourOf(edge({ n: 1 }), CENTRE),
      neighbourOf(edge({ n: 2, from_kind: 'project', from_id: CENTRE, to_kind: 'repository', to_id: id(2),
                         edge_kind: 'served_by', to_label: { name: 'acme/pets', slug: null, owner: null } }), CENTRE),
    ];
    const layout = graphLayout({ centre, neighbours });
    const byColumn = Object.fromEntries(layout.nodes.map((n) => [n.column, n]));
    expect(byColumn[0].name).toBe('Petstore');
    expect(byColumn[-1].ariaLabel).toBe('Consumer Consumer 1: Consumer 1 consumes Petstore');
    expect(byColumn[1].ariaLabel).toBe('Repository acme/pets: Petstore served by acme/pets');
    expect(byColumn[-1].x).toBeLessThan(byColumn[0].x);
    expect(byColumn[1].x).toBeGreaterThan(byColumn[0].x);
    expect(layout.links).toHaveLength(2);
    expect(graphAriaLabel(layout)).toBe('Dependency graph of Petstore: 1 depend on it, it depends on 1');
  });

  it('draws at most ten a column and counts the rest', () => {
    const neighbours = Array.from({ length: 14 }, (_, i) => neighbourOf(edge({ n: i + 1 }), CENTRE));
    const layout = graphLayout({ centre, neighbours });
    expect(layout.nodes.filter((n) => n.column === -1)).toHaveLength(MAX_NODES_PER_COLUMN);
    expect(layout.overflow).toEqual([expect.objectContaining({ column: -1, hidden: 4 })]);
    expect(layout.hiddenCount).toBe(4);
    expect(graphAriaLabel(layout)).toContain('4 more not drawn');
  });

  it('draws one node for two edges to the same neighbour, and marks it stale only if all are', () => {
    const neighbours = [
      neighbourOf(edge({ n: 1, id: 'a', pointer: '/paths/~1a/get', stale: true }), CENTRE),
      neighbourOf(edge({ n: 1, id: 'b', pointer: '/paths/~1b/get' }), CENTRE),
    ];
    const layout = graphLayout({ centre, neighbours });
    const left = layout.nodes.filter((n) => n.column === -1);
    expect(left).toHaveLength(1);
    expect(left[0].stale).toBe(false);
    expect(layout.links).toHaveLength(2);
  });

  it('expands a neighbour outward, never back to the centre or a drawn node', () => {
    const web = neighbourOf(edge({ n: 1 }), CENTRE);
    const reporting = neighbourOf(
      edge({ n: 5, to_kind: 'consumer', to_id: id(1), edge_kind: 'depends_on', provenance: 'declared',
             from_label: { name: 'Reporting', slug: 'reporting', owner: null } }),
      id(1)
    );
    const backToCentre = neighbourOf(
      edge({ n: 6, from_kind: 'consumer', from_id: id(1), to_kind: 'project', to_id: CENTRE }),
      id(1)
    );
    const layout = graphLayout({ centre, neighbours: [web], expanded: new Map([[id(1), [reporting, backToCentre]]]) });
    const outer = layout.nodes.filter((n) => n.column === -2);
    expect(outer.map((n) => n.name)).toEqual(['Reporting']);
    expect(outer[0].ariaLabel).toBe('Consumer Reporting: Reporting depends on Consumer 1');
    expect(outer[0].expandable).toBe(false);
    expect(layout.nodes.find((n) => n.id === id(1))!.expanded).toBe(true);
  });

  it('cuts long captions', () => {
    expect(caption('a'.repeat(40))).toHaveLength(22);
    expect(caption('short')).toBe('short');
  });
});
