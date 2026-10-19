/**
 * The catalog home across kinds — CDG-5.1 (#5979).
 *
 * * **Kinds panel**: one tile per kind the server lists (plus All kinds) with its count; a kind
 *   the UI has never heard of shows up like any other (registry-driven); the selected tile is
 *   pressed and pressing one selects it; the three callouts link to their pages and a callout the
 *   reader may not see is left out; axe passes.
 * * **Entity list**: one table for every kind, the name linked to the entity's page, its kind and
 *   owner; the search and owner filter go to the server; **Load more** reads the next page with
 *   the cursor; an empty or failed read says so.
 * * **Catalog home**: the panel appears once the summary loads and is left out when it fails;
 *   `?kind=all` shows the entity list instead of the catalog-item cards; a tile writes `?kind=`.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixture `catalog-kinds`.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockReplace = jest.fn();
let searchParams = new URLSearchParams();

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: mockReplace }),
  useSearchParams: () => searchParams,
  usePathname: () => '/ade/dashboard/catalog',
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({
    data: { user: { user_id: 'u-ada', current_tenant_id: 't-acme', email: 'ada@acme.io' } },
    status: 'authenticated',
  }),
  AuthSessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

jest.mock('@/app/components/providers/DialogProvider', () => ({
  useDialog: () => ({ confirm: jest.fn(async () => true), alert: jest.fn(async () => undefined) }),
}));

jest.mock('@/app/components/ade/dashboard/catalog/CatalogImportDialog', () => ({
  __esModule: true,
  CatalogImportDialog: () => null,
}));

import { CatalogKindsPanel } from '../src/app/components/ade/catalog/CatalogKindsPanel';
import { CatalogEntityList } from '../src/app/components/ade/catalog/CatalogEntityList';
import CatalogClient from '../src/app/ade/dashboard/catalog/CatalogClient';
import {
  catalogKindParam,
  entityQuery,
  withKindParam,
  type CatalogEntity,
  type CatalogEntitySummary,
} from '../lib/catalog-entities';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };

const SUMMARY: CatalogEntitySummary = {
  kinds: [
    { kind: 'api', label: 'Project', pluralLabel: 'Projects', count: 12, ownerSupport: true, graphKind: 'project', listHref: '/ade/dashboard/projects' },
    { kind: 'spec', label: 'Catalog item', pluralLabel: 'Catalog items', count: 48, ownerSupport: true, graphKind: 'catalog_item', listHref: '/ade/dashboard/catalog' },
    { kind: 'mcp_server', label: 'MCP server', pluralLabel: 'MCP servers', count: 5, ownerSupport: true, graphKind: 'mcp_endpoint', listHref: '/ade/dashboard/mcp' },
    { kind: 'consumer', label: 'Consumer', pluralLabel: 'Consumers', count: 9, ownerSupport: true, graphKind: 'consumer', listHref: null },
    { kind: 'connector', label: 'Connector', pluralLabel: 'Connectors', count: 3, ownerSupport: true, graphKind: 'connector', listHref: '/ade/dashboard/connectors' },
    { kind: 'team', label: 'Team', pluralLabel: 'Teams', count: 4, ownerSupport: false, graphKind: null, listHref: '/ade/dashboard/teams' },
  ],
  callouts: { unowned: 7, stale: 2, shadow: 0 },
};

const OWNER = { team: { id: 't-1', slug: 'payments', name: 'Payments' }, status: 'confirmed' as const, source: 'manual' };

function entity(n: number, over: Partial<CatalogEntity> = {}): CatalogEntity {
  return {
    kind: 'api',
    id: `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`,
    slug: `entity-${n}`,
    name: `Entity ${n}`,
    description: null,
    owner: null,
    updatedAt: '2026-06-01T10:00:00Z',
    href: `/ade/dashboard/versions?projectId=${n}`,
    graphNode: { kind: 'project', id: String(n) },
    ...over,
  };
}

const PAGE_ONE: CatalogEntity[] = [
  entity(1, { name: 'Billing API', owner: OWNER }),
  entity(2, { kind: 'mcp_server', name: 'Docs MCP', href: '/ade/dashboard/mcp/2', graphNode: { kind: 'mcp_endpoint', id: '2' } }),
  entity(3, { kind: 'team', name: 'Payments', slug: 'payments', href: '/ade/dashboard/teams/payments', graphNode: null, description: 'Card rails and refunds.' }),
];
const PAGE_TWO: CatalogEntity[] = [entity(4, { kind: 'connector', name: 'Kong prod', slug: null, href: '/ade/dashboard/connectors/4', graphNode: { kind: 'connector', id: '4' } })];

const res = (body: unknown, status = 200) =>
  ({ ok: status >= 200 && status < 300, status, statusText: 'OK', json: async () => body }) as unknown as Response;

let calls: string[] = [];
let summaryFails = false;

beforeEach(() => {
  calls = [];
  summaryFails = false;
  searchParams = new URLSearchParams();
  mockReplace.mockReset();
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    if (url.startsWith('/api/catalog/entities/summary')) {
      return summaryFails ? res({ success: false, error: 'down' }, 503) : res(SUMMARY);
    }
    if (url.startsWith('/api/catalog/entities')) {
      const cursor = new URL(url, 'http://ui.test').searchParams.get('cursor');
      return cursor === 'c-2'
        ? res({ items: PAGE_TWO, pagination: { nextCursor: null } })
        : res({ items: PAGE_ONE, pagination: { nextCursor: 'c-2' } });
    }
    if (url.startsWith('/api/import/sources')) return res({ success: true, sources: [] });
    return res({ success: true, catalog: [] });
  }) as unknown as typeof fetch;
});

describe('the kind helpers', () => {
  it('reads and writes ?kind=', () => {
    expect(catalogKindParam(null)).toBe('spec');
    expect(catalogKindParam('all')).toBe('all');
    expect(catalogKindParam('mcp_server')).toBe('mcp_server');
    expect(catalogKindParam('../x')).toBe('spec');
    expect(withKindParam('team=payments', 'api')).toBe('?team=payments&kind=api');
    expect(withKindParam('kind=api', 'spec')).toBe('?');
  });

  it('forwards only allowed, well-formed parameters', () => {
    const params = new URLSearchParams('kind=api&kind=Bad!&team=payments&q=orders&cursor=abc&limit=50&limit2=9&evil=1');
    expect(entityQuery(params)).toBe('?kind=api&team=payments&q=orders&cursor=abc&limit=50');
    expect(entityQuery(params, ['team', 'q'])).toBe('?team=payments&q=orders');
    expect(entityQuery(new URLSearchParams('limit=5000'))).toBe('');
  });
});

describe('the kinds panel', () => {
  it('draws a tile per kind the server lists, with counts, and All kinds first', () => {
    render(<CatalogKindsPanel summary={SUMMARY} selected="spec" onSelect={jest.fn()} />);
    const tiles = within(screen.getByRole('group', { name: 'Kind' })).getAllByRole('button');
    expect(tiles.map((tile) => tile.textContent)).toEqual([
      '81All kinds', '12Projects', '48Catalog items', '5MCP servers', '9Consumers', '3Connectors', '4Teams',
    ]);
    expect(screen.getByTestId('catalog-kind-spec')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('catalog-kind-all')).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows a kind the UI has never heard of, like any other (registry-driven)', () => {
    const withAgents = {
      ...SUMMARY,
      kinds: [...SUMMARY.kinds, { kind: 'agent', label: 'Agent', pluralLabel: 'Agents', count: 2, ownerSupport: true, graphKind: null, listHref: null }],
    };
    const onSelect = jest.fn();
    render(<CatalogKindsPanel summary={withAgents} selected="spec" onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId('catalog-kind-agent'));
    expect(screen.getByTestId('catalog-kind-agent')).toHaveTextContent('2Agents');
    expect(onSelect).toHaveBeenCalledWith('agent');
  });

  it('links each callout to the page that acts on it', () => {
    render(<CatalogKindsPanel summary={SUMMARY} selected="spec" onSelect={jest.fn()} />);
    expect(screen.getByTestId('catalog-callout-unowned')).toHaveAttribute('href', '/ade/dashboard/teams#tm-drift');
    expect(screen.getByTestId('catalog-callout-stale')).toHaveAttribute('href', '/ade/dashboard/connectors');
    expect(screen.getByTestId('catalog-callout-shadow')).toHaveAttribute('href', '/ade/dashboard/connectors/shadow');
    expect(screen.getByTestId('catalog-callout-unowned')).toHaveAttribute('data-attention');
    expect(screen.getByTestId('catalog-callout-shadow')).not.toHaveAttribute('data-attention');
    expect(screen.getByTestId('catalog-callout-unowned')).toHaveTextContent('7Unowned');
  });

  it('leaves out a callout the reader may not see', () => {
    render(
      <CatalogKindsPanel summary={{ ...SUMMARY, callouts: { unowned: 3, stale: null, shadow: null } }} selected="spec" onSelect={jest.fn()} />,
    );
    expect(screen.queryByTestId('catalog-callout-stale')).not.toBeInTheDocument();
    expect(screen.queryByTestId('catalog-callout-shadow')).not.toBeInTheDocument();
    expect(screen.getByTestId('catalog-callout-unowned')).toBeInTheDocument();
  });
});

describe('the entity list', () => {
  async function renderList(kind = 'all', team: string | null = null) {
    const view = render(<CatalogEntityList kind={kind} team={team} kinds={SUMMARY.kinds} />);
    await screen.findByTestId('catalog-entity-table');
    return view;
  }

  it('lists every kind in one table, linked to each entity’s page', async () => {
    await renderList();
    expect(screen.getByRole('heading', { name: 'All kinds' })).toBeInTheDocument();
    const rows = within(screen.getByTestId('catalog-entity-table')).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByRole('link', { name: 'Billing API' })).toHaveAttribute('href', '/ade/dashboard/versions?projectId=1');
    expect(rows[0]).toHaveTextContent('Project');
    expect(rows[0]).toHaveTextContent('Payments');
    expect(rows[1]).toHaveTextContent('MCP server');
    expect(rows[2]).toHaveTextContent('Card rails and refunds.');
    expect(calls.at(-1)).toBe('/api/catalog/entities?limit=50');
  });

  it('asks the server for one kind and the owner team', async () => {
    await renderList('mcp_server', 'payments');
    expect(screen.getByRole('heading', { name: 'MCP servers' })).toBeInTheDocument();
    expect(calls.at(-1)).toBe('/api/catalog/entities?kind=mcp_server&team=payments&limit=50');
  });

  it('loads the next page with the cursor', async () => {
    await renderList();
    fireEvent.click(screen.getByTestId('catalog-entity-more'));
    expect(await screen.findByText('Kong prod')).toBeInTheDocument();
    expect(calls.at(-1)).toContain('cursor=c-2');
    expect(within(screen.getByTestId('catalog-entity-table')).getAllByRole('row')).toHaveLength(5);
    expect(screen.queryByTestId('catalog-entity-more')).not.toBeInTheDocument();
  });

  it('sends the search to the server', async () => {
    jest.useFakeTimers();
    try {
      render(<CatalogEntityList kind="all" team={null} kinds={SUMMARY.kinds} />);
      fireEvent.change(screen.getByTestId('catalog-entity-search'), { target: { value: 'orders' } });
      await act(async () => {
        jest.advanceTimersByTime(300);
      });
      await waitFor(() => expect(calls.at(-1)).toBe('/api/catalog/entities?q=orders&limit=50'));
    } finally {
      jest.useRealTimers();
    }
  });

  it('says so when nothing matches, and when the read fails', async () => {
    global.fetch = jest.fn(async () => res({ items: [], pagination: { nextCursor: null } })) as unknown as typeof fetch;
    const { unmount } = render(<CatalogEntityList kind="team" team={null} kinds={SUMMARY.kinds} />);
    expect(await screen.findByText('Nothing matches')).toBeInTheDocument();
    unmount();
    global.fetch = jest.fn(async () => res({ success: false, error: 'apiome-rest not reachable' }, 503)) as unknown as typeof fetch;
    render(<CatalogEntityList kind="team" team={null} kinds={SUMMARY.kinds} />);
    expect(await screen.findByText('apiome-rest not reachable')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('passes axe', async () => {
    const { container } = await renderList();
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });
});

describe('the catalog home', () => {
  it('shows the kinds panel once the summary loads, on catalog items by default', async () => {
    render(<CatalogClient />);
    expect(await screen.findByTestId('catalog-kinds')).toBeInTheDocument();
    expect(screen.getByTestId('catalog-kind-spec')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByTestId('catalog-entity-list')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('catalog-kind-mcp_server'));
    expect(mockReplace).toHaveBeenCalledWith('?kind=mcp_server', { scroll: false });
  });

  it('shows the cross-kind list for ?kind=all', async () => {
    searchParams = new URLSearchParams('kind=all');
    render(<CatalogClient />);
    expect(await screen.findByTestId('catalog-entity-list')).toBeInTheDocument();
    expect(screen.getByTestId('catalog-kind-all')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByTestId('catalog-cards')).not.toBeInTheDocument();
  });

  it('offers Register agent and Add model on those kinds (CDG-5.2)', async () => {
    searchParams = new URLSearchParams('kind=agent');
    const { unmount } = render(<CatalogClient />);
    expect(await screen.findByTestId('catalog-register-agent')).toHaveTextContent('Register agent');
    unmount();
    searchParams = new URLSearchParams('kind=model');
    render(<CatalogClient />);
    expect(await screen.findByTestId('catalog-add-model')).toHaveTextContent('Add model');
    expect(screen.queryByTestId('catalog-register-agent')).not.toBeInTheDocument();
  });

  it('leaves the panel out when the summary cannot be read', async () => {
    summaryFails = true;
    searchParams = new URLSearchParams('kind=all');
    render(<CatalogClient />);
    await waitFor(() => expect(calls.some((url) => url.startsWith('/api/catalog/entities/summary'))).toBe(true));
    await waitFor(() => expect(calls.some((url) => url.startsWith('/api/catalog?') || url === '/api/catalog')).toBe(true));
    expect(screen.queryByTestId('catalog-kinds')).not.toBeInTheDocument();
    expect(screen.queryByTestId('catalog-entity-list')).not.toBeInTheDocument();
  });

  it('passes axe and dumps the docs fixture', async () => {
    searchParams = new URLSearchParams('kind=all');
    const { container } = render(<CatalogClient />);
    await screen.findByTestId('catalog-entity-table');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('catalog-kinds', (document.querySelector('.page') ?? container.firstElementChild)!.outerHTML);
  });
});
