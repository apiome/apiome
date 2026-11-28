/**
 * **Export a contract** — the Export page, PFX-8.18 (#7315).
 *
 * The page: three option cards, one kind visible at a time; no primary in the header, Export studio
 * beside it; the Contracts tabs; a prefill problem on the one status line.
 *
 * A pact from a project: the checklist says where each example came from or why an operation was
 * left out; unticking an operation leaves it out of the preview and the download and the command
 * block says why the command cannot; every finding is listed; a revision with nothing to derive
 * says so, with its findings; a large pact downloads without a preview; **Review and publish** hands
 * the exact pact to the Publish page, and is not offered without `pacts:create`.
 *
 * A Postman collection: the form becomes `export-postman`'s body; the result shows the fidelity bar
 * and every notice; **All consumers** sends `allConsumers`; a pair without a pact says what to do;
 * a refusal's notices are listed.
 *
 * A pact file: a pair without a pact says so; a download saves the file; every pact for a provider
 * downloads the zip. axe passes on every kind.
 *
 * Provider test scaffolding (PFX-8.19): the language and provider reach REST; the states table flags
 * each state with no handler in Apiome; the file previews, downloads and copies; a refusal says why.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `pact-export` and `pact-export-scaffold`.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockPush = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ replace: jest.fn(), push: mockPush }) }));
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import { ExportPactClient } from '../src/app/components/ade/pactExport';
import { EXCLUDED_REASON, NOTHING_TO_DERIVE, readExportPrefill, type ExportPrefill } from '../lib/pact-export';
import { PUBLISH_HANDOFF_KEY } from '../lib/pact-publish-page';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const EDITOR = { is_admin: false, permissions: ['pacts:view', 'pacts:create', 'consumer_contracts:view'] };
const VIEWER = { is_admin: false, permissions: ['pacts:view', 'consumer_contracts:view'] };

type Answer = { status: number; body: unknown };
type Call = { url: string; method: string; body: unknown };
let answers: Record<string, (call: Call) => Answer>;
let calls: Call[];
let saved: string[];

/** REST through the proxies: the longest route key the URL starts with answers. */
function installFetch() {
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const call = { url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    const key = Object.keys(answers)
      .sort((a, b) => b.length - a.length)
      .find((candidate) => url.startsWith(candidate));
    const { status, body } = key ? answers[key](call) : { status: 404, body: { success: false, error: 'not found' } };
    return {
      ok: status < 400,
      status,
      json: async () => body,
      blob: async () => new Blob(['zip']),
      headers: new Headers(status < 400 && url.includes('provider-pacts') ? { 'Content-Disposition': 'attachment; filename="billing-pacts.zip"' } : {}),
    } as Response;
  }) as unknown as typeof fetch;
}

function as(role: typeof EDITOR) {
  answers['/api/access/permissions/me'] = () => ({ status: 200, body: { success: true, data: role } });
}

/** The derived pact of a consumer with three declared operations. */
function derived(extraInteractions = 0) {
  return {
    consumer_name: 'Orders UI',
    provider_name: 'Billing Service',
    revision: 4,
    version_label: '2.7.0',
    interaction_count: 3,
    findings: [
      { outcome: 'placeholder', reason: 'no-example', message: 'no example for total', method: 'POST', path: '/invoices', status: '201', location: 'response', field: 'total' },
      { outcome: 'omitted', reason: 'no-response-declared', message: 'no response to assert on', method: 'DELETE', path: '/invoices/{id}' },
    ],
    operations: [
      { method: 'GET', path: '/invoices/{id}', operation_id: 'getInvoice', interactions: [0], placeholder_count: 0, omitted_count: 0 },
      { method: 'POST', path: '/invoices', operation_id: null, interactions: [1], placeholder_count: 1, omitted_count: 0 },
      { method: 'DELETE', path: '/invoices/{id}', operation_id: null, interactions: [], placeholder_count: 0, omitted_count: 1 },
    ],
    pact: {
      consumer: { name: 'Orders UI' },
      provider: { name: 'Billing Service' },
      interactions: [
        { description: 'getInvoice returns 200', request: { method: 'GET', path: '/invoices/42' } },
        { description: 'POST /invoices returns 201', request: { method: 'POST', path: '/invoices' } },
        ...Array.from({ length: extraInteractions }, (_, i) => ({ description: `padding ${i}`, request: { method: 'GET', path: `/x/${'p'.repeat(400)}` } })),
      ],
      metadata: { pactSpecification: { version: '4.0' } },
    },
  };
}

/** A Postman export of one pact: 5 of 6 interactions kept. */
const POSTMAN = {
  collection: { info: { name: 'Pact: Orders UI → Billing Service' }, item: [], variable: [{ key: 'baseUrl', value: '' }] },
  pact: { consumer: 'Orders UI', provider: 'Billing Service', consumerVersion: '3.4.0', pactVersionSha: 'ab'.repeat(32) },
  counts: { interactions: 6, exported: 5, leftOut: 1 },
  notices: [
    { code: 'pact-postman-message-left-out', outcome: 'left-out', pointer: '/messages/0', message: 'a message interaction has no HTTP request for Postman to send', description: 'invoice paid' },
    { code: 'pact-postman-provider-states', outcome: 'info', pointer: '', message: '2 provider state(s) are set up by each request’s pre-request script', paths: ['an invoice exists', 'a customer 7 exists'] },
  ],
};

const PREFILL: ExportPrefill = readExportPrefill({});

// jsdom's Blob/File lack the standard `.text()`; back it with FileReader (as the Publish page test does).
beforeAll(() => {
  const proto = Blob.prototype as unknown as { text?: () => Promise<string> };
  if (typeof proto.text !== 'function') {
    proto.text = function (this: Blob) {
      return new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(reader.error);
        reader.readAsText(this);
      });
    };
  }
});

beforeEach(() => {
  mockPush.mockReset();
  calls = [];
  saved = [];
  answers = {
    '/api/projects': () => ({ status: 200, body: { success: true, projects: [{ id: 'p-1', slug: 'billing-api', name: 'Billing API' }] } }),
    '/api/consumers/billing-api': () => ({
      status: 200,
      body: {
        success: true,
        data: {
          consumers: [
            { consumer: { slug: 'orders-ui', name: 'Orders UI' }, contract: { source: 'manual' } },
            { consumer: { slug: 'legacy', name: 'Legacy app' }, contract: { source: 'pact' } },
          ],
        },
      },
    }),
    '/api/pact/pacticipants': () => ({ status: 200, body: { pacticipants: [{ slug: 'billing-service', name: 'Billing Service' }, { slug: 'orders-ui', name: 'Orders UI' }] } }),
    '/api/pact/export/consumer-pact': () => ({ status: 200, body: derived() }),
    '/api/pact/export/postman': () => ({ status: 200, body: POSTMAN }),
  };
  as(EDITOR);
  installFetch();
  window.sessionStorage.clear();
  URL.createObjectURL = jest.fn(() => 'blob:x');
  URL.revokeObjectURL = jest.fn();
  jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    saved.push(this.download);
  });
});

afterEach(() => jest.restoreAllMocks());

async function deriveOrders() {
  await screen.findByRole('option', { name: 'Billing API' });
  fireEvent.change(screen.getByLabelText('Project'), { target: { value: 'billing-api' } });
  await screen.findByRole('option', { name: 'Orders UI' });
  fireEvent.change(screen.getByLabelText('Consumer'), { target: { value: 'orders-ui' } });
  fireEvent.click(screen.getByTestId('pexp-derive-run'));
  await screen.findByTestId('pexp-operations');
}

describe('the page', () => {
  it('shows three kinds, one at a time, with no primary in the header', async () => {
    render(<ExportPactClient prefill={PREFILL} />);
    const kinds = screen.getByTestId('pexp-kinds');
    expect(within(kinds).getAllByRole('radio')).toHaveLength(4);
    expect(screen.getByTestId('pexp-derive')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Export studio/ })).toHaveAttribute('href', '/ade/dashboard/export/studio');
    fireEvent.click(screen.getByRole('radio', { name: /^A Postman collection/ }));
    expect(screen.queryByTestId('pexp-derive')).not.toBeInTheDocument();
    expect(screen.getByTestId('pexp-postman')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: /^A pact file/ }));
    expect(screen.getByTestId('pexp-file')).toBeInTheDocument();
    await waitFor(() => expect(calls.some((call) => call.url === '/api/pact/pacticipants')).toBe(true));
  });

  it('reports what the address could not use, and opens on the kind it names', () => {
    render(<ExportPactClient prefill={readExportPrefill({ kind: 'file', provider: 'billing-service', consumer: 'orders-ui', colour: 'red' })} />);
    expect(screen.getByTestId('pexp-status')).toHaveTextContent('?colour= is not something this page reads.');
    expect(screen.getByTestId('pexp-file')).toBeInTheDocument();
    expect(screen.getByLabelText('Provider')).toHaveValue('billing-service');
  });
});

describe('a pact from a project', () => {
  it('lists each operation with where its example came from, and every finding', async () => {
    const { container } = render(<ExportPactClient prefill={PREFILL} />);
    await deriveOrders();
    expect(calls.find((call) => call.url.startsWith('/api/pact/export/consumer-pact'))?.url).toBe('/api/pact/export/consumer-pact?project=billing-api&consumer=orders-ui');
    const rows = screen.getAllByTestId('pexp-operation');
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining('The spec’s example'),
      expect.stringContaining('Generated from the schema — review (1 value)'),
      expect.stringContaining('Left out — no response to assert on'),
    ]);
    expect(within(rows[2]).getByRole('checkbox')).toBeDisabled();
    expect(screen.getByTestId('pexp-derive-findings')).toHaveTextContent('no-example');
    expect(screen.getByTestId('pexp-derive-findings')).toHaveTextContent('no-response-declared');
    expect(screen.getByTestId('pexp-derive-preview')).toHaveTextContent('getInvoice returns 200');
    expect(screen.getByTestId('pexp-derive-command')).toHaveTextContent('apiome pact export-consumer-contract');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-export', liveMarkup(container.firstElementChild!));
  });

  it('leaves an unticked operation out of the preview and the download, and says the command cannot', async () => {
    render(<ExportPactClient prefill={PREFILL} />);
    await deriveOrders();
    fireEvent.click(screen.getByLabelText('Include GET /invoices/{id}'));
    expect(screen.getByTestId('pexp-derive-preview')).not.toHaveTextContent('getInvoice returns 200');
    expect(screen.getByTestId('pexp-derive-command')).toHaveTextContent(EXCLUDED_REASON);
    fireEvent.click(screen.getByTestId('pexp-derive-download'));
    expect(saved).toEqual(['orders-ui-billing-service.json']);
  });

  it('hands the exact pact to the Publish page when operations are left out', async () => {
    render(<ExportPactClient prefill={PREFILL} />);
    await deriveOrders();
    fireEvent.click(screen.getByLabelText('Include POST /invoices'));
    fireEvent.click(screen.getByTestId('pexp-derive-publish'));
    const handed = JSON.parse(window.sessionStorage.getItem(PUBLISH_HANDOFF_KEY) ?? '{}');
    expect(JSON.parse(handed.pact).interactions).toHaveLength(1);
    expect(mockPush).toHaveBeenCalledWith('/ade/dashboard/pacts/publish?source=paste');
  });

  it('opens the Publish page’s derive tab for the whole surface', async () => {
    render(<ExportPactClient prefill={PREFILL} />);
    await deriveOrders();
    fireEvent.click(screen.getByTestId('pexp-derive-publish'));
    expect(mockPush).toHaveBeenCalledWith('/ade/dashboard/pacts/publish?source=derive&project=billing-api&consumer=orders-ui');
    expect(window.sessionStorage.getItem(PUBLISH_HANDOFF_KEY)).toBeNull();
  });

  it('does not offer Review and publish without pacts:create', async () => {
    as(VIEWER);
    render(<ExportPactClient prefill={PREFILL} />);
    await deriveOrders();
    expect(screen.getByTestId('pexp-derive-download')).toBeEnabled();
    expect(screen.queryByTestId('pexp-derive-publish')).not.toBeInTheDocument();
  });

  it('says when there is nothing to derive, with the findings', async () => {
    answers['/api/pact/export/consumer-pact'] = () => ({
      status: 422,
      body: { success: false, error: 'revision 4 yields no interaction', code: 'consumer-pact-export-empty', findings: [{ outcome: 'omitted', reason: 'status-default', message: 'only a default response' }] },
    });
    render(<ExportPactClient prefill={PREFILL} />);
    await screen.findByRole('option', { name: 'Billing API' });
    fireEvent.change(screen.getByLabelText('Project'), { target: { value: 'billing-api' } });
    await screen.findByRole('option', { name: 'Orders UI' });
    fireEvent.change(screen.getByLabelText('Consumer'), { target: { value: 'orders-ui' } });
    fireEvent.click(screen.getByTestId('pexp-derive-run'));
    expect(await screen.findByTestId('pexp-status')).toHaveTextContent(NOTHING_TO_DERIVE);
    expect(screen.getByTestId('pexp-derive-findings')).toHaveTextContent('only a default response');
    expect(screen.getByTestId('pexp-derive-download')).toBeDisabled();
  });

  it('refuses to derive without a project, and sends nothing', async () => {
    render(<ExportPactClient prefill={PREFILL} />);
    fireEvent.click(screen.getByTestId('pexp-derive-run'));
    expect(screen.getByTestId('pexp-status')).toHaveTextContent('Pick the project');
    expect(calls.some((call) => call.url.startsWith('/api/pact/export/'))).toBe(false);
  });

  it('downloads a large pact without an inline preview', async () => {
    answers['/api/pact/export/consumer-pact'] = () => ({ status: 200, body: derived(600) });
    render(<ExportPactClient prefill={PREFILL} />);
    await deriveOrders();
    expect(screen.queryByTestId('pexp-derive-preview')).not.toBeInTheDocument();
    expect(screen.getByTestId('pexp-derive-large')).toHaveTextContent('too large to preview');
    fireEvent.click(screen.getByTestId('pexp-derive-download'));
    expect(saved).toEqual(['orders-ui-billing-service.json']);
  });

  it('marks a consumer that cannot be derived', async () => {
    render(<ExportPactClient prefill={PREFILL} />);
    await screen.findByRole('option', { name: 'Billing API' });
    fireEvent.change(screen.getByLabelText('Project'), { target: { value: 'billing-api' } });
    expect(await screen.findByRole('option', { name: /Legacy app — was imported from a Pact file/ })).toBeDisabled();
  });
});

describe('a Postman collection', () => {
  function openPostman() {
    render(<ExportPactClient prefill={PREFILL} />);
    fireEvent.click(screen.getByRole('radio', { name: /^A Postman collection/ }));
  }

  it('sends export-postman’s body and shows the fidelity bar and every notice', async () => {
    openPostman();
    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'Billing Service' } });
    fireEvent.change(screen.getByLabelText('Consumer'), { target: { value: 'Orders UI' } });
    fireEvent.change(screen.getByLabelText('Which pact'), { target: { value: 'branch' } });
    fireEvent.change(screen.getByLabelText('Branch'), { target: { value: 'main' } });
    fireEvent.change(screen.getByLabelText('State change URL (optional)'), { target: { value: 'http://localhost:8080/_pact/provider_states' } });
    fireEvent.click(screen.getByTestId('pexp-postman-run'));
    expect(await screen.findByTestId('pexp-fidelity-label')).toHaveTextContent('5 of 6 interactions');
    expect(calls.find((call) => call.url === '/api/pact/export/postman')?.body).toEqual({
      tests: true,
      provider: 'Billing Service',
      consumer: 'Orders UI',
      branch: 'main',
      stateSetup: true,
      stateChangeUrl: 'http://localhost:8080/_pact/provider_states',
    });
    expect(screen.getByTestId('pexp-fidelity')).toHaveAttribute('aria-label', '5 of 6 interactions included');
    expect(screen.getByTestId('pexp-postman-notices')).toHaveTextContent('invoice paid');
    expect(screen.getByTestId('pexp-postman-notices')).toHaveTextContent('an invoice exists, a customer 7 exists');
    expect(screen.getByTestId('pexp-postman-command')).toHaveTextContent('--state-setup');
    fireEvent.click(screen.getByTestId('pexp-postman-download'));
    expect(saved).toEqual(['orders-ui-billing-service.postman.json']);
    expect(await axe(document.body, AXE_OPTIONS)).toHaveNoViolations();
  });

  it('exports every consumer in one go', async () => {
    openPostman();
    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'Billing Service' } });
    fireEvent.click(screen.getByTestId('pexp-postman-all'));
    expect(screen.getByLabelText('Consumer')).toBeDisabled();
    fireEvent.click(screen.getByTestId('pexp-postman-run'));
    await screen.findByTestId('pexp-fidelity');
    expect(calls.find((call) => call.url === '/api/pact/export/postman')?.body).toMatchObject({ provider: 'Billing Service', allConsumers: true });
    expect(screen.getByTestId('pexp-postman-command')).toHaveTextContent('--all-consumers');
  });

  it('says what to do when the pair has no pact', async () => {
    answers['/api/pact/export/postman'] = () => ({ status: 404, body: { success: false, error: 'no pact between consumer', code: 'pact-not-found' } });
    openPostman();
    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'Billing Service' } });
    fireEvent.change(screen.getByLabelText('Consumer'), { target: { value: 'Orders UI' } });
    fireEvent.click(screen.getByTestId('pexp-postman-run'));
    expect(await screen.findByTestId('pexp-status')).toHaveTextContent(
      'Orders UI has not published a pact for Billing Service. Record one from a mock, or upload a file.',
    );
  });

  it('lists the notices of a refusal', async () => {
    answers['/api/pact/export/postman'] = () => ({
      status: 422,
      body: { success: false, error: 'the pact has no HTTP interaction', code: 'pact-postman-no-http-interactions', notices: [POSTMAN.notices[0]] },
    });
    openPostman();
    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'Billing Service' } });
    fireEvent.change(screen.getByLabelText('Consumer'), { target: { value: 'Orders UI' } });
    fireEvent.click(screen.getByTestId('pexp-postman-run'));
    expect(await screen.findByTestId('pexp-postman-notices')).toHaveTextContent('a message interaction has no HTTP request');
    expect(screen.getByTestId('pexp-status')).toHaveTextContent('the pact has no HTTP interaction');
  });

  it('sends an uploaded pact inline', async () => {
    openPostman();
    fireEvent.change(screen.getByLabelText('Which pact'), { target: { value: 'file' } });
    const file = new File(['{"consumer":{"name":"A"},"provider":{"name":"B"},"interactions":[]}'], 'mine.json', { type: 'application/json' });
    fireEvent.change(screen.getByTestId('pexp-postman-file'), { target: { files: [file] } });
    await screen.findByRole('button', { name: /mine\.json/ });
    fireEvent.click(screen.getByTestId('pexp-postman-run'));
    await screen.findByTestId('pexp-fidelity');
    expect(calls.find((call) => call.url === '/api/pact/export/postman')?.body).toMatchObject({ pact: { consumer: { name: 'A' } } });
    expect(screen.getByTestId('pexp-postman-command')).toHaveTextContent('--pact-file mine.json');
  });
});

describe('a pact file', () => {
  function openFile() {
    render(<ExportPactClient prefill={PREFILL} />);
    fireEvent.click(screen.getByRole('radio', { name: /^A pact file/ }));
    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'billing-service' } });
    fireEvent.change(screen.getByLabelText('Consumer'), { target: { value: 'orders-ui' } });
  }

  it('saves the stored pact', async () => {
    answers['/api/pact/export/pact-file'] = () => ({ status: 200, body: { pact: { consumer: { name: 'Orders UI' } }, fileName: 'orders-ui-billing-service.json' } });
    openFile();
    fireEvent.click(screen.getByTestId('pexp-file-download'));
    expect(await screen.findByTestId('pexp-file-saved')).toHaveTextContent('Saved orders-ui-billing-service.json.');
    expect(saved).toEqual(['orders-ui-billing-service.json']);
    expect(await axe(document.body, AXE_OPTIONS)).toHaveNoViolations();
  });

  it('says when the pair has no pact', async () => {
    answers['/api/pact/export/pact-file'] = () => ({ status: 404, body: { success: false, error: 'no pact', code: 'pact-not-found' } });
    openFile();
    fireEvent.click(screen.getByTestId('pexp-file-download'));
    expect(await screen.findByTestId('pexp-status')).toHaveTextContent('orders-ui has not published a pact for billing-service.');
  });

  it('downloads every pact for the provider, and not for a single version', async () => {
    answers['/api/pact/export/provider-pacts'] = () => ({ status: 200, body: null });
    openFile();
    fireEvent.click(screen.getByTestId('pexp-file-every'));
    expect(await screen.findByTestId('pexp-file-saved')).toHaveTextContent('Saved billing-pacts.zip.');
    expect(calls.find((call) => call.url.startsWith('/api/pact/export/provider-pacts'))?.url).toBe('/api/pact/export/provider-pacts?provider=billing-service');
    fireEvent.change(screen.getByLabelText('Which pact'), { target: { value: 'version' } });
    expect(screen.getByTestId('pexp-file-every')).toBeDisabled();
    expect(screen.getByTestId('pexp-file-command')).toHaveTextContent('No apiome pact command downloads a stored pact');
  });
});

describe('provider test scaffolding', () => {
  const SCAFFOLD = {
    provider: 'billing-service',
    provider_name: 'Billing Service',
    language: 'typescript',
    label: 'TypeScript · pact-js',
    dependency: 'npm install --save-dev @pact-foundation/pact',
    file_name: 'billing-service.pact.test.ts',
    content: "import { Verifier } from '@pact-foundation/pact';\n\nnew Verifier({ provider: 'Billing Service' });\n",
    pacts: 3,
    states: [
      { name: 'a customer 7 exists', params: [], registered: false, interactions: 1, consumers: ['admin'] },
      { name: 'an invoice exists', params: ['id'], registered: true, interactions: 4, consumers: ['orders-ui'] },
    ],
    unregistered: 1,
    notices: [{ code: 'provider-scaffold-state-unregistered', message: 'not registered in Apiome: hosted verification cannot set this state up until it is', state: 'a customer 7 exists' }],
  };

  function openTests() {
    const view = render(<ExportPactClient prefill={PREFILL} />);
    fireEvent.click(screen.getByRole('radio', { name: /^Provider test scaffolding/ }));
    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'Billing Service' } });
    return view;
  }

  it('writes the tests, flags each state with no handler, and passes axe', async () => {
    answers['/api/pact/export/provider-tests'] = () => ({ status: 200, body: SCAFFOLD });
    const { container } = openTests();
    fireEvent.change(screen.getByLabelText('Language'), { target: { value: 'java' } });
    fireEvent.change(screen.getByLabelText('Language'), { target: { value: 'typescript' } });
    expect(screen.getByTestId('pexp-tests-selectors')).toHaveTextContent('Recommended selectors');
    fireEvent.click(screen.getByTestId('pexp-tests-run'));
    const rows = await screen.findAllByTestId('pexp-tests-state');
    expect(calls.find((call) => call.url.startsWith('/api/pact/export/provider-tests'))?.url).toBe('/api/pact/export/provider-tests?provider=Billing+Service&language=typescript');
    expect(rows[0]).toHaveTextContent('a customer 7 exists');
    expect(rows[0]).toHaveTextContent('No handler');
    expect(rows[1]).toHaveTextContent('Registered');
    expect(screen.getByTestId('pexp-tests-summary')).toHaveTextContent('2 provider states · 1 has no handler in Apiome');
    expect(screen.getByTestId('pexp-tests-notices')).toHaveTextContent('hosted verification cannot set this state up');
    expect(screen.getByTestId('pexp-tests-preview')).toHaveTextContent("import { Verifier }");
    expect(screen.getByTestId('pexp-tests-command')).toHaveTextContent('apiome pact scaffold-provider-tests');
    expect(screen.getByTestId('pexp-tests-command')).toHaveTextContent('--output billing-service.pact.test.ts');
    fireEvent.click(screen.getByTestId('pexp-tests-download'));
    expect(saved).toEqual(['billing-service.pact.test.ts']);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-export-scaffold', liveMarkup(container.firstElementChild!));
  });

  it('copies the file', async () => {
    answers['/api/pact/export/provider-tests'] = () => ({ status: 200, body: SCAFFOLD });
    const writeText = jest.fn(async () => undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    openTests();
    fireEvent.click(screen.getByTestId('pexp-tests-run'));
    await screen.findByTestId('pexp-tests-preview');
    fireEvent.click(screen.getByTestId('pexp-tests-copy'));
    expect(await screen.findByText('Copied.')).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(SCAFFOLD.content);
  });

  it('says why when the provider is unknown, and sends nothing without one', async () => {
    answers['/api/pact/export/provider-tests'] = () => ({ status: 404, body: { success: false, error: 'no pacticipant Billing Service', code: 'pacticipant-not-found' } });
    render(<ExportPactClient prefill={PREFILL} />);
    fireEvent.click(screen.getByRole('radio', { name: /^Provider test scaffolding/ }));
    fireEvent.click(screen.getByTestId('pexp-tests-run'));
    expect(screen.getByTestId('pexp-status')).toHaveTextContent('Provider is required.');
    expect(calls.some((call) => call.url.startsWith('/api/pact/export/provider-tests'))).toBe(false);
    fireEvent.change(screen.getByLabelText('Provider'), { target: { value: 'Billing Service' } });
    fireEvent.click(screen.getByTestId('pexp-tests-run'));
    expect(await screen.findByTestId('pexp-status')).toHaveTextContent('no pacticipant Billing Service');
    expect(screen.getByTestId('pexp-tests-download')).toBeDisabled();
  });

  it('downloads a large file without a preview', async () => {
    answers['/api/pact/export/provider-tests'] = () => ({ status: 200, body: { ...SCAFFOLD, content: 'x'.repeat(250_000) } });
    openTests();
    fireEvent.click(screen.getByTestId('pexp-tests-run'));
    expect(await screen.findByTestId('pexp-tests-large')).toHaveTextContent('too large to preview');
    expect(screen.queryByTestId('pexp-tests-preview')).not.toBeInTheDocument();
  });
});
