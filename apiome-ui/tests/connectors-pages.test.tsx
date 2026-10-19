/**
 * The Connectors pages (CDG-1.7, #5958): the list, the add wizard, a connector's Items / Runs /
 * Settings, and the shared refresh-runs ledger.
 *
 * Pins the acceptance criteria that live in the browser: a failing dry run blocks the save and shows
 * the provider's reason, a successful one shows the inventory count before anything is stored, saving
 * opens the connector without a reload, an item links to its catalog page, and the ledger interleaves
 * Git and connector runs behind a source badge.
 */

import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn(), refresh: jest.fn() }),
  usePathname: () => '/ade/dashboard/connectors',
  useSearchParams: () => new URLSearchParams(),
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({ data: { user: { user_id: 'u1', current_tenant_id: 't1' } } }),
}));

const mockToast = { success: jest.fn(), error: jest.fn() };
jest.mock('@/app/components/ui/toast', () => ({ toast: mockToast }));

const mockConfirm = jest.fn();
jest.mock('@/app/components/providers/DialogProvider', () => ({
  useDialog: () => ({ confirm: (options: unknown) => mockConfirm(options), alert: jest.fn() }),
}));

import ConnectorsClient, { scheduleLabel } from '../src/app/ade/dashboard/connectors/ConnectorsClient';
import AddConnectorClient from '../src/app/ade/dashboard/connectors/new/AddConnectorClient';
import ConnectorDetailClient from '../src/app/ade/dashboard/connectors/[id]/ConnectorDetailClient';
import { RefreshRunsLedger } from '../src/app/components/ade/connectors/RefreshRunsLedger';
import type { Connector, RefreshRun } from '../lib/connectors-api';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

function connector(overrides: Partial<Connector> = {}): Connector {
  return {
    id: 'c1',
    kind: 'kong-admin',
    name: 'Prod Kong',
    baseUrl: 'https://kong.example.com:8001',
    scope: { workspaces: ['default'] },
    refreshIntervalSeconds: 86400,
    conflictPolicy: 'hold-for-review',
    status: 'active',
    hasCredentials: true,
    syncable: true,
    lastRunAt: '2026-10-18T10:00:00Z',
    createdAt: '2026-10-01T10:00:00Z',
    ...overrides,
  };
}

function run(overrides: Partial<RefreshRun>): RefreshRun {
  return {
    id: 'r1',
    source: 'connector',
    status: 'succeeded',
    reason: null,
    trigger: 'manual',
    connectorId: 'c1',
    connectorName: 'Prod Kong',
    connectorKind: 'kong-admin',
    repositoryId: null,
    repositoryName: null,
    branch: null,
    path: null,
    errorClass: null,
    httpStatus: null,
    errorMessage: null,
    pullCount: 0,
    summary: { imported: 2, candidates: 3 },
    createdAt: '2026-10-18T10:00:00Z',
    startedAt: '2026-10-18T10:00:00Z',
    finishedAt: '2026-10-18T10:00:05Z',
    ...overrides,
  };
}

const RUNS = [
  run({ id: 'r-conn' }),
  run({
    id: 'r-git',
    source: 'git',
    connectorId: null,
    connectorName: null,
    connectorKind: null,
    repositoryId: 'repo1',
    repositoryName: 'acme/apis',
    branch: 'main',
    path: 'openapi.yaml',
    summary: {},
  }),
];

type Route = (url: string, init?: RequestInit) => { status?: number; body: unknown } | undefined;

let calls: { url: string; method: string; body: unknown }[];
let routes: Route[];

function reply(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function defaultRoute(url: string, init?: RequestInit) {
  const method = init?.method ?? 'GET';
  if (url === '/api/connectors' && method === 'GET') {
    return { body: { connectors: [connector()], kinds: ['kong-admin', 'apigee'], syncableKinds: ['kong-admin'] } };
  }
  if (url.startsWith('/api/refresh-runs')) return { body: { runs: RUNS, total: 2 } };
  if (url === '/api/connectors/c1' && method === 'GET') return { body: connector() };
  if (url.startsWith('/api/connectors/c1/items')) {
    return {
      body: {
        total: 2,
        items: [
          {
            id: 'i1',
            remoteId: 'svc-orders',
            remoteName: 'orders',
            environment: 'default',
            hosts: ['orders.example.com'],
            basePath: '/orders',
            remoteRevision: '3',
            status: 'imported',
            catalogItemId: 'cat-1',
            lastSeenAt: '2026-10-18T10:00:00Z',
          },
          {
            id: 'i2',
            remoteId: 'svc-billing',
            remoteName: 'billing',
            environment: 'default',
            hosts: [],
            basePath: null,
            remoteRevision: null,
            status: 'discovered',
            catalogItemId: null,
            lastSeenAt: null,
          },
        ],
      },
    };
  }
  return undefined;
}

beforeEach(() => {
  calls = [];
  routes = [];
  mockPush.mockReset();
  mockToast.success.mockReset();
  mockToast.error.mockReset();
  mockConfirm.mockReset();
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    for (const route of [...routes, defaultRoute]) {
      const answer = route(url, init);
      if (answer) return reply(answer.body, answer.status ?? 200);
    }
    return reply({ error: `not routed: ${method} ${url}` }, 404);
  }) as unknown as typeof fetch;
});

describe('Connectors list', () => {
  it('shows each connector with its health, last run and schedule', async () => {
    render(<ConnectorsClient />);
    const row = await screen.findByTestId('connector-row-c1');
    expect(within(row).getByRole('link', { name: 'Prod Kong' })).toHaveAttribute('href', '/ade/dashboard/connectors/c1');
    expect(within(row).getByText('Kong Gateway (Admin API)')).toBeInTheDocument();
    expect(within(row).getByText('active')).toBeInTheDocument();
    expect(within(row).getByText(scheduleLabel(86400))).toBeInTheDocument();
    writeA11yFixture('connectors', document.body.innerHTML);
  });

  it('switches to the grid', async () => {
    const user = userEvent.setup();
    render(<ConnectorsClient />);
    await screen.findByTestId('connectors-table');
    await user.click(screen.getByTestId('connectors-view-grid'));
    expect(screen.getByTestId('connectors-grid')).toBeInTheDocument();
  });

  it('syncs now and reports the outcome', async () => {
    routes.push((url, init) =>
      url === '/api/connectors/c1/sync' && init?.method === 'POST'
        ? { body: { id: 'run1', status: 'succeeded', summary: { imported: 1, candidates: 4 } } }
        : undefined
    );
    const user = userEvent.setup();
    render(<ConnectorsClient />);
    await user.click(await screen.findByTestId('connector-sync-c1'));
    await waitFor(() => expect(mockToast.success).toHaveBeenCalledWith('Prod Kong: Imported 1 of 4.'));
  });

  it('invites the first connector when there are none', async () => {
    routes.push((url) =>
      url === '/api/connectors' ? { body: { connectors: [], kinds: [], syncableKinds: [] } } : undefined
    );
    render(<ConnectorsClient />);
    expect(await screen.findByText('Connect your first gateway')).toBeInTheDocument();
  });

  it('says when the list could not be read, with a retry', async () => {
    routes.push((url) => (url === '/api/connectors' ? { status: 403, body: { error: 'Not allowed.' } } : undefined));
    render(<ConnectorsClient />);
    expect(await screen.findByText('Not allowed.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
  });

  it('schedules read as words', () => {
    expect(scheduleLabel(null)).toBe('Deployment default');
  });
});

/** Walk the wizard to the dry-run step for a Kong Admin API connector. */
async function toDryRun(user: ReturnType<typeof userEvent.setup>) {
  render(<AddConnectorClient />);
  const kong = await screen.findByTestId('connector-kind-kong-admin');
  await waitFor(() => expect(kong).not.toBeDisabled());
  expect(screen.getByTestId('connector-kind-apigee')).toBeDisabled();
  await user.click(kong);
  await user.click(screen.getByTestId('connector-next'));
  expect(screen.getByTestId('connector-step-credentials')).toBeInTheDocument();
  await user.type(screen.getByTestId('connector-credential-token'), 'kong-secret');
  await user.click(screen.getByTestId('connector-next'));
  expect(screen.getByTestId('connector-step-scope')).toBeInTheDocument();
  expect(screen.getByTestId('connector-next')).toBeDisabled();
  expect(screen.getByTestId('connector-missing')).toHaveTextContent('Base URL');
  await user.type(screen.getByTestId('connector-base-url'), 'https://kong.example.com:8001');
  await user.click(screen.getByTestId('connector-next'));
  expect(screen.getByTestId('connector-step-dry-run')).toBeInTheDocument();
}

describe('Add connector wizard', () => {
  it('blocks the save when the dry run fails and shows the provider reason', async () => {
    routes.push((url) =>
      url === '/api/connectors/dry-run'
        ? { status: 422, body: { error: 'The dry run failed (auth, HTTP 401): invalid credentials' } }
        : undefined
    );
    const user = userEvent.setup();
    await toDryRun(user);
    await user.click(screen.getByTestId('connector-dry-run'));
    expect(await screen.findByTestId('connector-dry-run-error')).toHaveTextContent(
      'The dry run failed (auth, HTTP 401): invalid credentials'
    );
    expect(screen.getByTestId('connector-next')).toBeDisabled();
    expect(calls.some((call) => call.url === '/api/connectors' && call.method === 'POST')).toBe(false);
  });

  it('shows the inventory count, then saves and opens the connector', async () => {
    routes.push((url, init) => {
      if (url === '/api/connectors/dry-run') {
        return {
          body: {
            itemCount: 3,
            items: [{ remoteId: 'svc-orders', name: 'orders', environment: 'default', revision: null }],
            truncated: false,
            findings: [],
          },
        };
      }
      if (url === '/api/connectors' && init?.method === 'POST') return { status: 201, body: connector({ id: 'c9' }) };
      if (url === '/api/connectors/c9/credentials') return { body: { hasCredentials: true } };
      return undefined;
    });
    const user = userEvent.setup();
    await toDryRun(user);
    await user.click(screen.getByTestId('connector-dry-run'));
    const result = await screen.findByTestId('connector-dry-run-result');
    expect(result).toHaveTextContent('3');
    expect(result).toHaveTextContent('orders');
    const dryRun = calls.find((call) => call.url === '/api/connectors/dry-run');
    expect(dryRun?.body).toEqual({
      kind: 'kong-admin',
      baseUrl: 'https://kong.example.com:8001',
      scope: {},
      credentials: { token: 'kong-secret' },
    });
    expect(calls.some((call) => call.url === '/api/connectors' && call.method === 'POST')).toBe(false);
    writeA11yFixture('connector-add', document.body.innerHTML);

    await user.click(screen.getByTestId('connector-next'));
    expect(screen.getByTestId('connector-step-schedule')).toBeInTheDocument();
    await user.type(screen.getByTestId('connector-name'), 'Prod Kong');
    await user.click(screen.getByTestId('connector-save'));
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/ade/dashboard/connectors/c9'));
    const created = calls.find((call) => call.url === '/api/connectors' && call.method === 'POST');
    expect(created?.body).toMatchObject({ kind: 'kong-admin', name: 'Prod Kong', conflictPolicy: 'hold-for-review' });
    expect(JSON.stringify(created?.body)).not.toContain('kong-secret');
    expect(calls.find((call) => call.url === '/api/connectors/c9/credentials')?.body).toEqual({
      credentials: { token: 'kong-secret' },
    });
  });

  it('a changed input invalidates the dry run', async () => {
    routes.push((url) =>
      url === '/api/connectors/dry-run'
        ? { body: { itemCount: 1, items: [], truncated: false, findings: [] } }
        : undefined
    );
    const user = userEvent.setup();
    await toDryRun(user);
    await user.click(screen.getByTestId('connector-dry-run'));
    await screen.findByTestId('connector-dry-run-result');
    await user.click(screen.getByTestId('connector-back'));
    await user.type(screen.getByTestId('connector-base-url'), '/');
    await user.click(screen.getByTestId('connector-next'));
    expect(screen.queryByTestId('connector-dry-run-result')).not.toBeInTheDocument();
    expect(screen.getByTestId('connector-next')).toBeDisabled();
  });
});

describe('MCP registry connector (CDG-4.4)', () => {
  it('asks for the registry root, a search and an optional credential, and dry-runs them', async () => {
    routes.push((url, init) => {
      if (url === '/api/connectors' && (init?.method ?? 'GET') === 'GET') {
        return { body: { connectors: [], kinds: ['mcp-registry'], syncableKinds: ['mcp-registry'] } };
      }
      if (url === '/api/connectors/dry-run') {
        return {
          body: {
            itemCount: 2,
            items: [{ remoteId: 'io.github.acme/weather', name: 'Weather', environment: null, revision: '1.0.0' }],
            truncated: false,
            findings: [],
          },
        };
      }
      return undefined;
    });
    const user = userEvent.setup();
    render(<AddConnectorClient />);
    const kind = await screen.findByTestId('connector-kind-mcp-registry');
    await waitFor(() => expect(kind).not.toBeDisabled());
    await user.click(kind);
    await user.click(screen.getByTestId('connector-next'));
    expect(screen.getByTestId('connector-credential-token')).toBeInTheDocument();
    expect(screen.getByTestId('connector-credential-apiKey')).toBeInTheDocument();
    await user.click(screen.getByTestId('connector-next')); // both credentials are optional
    expect(screen.getByTestId('connector-missing')).toHaveTextContent('Base URL');
    await user.type(screen.getByTestId('connector-base-url'), 'https://registry.modelcontextprotocol.io');
    await user.type(screen.getByTestId('connector-scope-search'), 'io.github.acme');
    await user.type(screen.getByTestId('connector-scope-updatedSince'), '2026-01-01T00:00:00Z');
    writeA11yFixture('connector-add-mcp-registry', liveMarkup(document.body));
    await user.click(screen.getByTestId('connector-next'));
    await user.click(screen.getByTestId('connector-dry-run'));
    expect(await screen.findByTestId('connector-dry-run-result')).toHaveTextContent('Weather');
    expect(calls.find((call) => call.url === '/api/connectors/dry-run')?.body).toMatchObject({
      kind: 'mcp-registry',
      baseUrl: 'https://registry.modelcontextprotocol.io',
      scope: { search: 'io.github.acme', updatedSince: '2026-01-01T00:00:00Z' },
    });
  });

  it('links each entry to its MCP server and says why an entry is still discovered', async () => {
    routes.push((url) => {
      if (url === '/api/connectors/c1') return { body: connector({ kind: 'mcp-registry', name: 'Official registry' }) };
      if (url.startsWith('/api/connectors/c1/items')) {
        return {
          body: {
            total: 2,
            items: [
              {
                id: 'm1',
                remoteId: 'io.github.acme/weather',
                remoteName: 'Weather',
                environment: null,
                hosts: ['weather.acme.test'],
                basePath: null,
                remoteRevision: '1.0.0+sha256.0123456789ab',
                status: 'imported',
                catalogItemId: null,
                mcpEndpointId: 'e1',
                discoveredReason: null,
                lastSeenAt: '2026-10-18T10:00:00Z',
              },
              {
                id: 'm2',
                remoteId: 'io.github.acme/local-files',
                remoteName: 'io.github.acme/local-files',
                environment: null,
                hosts: [],
                basePath: null,
                remoteRevision: '0.3.1+sha256.ba9876543210',
                status: 'discovered',
                catalogItemId: null,
                mcpEndpointId: null,
                discoveredReason: 'no-remote: the server lists only packages, which run locally (stdio).',
                lastSeenAt: '2026-10-18T10:00:00Z',
              },
            ],
          },
        };
      }
      return undefined;
    });
    const preview = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'mcp';
    const view = render(<ConnectorDetailClient connectorId="c1" />);
    const link = await screen.findByTestId('connector-item-link-m1');
    expect(link).toHaveAttribute('href', '/ade/dashboard/mcp/e1');
    expect(link).toHaveTextContent('Open the MCP server');
    expect(screen.getByRole('columnheader', { name: 'MCP server' })).toBeInTheDocument();
    expect(screen.queryByTestId('connector-item-link-m2')).not.toBeInTheDocument();
    expect(screen.getByTestId('connector-item-reason-m2')).toHaveTextContent('no-remote');
    view.unmount();

    // While the MCP servers screen is unreleased, the entry names its server without a dead link.
    delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    render(<ConnectorDetailClient connectorId="c1" />);
    expect(await screen.findByTestId('connector-item-mcp-m1')).toHaveTextContent('Added to the MCP servers');
    expect(screen.queryByTestId('connector-item-link-m1')).not.toBeInTheDocument();
    if (preview !== undefined) process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = preview;
  });
});

describe('Connector detail', () => {
  it('lists the inventory with a link to each catalog item', async () => {
    render(<ConnectorDetailClient connectorId="c1" />);
    const link = await screen.findByTestId('connector-item-link-i1');
    expect(link).toHaveAttribute('href', '/ade/dashboard/catalog/cat-1');
    expect(screen.queryByTestId('connector-item-link-i2')).not.toBeInTheDocument();
    writeA11yFixture('connector-detail', document.body.innerHTML);
  });

  it('shows this connector runs on the Runs tab', async () => {
    const user = userEvent.setup();
    render(<ConnectorDetailClient connectorId="c1" />);
    await screen.findByTestId('connector-item-i1');
    await user.click(screen.getByTestId('connector-tab-runs'));
    await screen.findByTestId('refresh-runs-ledger');
    expect(calls.some((call) => call.url.startsWith('/api/refresh-runs?connector=c1'))).toBe(true);
    writeA11yFixture('connector-runs', document.body.innerHTML);
  });

  it('saves settings and deletes after confirmation', async () => {
    routes.push((url, init) =>
      url === '/api/connectors/c1' && init?.method === 'PATCH'
        ? { body: connector({ name: 'Edge Kong' }) }
        : url === '/api/connectors/c1' && init?.method === 'DELETE'
          ? { body: { deleted: true } }
          : undefined
    );
    mockConfirm.mockImplementation(async (options: { perform: () => Promise<void> }) => {
      await options.perform();
      return true;
    });
    const user = userEvent.setup();
    render(<ConnectorDetailClient connectorId="c1" />);
    await screen.findByTestId('connector-item-i1');
    await user.click(screen.getByTestId('connector-tab-settings'));
    const name = await screen.findByLabelText(/^Name/);
    await user.clear(name);
    await user.type(name, 'Edge Kong');
    await user.click(screen.getByTestId('connector-settings-save'));
    await waitFor(() => expect(mockToast.success).toHaveBeenCalled());
    expect(calls.find((call) => call.method === 'PATCH')?.body).toMatchObject({ name: 'Edge Kong' });

    await user.click(screen.getByTestId('connector-settings-delete'));
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith('/ade/dashboard/connectors'));
    expect(calls.some((call) => call.method === 'DELETE' && call.url === '/api/connectors/c1')).toBe(true);
  });
});

describe('Refresh runs ledger', () => {
  it('interleaves Git and connector runs behind a source badge', async () => {
    render(<RefreshRunsLedger />);
    const conn = await screen.findByTestId('refresh-run-r-conn');
    const git = screen.getByTestId('refresh-run-r-git');
    expect(within(conn).getByTestId('refresh-run-source')).toHaveTextContent('Connector');
    expect(within(git).getByTestId('refresh-run-source')).toHaveTextContent('Git');
    expect(within(conn).getByRole('link', { name: 'Prod Kong' })).toHaveAttribute('href', '/ade/dashboard/connectors/c1');
    expect(within(git).getByText(/acme\/apis/)).toBeInTheDocument();
    expect(within(conn).getByText('Imported 2 of 3')).toBeInTheDocument();
    expect(calls.find((call) => call.url.startsWith('/api/refresh-runs'))?.url).toBe('/api/refresh-runs?limit=25');
  });

  it('says when there are no runs', async () => {
    routes.push((url) => (url.startsWith('/api/refresh-runs') ? { body: { runs: [], total: 0 } } : undefined));
    render(<RefreshRunsLedger connectorId="c1" />);
    expect(await screen.findByTestId('refresh-runs-empty')).toBeInTheDocument();
  });
});
