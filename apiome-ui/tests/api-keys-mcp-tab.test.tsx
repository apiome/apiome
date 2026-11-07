/**
 * The API keys page's **MCP server** tab, rendered.
 *
 * `api-keys-hive-redesign.test.tsx` holds the REST tab; this holds the MCP one, against a
 * `fetch` that answers the `/api/tenants/mcp-keys` proxies with the envelopes they really
 * return. What it pins:
 *
 *   1. Both kinds of key are on one page, each in its own tab, with a count.
 *   2. The MCP tab lists the workspace's MCP keys — revoked ones too, with nothing to press.
 *   3. Creating an MCP key sends a label and an expiry and reveals the secret once.
 *   4. Revoking asks first and reports a refusal in the dialog.
 *   5. A member who does not administer the workspace is told so, and the list is not read.
 */

import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

const TENANT_ID = 't-acme';

/** The REST keys the REST tab reads — empty, except in the docs fixture. */
let restKeysResponse = '[]';

jest.mock('../lib/db/helper-actions', () => ({
  getApiKeysForTenant: jest.fn(async () => restKeysResponse),
  createApiKey: jest.fn(async () => ''),
  deleteApiKey: jest.fn(async () => JSON.stringify({ success: true })),
  toggleApiKeyStatus: jest.fn(async () => JSON.stringify({ success: true })),
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), refresh: jest.fn() }),
  usePathname: () => '/ade/dashboard/api-keys',
  useSearchParams: () => new URLSearchParams(),
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({
    data: { user: { user_id: 'u-ada', email: 'ada@acme.io', current_tenant_id: TENANT_ID } },
    status: 'authenticated',
    update: jest.fn(),
  }),
  AuthSessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

/** Which tenants the reader administers. Reassigned by the member test. */
let adminTenantIds: string[] = [TENANT_ID];
/** The workspace's name in the membership context. */
let tenantName = 'Acme Corp';

jest.mock('@lib/auth/tenant-membership-context', () => ({
  loadTenantMembershipContext: jest.fn(async () => ({
    tenants: [{ id: 't-acme', name: tenantName, slug: 'acme' }],
    adminTenantIds,
    createTenant: null,
  })),
}));

import ApiKeysClient from '../src/app/ade/dashboard/api-keys/ApiKeysClient';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const FAR_FUTURE = '2099-01-02T00:00:00Z';

const MCP_KEYS = [
  {
    id: 'm-claude',
    prefix: 'aB3dE5gH7jK9...',
    label: 'Claude Desktop',
    scope_json: { tenants: [], projects: [] },
    capability_mode: 'inherit',
    enabled_tools: [],
    created_at: '2026-10-01T10:00:00Z',
    expires_at: FAR_FUTURE,
    revoked_at: null,
    last_used_at: '2026-11-06T18:20:00Z',
  },
  {
    id: 'm-cursor',
    prefix: 'zZ9yY8xX7wW6...',
    label: 'Cursor',
    scope_json: { tenants: [], projects: [] },
    capability_mode: 'explicit',
    enabled_tools: ['spec.list', 'spec.describe'],
    created_at: '2026-09-12T08:00:00Z',
    expires_at: null,
    revoked_at: '2026-10-20T09:00:00Z',
    last_used_at: '2026-10-19T17:00:00Z',
  },
];

const MCP_SECRET = 'aB9cD8eF7gH6iJ5kL4mN3oP2qR1sT0uV9wX8yZ7';

/** Every request the page made, as `METHOD url body`. */
let requests: { method: string; url: string; body: unknown }[] = [];
/** The MCP list the next GET answers with. */
let listedKeys: typeof MCP_KEYS = MCP_KEYS;
/** What the next revoke answers with. */
let revokeAnswer: { success: boolean; error?: string } = { success: true };

function installFetch() {
  global.fetch = jest.fn(async (input: unknown, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    requests.push({ method, url, body });
    let payload: unknown = { success: false, error: 'unexpected request' };
    if (url === '/api/tenants/mcp-keys' && method === 'GET') {
      payload = { success: true, data: { keys: listedKeys } };
    } else if (url === '/api/tenants/mcp-keys' && method === 'POST') {
      payload = {
        success: true,
        data: { ...MCP_KEYS[0], id: 'm-new', label: body.label, prefix: 'aB9cD8eF7gH6...', secret: MCP_SECRET },
      };
    } else if (url.startsWith('/api/tenants/mcp-keys/') && method === 'DELETE') {
      payload = revokeAnswer.success ? { success: true, data: null } : revokeAnswer;
    }
    return { json: async () => payload } as Response;
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  requests = [];
  listedKeys = MCP_KEYS;
  revokeAnswer = { success: true };
  adminTenantIds = [TENANT_ID];
  tenantName = 'Acme Corp';
  restKeysResponse = '[]';
  installFetch();
});

/** Render the page and open the MCP tab. */
async function openMcpTab() {
  const user = userEvent.setup();
  render(<ApiKeysClient />);
  const tab = await screen.findByTestId('api-keys-tab-mcp');
  await user.click(tab);
  return { user };
}

function rowFor(label: string): HTMLElement {
  const cell = document.querySelector(`[data-mcp-key-label="${label}"]`);
  const row = cell?.closest('tr');
  if (!row) throw new Error(`No row for ${label}`);
  return row as HTMLElement;
}

describe('one page for both kinds of key', () => {
  it('offers a REST API tab and an MCP server tab, REST first', async () => {
    render(<ApiKeysClient />);
    const tabs = await screen.findAllByRole('tab');
    expect(tabs.map((tab) => tab.textContent?.replace(/\d+$/, ''))).toEqual(['REST API', 'MCP server']);
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true');
  });

  it('counts the MCP keys on their tab before it is opened', async () => {
    render(<ApiKeysClient />);
    await waitFor(() => expect(screen.getByTestId('api-keys-tab-mcp')).toHaveTextContent('MCP server2'));
  });

  it('turns the header button into Create MCP key on the MCP tab', async () => {
    await openMcpTab();
    expect(screen.getByTestId('mcp-keys-create')).toHaveTextContent('Create MCP key');
    expect(screen.queryByTestId('api-keys-create')).not.toBeInTheDocument();
  });

  it('points the REST create dialog at the MCP tab for MCP hosts', async () => {
    const user = userEvent.setup();
    render(<ApiKeysClient />);
    await user.click(await screen.findByTestId('api-keys-create'));
    expect(await screen.findByTestId('api-key-create-dialog')).toHaveTextContent(
      'For an MCP host or agent, create an MCP key on the MCP server tab.'
    );
  });
});

describe('the MCP keys table', () => {
  it('lists every key with its prefix, tools and status', async () => {
    await openMcpTab();
    await screen.findByText('Claude Desktop');
    const claude = rowFor('Claude Desktop');
    expect(claude).toHaveTextContent('aB3dE5gH7jK9…');
    expect(claude).toHaveTextContent('Workspace defaults');
    expect(claude).toHaveTextContent('Active');
    const cursor = rowFor('Cursor');
    expect(cursor).toHaveTextContent('Custom · 2 tools');
    expect(cursor).toHaveTextContent('Revoked');
    expect(screen.getByTestId('mcp-keys-summary')).toHaveTextContent('2 keys · 1 active · 1 revoked');
  });

  it('offers Revoke on an active key and nothing on a revoked one', async () => {
    await openMcpTab();
    await screen.findByText('Claude Desktop');
    expect(screen.getByTestId('mcp-key-revoke-m-claude')).toBeInTheDocument();
    expect(screen.queryByTestId('mcp-key-revoke-m-cursor')).not.toBeInTheDocument();
  });

  it('shows how to connect a host and where capabilities are edited', async () => {
    await openMcpTab();
    expect(await screen.findByTestId('mcp-keys-example-config')).toHaveTextContent(
      'Authorization: Bearer <your-mcp-key>'
    );
    expect(screen.getByTestId('mcp-keys-workspaces-link')).toHaveAttribute('href', '/ade/dashboard/tenants');
  });

  it('says "No MCP keys yet" when there are none', async () => {
    listedKeys = [];
    await openMcpTab();
    expect(await screen.findByText('No MCP keys yet')).toBeInTheDocument();
  });
});

describe('creating an MCP key', () => {
  it('sends the label and expiry, then reveals the secret once', async () => {
    const { user } = await openMcpTab();
    await user.click(screen.getByTestId('mcp-keys-create'));
    const dialog = await screen.findByTestId('mcp-key-create-dialog');
    await user.type(within(dialog).getByLabelText(/^Label/), 'Claude Code');
    await user.type(within(dialog).getByLabelText('Expires in (days)'), '30');
    await user.click(within(dialog).getByTestId('mcp-key-create-submit'));

    const reveal = await screen.findByTestId('api-key-secret-dialog');
    expect(reveal).toHaveTextContent('MCP key created');
    expect(within(reveal).getByTestId('api-key-secret-value')).toHaveTextContent(MCP_SECRET);
    expect(reveal).toHaveTextContent('“Claude Code” · workspace default tools · expires in 30 days');

    const post = requests.find((r) => r.method === 'POST');
    expect(post?.body).toMatchObject({ label: 'Claude Code' });
    expect(typeof (post?.body as { expires_at: string }).expires_at).toBe('string');

    await user.click(within(reveal).getByTestId('api-key-secret-ack'));
    await waitFor(() => expect(screen.queryByTestId('api-key-secret-dialog')).not.toBeInTheDocument());
    expect(document.body.textContent).not.toContain(MCP_SECRET);
  });

  it('requires a label before anything is sent', async () => {
    const { user } = await openMcpTab();
    await user.click(screen.getByTestId('mcp-keys-create'));
    const dialog = await screen.findByTestId('mcp-key-create-dialog');
    await user.click(within(dialog).getByTestId('mcp-key-create-submit'));
    expect(within(dialog).getByTestId('mcp-key-create-error')).toHaveTextContent('Label is required');
    expect(requests.some((r) => r.method === 'POST')).toBe(false);
  });
});

describe('revoking an MCP key', () => {
  it('asks first, naming the key, then revokes and reloads', async () => {
    const { user } = await openMcpTab();
    await user.click(await screen.findByTestId('mcp-key-revoke-m-claude'));
    const dialog = await screen.findByTestId('mcp-key-revoke-dialog');
    expect(dialog).toHaveTextContent('Claude Desktop');
    expect(dialog).toHaveTextContent('aB3dE5gH7jK9…');
    expect(requests.some((r) => r.method === 'DELETE')).toBe(false);

    await user.click(within(dialog).getByTestId('mcp-key-revoke-confirm'));
    await waitFor(() => expect(screen.queryByTestId('mcp-key-revoke-dialog')).not.toBeInTheDocument());
    expect(requests.find((r) => r.method === 'DELETE')?.url).toBe('/api/tenants/mcp-keys/m-claude');
    expect(requests.filter((r) => r.method === 'GET')).toHaveLength(2);
  });

  it('reports a refused revoke in the dialog', async () => {
    revokeAnswer = { success: false, error: 'MCP API key not found' };
    const { user } = await openMcpTab();
    await user.click(await screen.findByTestId('mcp-key-revoke-m-claude'));
    const dialog = await screen.findByTestId('mcp-key-revoke-dialog');
    await user.click(within(dialog).getByTestId('mcp-key-revoke-confirm'));
    expect(await within(dialog).findByText('MCP API key not found')).toBeInTheDocument();
  });
});

describe('a member who does not administer the workspace', () => {
  it('is told who manages MCP keys, and the list is not read', async () => {
    adminTenantIds = [];
    await openMcpTab();
    expect(await screen.findByTestId('mcp-keys-admin-only')).toHaveTextContent(
      'Only workspace administrators manage MCP keys'
    );
    expect(screen.queryByTestId('mcp-keys-create')).not.toBeInTheDocument();
    expect(requests.some((r) => r.url === '/api/tenants/mcp-keys')).toBe(false);
  });
});

/**
 * The documentation site's MCP tab screenshot (`apiome-docs/screens.json`, `api-keys-mcp`):
 * `A11Y_FIXTURE_DUMP=1 npx jest tests/api-keys-mcp-tab.test.tsx -t "docs fixture"`.
 */
describe('the docs fixture', () => {
  beforeEach(() => {
    jest.useFakeTimers({
      now: new Date('2026-10-07T09:30:00Z').getTime(),
      doNotFake: [
        'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'setImmediate', 'clearImmediate',
        'queueMicrotask', 'nextTick', 'requestAnimationFrame', 'cancelAnimationFrame',
        'requestIdleCallback', 'cancelIdleCallback', 'hrtime', 'performance',
      ],
    });
    tenantName = 'Northwind';
    // A workspace with REST keys too, so the tab strip reads like a real one.
    restKeysResponse = JSON.stringify(
      ['CI contract gate', 'Terraform plan checks', 'Nightly lint', 'Release automation'].map(
        (name, index) => ({
          id: `k-${index}`,
          tenant_id: TENANT_ID,
          name,
          description: '',
          key_prefix: `sk_${index}aaaaaaaaa...`,
          scopes: ['diff:read'],
          last_used_at: null,
          expires_at: null,
          enabled: true,
          created_at: '2026-07-07T10:14:00Z',
          updated_at: '2026-07-07T10:14:00Z',
        })
      )
    );
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('renders the MCP server tab', async () => {
    await openMcpTab();
    await screen.findByText('Claude Desktop');
    await screen.findByText('Northwind', { selector: 'strong' });
    await waitFor(() => expect(screen.getByTestId('api-keys-tab-rest')).toHaveTextContent('REST API4'));
    writeA11yFixture('api-keys-mcp', liveMarkup(document.querySelector('.page') as HTMLElement));
  });
});
