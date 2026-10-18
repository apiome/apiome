/**
 * The shadow-API report page — `/ade/dashboard/connectors/shadow` (CDG-1.6, #5957).
 *
 * Pins what the page owes the acceptance criteria: the section chips carry the report's counts, a
 * possible match shows its tier and confidence and is linked only after a person confirms it in the
 * dialog, an ignore needs a reason, a stale connector says "inventory stale since …" instead of an
 * empty list passing for a clean one, and "Import" imports exactly that row.
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

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({ data: { user: { user_id: 'u1', current_tenant_id: 't1' } } }),
}));

const mockToast = { success: jest.fn(), error: jest.fn() };
jest.mock('@/app/components/ui/toast', () => ({ toast: mockToast }));

import ShadowApisClient from '../src/app/ade/dashboard/connectors/shadow/ShadowApisClient';
import type { ShadowItem, ShadowReport } from '../lib/shadow-report';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

function item(id: string, overrides: Partial<ShadowItem> = {}): ShadowItem {
  return {
    itemId: id,
    connectorId: 'c1',
    connectorName: 'Prod Kong',
    connectorKind: 'kong-admin',
    remoteId: `svc-${id}`,
    name: `Service ${id}`,
    environment: 'prod',
    hosts: [`${id}.example.com`],
    basePath: null,
    status: 'discovered',
    firstSeenAt: null,
    lastSeenAt: null,
    stale: false,
    ...overrides,
  };
}

const MATCH = {
  tier: 'host',
  confidence: 0.9,
  reason: 'Served on https://orders.example.com/v2, a declared server.',
  target: { projectId: 'p-orders', name: 'Orders API', kind: 'project', versionId: 'v1', versionLabel: '1.0.0' },
};
const ALTERNATIVE = {
  tier: 'title',
  confidence: 0.42,
  reason: 'Name is 84% similar.',
  target: { projectId: 'p-legacy', name: 'Orders legacy', kind: 'catalog-item', versionId: null, versionLabel: null },
};

function baseReport(overrides: Partial<ShadowReport> = {}): ShadowReport {
  const shadow = [item('billing'), item('metrics')];
  const possibleMatches = [item('orders', { match: MATCH, alternatives: [ALTERNATIVE] })];
  return {
    generatedAt: '2026-10-18T12:00:00Z',
    filters: { connector: null, environment: null },
    connectors: [
      { id: 'c1', name: 'Prod Kong', kind: 'kong-admin', status: 'active', itemCount: 5, stale: false, staleSince: null },
    ],
    stale: [],
    summary: { shadow: 2, possibleMatches: 1, drift: 0, undeployed: 0, ignored: 0 },
    shadow,
    possibleMatches,
    undeployed: [],
    drift: [],
    ignored: [],
    ...overrides,
  };
}

let current: ShadowReport;
let posts: { url: string; body: unknown }[];
let queries: string[];

function reply(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

beforeEach(() => {
  current = baseReport();
  posts = [];
  queries = [];
  mockToast.success.mockReset();
  mockToast.error.mockReset();
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.startsWith('/api/connectors/shadow-report')) {
      queries.push(url);
      return reply(current);
    }
    if (init?.method === 'POST') {
      posts.push({ url, body: init.body ? JSON.parse(String(init.body)) : undefined });
      if (url.endsWith('/import')) return reply({ status: 'succeeded', summary: { imported: 1 } });
      return reply({ id: 'x', status: 'imported' });
    }
    return reply({ error: 'not routed' }, 404);
  }) as unknown as typeof fetch;
});

describe('Shadow APIs page', () => {
  it('shows the shadow rows and the section counts', async () => {
    render(<ShadowApisClient initialConnector={null} />);
    expect(await screen.findByText('Service billing')).toBeInTheDocument();
    expect(screen.getByText('Service metrics')).toBeInTheDocument();
    expect(screen.getByTestId('shadow-section-shadow')).toHaveTextContent('2');
    expect(screen.getByTestId('shadow-section-possibleMatches')).toHaveTextContent('1');
  });

  it('reads the connector filter a notification links to', async () => {
    render(<ShadowApisClient initialConnector="c1" />);
    await screen.findByText('Service billing');
    expect(queries[0]).toBe('/api/connectors/shadow-report?connector=c1');
  });

  it('links a possible match only after a person confirms the item', async () => {
    const user = userEvent.setup();
    render(<ShadowApisClient initialConnector={null} />);
    await user.click(await screen.findByTestId('shadow-section-possibleMatches'));
    const row = await screen.findByTestId('shadow-row-orders');
    expect(within(row).getByTestId('shadow-match-tier')).toHaveTextContent('Same host · 90%');
    expect(posts).toEqual([]);

    await user.click(within(row).getByTestId('shadow-link-orders'));
    const dialog = await screen.findByTestId('shadow-link-dialog');
    expect(posts).toEqual([]);
    await user.click(within(dialog).getByTestId('shadow-link-target-p-legacy'));
    await user.click(within(dialog).getByTestId('shadow-link-confirm'));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({ url: '/api/connectors/c1/items/orders/link', body: { catalogItemId: 'p-legacy' } });
    await waitFor(() => expect(screen.queryByTestId('shadow-link-dialog')).not.toBeInTheDocument());
  });

  it('asks for a reason before ignoring', async () => {
    const user = userEvent.setup();
    render(<ShadowApisClient initialConnector={null} />);
    await user.click(within(await screen.findByTestId('shadow-row-billing')).getByTestId('shadow-ignore-billing'));
    const dialog = await screen.findByTestId('shadow-ignore-dialog');
    await user.click(within(dialog).getByTestId('shadow-ignore-confirm'));
    expect(await within(dialog).findByText('Say why this API is not in the catalog.')).toBeInTheDocument();
    expect(posts).toEqual([]);

    await user.type(within(dialog).getByTestId('shadow-ignore-reason'), 'Internal health check');
    await user.click(within(dialog).getByTestId('shadow-ignore-confirm'));
    await waitFor(() =>
      expect(posts).toEqual([
        { url: '/api/connectors/c1/items/billing/ignore', body: { reason: 'Internal health check' } },
      ])
    );
  });

  it('imports exactly the row asked for', async () => {
    const user = userEvent.setup();
    render(<ShadowApisClient initialConnector={null} />);
    await user.click(within(await screen.findByTestId('shadow-row-metrics')).getByTestId('shadow-import-metrics'));
    await waitFor(() => expect(posts).toEqual([{ url: '/api/connectors/c1/items/metrics/import', body: undefined }]));
    await waitFor(() => expect(mockToast.success).toHaveBeenCalledWith('Service metrics was imported into the catalog.'));
  });

  it('says the inventory is stale rather than showing a clean empty list', async () => {
    current = baseReport({
      shadow: [],
      possibleMatches: [],
      summary: { shadow: 0, possibleMatches: 0, drift: 0, undeployed: 0, ignored: 0 },
      stale: [
        {
          connectorId: 'c1',
          connectorName: 'Prod Kong',
          since: '2026-10-17T09:30:00Z',
          message: 'Inventory stale since 2026-10-17T09:30:00Z: the last sync of Prod Kong failed.',
        },
      ],
    });
    render(<ShadowApisClient initialConnector={null} />);
    expect(await screen.findByTestId('shadow-stale')).toHaveTextContent('Inventory stale since 2026-10-17T09:30:00Z');
    expect(screen.getByTestId('shadow-empty')).toHaveTextContent(/stale/);
  });

  it('shows a reappeared ignored API with its old reason', async () => {
    current = baseReport({
      shadow: [
        item('quiet', {
          ignored: { reason: 'Health check', at: null, by: null, hosts: ['old.example.com'], basePath: null, reappeared: true },
        }),
      ],
    });
    render(<ShadowApisClient initialConnector={null} />);
    expect(await screen.findByTestId('shadow-reappeared-quiet')).toHaveTextContent('Ignored before (“Health check”)');
  });

  it('stops ignoring from the Ignored section', async () => {
    current = baseReport({
      ignored: [item('quiet', { status: 'ignored', ignored: { reason: 'Health check', at: null, by: null, hosts: [], basePath: null, reappeared: false } })],
      summary: { shadow: 2, possibleMatches: 1, drift: 0, undeployed: 0, ignored: 1 },
    });
    const user = userEvent.setup();
    render(<ShadowApisClient initialConnector={null} />);
    await user.click(await screen.findByTestId('shadow-section-ignored'));
    const row = await screen.findByTestId('shadow-row-quiet');
    expect(row).toHaveTextContent('Health check');
    await user.click(within(row).getByTestId('shadow-unignore-quiet'));
    await waitFor(() => expect(posts).toEqual([{ url: '/api/connectors/c1/items/quiet/unignore', body: undefined }]));
  });

  it('lists undeployed APIs with their servers', async () => {
    current = baseReport({
      undeployed: [
        { projectId: 'p-idle', name: 'Idle API', kind: 'catalog-item', versionId: null, versionLabel: '2', servers: ['https://idle.example.com'] },
      ],
      summary: { shadow: 2, possibleMatches: 1, drift: 0, undeployed: 1, ignored: 0 },
    });
    const user = userEvent.setup();
    render(<ShadowApisClient initialConnector={null} />);
    await user.click(await screen.findByTestId('shadow-section-undeployed'));
    const row = await screen.findByTestId('shadow-undeployed-p-idle');
    expect(within(row).getByRole('link', { name: 'Idle API' })).toHaveAttribute('href', '/ade/dashboard/catalog/p-idle');
    expect(row).toHaveTextContent('https://idle.example.com');
  });

  it('explains what to do with no connector', async () => {
    current = baseReport({ connectors: [] });
    render(<ShadowApisClient initialConnector={null} />);
    expect(await screen.findByTestId('shadow-no-connectors')).toHaveTextContent('Connect a gateway');
  });

  it('offers a retry when the report cannot be read', async () => {
    global.fetch = jest.fn(async () => reply({ error: 'Report unavailable. Try again.' }, 503)) as unknown as typeof fetch;
    render(<ShadowApisClient initialConnector={null} />);
    const alert = await screen.findByTestId('shadow-error');
    expect(alert).toHaveTextContent('Report unavailable');
    expect(within(alert).getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('dumps the docs screenshot fixtures (shadow-apis, shadow-apis-link)', async () => {
    current = baseReport({
      connectors: [
        { id: 'c1', name: 'Prod Kong', kind: 'kong-admin', status: 'active', itemCount: 5, stale: false, staleSince: null },
        { id: 'c2', name: 'APIM production', kind: 'azure-apim', status: 'active', itemCount: 3, stale: false, staleSince: null },
      ],
      shadow: [
        item('billing', { name: 'Legacy billing', hosts: ['billing.internal.example.com'], basePath: '/v1' }),
        item('metrics', {
          name: 'Internal metrics',
          connectorId: 'c2',
          connectorName: 'APIM production',
          hosts: ['https://contoso-apim.azure-api.net/metrics'],
        }),
      ],
      possibleMatches: [
        item('orders', {
          name: 'orders-gateway',
          hosts: ['orders.example.com'],
          basePath: '/v2',
          match: MATCH,
          alternatives: [ALTERNATIVE],
        }),
      ],
      summary: { shadow: 2, possibleMatches: 1, drift: 1, undeployed: 2, ignored: 1 },
    });
    const user = userEvent.setup();
    render(<ShadowApisClient initialConnector={null} />);
    await screen.findByText('Legacy billing');
    const page = () => (document.querySelector('.page') ?? document.body.firstElementChild) as HTMLElement;
    writeA11yFixture('shadow-apis', page().outerHTML);

    await user.click(screen.getByTestId('shadow-section-possibleMatches'));
    await user.click(await screen.findByTestId('shadow-link-orders'));
    writeA11yFixture('shadow-apis-link', (await screen.findByTestId('shadow-link-dialog')).outerHTML);
  });
});
