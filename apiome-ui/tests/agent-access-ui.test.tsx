/**
 * MCP → Agent access, rendered — AGX-3.4 (#4540).
 *
 * `agent-access-model.test.ts` holds the derivations; this drives the page against a fake
 * `/api/agent-access/*` and a mocked published-versions server action, and pins the ticket's
 * acceptance criteria:
 *
 *   1. **Published version → working agent key with a curated toolset, entirely in the UI**:
 *      enable Agent Access on a version, switch a tool off, mint a key for the toolset, see its
 *      secret once.
 *   2. **Enabling a write operation surfaces the explicit confirmation** — and only the dialog's
 *      confirm sends `confirmWriteOp: true`; cancelling sends nothing.
 *   3. **Charts render calls/tool, errors, latency and top agents from the rollups**, and a
 *      window without calls is an empty state rather than flat charts.
 */

import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

const TENANT_ID = 't-acme';

jest.mock('../lib/db/helper', () => ({
  getPublishedVersionsForTenant: jest.fn(async () =>
    JSON.stringify({
      success: true,
      versions: [
        { id: 'v-1', version_id: '1.0.0', project_id: 'p-1', project_name: 'Pet Store' },
        { id: 'v-2', version_id: '2.0.0', project_id: 'p-1', project_name: 'Pet Store' },
      ],
    })
  ),
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), refresh: jest.fn() }),
  usePathname: () => '/ade/dashboard/mcp/agents',
  useSearchParams: () => new URLSearchParams(),
}));

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

let mockSessionUser: Record<string, unknown> = { user_id: 'u-ada', current_tenant_id: TENANT_ID };

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({ data: { user: mockSessionUser }, status: 'authenticated', update: jest.fn() }),
  AuthSessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

import AgentAccessClient from '../src/app/ade/dashboard/mcp/agents/AgentAccessClient';

// ---------------------------------------------------------------------------------------
// The fake BFF
// ---------------------------------------------------------------------------------------

interface Tool {
  id: string;
  operation: string;
  toolName: string;
  writeOp: boolean;
  enabled: boolean;
}

/** Server-side state, reset per test. */
let toolsets: Array<Record<string, unknown> & { tools: Tool[] }> = [];
let keys: Array<Record<string, unknown>> = [];
let usageReply: Record<string, unknown> = {};
/** Every request the page made: method, path, body. */
let requests: Array<{ method: string; path: string; body: unknown }> = [];

function seedToolset(): void {
  toolsets = [
    {
      id: 'ts-1',
      versionId: 'v-1',
      projectId: 'p-1',
      versionLabel: '1.0.0',
      enabled: true,
      target: 'prod',
      toolCount: 3,
      enabledToolCount: 2,
      enabledWriteOpCount: 0,
      tools: [
        { id: 'tool-list', operation: 'GET /pets', toolName: 'listPets', writeOp: false, enabled: true },
        { id: 'tool-get', operation: 'GET /pets/{id}', toolName: 'getPet', writeOp: false, enabled: true },
        { id: 'tool-create', operation: 'POST /pets', toolName: 'createPet', writeOp: true, enabled: false },
      ],
    },
  ];
}

function counts(ts: { tools: Tool[] }) {
  return {
    toolCount: ts.tools.length,
    enabledToolCount: ts.tools.filter((t) => t.enabled).length,
    enabledWriteOpCount: ts.tools.filter((t) => t.enabled && t.writeOp).length,
  };
}

/** A fetch reply. jsdom has no WHATWG `Response`, so this is the shape the client reads. */
type Reply = { ok: boolean; status: number; json: () => Promise<unknown> };

function reply(body: unknown, status: number): Reply {
  return { ok: status < 400, status, json: async () => body };
}

function ok(data: unknown, status = 200): Reply {
  return reply({ success: true, data }, status);
}

function refuse(error: string, status: number, code?: string): Reply {
  return reply({ success: false, error, ...(code ? { code } : {}) }, status);
}

/** Route one request like the BFF + apiome-rest would. */
async function handle(path: string, method: string, body: unknown): Promise<Reply> {
  const url = new URL(path, 'http://ui.test');
  const parts = url.pathname.replace('/api/agent-access/', '').split('/');

  if (parts[0] === 'toolsets') {
    if (parts.length === 1 && method === 'GET') {
      return ok({ toolsets: toolsets.map((t) => ({ ...t, ...counts(t), tools: undefined })) });
    }
    if (parts.length === 1 && method === 'POST') {
      const b = body as { versionId: string; target: string };
      const created = {
        id: `ts-${b.versionId}`,
        versionId: b.versionId,
        projectId: 'p-1',
        versionLabel: b.versionId === 'v-2' ? '2.0.0' : '1.0.0',
        enabled: true,
        target: b.target,
        tools: [
          { id: 'n-read', operation: 'GET /orders', toolName: 'listOrders', writeOp: false, enabled: true },
          { id: 'n-write', operation: 'DELETE /orders/{id}', toolName: 'deleteOrder', writeOp: true, enabled: false },
        ],
      };
      toolsets = [created, ...toolsets];
      return ok({ ...created, ...counts(created) }, 201);
    }
    const ts = toolsets.find((t) => t.id === parts[1]);
    if (!ts) return refuse('no such agent toolset', 404, 'agent-toolset-not-found');
    if (parts.length === 2 && method === 'GET') return ok({ ...ts, ...counts(ts) });
    if (parts.length === 2 && method === 'PATCH') {
      Object.assign(ts, body as object);
      return ok({ ...ts, ...counts(ts), tools: undefined });
    }
    if (parts.length === 2 && method === 'DELETE') {
      toolsets = toolsets.filter((t) => t !== ts);
      keys = keys.filter((k) => k.toolsetId !== ts.id);
      return ok(null);
    }
    if (parts[2] === 'tools' && method === 'PATCH') {
      const tool = ts.tools.find((t) => t.id === parts[3]);
      if (!tool) return refuse('no such tool', 404);
      const b = body as { enabled: boolean; confirmWriteOp?: boolean };
      if (b.enabled && tool.writeOp && !tool.enabled && !b.confirmWriteOp) {
        return refuse('needs confirmWriteOp', 422, 'agent-toolset-write-op-unconfirmed');
      }
      tool.enabled = b.enabled;
      return ok(tool);
    }
  }

  if (parts[0] === 'keys') {
    if (parts.length === 1 && method === 'GET') {
      const all = url.searchParams.get('includeRevoked') === 'true';
      return ok({ keys: keys.filter((k) => all || k.status !== 'revoked') });
    }
    if (parts.length === 1 && method === 'POST') {
      const b = body as Record<string, unknown>;
      const key = {
        id: `k-${keys.length + 1}`,
        name: b.name,
        keyPrefix: 'ak_abcdef12...',
        toolsetId: b.toolsetId,
        toolAllowlist: b.toolAllowlist,
        status: 'active',
        expiresAt: b.expiresAt ?? null,
      };
      keys = [key, ...keys];
      return ok({ ...key, secret: 'ak_SECRET_shown_once' }, 201);
    }
    const key = keys.find((k) => k.id === parts[1]);
    if (!key) return refuse('no such key', 404);
    if (parts[2] === 'usage') {
      return ok({
        keyId: key.id,
        rps: { cap: 2 },
        dailyCalls: { day: '2026-10-06', cap: 1000, used: 240, remaining: 760, resetsAt: 'x' },
      });
    }
    if (parts[2] === 'allowlist' && method === 'PUT') {
      key.toolAllowlist = (body as { toolAllowlist: string[] }).toolAllowlist;
      return ok(key);
    }
    if (parts.length === 2 && method === 'DELETE') {
      key.status = 'revoked';
      return ok(null);
    }
  }

  if (parts[0] === 'usage') return ok(usageReply);
  return refuse(`unrouted ${method} ${path}`, 500);
}

const USAGE_WITH_CALLS = {
  startDay: '2026-09-30',
  endDay: '2026-10-06',
  days: 7,
  totals: {
    calls: 120,
    errors: 6,
    errorRate: 0.05,
    latencyAvgMs: 182,
    latencyP95MaxMs: 410,
    successCalls: 114,
    upstreamErrors: 4,
    validationFailures: 0,
    quotaRejections: 2,
    internalErrors: 0,
  },
  daily: Array.from({ length: 7 }, (_, i) => ({
    day: `2026-10-0${i}`.replace('2026-10-00', '2026-09-30'),
    calls: i === 2 ? 0 : 20,
    errors: i === 2 ? 0 : 1,
    errorRate: i === 2 ? 0 : 0.05,
    latencyAvgMs: i === 2 ? null : 180,
    latencyP95MaxMs: i === 2 ? null : 400,
  })),
  tools: [
    { toolName: 'listPets', calls: 90, errors: 2, errorRate: 0.022, latencyAvgMs: 150, latencyP95MaxMs: 300 },
    { toolName: 'getPet', calls: 30, errors: 4, errorRate: 0.133, latencyAvgMs: 280, latencyP95MaxMs: 410 },
  ],
  agents: [
    { keyId: 'k-1', name: 'claude-desktop', keyPrefix: 'ak_1...', revoked: false, calls: 100, errors: 5, errorRate: 0.05, latencyAvgMs: 190, latencyP95MaxMs: 410 },
    { keyId: 'k-0', name: null, keyPrefix: 'ak_0...', revoked: true, calls: 20, errors: 1, errorRate: 0.05, latencyAvgMs: 150, latencyP95MaxMs: 200 },
  ],
};

const EMPTY_USAGE = {
  ...USAGE_WITH_CALLS,
  totals: { ...USAGE_WITH_CALLS.totals, calls: 0, errors: 0, errorRate: 0 },
  tools: [],
  agents: [],
};

beforeEach(() => {
  mockSessionUser = { user_id: 'u-ada', current_tenant_id: TENANT_ID };
  seedToolset();
  keys = [];
  usageReply = USAGE_WITH_CALLS;
  requests = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const method = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    if (path.startsWith('/api/mcp/browse')) {
      return reply({ groups: [] }, 200);
    }
    requests.push({ method, path, body });
    return handle(path, method, body);
  }) as unknown as typeof fetch;
});

/** Render and wait for the toolset detail to load. */
async function renderPage() {
  const user = userEvent.setup();
  render(<AgentAccessClient />);
  await screen.findByTestId('agx-toolset-detail');
  return user;
}

const writes = () => requests.filter((r) => r.method !== 'GET');

// ---------------------------------------------------------------------------------------

describe('the page', () => {
  test('lives in the MCP section, with Agent access as the current tab', async () => {
    await renderPage();
    const tabs = await screen.findByTestId('mcp-section-tabs');
    expect(within(tabs).getByTestId('mcp-section-tab-agents')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('heading', { level: 1, name: 'Agent access' })).toBeInTheDocument();
  });

  test('a reader with no workspace is gated', async () => {
    mockSessionUser = { user_id: 'u-ada' };
    render(<AgentAccessClient />);
    expect(await screen.findByTestId('agx-no-tenant')).toBeInTheDocument();
    expect(requests).toHaveLength(0);
  });

  test('a tenant without toolsets is invited to enable Agent Access', async () => {
    toolsets = [];
    render(<AgentAccessClient />);
    expect(await screen.findByTestId('agx-toolsets-empty')).toBeInTheDocument();
  });

  test('a failed toolset read is an error with a retry, not an empty state', async () => {
    const original = global.fetch;
    global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
      String(input) === '/api/agent-access/toolsets'
        ? refuse('Permission denied', 403)
        : (original as (i: RequestInfo | URL, n?: RequestInit) => Promise<Reply>)(input, init)
    ) as unknown as typeof fetch;
    render(<AgentAccessClient />);
    expect(await screen.findByTestId('agx-toolsets-error')).toHaveTextContent('Permission denied');
    expect(screen.queryByTestId('agx-toolsets-empty')).toBeNull();
  });
});

describe('toolset editor', () => {
  test('shows each tool with its kind and switch, write ops marked', async () => {
    await renderPage();
    const row = screen.getByTestId('agx-tool-row-createPet');
    expect(within(row).getByText('Write')).toBeInTheDocument();
    expect(within(row).getByText('POST /pets')).toBeInTheDocument();
    expect(screen.getByTestId('agx-tool-switch-createPet')).not.toBeChecked();
    expect(screen.getByTestId('agx-tool-switch-listPets')).toBeChecked();
    expect(screen.getByTestId('agx-toolset-ts-1')).toHaveTextContent('Pet Store · 1.0.0');
    expect(screen.getByTestId('agx-toolset-ts-1')).toHaveTextContent('2 of 3 tools');
  });

  test('disabling a read is immediate', async () => {
    const user = await renderPage();
    await user.click(screen.getByTestId('agx-tool-switch-listPets'));
    await waitFor(() => expect(screen.getByTestId('agx-tool-switch-listPets')).not.toBeChecked());
    expect(writes()).toEqual([
      { method: 'PATCH', path: '/api/agent-access/toolsets/ts-1/tools/tool-list', body: { enabled: false } },
    ]);
    await waitFor(() => expect(screen.getByTestId('agx-toolset-ts-1')).toHaveTextContent('1 of 3 tools'));
  });

  test('enabling a write op asks first; cancelling sends nothing', async () => {
    const user = await renderPage();
    await user.click(screen.getByTestId('agx-tool-switch-createPet'));
    const dialog = await screen.findByTestId('agx-write-confirm');
    expect(dialog).toHaveTextContent('createPet');
    expect(dialog).toHaveTextContent('can change data in production');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByTestId('agx-write-confirm')).toBeNull());
    expect(writes()).toHaveLength(0);
    expect(screen.getByTestId('agx-tool-switch-createPet')).not.toBeChecked();
  });

  test('confirming sends confirmWriteOp and counts the exposed write', async () => {
    const user = await renderPage();
    await user.click(screen.getByTestId('agx-tool-switch-createPet'));
    await user.click(await screen.findByTestId('agx-write-confirm-confirm'));
    await waitFor(() => expect(screen.getByTestId('agx-tool-switch-createPet')).toBeChecked());
    expect(writes()).toEqual([
      {
        method: 'PATCH',
        path: '/api/agent-access/toolsets/ts-1/tools/tool-create',
        body: { enabled: true, confirmWriteOp: true },
      },
    ]);
    await waitFor(() => expect(screen.getByTestId('agx-toolset-ts-1')).toHaveTextContent('1 write'));
  });

  test('a server-side confirmation demand opens the dialog instead of an error', async () => {
    // The page loads the tool as a read; by the time the switch moves, the server knows it is a
    // write (a stale row). The refusal's code — not the row — decides what happens next.
    toolsets[0].tools[2].writeOp = false;
    const user = await renderPage();
    toolsets[0].tools[2].writeOp = true;
    await user.click(screen.getByTestId('agx-tool-switch-createPet'));
    const dialog = await screen.findByTestId('agx-write-confirm');
    expect(screen.queryByTestId('agx-page-error')).toBeNull();
    expect(writes()).toEqual([
      { method: 'PATCH', path: '/api/agent-access/toolsets/ts-1/tools/tool-create', body: { enabled: true } },
    ]);
    await user.click(within(dialog).getByTestId('agx-write-confirm-confirm'));
    await waitFor(() => expect(screen.getByTestId('agx-tool-switch-createPet')).toBeChecked());
    expect(writes()[1].body).toEqual({ enabled: true, confirmWriteOp: true });
  });

  test('switching to mock and off goes through PATCH', async () => {
    const user = await renderPage();
    await user.click(within(screen.getByTestId('agx-toolset-target')).getByRole('radio', { name: 'Mock' }));
    await waitFor(() =>
      expect(writes()).toContainEqual({ method: 'PATCH', path: '/api/agent-access/toolsets/ts-1', body: { target: 'mock' } })
    );
    await user.click(screen.getByTestId('agx-toolset-enabled'));
    expect(await screen.findByTestId('agx-toolset-off-note')).toBeInTheDocument();
    expect(writes()).toContainEqual({ method: 'PATCH', path: '/api/agent-access/toolsets/ts-1', body: { enabled: false } });
  });

  test('deleting a toolset warns that its keys go with it', async () => {
    const user = await renderPage();
    await user.click(screen.getByTestId('agx-toolset-delete'));
    const dialog = await screen.findByTestId('agx-delete-toolset');
    expect(dialog).toHaveTextContent(/agent keys and upstream credentials are deleted/);
    await user.click(within(dialog).getByTestId('agx-delete-toolset-confirm'));
    expect(await screen.findByTestId('agx-toolsets-empty')).toBeInTheDocument();
  });
});

describe('published version → working agent key', () => {
  test('enable, curate, mint, reveal once', async () => {
    const user = await renderPage();

    // 1. Enable Agent Access on the version without a toolset (only v-2 is offered).
    await user.click(screen.getByTestId('agx-enable'));
    const enable = await screen.findByTestId('agx-enable-dialog');
    const select = within(enable).getByLabelText('Published version') as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(['v-2']);
    await user.click(within(enable).getByRole('radio', { name: 'Mock' }));
    await user.click(within(enable).getByTestId('agx-enable-submit'));
    expect(writes()[0]).toEqual({
      method: 'POST',
      path: '/api/agent-access/toolsets',
      body: { versionId: 'v-2', target: 'mock', enabled: true },
    });

    // The new toolset is selected; its write op is off by default.
    await waitFor(() => expect(screen.getByTestId('agx-tool-row-deleteOrder')).toBeInTheDocument());
    expect(screen.getByTestId('agx-tool-switch-deleteOrder')).not.toBeChecked();

    // 2. Mint a key for it from the editor.
    await user.click(screen.getByTestId('agx-toolset-create-key'));
    const create = await screen.findByTestId('agx-key-create-dialog');
    await user.type(within(create).getByLabelText(/Name/), 'claude-desktop');
    await waitFor(() => expect(within(create).getByLabelText('listOrders')).toBeChecked());
    await user.type(within(create).getByLabelText('Expires in (days)'), '30');
    await user.click(within(create).getByTestId('agx-key-create-submit'));

    const sent = writes().find((r) => r.path === '/api/agent-access/keys');
    expect(sent?.body).toMatchObject({
      name: 'claude-desktop',
      toolsetId: 'ts-v-2',
      toolAllowlist: ['listOrders'],
    });
    expect((sent?.body as { expiresAt?: string }).expiresAt).toMatch(/^\d{4}-\d{2}-\d{2}T/);

    // 3. The secret, once.
    const reveal = await screen.findByTestId('api-key-secret-dialog');
    expect(within(reveal).getByText('Agent key created')).toBeInTheDocument();
    expect(within(reveal).getByTestId('api-key-secret-value')).toHaveTextContent('ak_SECRET_shown_once');
    await user.click(within(reveal).getByTestId('api-key-secret-ack'));
    await waitFor(() => expect(screen.queryByTestId('api-key-secret-dialog')).toBeNull());
    expect(document.body).not.toHaveTextContent('ak_SECRET_shown_once');

    // The key is listed with today's usage against the cap.
    const row = await screen.findByTestId('agx-key-row-k-1');
    expect(row).toHaveTextContent('claude-desktop');
    expect(row).toHaveTextContent('Pet Store · 2.0.0');
    await waitFor(() => expect(within(row).getByRole('meter')).toBeInTheDocument());
    expect(row).toHaveTextContent('2 calls/s · 1,000 calls/day');
  });

  test('a key needs at least one tool', async () => {
    const user = await renderPage();
    await user.click(screen.getByTestId('agx-toolset-create-key'));
    const create = await screen.findByTestId('agx-key-create-dialog');
    await user.type(within(create).getByLabelText(/Name/), 'agent');
    await waitFor(() => expect(within(create).getByLabelText('listPets')).toBeChecked());
    await user.click(within(create).getByRole('button', { name: 'Clear' }));
    await user.click(within(create).getByTestId('agx-key-create-submit'));
    expect(await within(create).findByTestId('agx-key-create-error')).toHaveTextContent(/at least one tool/);
    expect(writes()).toHaveLength(0);
  });
});

describe('agent keys', () => {
  beforeEach(() => {
    keys = [
      {
        id: 'k-1',
        name: 'claude-desktop',
        keyPrefix: 'ak_1...',
        toolsetId: 'ts-1',
        toolAllowlist: ['listPets', 'createPet'],
        status: 'active',
        expiresAt: null,
      },
    ];
  });

  async function openKeys() {
    const user = await renderPage();
    await user.click(screen.getByTestId('agx-tab-keys'));
    await screen.findByTestId('agx-key-row-k-1');
    return user;
  }

  test('editing the allowlist marks tools the toolset does not expose and saves the change', async () => {
    const user = await openKeys();
    await user.click(screen.getByTestId('agx-key-allowlist-k-1'));
    const dialog = await screen.findByTestId('agx-allowlist-dialog');
    await waitFor(() => expect(within(dialog).getByLabelText('getPet')).toBeInTheDocument());
    // createPet is in the allowlist but not exposed by the toolset.
    expect(within(dialog).getByText('Not exposed')).toBeInTheDocument();
    expect(within(dialog).getByTestId('agx-allowlist-save')).toBeDisabled();
    await user.click(within(dialog).getByLabelText('getPet'));
    await user.click(within(dialog).getByTestId('agx-allowlist-save'));
    await waitFor(() => expect(screen.queryByTestId('agx-allowlist-dialog')).toBeNull());
    expect(writes()).toEqual([
      {
        method: 'PUT',
        path: '/api/agent-access/keys/k-1/allowlist',
        body: { toolAllowlist: ['createPet', 'getPet', 'listPets'] },
      },
    ]);
  });

  test('revoking asks, then the key leaves the list; revoked keys can be shown', async () => {
    const user = await openKeys();
    await user.click(screen.getByTestId('agx-key-revoke-k-1'));
    const dialog = await screen.findByTestId('agx-revoke');
    expect(dialog).toHaveTextContent('claude-desktop');
    await user.click(within(dialog).getByTestId('agx-revoke-confirm'));
    expect(await screen.findByTestId('agx-keys-empty')).toBeInTheDocument();

    await user.click(screen.getByTestId('agx-keys-include-revoked'));
    const row = await screen.findByTestId('agx-key-row-k-1');
    expect(row).toHaveAttribute('data-status', 'revoked');
    expect(within(row).getByTestId('agx-key-revoke-k-1')).toBeDisabled();
    expect(within(row).getByTestId('agx-key-allowlist-k-1')).toBeDisabled();
  });
});

describe('usage', () => {
  test('draws calls, errors, latency, calls per tool and top agents from the rollups', async () => {
    const user = await renderPage();
    await user.click(screen.getByTestId('agx-tab-usage'));
    const panel = await screen.findByTestId('agx-usage');
    const stat = (label: string) =>
      within(panel).getByText(label, { selector: '.hive-stat__label *, .hive-stat__label' }).closest('.hive-stat') as HTMLElement;
    expect(stat('Calls')).toHaveTextContent('120');
    expect(stat('Error rate')).toHaveTextContent('5%');
    expect(stat('Error rate')).toHaveTextContent('2 over quota');
    expect(stat('Avg latency')).toHaveTextContent('182 ms');
    expect(stat('Avg latency')).toHaveTextContent('Worst p95 410 ms');
    for (const chart of ['calls', 'errors', 'latency', 'tools', 'agents']) {
      expect(screen.getByTestId(`agx-chart-${chart}`).querySelector('svg')).not.toBeNull();
    }
    const tools = screen.getByTestId('agx-usage-tools-table');
    expect(within(tools).getByText('listPets')).toBeInTheDocument();
    expect(within(tools).getByText('13%')).toBeInTheDocument();
    const agents = screen.getByTestId('agx-usage-agents-table');
    expect(within(agents).getByText('claude-desktop')).toBeInTheDocument();
    expect(within(agents).getByText('ak_0... (revoked)')).toBeInTheDocument();
    expect(requests.some((r) => r.path === '/api/agent-access/usage?days=30')).toBe(true);
  });

  test('changing the period re-reads the rollups', async () => {
    const user = await renderPage();
    await user.click(screen.getByTestId('agx-tab-usage'));
    await screen.findByTestId('agx-usage');
    await user.click(within(screen.getByTestId('agx-usage-range')).getByRole('radio', { name: '7 days' }));
    await waitFor(() =>
      expect(requests.some((r) => r.path === '/api/agent-access/usage?days=7')).toBe(true)
    );
  });

  test('a period without calls is an empty state, not flat charts', async () => {
    usageReply = EMPTY_USAGE;
    const user = await renderPage();
    await user.click(screen.getByTestId('agx-tab-usage'));
    expect(await screen.findByTestId('agx-usage-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('agx-chart-calls')).toBeNull();
  });

  test('a failed usage read offers a retry', async () => {
    const user = await renderPage();
    const original = global.fetch;
    global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
      String(input).startsWith('/api/agent-access/usage')
        ? refuse('Permission denied', 403)
        : (original as (i: RequestInfo | URL, n?: RequestInit) => Promise<Reply>)(input, init)
    ) as unknown as typeof fetch;
    await user.click(screen.getByTestId('agx-tab-usage'));
    expect(await screen.findByTestId('agx-usage-error')).toHaveTextContent('Permission denied');
  });
});
