/**
 * The Consumers screen, rendered — CTG-4.1 (#4479).
 *
 * `consumers-model.test.ts` holds the derivations; this holds what the screen *does*, against
 * a mocked `global.fetch` returning the `{success, data}` envelopes the proxy really answers
 * with. Between them they cover the ticket's four acceptance criteria:
 *
 *   1. **A Pact file imports into a stored contract**, and unresolvable interactions are
 *      *reported* — the dialog stays open on the report rather than closing over it;
 *   2. **The picker creates a contract without a Pact file**, sending operations and fields
 *      rather than pointers;
 *   3. **The project page lists consumers with their contract summaries**, including the ones
 *      that have declared nothing;
 *   4. a viewer without write permission gets a read-only screen rather than buttons whose
 *      writes will be refused.
 */

import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import ConsumersClient from '../src/app/ade/dashboard/projects/[projectId]/consumers/ConsumersClient';
import type {
  ConsumerContract,
  ConsumerSummary,
} from '../src/app/components/ade/consumers/consumersModel';

// ---------------------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------------------

function contract(over: Partial<ConsumerContract> = {}): ConsumerContract {
  return {
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
        {
          method: 'get',
          path: '/pets',
          pointer: '/paths/~1pets/get',
          operation_id: 'listPets',
          summary: 'List pets',
          fields: [
            {
              pointer:
                '/paths/~1pets/get/responses/200/content/application~1json/schema/properties/total',
              schema_pointer: '/components/schemas/PetList/properties/total',
              location: 'response',
              status: '200',
              media_type: 'application/json',
              path: 'total',
            },
          ],
        },
      ],
    },
    operation_count: 1,
    field_count: 1,
    unresolved: [],
    unresolved_count: 0,
    source_metadata: {},
    source_digest: null,
    note: null,
    actor_label: null,
    created_at: '2026-09-02T00:00:00Z',
    ...over,
  };
}

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
  },
  contract: contract(),
};

const CHECKOUT: ConsumerSummary = {
  consumer: { ...BILLING.consumer, id: 'c2', slug: 'checkout', name: 'Checkout', owner: null },
  contract: null,
};

const CATALOGUE = {
  version_record_id: 'v1',
  version_label: '1.2.0',
  count: 1,
  truncated: false,
  operations: [
    {
      method: 'get',
      path: '/pets',
      pointer: '/paths/~1pets/get',
      operation_id: 'listPets',
      summary: 'List pets',
      tags: ['pets'],
      truncated: false,
      fields: [
        {
          pointer:
            '/paths/~1pets/get/responses/200/content/application~1json/schema/properties/total',
          schema_pointer: '/components/schemas/PetList/properties/total',
          location: 'response',
          path: 'total',
          status: '200',
          media_type: 'application/json',
          type_name: 'integer',
          required: false,
        },
      ],
    },
  ],
};

// ---------------------------------------------------------------------------------------
// Harness
// ---------------------------------------------------------------------------------------

let calls: { url: string; method: string; body: unknown }[] = [];
let listResponse: { ok: boolean; rows: ConsumerSummary[]; error?: string } = {
  ok: true,
  rows: [BILLING, CHECKOUT],
};
let permissions = { is_admin: true, permissions: [] as string[] };
let writeResponse: { ok: boolean; data?: unknown; error?: string } = { ok: true };

/**
 * A resolved `Response` double carrying a JSON payload.
 *
 * @param payload The envelope.
 * @param status The status code.
 * @returns The double.
 */
function jsonResponse(payload: unknown, status = 200) {
  return Promise.resolve({ status, json: () => Promise.resolve(payload) } as Response);
}

/** Install a `fetch` double for the consumers and access proxies. */
function mockFetch() {
  const fn = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = init?.method || 'GET';
    calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : null });

    if (url.includes('/api/access/permissions/me')) {
      return jsonResponse({ success: true, data: permissions });
    }
    if (url.includes(':surface')) {
      return jsonResponse({ success: true, data: CATALOGUE });
    }
    if (url.startsWith('/api/consumers') && method === 'GET') {
      return listResponse.ok
        ? jsonResponse({
            success: true,
            data: { consumers: listResponse.rows, count: listResponse.rows.length },
          })
        : jsonResponse({ success: false, error: listResponse.error }, 500);
    }
    if (method === 'DELETE') {
      return Promise.resolve({ status: 204, json: () => Promise.resolve(null) } as Response);
    }
    return writeResponse.ok
      ? jsonResponse({ success: true, data: writeResponse.data ?? {} })
      : jsonResponse({ success: false, error: writeResponse.error }, 400);
  });
  // @ts-expect-error - assigning a test double to the global
  global.fetch = fn;
  return fn;
}

beforeEach(() => {
  calls = [];
  listResponse = { ok: true, rows: [BILLING, CHECKOUT] };
  permissions = { is_admin: true, permissions: [] };
  writeResponse = { ok: true };
  mockFetch();
});

/**
 * Render the screen and wait for the list read to land.
 *
 * @returns The render result.
 */
async function renderPage() {
  const view = render(<ConsumersClient projectRef="pets" />);
  await waitFor(() => expect(screen.queryByText('Billing Service')).toBeInTheDocument());
  return view;
}

// ---------------------------------------------------------------------------------------
// 3. The project page lists consumers with their contract summaries
// ---------------------------------------------------------------------------------------

describe('the consumer list', () => {
  it('reads the project it was routed for', async () => {
    await renderPage();
    expect(calls.some((call) => call.url === '/api/consumers/pets')).toBe(true);
  });

  it('shows each consumer with its declared surface', async () => {
    await renderPage();
    const table = screen.getByRole('table');
    expect(within(table).getByText('Billing Service')).toBeInTheDocument();
    expect(within(table).getByText('billing-service')).toBeInTheDocument();
    expect(within(table).getByText('1 operation · 1 field')).toBeInTheDocument();
    expect(within(table).getByText('GET /pets')).toBeInTheDocument();
  });

  it('lists a consumer that has declared nothing rather than hiding it', async () => {
    await renderPage();
    const table = screen.getByRole('table');
    expect(within(table).getByText('Checkout')).toBeInTheDocument();
    expect(within(table).getByText('Nothing declared yet')).toBeInTheDocument();
    expect(within(table).getByText('No contract')).toBeInTheDocument();
  });

  it('says an owner is unassigned rather than leaving the cell blank', async () => {
    await renderPage();
    expect(screen.getByText('Unassigned')).toBeInTheDocument();
  });

  it('narrows to the consumers a chip covers', async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByRole('button', { name: /No contract/ }));
    expect(screen.queryByText('Billing Service')).not.toBeInTheDocument();
    expect(screen.getByText('Checkout')).toBeInTheDocument();
  });

  it('searches by a declared path, which is the question the screen exists for', async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.type(screen.getByRole('searchbox', { name: 'Search consumers' }), '/pets');
    expect(screen.getByText('Billing Service')).toBeInTheDocument();
    expect(screen.queryByText('Checkout')).not.toBeInTheDocument();
  });

  it('reports a failed read instead of drawing an empty registry', async () => {
    listResponse = { ok: false, rows: [], error: 'REST is down' };
    render(<ConsumersClient projectRef="pets" />);
    expect(await screen.findByText('REST is down')).toBeInTheDocument();
    expect(screen.queryByText('No consumers registered yet')).not.toBeInTheDocument();
  });

  it('explains what to do when the registry is genuinely empty', async () => {
    listResponse = { ok: true, rows: [] };
    render(<ConsumersClient projectRef="pets" />);
    expect(await screen.findByText('No consumers registered yet')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------
// 4. Read-only for a viewer who may not write
// ---------------------------------------------------------------------------------------

describe('permissions', () => {
  it('offers the two ingestion paths to a viewer who may create', async () => {
    await renderPage();
    expect(screen.getByRole('button', { name: /Register consumer/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Import Pact file/ })).toBeInTheDocument();
  });

  it('offers no write control to a viewer who may not', async () => {
    permissions = { is_admin: false, permissions: ['consumer_contracts:view'] };
    await renderPage();
    expect(screen.queryByRole('button', { name: /Register consumer/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Import Pact file/ })).not.toBeInTheDocument();
  });

  it('grants the verbs a granular grant actually carries', async () => {
    permissions = {
      is_admin: false,
      permissions: ['consumer_contracts:view', 'consumer_contracts:create'],
    };
    await renderPage();
    expect(screen.getByRole('button', { name: /Register consumer/ })).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------
// 1. Registering, and the handle rule
// ---------------------------------------------------------------------------------------

describe('registering a consumer', () => {
  it('posts the typed identity and reloads the list', async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByRole('button', { name: /Register consumer/ }));
    await user.type(screen.getByLabelText('Name'), 'Ledger');
    await user.click(screen.getByRole('button', { name: 'Register consumer' }));

    await waitFor(() =>
      expect(calls.some((call) => call.method === 'POST' && call.url === '/api/consumers/pets')).toBe(
        true,
      ),
    );
    const post = calls.find((call) => call.method === 'POST');
    expect(post?.body).toMatchObject({ name: 'Ledger' });
  });

  it('does not send a handle the person left empty, so the server derives one', async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByRole('button', { name: /Register consumer/ }));
    await user.type(screen.getByLabelText('Name'), 'Ledger');
    await user.click(screen.getByRole('button', { name: 'Register consumer' }));

    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true));
    expect(calls.find((call) => call.method === 'POST')?.body).not.toHaveProperty('slug');
  });

  it('reports a refused write inline rather than closing over it', async () => {
    const user = userEvent.setup();
    writeResponse = { ok: false, error: "a consumer 'ledger' already exists in this project" };
    await renderPage();
    await user.click(screen.getByRole('button', { name: /Register consumer/ }));
    await user.type(screen.getByLabelText('Name'), 'Ledger');
    await user.click(screen.getByRole('button', { name: 'Register consumer' }));

    expect(
      await screen.findByText("a consumer 'ledger' already exists in this project"),
    ).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------
// 2. The picker declares a contract without a Pact file
// ---------------------------------------------------------------------------------------

describe('the surface picker', () => {
  /**
   * Open the picker on the Billing Service row.
   *
   * @param user The interaction driver.
   */
  async function openPicker(user: ReturnType<typeof userEvent.setup>, rowId = 'c1') {
    await user.click(screen.getByTestId(`consumers-menu-${rowId}`));
    await user.click(await screen.findByText('Declare surface…'));
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByText('GET /pets');
    return dialog;
  }

  it('loads the catalogue only when it is opened', async () => {
    const user = userEvent.setup();
    await renderPage();
    expect(calls.some((call) => call.url.includes(':surface'))).toBe(false);
    await openPicker(user);
    expect(calls.some((call) => call.url.includes(':surface'))).toBe(true);
  });

  it('starts from what the consumer already declares', async () => {
    const user = userEvent.setup();
    await renderPage();
    await openPicker(user);
    expect(screen.getByTestId('picker-totals')).toHaveTextContent('1 operations · 1 fields');
  });

  it('sends operations and fields, never pointers', async () => {
    const user = userEvent.setup();
    await renderPage();
    await openPicker(user);
    await user.click(screen.getByRole('button', { name: 'Save contract' }));

    await waitFor(() => expect(calls.some((call) => call.method === 'PUT')).toBe(true));
    const put = calls.find((call) => call.method === 'PUT');
    expect(put?.url).toBe('/api/consumers/pets/billing-service/contract');
    expect(put?.body).toEqual({
      operations: [
        {
          method: 'get',
          path: '/pets',
          fields: [{ location: 'response', path: 'total', status: '200' }],
        },
      ],
    });
    expect(JSON.stringify(put?.body)).not.toContain('pointer');
  });

  it('reopens from the revision the save produced, not the one it replaced', async () => {
    // The overlay tracks a row *id*; a stored summary would still describe the previous
    // revision after the write reloaded the list.
    const user = userEvent.setup();
    writeResponse = {
      ok: true,
      data: { consumer: BILLING.consumer, contract: contract({ revision: 3 }), unresolved: [] },
    };
    await renderPage();
    await openPicker(user);

    // The reload the save triggers answers with a Billing Service that now declares nothing.
    listResponse = { ok: true, rows: [{ ...BILLING, contract: null }, CHECKOUT] };
    await user.click(screen.getByRole('button', { name: 'Save contract' }));
    await waitFor(() => expect(calls.some((call) => call.method === 'PUT')).toBe(true));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await waitFor(() =>
      expect(screen.getAllByText('Nothing declared yet')).toHaveLength(2)
    );

    await openPicker(user);
    expect(screen.getByTestId('picker-totals')).toHaveTextContent('0 operations · 0 fields');
  });

  it('refuses to save an empty selection', async () => {
    const user = userEvent.setup();
    await renderPage();
    await openPicker(user, 'c2');
    expect(screen.getByRole('button', { name: 'Save contract' })).toBeDisabled();
  });
});

// ---------------------------------------------------------------------------------------
// 1. Pact import, and the unresolved report
// ---------------------------------------------------------------------------------------

describe('the Pact import', () => {
  const PACT = JSON.stringify({
    consumer: { name: 'Ledger' },
    interactions: [
      { request: { method: 'GET', path: '/pets' }, response: { status: 200, body: { total: 1 } } },
    ],
  });

  it('posts the document to the import sibling path', async () => {
    const user = userEvent.setup();
    writeResponse = {
      ok: true,
      data: {
        consumer: BILLING.consumer,
        contract: contract({ revision: 3 }),
        unresolved: [],
      },
    };
    await renderPage();
    await user.click(screen.getByRole('button', { name: /Import Pact file/ }));
    await user.click(screen.getByLabelText('Pact document'));
    await user.paste('{"interactions":[]}');
    await user.click(screen.getByRole('button', { name: 'Import' }));

    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true));
    expect(calls.find((call) => call.method === 'POST')?.url).toBe(
      '/api/consumers/pets/:pact-imports',
    );
  });

  it('reports what could not be resolved instead of closing over it', async () => {
    const user = userEvent.setup();
    writeResponse = {
      ok: true,
      data: {
        consumer: BILLING.consumer,
        contract: contract({ revision: 3, unresolved_count: 2 }),
        unresolved: [
          {
            reason: 'operation-not-found',
            message: 'the specification declares no GET /orders operation',
            description: 'a retired call',
            method: 'get',
            path: '/orders',
            status: null,
            field_path: null,
          },
          {
            reason: 'field-not-found',
            message: "GET /pets does not declare response field 'legacy'",
            description: null,
            method: 'get',
            path: '/pets',
            status: '200',
            field_path: 'legacy',
          },
        ],
      },
    };
    await renderPage();
    await user.click(screen.getByRole('button', { name: /Import Pact file/ }));
    await user.click(screen.getByLabelText('Pact document'));
    await user.paste('{"interactions":[]}');
    await user.click(screen.getByRole('button', { name: 'Import' }));

    const outcome = await screen.findByTestId('pact-import-outcome');
    // The dialog is still open, and the report is in it.
    expect(outcome).toHaveTextContent('2 interactions unresolved');
    expect(within(outcome).getByText('Operation not in this version')).toBeInTheDocument();
    expect(within(outcome).getByText('Field not in the schema')).toBeInTheDocument();
    expect(
      within(outcome).getByText('the specification declares no GET /orders operation'),
    ).toBeInTheDocument();
  });

  it('reports a refused import as an error, not as an empty success', async () => {
    const user = userEvent.setup();
    writeResponse = { ok: false, error: 'the Pact document is not valid JSON' };
    await renderPage();
    await user.click(screen.getByRole('button', { name: /Import Pact file/ }));
    await user.click(screen.getByLabelText('Pact document'));
    await user.paste('nonsense');
    await user.click(screen.getByRole('button', { name: 'Import' }));

    expect(await screen.findByText('the Pact document is not valid JSON')).toBeInTheDocument();
    expect(screen.queryByTestId('pact-import-outcome')).not.toBeInTheDocument();
  });

  it('files the import under the row it was opened from', async () => {
    const user = userEvent.setup();
    writeResponse = {
      ok: true,
      data: { consumer: BILLING.consumer, contract: contract(), unresolved: [] },
    };
    await renderPage();
    await user.click(screen.getByTestId('consumers-menu-c1'));
    await user.click(await screen.findByText('Import Pact file…'));
    await user.click(screen.getByLabelText('Pact document'));
    await user.paste('{"interactions":[]}');
    await user.click(screen.getByRole('button', { name: 'Import' }));

    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true));
    expect(calls.find((call) => call.method === 'POST')?.body).toMatchObject({
      consumer_slug: 'billing-service',
    });
  });

  it('sends no handle at all when the document is to name its own consumer', async () => {
    const user = userEvent.setup();
    writeResponse = {
      ok: true,
      data: { consumer: BILLING.consumer, contract: contract(), unresolved: [] },
    };
    await renderPage();
    await user.click(screen.getByRole('button', { name: /Import Pact file/ }));
    await user.click(screen.getByLabelText('Pact document'));
    await user.paste(PACT);
    await user.click(screen.getByRole('button', { name: 'Import' }));

    await waitFor(() => expect(calls.some((call) => call.method === 'POST')).toBe(true));
    expect(calls.find((call) => call.method === 'POST')?.body).not.toHaveProperty(
      'consumer_slug',
    );
  });
});

// ---------------------------------------------------------------------------------------
// The declared-surface drawer
// ---------------------------------------------------------------------------------------

describe('the declared-surface drawer', () => {
  it('shows the full surface, not the row preview', async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByText('Billing Service'));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText('Declared operations')).toBeInTheDocument();
    expect(within(dialog).getByText('total')).toBeInTheDocument();
    expect(within(dialog).getByText('response · 200')).toBeInTheDocument();
  });

  it('puts what could not be resolved above the declared operations', async () => {
    listResponse = {
      ok: true,
      rows: [
        {
          ...BILLING,
          contract: contract({
            unresolved_count: 1,
            unresolved: [
              {
                reason: 'operation-not-found',
                message: 'the specification declares no GET /orders operation',
                description: null,
                method: 'get',
                path: '/orders',
                status: null,
                field_path: null,
              },
            ],
          }),
        },
      ],
    };
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByText('Billing Service'));

    const dialog = await screen.findByRole('dialog');
    const unresolved = within(dialog).getByTestId('drawer-unresolved');
    expect(unresolved).toHaveTextContent('Operation not in this version');
    expect(
      unresolved.compareDocumentPosition(within(dialog).getByText('Declared operations')) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('tells a consumer with no contract what to do about it', async () => {
    const user = userEvent.setup();
    await renderPage();
    await user.click(screen.getByText('Checkout'));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByText(/declared nothing yet/)).toBeInTheDocument();
  });
});
