/**
 * The Consumers screen's bindings and traffic drawer, rendered — RDG-1.8 (#5765).
 *
 * Against a mocked `global.fetch` returning the proxy's `{success, data}` envelopes:
 *
 *   - **Bindings and traffic** opens the drawer, which reads the consumer's bindings and its
 *     declared-versus-observed report;
 *   - a header binding is submitted with its value once, and the list never shows the value;
 *   - a user-agent binding sends no value;
 *   - deleting a binding calls `DELETE …/bindings/{id}`;
 *   - **Add to contract** re-submits the current contract plus the observed operation through the
 *     existing `PUT …/contract`;
 *   - a viewer without write permission sees the report but no form, no delete and no
 *     **Add to contract**.
 *
 * The documentation screenshot `project-consumers-bindings` is captured from the dump at the end:
 * `A11Y_FIXTURE_DUMP=1 npx jest tests/consumers-bindings.test.tsx -t "docs fixtures"`.
 */

import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import ConsumersClient from '../src/app/ade/dashboard/projects/[projectId]/consumers/ConsumersClient';
import type {
  ConsumerBinding,
  ConsumerRuntime,
} from '../src/app/components/ade/consumers/bindingsModel';
import type { ConsumerSummary } from '../src/app/components/ade/consumers/consumersModel';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const SECRET = 'hdr-Billing-Client-7f3a9c';

const BILLING: ConsumerSummary = {
  consumer: {
    id: 'c1',
    tenant_id: 't1',
    project_id: 'p1',
    slug: 'billing-service',
    name: 'Billing Service',
    description: null,
    owner: 'Payments squad',
    contact: null,
    metadata: {},
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    deleted_at: null,
    runtime_last_seen_at: '2026-10-18T09:12:00Z',
  },
  contract: {
    id: 'k1',
    consumer_id: 'c1',
    revision: 2,
    is_current: true,
    source: 'pact',
    version_id: 'v1',
    version_label: '1.2.0',
    surface: {
      schema_version: 'apiome.consumer.contract/v1',
      operations: [
        { method: 'get', path: '/pets', pointer: '/paths/~1pets/get', operation_id: null, summary: null, fields: [] },
        {
          method: 'get',
          path: '/pets/{petId}',
          pointer: '/paths/~1pets~1{petId}/get',
          operation_id: null,
          summary: null,
          fields: [],
        },
      ],
    },
    operation_count: 2,
    field_count: 0,
    unresolved: [],
    unresolved_count: 0,
    source_metadata: {},
    source_digest: null,
    note: null,
    actor_label: null,
    created_at: '2026-09-02T00:00:00Z',
  },
  runtime: { calls: 1025, declared_and_used: 1, declared_unused: 1, used_undeclared: 1, last_seen_day: '2026-10-18' },
};

const BINDINGS: ConsumerBinding[] = [
  {
    id: 'b1',
    consumer_id: 'c1',
    kind: 'api_key',
    name: 'x-api-key',
    hashed: true,
    key_version: 1,
    last_matched_at: '2026-10-18T09:12:00Z',
    created_at: '2026-10-01T00:00:00Z',
    deleted_at: null,
  },
  {
    id: 'b2',
    consumer_id: 'c1',
    kind: 'user_agent',
    name: 'billing-service/*',
    hashed: false,
    key_version: null,
    last_matched_at: '2026-10-17T22:40:00Z',
    created_at: '2026-10-01T00:00:00Z',
    deleted_at: null,
  },
];

const RUNTIME: ConsumerRuntime = {
  consumer_id: 'c1',
  slug: 'billing-service',
  name: 'Billing Service',
  contract_state: 'declared',
  since_day: '2026-09-19',
  until_day: '2026-10-18',
  summary: { calls: 1025, declared_and_used: 1, declared_unused: 1, used_undeclared: 1, last_seen_day: '2026-10-18' },
  declared_and_used: [
    { operation_key: '/paths/~1pets/get', method: 'get', path: '/pets', calls: 1000, errors: 6, last_seen_day: '2026-10-18' },
  ],
  declared_unused: [
    { operation_key: '/paths/~1pets~1{petId}/get', method: 'get', path: '/pets/{petId}', calls: 0, errors: 0, last_seen_day: null },
  ],
  used_undeclared: [
    {
      operation_key: '/paths/~1users~1{userId}~1orders/get',
      method: 'get',
      path: '/users/{userId}/orders',
      calls: 25,
      errors: 5,
      last_seen_day: '2026-10-02',
    },
  ],
};

let calls: { url: string; method: string; body: unknown }[] = [];
let permissions = { is_admin: true, permissions: [] as string[] };
let bindings: ConsumerBinding[] = BINDINGS;

function json(payload: unknown, status = 200) {
  return Promise.resolve({ status, json: () => Promise.resolve(payload) } as Response);
}

beforeEach(() => {
  calls = [];
  permissions = { is_admin: true, permissions: [] };
  bindings = BINDINGS;
  // @ts-expect-error - assigning a test double to the global
  global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = init?.method || 'GET';
    calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : null });
    if (url.startsWith('/api/teams')) {
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ teams: [], count: 0 }) } as Response);
    }
    if (url.includes('/api/access/permissions/me')) return json({ success: true, data: permissions });
    if (url.includes('/bindings') && method === 'GET') {
      return json({ success: true, data: { bindings, count: bindings.length } });
    }
    if (url.includes('/bindings') && method === 'POST') {
      return json({ success: true, data: { ...BINDINGS[0], id: 'b3', kind: 'header', name: 'x-client-id' } }, 201);
    }
    if (url.includes('/bindings/') && method === 'DELETE') {
      return Promise.resolve({ status: 204, json: () => Promise.resolve(null) } as Response);
    }
    if (url.includes('/runtime')) return json({ success: true, data: RUNTIME });
    if (url.endsWith('/contract') && method === 'PUT') {
      return json({ success: true, data: { consumer: BILLING.consumer, contract: { ...BILLING.contract, revision: 3 }, unresolved: [] } });
    }
    return json({ success: true, data: { consumers: [BILLING], count: 1 } });
  });
});

async function openDrawer() {
  const user = userEvent.setup();
  render(<ConsumersClient projectRef="pets" />);
  await waitFor(() => expect(screen.queryByText('Billing Service')).toBeInTheDocument());
  await user.click(screen.getByTestId('consumers-menu-c1'));
  await user.click(await screen.findByRole('menuitem', { name: /Bindings and traffic/ }));
  const drawer = await screen.findByTestId('consumer-bindings-drawer');
  await within(drawer).findByText('x-api-key');
  await within(drawer).findByText('GET /users/{userId}/orders');
  return { user, drawer };
}

describe('the bindings and traffic drawer', () => {
  it('reads the consumer bindings and runtime report', async () => {
    const { drawer } = await openDrawer();
    expect(calls.some((call) => call.url === '/api/consumers/pets/billing-service/bindings')).toBe(true);
    expect(calls.some((call) => call.url === '/api/consumers/pets/billing-service/runtime?days=30')).toBe(true);
    expect(within(drawer).getByText('Value hashed · last matched 2026-10-18')).toBeInTheDocument();
    expect(within(drawer).getByText('Pattern · last matched 2026-10-17')).toBeInTheDocument();
    expect(within(drawer).getByTestId('runtime-declared-used')).toHaveTextContent('1,000 calls');
    expect(within(drawer).getByTestId('runtime-declared-unused')).toHaveTextContent('No calls');
    expect(within(drawer).getByText(/1,025 calls · 1 declared and used/)).toBeInTheDocument();
  });

  it('submits a header value once and never shows it', async () => {
    const { user, drawer } = await openDrawer();
    await user.type(within(drawer).getByLabelText('Header name'), 'x-client-id');
    await user.type(within(drawer).getByLabelText('Value'), SECRET);
    await user.click(within(drawer).getByRole('button', { name: 'Add binding' }));
    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true));
    const post = calls.find((call) => call.method === 'POST');
    expect(post?.url).toBe('/api/consumers/pets/billing-service/bindings');
    expect(post?.body).toEqual({ kind: 'header', name: 'x-client-id', value: SECRET });
    await waitFor(() => expect(within(drawer).getByLabelText('Value')).toHaveValue(''));
    expect(document.body.textContent).not.toContain(SECRET);
  });

  it('sends no value for a user-agent pattern', async () => {
    const { user, drawer } = await openDrawer();
    await user.selectOptions(within(drawer).getByLabelText('Kind'), 'user_agent');
    expect(within(drawer).queryByLabelText('Value')).not.toBeInTheDocument();
    await user.type(within(drawer).getByLabelText('User-agent pattern'), 'search-indexer/*');
    await user.click(within(drawer).getByRole('button', { name: 'Add binding' }));
    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true));
    expect(calls.find((call) => call.method === 'POST')?.body).toEqual({ kind: 'user_agent', name: 'search-indexer/*' });
  });

  it('refuses an empty draft without a request', async () => {
    const { user, drawer } = await openDrawer();
    await user.click(within(drawer).getByRole('button', { name: 'Add binding' }));
    expect(within(drawer).getByText('Enter the header name.')).toBeInTheDocument();
    expect(calls.some((call) => call.method === 'POST')).toBe(false);
  });

  it('deletes a binding', async () => {
    const { user, drawer } = await openDrawer();
    await user.click(within(drawer).getByRole('button', { name: 'Delete binding x-api-key' }));
    await waitFor(() =>
      expect(calls.some((call) => call.method === 'DELETE' && call.url === '/api/consumers/pets/billing-service/bindings/b1')).toBe(true),
    );
  });

  it('adds an observed operation to the contract through PUT contract', async () => {
    const { user, drawer } = await openDrawer();
    await user.click(within(within(drawer).getByTestId('runtime-used-undeclared')).getByRole('button', { name: 'Add to contract' }));
    await waitFor(() => expect(calls.some((call) => call.method === 'PUT')).toBe(true));
    const put = calls.find((call) => call.method === 'PUT');
    expect(put?.url).toBe('/api/consumers/pets/billing-service/contract');
    expect(put?.body).toEqual({
      operations: [
        { method: 'get', path: '/pets', fields: [] },
        { method: 'get', path: '/pets/{petId}', fields: [] },
        { method: 'get', path: '/users/{userId}/orders', fields: [] },
      ],
      note: 'Added GET /users/{userId}/orders from observed traffic',
    });
  });

  it('gives a viewer the report without any write control', async () => {
    permissions = { is_admin: false, permissions: ['consumer_contracts:view'] };
    const { drawer } = await openDrawer();
    expect(within(drawer).queryByTestId('binding-form')).not.toBeInTheDocument();
    expect(within(drawer).queryByRole('button', { name: /Delete binding/ })).not.toBeInTheDocument();
    expect(within(drawer).queryByRole('button', { name: 'Add to contract' })).not.toBeInTheDocument();
  });

  it('says traffic is anonymous until a binding exists', async () => {
    bindings = [];
    const user = userEvent.setup();
    render(<ConsumersClient projectRef="pets" />);
    await waitFor(() => expect(screen.queryByText('Billing Service')).toBeInTheDocument());
    await user.click(screen.getByTestId('consumers-menu-c1'));
    await user.click(await screen.findByRole('menuitem', { name: /Bindings and traffic/ }));
    expect(await screen.findByText(/counted as anonymous/)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------
// The docs fixtures
// ---------------------------------------------------------------------------------------

describe('the docs fixtures', () => {
  it('renders the bindings drawer with a draft binding', async () => {
    const { user, drawer } = await openDrawer();
    await user.type(within(drawer).getByLabelText('Header name'), 'x-client-id');
    writeA11yFixture('project-consumers-bindings', liveMarkup(drawer));
  });
});
