/**
 * The API keys page's one list — MCP server keys beside REST API keys — and Regenerate.
 *
 * `api-keys-hive-redesign.test.tsx` holds the REST keys' own behaviour; this holds the MCP keys
 * in the same list and the regenerate flow for both kinds, against a `fetch` that answers the
 * `/api/tenants/mcp-keys` proxies with the envelopes they really return. What it pins:
 *
 *   1. Both kinds of key are in one table, each row badged with its type, and the Type filter
 *      narrows to one kind.
 *   2. MCP rows show prefix, tools and status — revoked ones too, with nothing to press.
 *   3. Creating an MCP key sends a label and an expiry and reveals the secret once.
 *   4. Revoking asks first and reports a refusal in the dialog.
 *   5. Regenerate asks first, replaces the secret of the same key — REST or MCP — and reveals
 *      the new one once; it is not offered on expired or revoked keys.
 *   6. A member who does not administer the workspace sees the REST keys, a sentence about MCP
 *      keys, and the MCP list is not read; a failed MCP read leaves the REST rows in place.
 */

import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

const TENANT_ID = 't-acme';

/** The REST keys the list reads. */
let restKeysResponse = '[]';
/** What the next REST regenerate answers with. */
let regenerateRestResponse = '';
/** Every REST key regenerated, by id. */
const regeneratedRestIds: string[] = [];

jest.mock('../lib/db/helper-actions', () => ({
  getApiKeysForTenant: jest.fn(async () => restKeysResponse),
  createApiKey: jest.fn(async () => ''),
  deleteApiKey: jest.fn(async () => JSON.stringify({ success: true })),
  toggleApiKeyStatus: jest.fn(async () => JSON.stringify({ success: true })),
  regenerateApiKey: jest.fn(async (id: unknown) => {
    regeneratedRestIds.push(String(id));
    return regenerateRestResponse;
  }),
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
const REGENERATED_MCP_SECRET = 'Qw1Er2Ty3Ui4Op5As6Df7Gh8Jk9Lz0Xc1Vb2Nm3';
const REGENERATED_REST_SECRET = 'sk_0e1d2c3b4a5968778695a4b3c2d1e0f1a2b3c4d5';

/** Two REST keys: one live, one expired. */
const REST_KEYS = [
  {
    id: 'k-gate',
    tenant_id: TENANT_ID,
    name: 'CI contract gate',
    description: 'Blocks merges on breaking diffs.',
    key_prefix: 'sk_9f31c2Qm...',
    scopes: ['diff:read'],
    last_used_at: '2026-11-06T06:12:00Z',
    expires_at: FAR_FUTURE,
    enabled: true,
    created_at: '2026-10-05T10:14:00Z',
    updated_at: '2026-10-05T10:14:00Z',
  },
  {
    id: 'k-old',
    tenant_id: TENANT_ID,
    name: 'Partner sync',
    description: '',
    key_prefix: 'sk_c41d88Aa...',
    scopes: ['*'],
    last_used_at: null,
    expires_at: '2026-01-01T00:00:00Z',
    enabled: true,
    created_at: '2025-06-01T00:00:00Z',
    updated_at: '2025-06-01T00:00:00Z',
  },
];

/** Every request the page made, as `METHOD url body`. */
let requests: { method: string; url: string; body: unknown }[] = [];
/** The MCP list the next GET answers with. */
let listedKeys: typeof MCP_KEYS = MCP_KEYS;
/** What the next revoke answers with. */
let revokeAnswer: { success: boolean; error?: string } = { success: true };
/** What the next MCP list read answers with when it fails. */
let mcpListFailure: string | null = null;

function installFetch() {
  global.fetch = jest.fn(async (input: unknown, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    requests.push({ method, url, body });
    let payload: unknown = { success: false, error: 'unexpected request' };
    if (url === '/api/tenants/mcp-keys' && method === 'GET') {
      payload = mcpListFailure
        ? { success: false, error: mcpListFailure }
        : { success: true, data: { keys: listedKeys } };
    } else if (url === '/api/tenants/mcp-keys' && method === 'POST') {
      payload = {
        success: true,
        data: { ...MCP_KEYS[0], id: 'm-new', label: body.label, prefix: 'aB9cD8eF7gH6...', secret: MCP_SECRET },
      };
    } else if (url.endsWith('/regenerate') && method === 'POST') {
      payload = {
        success: true,
        data: { ...MCP_KEYS[0], prefix: 'Qw1Er2Ty3Ui4...', secret: REGENERATED_MCP_SECRET },
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
  mcpListFailure = null;
  restKeysResponse = JSON.stringify(REST_KEYS);
  regeneratedRestIds.length = 0;
  regenerateRestResponse = JSON.stringify({
    success: true,
    apiKey: REGENERATED_REST_SECRET,
    id: 'k-gate',
    keyPrefix: 'sk_0e1d2c3b...',
    scopes: ['diff:read'],
  });
  installFetch();
});

/** Render the page and wait for both lists. */
async function renderPage() {
  const user = userEvent.setup();
  render(<ApiKeysClient />);
  await screen.findByText('CI contract gate');
  await screen.findByText('Claude Desktop');
  return { user };
}

/**
 * The `<tr>` of one key.
 *
 * @param name A REST key's name or an MCP key's label.
 * @returns The row.
 */
function rowFor(name: string): HTMLElement {
  const cell = document.querySelector(
    `[data-mcp-key-label="${name}"], [data-api-key-name="${name}"]`
  );
  const row = cell?.closest('tr');
  if (!row) throw new Error(`No row for ${name}`);
  return row as HTMLElement;
}

describe('one list for both kinds of key', () => {
  it('has no tabs — both kinds are rows of the same table, newest first', async () => {
    await renderPage();
    expect(screen.queryAllByRole('tab')).toHaveLength(0);
    const table = screen.getByTestId('api-keys-table');
    const names = within(table)
      .getAllByTestId(/^(api|mcp)-key-row$/)
      .map((cell) => cell.getAttribute('data-api-key-name') ?? cell.getAttribute('data-mcp-key-label'));
    expect(names).toEqual(['CI contract gate', 'Claude Desktop', 'Cursor', 'Partner sync']);
  });

  it('badges each row with its type', async () => {
    await renderPage();
    expect(screen.getByTestId('key-type-mcp-m-claude')).toHaveTextContent('MCP server');
    expect(screen.getByTestId('key-type-rest-k-gate')).toHaveTextContent('REST API');
  });

  it('narrows to one kind with the Type filter', async () => {
    const { user } = await renderPage();
    await user.click(screen.getByRole('radio', { name: 'MCP server' }));
    expect(screen.queryByText('CI contract gate')).not.toBeInTheDocument();
    expect(screen.getByText('Claude Desktop')).toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: 'REST API' }));
    expect(screen.queryByText('Claude Desktop')).not.toBeInTheDocument();
    expect(screen.getByText('CI contract gate')).toBeInTheDocument();
  });

  it('counts both kinds in the foot', async () => {
    await renderPage();
    expect(screen.getByTestId('api-keys-summary')).toHaveTextContent(
      '4 keys · 2 REST API · 2 MCP server · 2 active · 1 expired · 1 revoked'
    );
  });

  it('offers both create buttons in the header, REST on N', async () => {
    await renderPage();
    expect(screen.getByTestId('mcp-keys-create')).toHaveTextContent('Create MCP key');
    expect(screen.getByTestId('api-keys-create')).toHaveTextContent('Create API key');
  });

  it('points the REST create dialog at Create MCP key for MCP hosts', async () => {
    const { user } = await renderPage();
    await user.click(screen.getByTestId('api-keys-create'));
    expect(await screen.findByTestId('api-key-create-dialog')).toHaveTextContent(
      'For an MCP host or agent, use Create MCP key instead.'
    );
  });
});

describe('MCP rows', () => {
  it('show prefix, tools and status', async () => {
    await renderPage();
    const claude = rowFor('Claude Desktop');
    expect(claude).toHaveTextContent('aB3dE5gH7jK9…');
    expect(claude).toHaveTextContent('Workspace defaults');
    expect(claude).toHaveTextContent('Active');
    const cursor = rowFor('Cursor');
    expect(cursor).toHaveTextContent('Custom · 2 tools');
    expect(cursor).toHaveTextContent('Revoked');
  });

  it('offer Revoke and Regenerate on an active key and nothing on a revoked one', async () => {
    await renderPage();
    expect(screen.getByTestId('mcp-key-revoke-m-claude')).toBeInTheDocument();
    expect(screen.getByTestId('key-regenerate-mcp-m-claude')).toBeInTheDocument();
    expect(screen.queryByTestId('mcp-key-revoke-m-cursor')).not.toBeInTheDocument();
    expect(screen.queryByTestId('key-regenerate-mcp-m-cursor')).not.toBeInTheDocument();
  });

  it('come with how to connect a host and where capabilities are edited', async () => {
    await renderPage();
    expect(screen.getByTestId('mcp-keys-example-config')).toHaveTextContent(
      'Authorization: Bearer <your-mcp-key>'
    );
    expect(screen.getByTestId('mcp-keys-workspaces-link')).toHaveAttribute('href', '/ade/dashboard/tenants');
  });

  it('leave the REST rows in place when the MCP read fails, with a retry', async () => {
    mcpListFailure = 'MCP service unavailable';
    render(<ApiKeysClient />);
    expect(await screen.findByTestId('mcp-keys-load-error')).toHaveTextContent('MCP service unavailable');
    expect(screen.getByText('CI contract gate')).toBeInTheDocument();
  });

  it('offers both kinds from the empty state when there are no keys at all', async () => {
    listedKeys = [];
    restKeysResponse = '[]';
    render(<ApiKeysClient />);
    expect(await screen.findByText('No API keys yet')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /Create MCP key/ }).length).toBeGreaterThan(1);
  });
});

describe('creating an MCP key', () => {
  it('sends the label and expiry, then reveals the secret once', async () => {
    const { user } = await renderPage();
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
    const { user } = await renderPage();
    await user.click(screen.getByTestId('mcp-keys-create'));
    const dialog = await screen.findByTestId('mcp-key-create-dialog');
    await user.click(within(dialog).getByTestId('mcp-key-create-submit'));
    expect(within(dialog).getByTestId('mcp-key-create-error')).toHaveTextContent('Label is required');
    expect(requests.some((r) => r.method === 'POST')).toBe(false);
  });
});

describe('revoking an MCP key', () => {
  it('asks first, naming the key, then revokes and reloads', async () => {
    const { user } = await renderPage();
    await user.click(screen.getByTestId('mcp-key-revoke-m-claude'));
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
    const { user } = await renderPage();
    await user.click(screen.getByTestId('mcp-key-revoke-m-claude'));
    const dialog = await screen.findByTestId('mcp-key-revoke-dialog');
    await user.click(within(dialog).getByTestId('mcp-key-revoke-confirm'));
    expect(await within(dialog).findByText('MCP API key not found')).toBeInTheDocument();
  });
});

describe('regenerating a key', () => {
  it('asks first, naming the key and the secret about to stop working', async () => {
    const { user } = await renderPage();
    await user.click(screen.getByTestId('key-regenerate-mcp-m-claude'));
    const dialog = await screen.findByTestId('key-regenerate-dialog');
    expect(dialog).toHaveTextContent('Regenerate MCP server key');
    expect(dialog).toHaveTextContent('Claude Desktop');
    expect(dialog).toHaveTextContent('aB3dE5gH7jK9…');
    expect(within(dialog).getByTestId('key-regenerate-warning')).toHaveTextContent(
      'The current secret stops working immediately'
    );
    expect(requests.some((r) => r.url.endsWith('/regenerate'))).toBe(false);
  });

  it('regenerates the same MCP key and reveals the new secret once', async () => {
    const { user } = await renderPage();
    await user.click(screen.getByTestId('key-regenerate-mcp-m-claude'));
    const dialog = await screen.findByTestId('key-regenerate-dialog');
    await user.click(within(dialog).getByTestId('key-regenerate-confirm'));

    const reveal = await screen.findByTestId('api-key-secret-dialog');
    expect(reveal).toHaveTextContent('MCP key regenerated');
    expect(within(reveal).getByTestId('api-key-secret-value')).toHaveTextContent(REGENERATED_MCP_SECRET);
    expect(reveal).toHaveTextContent('“Claude Desktop” · MCP server · same tools and expiry');
    const post = requests.find((r) => r.url.endsWith('/regenerate'));
    expect(post).toMatchObject({ method: 'POST', url: '/api/tenants/mcp-keys/m-claude/regenerate' });
    // No new key was created.
    expect(requests.some((r) => r.url === '/api/tenants/mcp-keys' && r.method === 'POST')).toBe(false);

    await user.click(within(reveal).getByTestId('api-key-secret-ack'));
    await waitFor(() => expect(screen.queryByTestId('api-key-secret-dialog')).not.toBeInTheDocument());
    expect(document.body.textContent).not.toContain(REGENERATED_MCP_SECRET);
  });

  it('regenerates the same REST key and reveals the new secret once', async () => {
    const { user } = await renderPage();
    await user.click(screen.getByTestId('key-regenerate-rest-k-gate'));
    const dialog = await screen.findByTestId('key-regenerate-dialog');
    expect(dialog).toHaveTextContent('Regenerate REST API key');
    expect(dialog).toHaveTextContent('Its name, scopes and expiry stay the same.');
    await user.click(within(dialog).getByTestId('key-regenerate-confirm'));

    const reveal = await screen.findByTestId('api-key-secret-dialog');
    expect(reveal).toHaveTextContent('API key regenerated');
    expect(within(reveal).getByTestId('api-key-secret-value')).toHaveTextContent(REGENERATED_REST_SECRET);
    expect(reveal).toHaveTextContent('sk_0e1d2c3b…');
    expect(regeneratedRestIds).toEqual(['k-gate']);
  });

  it('reports a refused regenerate in the dialog and keeps it open', async () => {
    regenerateRestResponse = JSON.stringify({
      success: false,
      error: 'Only a key that has not expired or been deleted can be regenerated',
    });
    const { user } = await renderPage();
    await user.click(screen.getByTestId('key-regenerate-rest-k-gate'));
    const dialog = await screen.findByTestId('key-regenerate-dialog');
    await user.click(within(dialog).getByTestId('key-regenerate-confirm'));
    expect(
      await within(dialog).findByText('Only a key that has not expired or been deleted can be regenerated')
    ).toBeInTheDocument();
    expect(screen.queryByTestId('api-key-secret-dialog')).not.toBeInTheDocument();
  });

  it('is not offered on an expired key', async () => {
    await renderPage();
    expect(screen.queryByTestId('key-regenerate-rest-k-old')).not.toBeInTheDocument();
    expect(screen.getByTestId('api-key-delete-k-old')).toBeInTheDocument();
  });
});

describe('a member who does not administer the workspace', () => {
  it('sees the REST keys and who manages MCP keys, and the MCP list is not read', async () => {
    adminTenantIds = [];
    render(<ApiKeysClient />);
    await screen.findByText('CI contract gate');
    expect(await screen.findByTestId('mcp-keys-admin-only')).toHaveTextContent(
      'MCP server keys are managed by workspace administrators'
    );
    expect(screen.queryByTestId('mcp-keys-create')).not.toBeInTheDocument();
    expect(screen.queryByTestId('mcp-keys-example-config')).not.toBeInTheDocument();
    expect(requests.some((r) => r.url === '/api/tenants/mcp-keys')).toBe(false);
  });
});

/**
 * The documentation site's screenshots (`apiome-docs/screens.json`): `api-keys-mcp` (the list
 * narrowed to MCP server keys) and `api-keys-regenerate` (the regenerate confirm):
 * `A11Y_FIXTURE_DUMP=1 npx jest tests/api-keys-mcp-and-regenerate.test.tsx -t "docs fixture"`.
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
    restKeysResponse = JSON.stringify([
      { ...REST_KEYS[0], last_used_at: '2026-10-07T06:12:00Z', created_at: '2026-07-07T10:14:00Z' },
    ]);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  /** Everything rendered — the page, and any dialog portalled over it — without the `<body>`. */
  const bodyMarkup = () => liveMarkup(document.body).replace(/^<body[^>]*>|<\/body>$/g, '');

  it('renders the list narrowed to MCP server keys, and the regenerate confirm', async () => {
    const { user } = await renderPage();
    await screen.findAllByText('Northwind', { selector: 'strong' });
    await user.click(screen.getByRole('radio', { name: 'MCP server' }));
    writeA11yFixture('api-keys-mcp', liveMarkup(document.querySelector('.page') as HTMLElement));

    await user.click(screen.getByRole('radio', { name: 'All types' }));
    await user.click(screen.getByTestId('key-regenerate-rest-k-gate'));
    await screen.findByTestId('key-regenerate-dialog');
    writeA11yFixture('api-keys-regenerate', bodyMarkup());
  });
});
