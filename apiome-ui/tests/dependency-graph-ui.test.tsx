/**
 * The dependency graph UI — CDG-3.4 (#5969).
 *
 * * **Dependencies panel**: loads only when its tab is active; groups in/out edges by kind with
 *   provenance and owner badges; stale edges are dimmed, labelled and show when they were last
 *   seen; the drawing's nodes are links and a node expands to draw its own neighbours; a truncated
 *   read says so; axe passes.
 * * **Blast radius drawer**: turns an operation into a pointer, lists direct and transitive
 *   entities and every evidence section with links; an empty answer is said in words; a truncated
 *   answer says "Showing 2,000 of at least N"; bad input is refused before any call; axe passes.
 * * **Graph page**: searches and filters through the BFF, says "Showing 2,000 of N" when cut
 *   short, opens an entity's panel from `?entity=`; axe passes.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures (`dependency-graph`,
 * `dependencies-tab`, `blast-radius`) and the browser suite's `dependency-graph-truncated`.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const replace = jest.fn();
let search = new URLSearchParams();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace, push: jest.fn() }),
  usePathname: () => '/ade/dashboard/graph',
  useSearchParams: () => search,
}));

import { DependenciesPanel } from '../src/app/components/ade/graph/DependenciesPanel';
import { BlastRadiusDrawer } from '../src/app/components/ade/graph/BlastRadiusDrawer';
import GraphClient from '../src/app/ade/dashboard/graph/GraphClient';
import type { BlastRadiusAnswer, GraphEdge, GraphEntity } from '../lib/graph';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const PROJECT = '11111111-1111-4111-8111-111111111111';
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const OWNER = { slug: 'payments', name: 'Payments', status: 'confirmed' };

function edge(n: number, over: Partial<GraphEdge> = {}): GraphEdge {
  return {
    id: `e${n}`,
    from_kind: 'consumer',
    from_id: id(n),
    to_kind: 'project',
    to_id: PROJECT,
    edge_kind: 'consumes',
    pointer: '/paths/~1pets~1{petId}/get',
    provenance: 'derived',
    source_ref: `consumer_contract:${n}`,
    evidence: {},
    first_seen_at: '2026-09-01T00:00:00Z',
    last_seen_at: '2026-10-17T00:00:00Z',
    stale_since: null,
    stale: false,
    from_label: { name: ['Web', 'Mobile', 'Batch'][n - 1] ?? `Consumer ${n}`, slug: `c${n}`, owner: n === 1 ? OWNER : null },
    to_label: { name: 'Petstore', slug: 'petstore', owner: OWNER },
    ...over,
  };
}

const INCOMING: GraphEdge[] = [
  edge(1),
  edge(2),
  edge(3, { stale: true, stale_since: '2026-10-05T00:00:00Z', last_seen_at: '2026-10-03T10:00:00Z' }),
];
const OUTGOING: GraphEdge[] = [
  edge(7, {
    from_kind: 'project', from_id: PROJECT, to_kind: 'repository', to_id: id(7), edge_kind: 'served_by',
    pointer: null, source_ref: 'binding:7',
    from_label: { name: 'Petstore', slug: 'petstore', owner: OWNER },
    to_label: { name: 'acme/petstore', slug: null, owner: null },
  }),
  edge(8, {
    from_kind: 'project', from_id: PROJECT, to_kind: 'project', to_id: id(8), edge_kind: 'depends_on',
    pointer: null, provenance: 'declared', source_ref: 'spec',
    from_label: { name: 'Petstore', slug: 'petstore', owner: OWNER },
    to_label: { name: 'Payments API', slug: 'payments', owner: OWNER },
  }),
];
const WEB_DEPENDENTS: GraphEdge[] = [
  edge(5, {
    to_kind: 'consumer', to_id: id(1), edge_kind: 'depends_on', provenance: 'declared', pointer: null,
    source_ref: 'manual', from_label: { name: 'Reporting', slug: 'reporting', owner: null },
    to_label: { name: 'Web', slug: 'c1', owner: OWNER },
  }),
];

function answer(over: Partial<BlastRadiusAnswer> = {}): BlastRadiusAnswer {
  const affected = (n: number, depth: number, name: string, extra = {}) => ({
    kind: 'consumer' as const, id: id(n), name, slug: name.toLowerCase(), depth, edge_kind: 'consumes' as const,
    provenance: 'derived' as const, pointers: ['/paths/~1pets~1{id}/get'], path: [], owner: n === 1 ? OWNER : null,
    ...extra,
  });
  return {
    entity: { kind: 'project', id: PROJECT, name: 'Petstore', slug: 'petstore', owner: OWNER },
    version: { id: 'v1', label: '1.0.0', published: true },
    pointers: ['/paths/~1pets~1{id}/get'],
    operations: ['GET /pets/{id}'],
    depth: 3,
    provenance: ['declared', 'derived', 'runtime'],
    direct: [affected(1, 1, 'Web'), affected(2, 1, 'Mobile'), affected(3, 1, 'Batch')],
    transitive: [affected(5, 2, 'Reporting', { edge_kind: 'depends_on', provenance: 'declared' })],
    invalidated_evidence: {
      verification_runs: [
        { run_id: 'r1', target: 'staging-a', outcome: 'passed', operations: ['GET /pets/{id}'] },
        { run_id: 'r2', target: 'prod-b', outcome: 'passed', operations: ['GET /pets/{petId}'] },
      ],
      consumer_contracts: [{ contract_id: 'k1', consumer_id: id(1), revision: 1, matched_pointers: ['/paths/~1pets~1{id}/get'] }],
      deploy_gate_evaluations: [{ id: 'g1', purpose: 'deploy', passed: true, evaluated_at: '2026-10-10T10:00:00Z' }],
      sdk_regen_targets: [{ id: 's1', ecosystem: 'npm', delivery_mode: 'registry' }],
      agent_toolset_tools: [{ id: 't1', tool_name: 'get_pet', operation_key: 'GET /pets/{petId}' }],
      mock_fixture_packs: [{ kind: 'fixture_pack', name: 'pets', collections: ['/pets'] }],
      sunset_consumers: [{ contract_id: 'k3', consumer_slug: 'batch', consumer_name: 'Batch', version_label: '0.9.0' }],
    },
    evidence_checked: true,
    truncated: false,
    node_count: 4,
    total_found: 4,
    warnings: [],
    ...over,
  };
}

const ENTITIES: GraphEntity[] = [
  { kind: 'project', id: PROJECT, name: 'Petstore', slug: 'petstore', owner: OWNER, in_count: 3, out_count: 2, stale_count: 1 },
  { kind: 'consumer', id: id(1), name: 'Web', slug: 'c1', owner: OWNER, in_count: 1, out_count: 1, stale_count: 0 },
  { kind: 'repository', id: id(7), name: 'acme/petstore', slug: null, owner: null, in_count: 1, out_count: 0, stale_count: 0 },
];

let calls: Array<{ url: string; body?: unknown }> = [];

/** A fetch answer: jsdom has no `Response`, so the shape the client reads is built by hand. */
function res(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as unknown as Response;
}
let entityPage: Record<string, unknown> = { entities: ENTITIES, total: 3, truncated: false, limit: 2000, offset: 0 };
let blastAnswer: BlastRadiusAnswer = answer();

beforeEach(() => {
  calls = [];
  search = new URLSearchParams();
  entityPage = { entities: ENTITIES, total: 3, truncated: false, limit: 2000, offset: 0 };
  blastAnswer = answer();
  replace.mockReset();
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const ok = (body: unknown) => res(body);
    if (url.startsWith('/api/teams')) return ok({ teams: [{ id: 't', slug: 'payments', name: 'Payments' }] });
    if (url.startsWith('/api/graph/entities')) return ok(entityPage);
    if (url.startsWith('/api/graph/blast-radius')) return ok(blastAnswer);
    if (url.startsWith(`/api/graph/edges/consumer/${id(1)}`)) {
      return ok({ edges: WEB_DEPENDENTS, total: 1, truncated: false, limit: 500, offset: 0 });
    }
    if (url.startsWith('/api/graph/edges/')) {
      const incoming = url.includes('direction=in');
      return ok({ edges: incoming ? INCOMING : OUTGOING, total: incoming ? 3 : 2, truncated: false, limit: 500, offset: 0 });
    }
    return res({}, 404);
  }) as unknown as typeof fetch;
});

async function renderPanel(active = true) {
  const view = render(
    <DependenciesPanel kind="project" id={PROJECT} active={active} label={{ name: 'Petstore', slug: 'petstore', owner: null }} />
  );
  if (active) await screen.findByTestId('dependency-edge-e1');
  return view;
}

describe('the Dependencies panel', () => {
  it('loads nothing until its tab is active', async () => {
    const { rerender } = render(<DependenciesPanel kind="project" id={PROJECT} active={false} />);
    expect(calls).toHaveLength(0);
    rerender(<DependenciesPanel kind="project" id={PROJECT} active />);
    await screen.findByTestId('dependency-edge-e1');
    expect(calls.map((c) => c.url).sort()).toEqual([
      `/api/graph/edges/project/${PROJECT}?direction=in&limit=500`,
      `/api/graph/edges/project/${PROJECT}?direction=out&limit=500`,
    ]);
  });

  it('groups edges by direction and kind, with provenance, owners and stale edges dimmed', async () => {
    await renderPanel();
    const groups = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(groups).toEqual(['Depends on1', 'Served by1', 'Consumed by31 stale']);
    const web = screen.getByTestId('dependency-edge-e1');
    expect(within(web).getByRole('link', { name: 'Web' })).toHaveAttribute(
      'href',
      `/ade/dashboard/graph?entity=${encodeURIComponent(`consumer:${id(1)}`)}`
    );
    expect(within(web).getByText('Derived')).toBeInTheDocument();
    expect(within(web).getByRole('link', { name: 'Payments' })).toHaveAttribute('href', '/ade/dashboard/teams/payments');
    const stale = screen.getByTestId('dependency-edge-e3');
    expect(stale).toHaveAttribute('data-stale');
    expect(within(stale).getByText('Stale')).toBeInTheDocument();
    expect(within(stale).getByText('Last seen 3 Oct 2026')).toBeInTheDocument();
    expect(within(screen.getByTestId('dependency-edge-e8')).getByText('Declared')).toBeInTheDocument();
  });

  it('draws every node as a link and expands a node to its own dependents', async () => {
    await renderPanel();
    const plot = screen.getByTestId('dependency-graph-plot');
    expect(within(plot).getByRole('group')).toHaveAccessibleName(
      'Dependency graph of Petstore: 3 depend on it, it depends on 2'
    );
    expect(within(plot).getByRole('link', { name: 'Consumer Batch: Batch consumes Petstore (stale)' })).toBeInTheDocument();
    const expand = screen.getByTestId(`graph-expand-${id(1)}`);
    expect(expand).toHaveAttribute('aria-pressed', 'false');
    await act(async () => {
      fireEvent.keyDown(expand, { key: 'Enter' });
    });
    await waitFor(() => expect(screen.getByTestId(`graph-node-${id(5)}`)).toBeInTheDocument());
    expect(calls.some((c) => c.url === `/api/graph/edges/consumer/${id(1)}?direction=in&limit=500`)).toBe(true);
    expect(screen.getByTestId(`graph-expand-${id(1)}`)).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByTestId(`graph-expand-${id(1)}`));
    expect(screen.queryByTestId(`graph-node-${id(5)}`)).not.toBeInTheDocument();
  });

  it('says when a read was cut short', async () => {
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const incoming = String(input).includes('direction=in');
      return res({ edges: incoming ? INCOMING : [], total: incoming ? 812 : 0, truncated: incoming, limit: 500, offset: 0 });
    }) as unknown as typeof fetch;
    await renderPanel();
    expect(screen.getByTestId('dependencies-truncated')).toHaveTextContent('Showing 3 of 812.');
  });

  it('says so when nothing depends on the entity', async () => {
    global.fetch = jest.fn(async () => res({ edges: [], total: 0, truncated: false, limit: 500, offset: 0 })) as unknown as typeof fetch;
    render(<DependenciesPanel kind="mcp_endpoint" id={PROJECT} active />);
    expect(await screen.findByText('Nothing depends on this yet')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Blast radius/ })).not.toBeInTheDocument();
  });

  it('passes axe and dumps the docs fixture', async () => {
    const { container } = await renderPanel();
    expect(await axe(container)).toHaveNoViolations();
    writeA11yFixture('dependencies-tab', container.innerHTML);
  });
});

describe('the Blast radius drawer', () => {
  async function openDrawer() {
    render(<BlastRadiusDrawer open onOpenChange={() => undefined} entity={{ kind: 'project', id: PROJECT, name: 'Petstore' }} />);
    return screen.findByTestId('blast-radius-drawer');
  }

  async function ask(operation = 'GET /pets/{id}') {
    fireEvent.change(screen.getByTestId('blast-radius-value'), { target: { value: operation } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('blast-radius-run'));
    });
    return screen.findByTestId('blast-radius-answer');
  }

  it('asks for the operation as a pointer and lists who is affected and what is invalidated', async () => {
    await openDrawer();
    fireEvent.change(screen.getByTestId('blast-radius-depth'), { target: { value: '2' } });
    const result = await ask();
    expect(calls.at(-1)).toEqual({
      url: '/api/graph/blast-radius',
      body: { entity: { kind: 'project', id: PROJECT }, pointers: ['/paths/~1pets~1{id}/get'], depth: 2,
              provenance: ['declared', 'derived', 'runtime'] },
    });
    expect(within(result).getByRole('status')).toHaveTextContent('4 affected · 8 pieces of evidence invalidated · version 1.0.0');
    expect(within(screen.getByTestId('blast-radius-direct')).getAllByRole('listitem')).toHaveLength(3);
    expect(within(screen.getByTestId('blast-radius-transitive')).getByRole('link', { name: 'Reporting' })).toBeInTheDocument();
    const runs = screen.getByTestId('blast-evidence-verification_runs');
    expect(within(runs).getAllByRole('link').map((a) => a.textContent)).toEqual(['staging-a · passed', 'prod-b · passed']);
    expect(within(screen.getByTestId('blast-evidence-agent_toolset_tools')).getByText('get_pet')).toBeInTheDocument();
  });

  it('says an empty answer in words', async () => {
    blastAnswer = answer({
      direct: [], transitive: [], node_count: 0, total_found: 0,
      invalidated_evidence: Object.fromEntries(
        Object.keys(answer().invalidated_evidence).map((key) => [key, []])
      ) as BlastRadiusAnswer['invalidated_evidence'],
    });
    await openDrawer();
    const result = await ask('GET /nobody');
    expect(within(result).getByRole('status')).toHaveTextContent('Nothing depends on this change, and no evidence is invalidated.');
  });

  it('says how much a truncated answer shows', async () => {
    blastAnswer = answer({ truncated: true, node_count: 2000, total_found: 2431 });
    await openDrawer();
    await ask();
    expect(screen.getByTestId('blast-radius-truncated')).toHaveTextContent('Showing 2,000 of at least 2,431.');
  });

  it('refuses a malformed operation before any call', async () => {
    await openDrawer();
    fireEvent.change(screen.getByTestId('blast-radius-value'), { target: { value: 'pets' } });
    fireEvent.click(screen.getByTestId('blast-radius-run'));
    expect(await screen.findByRole('alert')).toHaveTextContent('METHOD /path');
    expect(calls.some((c) => c.url === '/api/graph/blast-radius')).toBe(false);
  });

  it('passes axe and dumps the docs fixture', async () => {
    const drawer = await openDrawer();
    await ask();
    expect(await axe(document.body)).toHaveNoViolations();
    // `liveMarkup` keeps the depth select's value, which `outerHTML` drops.
    writeA11yFixture('blast-radius', liveMarkup(drawer));
  });
});

describe('the graph page', () => {
  it('lists the connected entities and filters through the BFF', async () => {
    render(<GraphClient />);
    const table = await screen.findByTestId('graph-entities');
    expect(within(table).getAllByRole('row')).toHaveLength(4);
    expect(within(table).getByRole('link', { name: 'Petstore' })).toHaveAttribute(
      'href',
      `/ade/dashboard/versions?projectId=${PROJECT}`
    );
    fireEvent.click(screen.getByTestId('graph-kind-consumer'));
    fireEvent.click(screen.getByTestId('graph-provenance-declared'));
    fireEvent.change(screen.getByTestId('graph-search'), { target: { value: 'pet' } });
    await waitFor(() =>
      expect(calls.at(-1)?.url).toBe('/api/graph/entities?q=pet&kind=consumer&provenance=declared&limit=2000')
    );
  });

  it('says "Showing 2,000 of N" when the search is cut short', async () => {
    entityPage = { entities: ENTITIES, total: 2431, truncated: true, limit: 2000, offset: 0 };
    const { container } = render(<GraphClient />);
    expect(await screen.findByTestId('graph-truncated')).toHaveTextContent('Showing 3 of 2,431.');
    // For the browser suite (`e2e/hive-dependency-graph.spec.ts`).
    writeA11yFixture('dependency-graph-truncated', (container.querySelector('.page') ?? container.firstElementChild)!.outerHTML);
  });

  it('opens an entity from ?entity= and from its Show button', async () => {
    search = new URLSearchParams({ entity: `project:${PROJECT}` });
    render(<GraphClient />);
    expect(await screen.findByTestId('dependencies-panel')).toBeInTheDocument();
    fireEvent.click(await screen.findByTestId(`graph-show-${id(1)}`));
    expect(replace).toHaveBeenCalledWith(
      `/ade/dashboard/graph?entity=${encodeURIComponent(`consumer:${id(1)}`)}`,
      { scroll: false }
    );
  });

  it('passes axe and dumps the docs fixture', async () => {
    search = new URLSearchParams({ entity: `project:${PROJECT}` });
    const { container } = render(<GraphClient />);
    await screen.findByTestId('dependency-edge-e1');
    expect(await axe(container)).toHaveNoViolations();
    writeA11yFixture('dependency-graph', (container.querySelector('.page') ?? container.firstElementChild)!.outerHTML);
  });
});
