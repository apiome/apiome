/**
 * Catalog facts on entity pages — CDG-5.4 (#5982).
 *
 * * **Checklist**: each fact with its status as an icon *and* a word, its value, detail and evidence
 *   links; `not_assessed` and `not_applicable` read as such; no score, grade or percentage anywhere.
 * * **Loading**: reads only when shown; a failed read offers a retry; a kind with no facts says so.
 * * **Rules**: the proxy path accepts only a kind key and a UUID.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `entity-facts` (a catalog item) and
 * `scorecard-kind` (an MCP server).
 */

import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
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

import { CatalogFactsPanel } from '../src/app/components/ade/catalogFacts/CatalogFactsPanel';
import { releasedFacts, factsProxyPath, type CatalogFactsResponse } from '../lib/catalog-facts';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const ITEM = '22222222-2222-4222-8222-222222222222';
const MCP = '33333333-3333-4333-8333-333333333333';
const owner = (present: boolean) => [
  { key: 'owner.present', label: 'Has an owner team', status: present ? 'met' : 'unmet', value: present,
    detail: present ? null : 'No confirmed owner team.', evidence: [{ label: 'Owner', href: `/ade/dashboard/catalog/${ITEM}`, api: null }] },
  { key: 'owner.contactable', label: 'Owner team is contactable', status: present ? 'unmet' : 'not_applicable', value: false,
    detail: present ? 'The owner team has no on-call or chat link.' : 'No owner team to contact.', evidence: [] },
];

const SPEC: CatalogFactsResponse = {
  kind: 'spec', id: ITEM, name: 'Orders events', score: null,
  facts: [
    ...owner(true),
    { key: 'consumers.declared', label: 'Consumers declared', status: 'met', value: 3, detail: '3 consumers registered.', evidence: [] },
    { key: 'dependencies.declared', label: 'Dependencies declared', status: 'unmet', value: 0, detail: '0 declared dependencies.', evidence: [] },
    { key: 'refresh.fresh', label: 'Refreshed within twice its cadence', status: 'met', value: true,
      detail: 'Repository acme/orders last refreshed 2026-06-15 09:00 UTC (cadence 5 min). Last revision 2026-06-12 14:20 UTC.',
      evidence: [{ label: 'Repository acme/orders', href: '/ade/dashboard/repositories/r-1', api: null }] },
    { key: 'deployment.known', label: 'Deployment known', status: 'met', value: 2, detail: 'Deployed on 2 gateway environments.',
      evidence: [{ label: 'Graph', href: `/ade/dashboard/graph?entity=catalog_item%3A${ITEM}`, api: null }] },
    { key: 'registry.level-set', label: 'Compatibility level set', status: 'unmet', value: false,
      detail: 'Using the workspace default: orders-value.', evidence: [{ label: 'Subjects', href: `/ade/dashboard/catalog/${ITEM}?tab=subjects`, api: null }] },
  ],
};

const MCP_FACTS: CatalogFactsResponse = {
  kind: 'mcp_server', id: MCP, name: 'Docs MCP', score: null,
  facts: [
    ...owner(false),
    { key: 'dependencies.declared', label: 'Dependencies declared', status: 'met', value: 1, detail: '1 declared dependency.', evidence: [] },
    { key: 'refresh.fresh', label: 'Refreshed within twice its cadence', status: 'not_assessed', value: null,
      detail: 'Discovery is disabled. Last discovered 2026-06-01 08:00 UTC (cadence 1 h).', evidence: [] },
    { key: 'mcp.baseline-approved', label: 'Trust baseline approved', status: 'met', value: true,
      detail: 'Approved 2026-06-10 11:30 UTC.', evidence: [{ label: 'MCP server', href: `/ade/dashboard/mcp/${MCP}`, api: null }] },
  ],
};

let calls: string[] = [];
let fail = false;
const res = (body: unknown, status = 200) =>
  ({ ok: status >= 200 && status < 300, status, json: async () => body }) as unknown as Response;

beforeEach(() => {
  calls = [];
  fail = false;
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    if (fail) return res({ success: false, error: 'apiome-rest not reachable' }, 503);
    if (url.includes(`/mcp_server/${MCP}/`)) return res(MCP_FACTS);
    if (url.includes('/team/')) return res({ kind: 'team', id: ITEM, name: 'Payments', facts: [], score: null });
    return res(SPEC);
  }) as unknown as typeof fetch;
});

describe('the rules', () => {
  it('accepts only a kind key and a UUID', () => {
    expect(factsProxyPath('spec', ITEM)).toBe(`entities/spec/${ITEM}/facts`);
    expect(factsProxyPath('../x', ITEM)).toBeNull();
    expect(factsProxyPath('spec', 'nope')).toBeNull();
  });
});

// Facts about owners, consumers, dependencies, MCP servers and shadow APIs wait for those features
// (lib/feature-release.ts). The checklist tests read every fact, so re-open them; the fixture
// dumps clear the override so the docs show the released panel.
const ALL_FACT_FEATURES = 'teams,consumers,dependency-graph,mcp,shadow-apis';
const PREVIEW_FEATURES = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
beforeAll(() => {
  process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = ALL_FACT_FEATURES;
});
afterAll(() => {
  if (PREVIEW_FEATURES === undefined) delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
  else process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = PREVIEW_FEATURES;
});

describe('the facts checklist', () => {
  it('shows each fact with its status in words, value, detail and evidence — and no score', async () => {
    const { container } = render(<CatalogFactsPanel kind="spec" id={ITEM} />);
    const consumers = await screen.findByTestId('catalog-fact-consumers.declared');
    expect(consumers).toHaveTextContent('Consumers declaredMet3');
    expect(consumers).toHaveAttribute('data-status', 'met');
    expect(screen.getByTestId('catalog-fact-registry.level-set')).toHaveTextContent('Not met');
    expect(screen.getByTestId('catalog-fact-owner.contactable')).toHaveTextContent('Not met');
    expect(within(screen.getByTestId('catalog-fact-refresh.fresh')).getByRole('link', { name: 'Repository acme/orders' })).toHaveAttribute(
      'href',
      '/ade/dashboard/repositories/r-1',
    );
    expect(screen.getByTestId('catalog-facts')).toHaveTextContent('No score until maturity ladders are available.');
    expect(container.textContent).not.toMatch(/\d+\s*%|grade|score:/i);
    expect(calls).toEqual([`/api/catalog/entities/spec/${ITEM}/facts`]);
  });

  it('reads not-assessed and not-applicable facts as such', async () => {
    render(<CatalogFactsPanel kind="mcp_server" id={MCP} />);
    expect(await screen.findByTestId('catalog-fact-refresh.fresh')).toHaveTextContent('Not assessed');
    expect(screen.getByTestId('catalog-fact-owner.contactable')).toHaveTextContent('Not applicable');
  });

  it('reads nothing until it is shown', () => {
    render(<CatalogFactsPanel kind="spec" id={ITEM} active={false} />);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('says so for a kind with no facts, and offers a retry on failure', async () => {
    const { unmount } = render(<CatalogFactsPanel kind="team" id={ITEM} />);
    expect(await screen.findByText('No facts apply to this kind of entity.')).toBeInTheDocument();
    unmount();
    fail = true;
    render(<CatalogFactsPanel kind="spec" id={ITEM} />);
    expect(await screen.findByText('apiome-rest not reachable')).toBeInTheDocument();
    fail = false;
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId('catalog-fact-consumers.declared')).toBeInTheDocument();
  });

  it('passes axe and dumps the docs fixtures', async () => {
    // The released build: no owner, consumer or dependency facts, no Graph evidence link.
    delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    try {
      const spec = render(<CatalogFactsPanel kind="spec" id={ITEM} />);
      await screen.findByTestId('catalog-fact-refresh.fresh');
      expect(screen.queryByTestId('catalog-fact-consumers.declared')).not.toBeInTheDocument();
      expect(screen.queryByRole('link', { name: 'Graph' })).not.toBeInTheDocument();
      expect(await axe(spec.container, AXE_OPTIONS)).toHaveNoViolations();
      writeA11yFixture('entity-facts', spec.container.innerHTML);
      spec.unmount();
    } finally {
      process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = ALL_FACT_FEATURES;
    }
    // `scorecard-kind` shows an MCP server, which is still held back; its screenshot stays unreleased.
    const mcp = render(<CatalogFactsPanel kind="mcp_server" id={MCP} />);
    await screen.findByTestId('catalog-fact-mcp.baseline-approved');
    expect(await axe(mcp.container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('scorecard-kind', mcp.container.innerHTML);
  });
});

describe('releasedFacts (RC7)', () => {
  const fact = (key: string, href: string | null = null) => ({
    key, label: key, status: 'met' as const, value: true, detail: null,
    evidence: href ? [{ label: 'Evidence', href, api: null }] : [],
  });
  const FACTS = [
    fact('owner.present'),
    fact('consumers.declared'),
    fact('dependencies.declared'),
    fact('mcp.baseline-approved'),
    fact('shadow.none', '/ade/dashboard/connectors/shadow?connector=c-1'),
    fact('deployment.known', '/ade/dashboard/graph?entity=catalog_item%3Ax'),
    fact('refresh.fresh', '/ade/dashboard/repositories/r-1'),
    fact('registry.level-set', '/ade/dashboard/catalog/x?tab=subjects'),
  ];

  it('leaves out facts and evidence links that belong to held-back features', () => {
    const shown = releasedFacts(FACTS, () => false);
    expect(shown.map((entry) => entry.key)).toEqual(['deployment.known', 'refresh.fresh', 'registry.level-set']);
    expect(shown.find((entry) => entry.key === 'deployment.known')!.evidence).toEqual([]);
    expect(shown.find((entry) => entry.key === 'refresh.fresh')!.evidence).toHaveLength(1);
  });

  it('shows everything once every feature is released', () => {
    expect(releasedFacts(FACTS, () => true)).toEqual(FACTS);
  });
});
