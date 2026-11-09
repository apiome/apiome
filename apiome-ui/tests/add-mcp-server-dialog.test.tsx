/**
 * The Add MCP server dialog, rendered.
 *
 * **Add MCP server** used to open the Import specification wizard on its MCP tab, which brought
 * the spec stepper, a tab for every spec source and the import-jobs drawer with it. The dialog is
 * now its own Connect → Discover → Done flow. This suite pins:
 *
 *   1. **Only MCP.** No spec-source tabs, no spec stepper, no jobs drawer — just the form.
 *   2. **One server.** Create → credential → discover, then the scan; a failure before the scan
 *      deletes the endpoint; a failed scan offers *Discard* and *Add this server anyway*.
 *   3. **A registry.** Registers an `mcp-registry` connector, syncs it and shows the counts; a run
 *      that failed outright deletes its connector.
 *   4. **The browser fixtures** `e2e/hive-import-wizard.spec.ts` mounts (`mcp`, `mcp-registry`),
 *      written into `e2e/fixtures/hive-import-wizard/` when `IMPORT_WIZARD_FIXTURE_DUMP=1`:
 *
 *          IMPORT_WIZARD_FIXTURE_DUMP=1 npx jest tests/add-mcp-server-dialog.test.tsx -t fixtures
 */

import * as fs from 'fs';
import * as path from 'path';
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';
import { jest } from '@jest/globals';

/**
 * The scan panel polls a job; here it is a stub with one button per outcome, so a test chooses
 * how the scan ends.
 */
jest.mock('@/app/components/ade/dashboard/McpDiscoveryPanel', () => ({
  __esModule: true,
  default: ({ onComplete, endpointName }: { onComplete: (ok: boolean, v: string | null) => void; endpointName: string }) => (
    <div data-testid="mcp-discovery-panel">
      <p>Scanning {endpointName}</p>
      <button type="button" onClick={() => onComplete(true, 'ver-1')}>
        Scan succeeds
      </button>
      <button type="button" onClick={() => onComplete(false, null)}>
        Scan fails
      </button>
    </div>
  ),
}));

import AddMcpServerDialog from '@/app/components/ade/dashboard/mcp/AddMcpServerDialog';

type Call = { url: string; method: string; body: unknown };

const fetchMock = jest.fn();
global.fetch = fetchMock as unknown as typeof fetch;

/** Route fetches through `answer`, recording each call; unanswered calls succeed with `{}`. */
function stubFetch(answer: (url: string, method: string) => { ok: boolean; body: unknown } | undefined): Call[] {
  const calls: Call[] = [];
  fetchMock.mockImplementation(((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const reply = answer(url, method) ?? { ok: true, body: {} };
    return Promise.resolve({ ok: reply.ok, json: async () => reply.body });
  }) as never);
  return calls;
}

/** A server that registers as `ep-1` and starts discovery job `job-1`. */
function stubServerFlow(overrides: Record<string, { ok: boolean; body: unknown }> = {}) {
  return stubFetch((url, method) => {
    const key = `${method} ${url}`;
    if (overrides[key]) return overrides[key];
    if (key === 'POST /api/mcp/endpoints') return { ok: true, body: { endpoint: { id: 'ep-1', name: 'Acme tools' } } };
    if (key === 'POST /api/mcp/endpoints/ep-1/discover') return { ok: true, body: { job: { id: 'job-1' } } };
    return undefined;
  });
}

function renderDialog() {
  const onClose = jest.fn();
  const onSuccess = jest.fn();
  const result = render(<AddMcpServerDialog open onClose={onClose} onSuccess={onSuccess} />);
  return { ...result, onClose, onSuccess };
}

function enterUrl(url = 'https://mcp.acme.example/mcp') {
  fireEvent.change(screen.getByLabelText(/Endpoint URL/), { target: { value: url } });
}

beforeEach(() => {
  jest.clearAllMocks();
  stubFetch(() => undefined);
});

/* -------------------------------------------------------------------------
   1. Only MCP
   ------------------------------------------------------------------------- */

describe('the Add MCP server dialog', () => {
  it('shows its own title and Connect → Discover → Done steps', () => {
    renderDialog();
    expect(screen.getByRole('heading', { name: 'Add an MCP server' })).toBeInTheDocument();
    const steps = screen.getByRole('list', { name: 'Add MCP server progress' });
    expect(steps).toHaveTextContent('Connect');
    expect(steps).toHaveTextContent('Discover');
    expect(steps).toHaveTextContent('Done');
  });

  it('carries none of the Import specification wizard', () => {
    renderDialog();
    expect(screen.queryByRole('tablist', { name: 'Import source' })).not.toBeInTheDocument();
    expect(screen.queryByText('Recent import jobs')).not.toBeInTheDocument();
    for (const label of ['File Upload', 'Analyze', 'Preview', 'SwaggerHub', 'Postman Collection']) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it('offers Discover → once an endpoint URL is entered', () => {
    renderDialog();
    expect(screen.getByRole('button', { name: 'Discover →' })).toBeDisabled();
    enterUrl();
    expect(screen.getByRole('button', { name: 'Discover →' })).toBeEnabled();
  });

  it('has no accessibility violations on either form', async () => {
    // Contrast needs real styles, which jsdom does not compute.
    const options = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
    const { baseElement } = renderDialog();
    expect(await axe(baseElement, options)).toHaveNoViolations();
    fireEvent.click(screen.getByRole('radio', { name: 'From a registry' }));
    await screen.findByText('Import from a registry');
    expect(await axe(baseElement, options)).toHaveNoViolations();
  });
});

/* -------------------------------------------------------------------------
   2. One server
   ------------------------------------------------------------------------- */

describe('adding one server', () => {
  it('registers the server, stores its token, starts discovery and lands on Done', async () => {
    const calls = stubServerFlow();
    const { onSuccess, onClose } = renderDialog();
    enterUrl();
    fireEvent.keyDown(screen.getByRole('combobox', { name: /Auth type/ }), { key: 'Enter' });
    fireEvent.click(await screen.findByRole('option', { name: 'Bearer token' }));
    fireEvent.change(screen.getByLabelText(/Access token/), { target: { value: 'sk-test-123' } });
    fireEvent.click(screen.getByRole('button', { name: 'Discover →' }));

    expect(await screen.findByText('Scanning Acme tools')).toBeInTheDocument();
    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      'POST /api/mcp/endpoints',
      'PUT /api/mcp/endpoints/ep-1/credentials',
      'POST /api/mcp/endpoints/ep-1/discover',
    ]);
    expect(calls[1].body).toEqual({ auth_type: 'bearer', payload: { token: 'sk-test-123' } });
    // Back is held while the scan runs.
    expect(screen.getByRole('button', { name: '← Back' })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Scan succeeds' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Continue' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Done' }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onSuccess).toHaveBeenCalled();
    // A server that landed is never deleted.
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
  });

  it('deletes the endpoint and shows the reason when discovery cannot start', async () => {
    const calls = stubServerFlow({
      'POST /api/mcp/endpoints/ep-1/discover': { ok: false, body: { error: 'Endpoint is quarantined.' } },
    });
    renderDialog();
    enterUrl();
    fireEvent.click(screen.getByRole('button', { name: 'Discover →' }));

    expect(await screen.findByText('Endpoint is quarantined.')).toBeInTheDocument();
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/mcp/endpoints/ep-1')).toBe(true)
    );
    expect(screen.getByLabelText(/Endpoint URL/)).toBeInTheDocument();
  });

  it('offers Discard and Add this server anyway after a failed scan; Discard deletes it', async () => {
    const calls = stubServerFlow();
    const { onClose, onSuccess } = renderDialog();
    enterUrl();
    fireEvent.click(screen.getByRole('button', { name: 'Discover →' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Scan fails' }));

    expect(await screen.findByRole('button', { name: 'Add this server anyway' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/mcp/endpoints/ep-1')).toBe(true);
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it('keeps a failed server when asked, and does not delete it on close', async () => {
    const calls = stubServerFlow();
    const { onSuccess } = renderDialog();
    enterUrl();
    fireEvent.click(screen.getByRole('button', { name: 'Discover →' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Scan fails' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Add this server anyway' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Done' }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
  });

  it('deletes an unkept server when Back returns to the form', async () => {
    const calls = stubServerFlow();
    renderDialog();
    enterUrl();
    fireEvent.click(screen.getByRole('button', { name: 'Discover →' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Scan fails' }));
    fireEvent.click(await screen.findByRole('button', { name: '← Back' }));

    expect(await screen.findByLabelText(/Endpoint URL/)).toBeInTheDocument();
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.url === '/api/mcp/endpoints/ep-1')).toBe(true)
    );
  });
});

/* -------------------------------------------------------------------------
   3. A registry (AAU-5.4, #5725)
   ------------------------------------------------------------------------- */

const REGISTRY_RUN = {
  id: 'run-1',
  status: 'succeeded',
  errorClass: null,
  httpStatus: null,
  errorMessage: null,
  summary: {
    candidates: 3,
    imported: 2,
    discovered: 1,
    failed: 0,
    discoveredItems: [
      { remoteId: 'io.github.acme/local-files', reason: 'no-remote: the server lists only packages, which run locally (stdio)' },
    ],
  },
};

function stubRegistryImport(run: Record<string, unknown>) {
  return stubFetch((url, method) => {
    if (url === '/api/connectors' && method === 'POST') return { ok: true, body: { id: 'conn-1', kind: 'mcp-registry' } };
    if (url === '/api/connectors/conn-1/sync') return { ok: true, body: run };
    return undefined;
  });
}

async function openRegistryMode() {
  const rendered = renderDialog();
  fireEvent.click(screen.getByRole('radio', { name: 'From a registry' }));
  await screen.findByText('Import from a registry');
  return rendered;
}

describe('importing MCP servers from a registry', () => {
  it('offers Import servers → once the registry is named', async () => {
    stubRegistryImport(REGISTRY_RUN);
    await openRegistryMode();
    expect(screen.getByRole('button', { name: 'Import servers →' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Registry URL/), {
      target: { value: 'https://registry.modelcontextprotocol.io' },
    });
    expect(screen.getByRole('button', { name: 'Import servers →' })).toBeEnabled();
  });

  it('registers an mcp-registry connector, syncs it and shows what was imported', async () => {
    const calls = stubRegistryImport(REGISTRY_RUN);
    await openRegistryMode();
    fireEvent.change(screen.getByLabelText(/Registry URL/), {
      target: { value: 'https://apiome.example/registry/mcp/acme' },
    });
    fireEvent.change(screen.getByLabelText(/Search/), { target: { value: 'io.github.acme' } });
    fireEvent.click(screen.getByRole('button', { name: 'Import servers →' }));

    expect(await screen.findByText('2 servers imported from the registry')).toBeInTheDocument();
    expect(screen.getByText('io.github.acme/local-files')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /View MCP servers/ })).toHaveAttribute('href', '/ade/dashboard/mcp');

    const created = calls.find((c) => c.url === '/api/connectors' && c.method === 'POST');
    expect(created?.body).toEqual({
      kind: 'mcp-registry',
      name: 'MCP registry · apiome.example · io.github.acme',
      baseUrl: 'https://apiome.example/registry/mcp/acme',
      scope: { search: 'io.github.acme' },
      conflictPolicy: 'hold-for-review',
    });
    expect(calls.some((c) => c.url.endsWith('/credentials'))).toBe(false);
  });

  it('registers a paused connector when the servers are not kept in sync', async () => {
    const calls = stubRegistryImport(REGISTRY_RUN);
    await openRegistryMode();
    fireEvent.change(screen.getByLabelText(/Registry URL/), {
      target: { value: 'https://registry.modelcontextprotocol.io' },
    });
    fireEvent.click(screen.getByRole('checkbox', { name: /Keep these servers in sync/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Import servers →' }));
    expect(await screen.findByText('2 servers imported from the registry')).toBeInTheDocument();

    const created = calls.find((c) => c.url === '/api/connectors' && c.method === 'POST');
    expect(created?.body).toMatchObject({ kind: 'mcp-registry', status: 'paused' });
    expect(created?.body).not.toHaveProperty('refreshIntervalSeconds');
  });

  it('deletes the connector of a run that failed outright and shows the reason on the form', async () => {
    const calls = stubRegistryImport({
      ...REGISTRY_RUN,
      status: 'failed',
      errorMessage: 'Base URL refused: host resolves to a private or reserved address.',
      summary: {},
    });
    await openRegistryMode();
    fireEvent.change(screen.getByLabelText(/Registry URL/), { target: { value: 'https://10.0.0.8' } });
    fireEvent.click(screen.getByRole('button', { name: 'Import servers →' }));

    expect(await screen.findByText(/private or reserved address/)).toBeInTheDocument();
    await waitFor(() =>
      expect(calls.some((c) => c.url === '/api/connectors/conn-1' && c.method === 'DELETE')).toBe(true)
    );
    expect(screen.getByText('Import from a registry')).toBeInTheDocument();
  });
});

/* -------------------------------------------------------------------------
   4. The browser fixtures
   ------------------------------------------------------------------------- */

describe('the browser fixtures', () => {
  const OUT = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-import-wizard');
  const dump = process.env.IMPORT_WIZARD_FIXTURE_DUMP === '1';
  const write = (name: string, html: string) => {
    if (!dump) return;
    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, `${name}.html`), html);
  };
  const dialog = () => document.querySelector('.imp-wizard') as HTMLElement;

  it('renders the one-server and registry forms (and writes the fixtures on request)', async () => {
    renderDialog();
    expect(dialog()).not.toBeNull();
    write('mcp', dialog().outerHTML);

    fireEvent.click(screen.getByRole('radio', { name: 'From a registry' }));
    await screen.findByText('Import from a registry');
    fireEvent.change(screen.getByLabelText(/Registry URL/), {
      target: { value: 'https://registry.modelcontextprotocol.io' },
    });
    fireEvent.change(screen.getByLabelText(/Search/), { target: { value: 'io.github.acme' } });
    write('mcp-registry', dialog().outerHTML);
  });
});
