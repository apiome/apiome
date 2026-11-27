/**
 * **Write interactions** on the Publish page — PFX-8.5 (#7302), built to
 * `docs/mockups/contracts/publish-pact.html` (`src-build`):
 *
 * * leaving the provider field reads its spec; a path in the spec reads “Matches …”, and **Fill
 *   from the spec** fills the status, the example and the matcher chips;
 * * a path that is not in the spec is flagged in the list and the form, and still publishes;
 * * the written pact goes through the normal publish path as a Pact v4 document;
 * * the list is one Tab stop and ↑ ↓ Home End move the selection; every control is labelled; axe;
 * * an interaction that cannot be written yet says why, and nothing is sent;
 * * message, GraphQL and gRPC interactions sit in the same list;
 * * a pasted pact opens in the editor, with what it cannot hold listed;
 * * a refused spec read is shown; a read-only role gets no editor.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixture `pact-publish-editor`.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/navigation', () => ({ useRouter: () => ({ replace: jest.fn(), push: jest.fn() }) }));
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import PublishPactClient from '../src/app/components/ade/pactPublish/PublishPactClient';
import { readPublishPrefill } from '../lib/pact-publish-page';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const EDITOR = { is_admin: false, permissions: ['pacts:view', 'pacts:create'] };
const VIEWER = { is_admin: false, permissions: ['pacts:view'] };

type Answer = { status: number; body: unknown };
type Call = { url: string; method: string; body: unknown };
let answers: Record<string, (call: Call) => Answer>;
let calls: Call[];

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
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
}

function as(role: typeof EDITOR) {
  answers['/api/access/permissions/me'] = () => ({ status: 200, body: { success: true, data: role } });
}

/** What the BFF answers for Billing Service. */
const SPEC = {
  provider: 'Billing Service',
  revision: { projectId: 'p-1', versionId: 'v-2', label: '2.7.0' },
  operations: [
    {
      method: 'GET',
      path: '/invoices/{id}',
      summary: 'Get an invoice',
      responses: [
        {
          status: '200',
          contentType: 'application/json',
          example: { id: 42, amount: 1200, currency: 'EUR' },
          exampleSource: 'spec',
          fields: [
            { path: '$.id', type: 'integer' },
            { path: '$.amount', type: 'integer' },
            { path: '$.currency', type: 'string', pattern: '^[A-Z]{3}$' },
          ],
        },
      ],
    },
    { method: 'POST', path: '/invoices', summary: 'Create an invoice', responses: [] },
  ],
  states: [
    { name: 'an invoice exists', source: 'catalogue', parameters: [{ name: 'id', required: true }], description: null },
    { name: 'billing is down', source: 'mock', parameters: [], description: 'Every call answers 503' },
  ],
  problems: [],
};

beforeEach(() => {
  calls = [];
  window.sessionStorage.clear();
  answers = { '/api/pact/environments': () => ({ status: 200, body: { environments: [] } }) };
  answers['/api/pact/publish/provider-spec'] = () => ({ status: 200, body: SPEC });
  as(EDITOR);
  installFetch();
});

const open = (query: Record<string, string> = { source: 'write' }) => render(<PublishPactClient prefill={readPublishPrefill(query)} />);

/** Set a field by its id or label. */
function set(target: string | HTMLElement, value: string) {
  const element = typeof target === 'string' ? screen.getByLabelText(target) : target;
  fireEvent.change(element, { target: { value } });
}

/** Name the pair; leaving the provider reads its spec. */
async function namePair(consumer = 'Orders UI', provider = 'Billing Service') {
  const consumerField = await screen.findByRole('textbox', { name: 'Consumer' });
  set(consumerField, consumer);
  const providerField = screen.getByRole('textbox', { name: 'Provider' });
  set(providerField, provider);
  fireEvent.blur(providerField);
}

/** Add one interaction of the kind chosen in the segmented control. */
function addInteraction(kind: 'HTTP' | 'Message' | 'GraphQL' | 'gRPC' = 'HTTP') {
  fireEvent.click(within(screen.getByRole('radiogroup', { name: 'Kind of new interactions' })).getByRole('radio', { name: kind }));
  fireEvent.click(screen.getByTestId('ppub-add-interaction'));
}

/** Write the mockup's first interaction and fill its response from the spec. */
async function writeInvoice() {
  await namePair();
  await screen.findByText(/revision 2\.7\.0 \(2 operations\)/);
  addInteraction();
  set('Description', 'get invoice 42');
  set('Path', '/invoices/42');
  fireEvent.click(screen.getByRole('button', { name: 'Provider state' }));
  set('Provider state 1', 'an invoice exists');
  set('Parameters of provider state 1', 'id = 42');
  fireEvent.click(screen.getByTestId('ppub-fill-from-spec'));
}

describe('Write interactions', () => {
  it('writes an interaction to the mockup, fills it from the spec, and passes axe', async () => {
    const { container } = open();
    await writeInvoice();
    expect(calls.map((call) => call.url)).toContain('/api/pact/publish/provider-spec?provider=Billing+Service');
    expect(screen.getByTestId('ppub-spec-flag')).toHaveTextContent('Matches GET /invoices/{id} in revision 2.7.0.');
    expect(screen.getByTestId('ppub-fill-note')).toHaveTextContent('Filled from the 200 response of GET /invoices/{id}: the spec’s example.');
    expect(screen.getByLabelText('Status')).toHaveValue('200');
    expect(JSON.parse((screen.getByLabelText('Response body') as HTMLTextAreaElement).value)).toEqual({ id: 42, amount: 1200, currency: 'EUR' });
    expect(screen.getByLabelText('Matcher of field 3 of the response')).toHaveValue('regex');
    expect(screen.getByLabelText('Pattern for field 3 of the response')).toHaveValue('^[A-Z]{3}$');
    // The catalogue's state is recognised, with its parameter.
    expect(screen.getByTestId('ppub-state-known')).toHaveTextContent('In the provider’s state catalogue — takes id (required).');
    // The written pact is a row like any file: its pair, Pact v4, one interaction, HTTP.
    const row = screen.getByTestId('ppub-file-written');
    expect(row).toHaveTextContent('Orders UI → Billing Service');
    expect(row).toHaveTextContent('Pact v4');
    expect(row).toHaveTextContent('HTTP');
    expect(screen.getByTestId('ppub-command-block')).toBeInTheDocument();
    // Read one more state suggestion so the docs fixture shows the list with two kinds.
    addInteraction();
    set('Description', 'create an invoice');
    fireEvent.change(screen.getByLabelText('Method'), { target: { value: 'POST' } });
    set('Path', '/invoices');
    set('Status', '201');
    addInteraction();
    set('Description', 'list credit notes');
    set('Path', '/credit-notes');
    fireEvent.click(within(screen.getByTestId('ppub-ix-list')).getByText('get invoice 42'));
    await waitFor(() => expect(screen.getByLabelText('Description')).toHaveValue('get invoice 42'));
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-publish-editor', liveMarkup(container.firstElementChild!));
  });

  it('publishes the written pact as Pact v4 through the normal publish path', async () => {
    answers['/api/pact/publish'] = () => ({
      status: 200,
      body: {
        notices: [{ type: 'success', text: 'Pact successfully published for Orders UI version 3.4.0 and provider Billing Service.' }],
        _links: { 'pb:contracts': [{ pactVersionSha: 'abc1234' }] },
      },
    });
    open();
    await writeInvoice();
    set('Consumer version', '3.4.0');
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppub-publish'));
    });
    const sent = calls.find((call) => call.url === '/api/pact/publish' && call.method === 'POST');
    expect(sent).toBeDefined();
    const body = sent!.body as { consumerName: string; version: string; pacts: Array<{ providerName: string; pact: string }> };
    expect(body).toMatchObject({ consumerName: 'Orders UI', version: '3.4.0', pacts: [{ providerName: 'Billing Service' }] });
    const pact = JSON.parse(body.pacts[0].pact);
    expect(pact.metadata.pactSpecification.version).toBe('4.0');
    expect(pact.interactions[0]).toMatchObject({
      type: 'Synchronous/HTTP',
      description: 'get invoice 42',
      providerStates: [{ name: 'an invoice exists', params: { id: 42 } }],
      request: { method: 'GET', path: '/invoices/42' },
      response: { status: 200, headers: { 'Content-Type': ['application/json'] }, matchingRules: { body: { '$.id': { combine: 'AND', matchers: [{ match: 'integer' }] } } } },
    });
    expect(await screen.findByRole('dialog')).toHaveTextContent('Billing Service');
  });

  it('flags a path that is not in the spec, and still publishes it', async () => {
    answers['/api/pact/publish'] = () => ({ status: 200, body: { notices: [], _links: {} } });
    open();
    await namePair();
    await screen.findByText(/revision 2\.7\.0/);
    addInteraction();
    set('Description', 'list credit notes');
    set('Path', '/credit-notes');
    expect(screen.getByTestId('ppub-spec-flag')).toHaveTextContent('GET /credit-notes is not in the spec in 2.7.0. It can still be published; the comparison will report it.');
    expect(within(screen.getByTestId('ppub-ix-list')).getByText(', not in the spec')).toBeInTheDocument();
    expect(screen.getByTestId('ppub-fill-from-spec')).toBeDisabled();
    expect(screen.getByTestId('ppub-file-written')).not.toHaveTextContent('Not ready');
    set('Consumer version', '3.4.0');
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppub-publish'));
    });
    expect(calls.some((call) => call.url === '/api/pact/publish' && call.method === 'POST')).toBe(true);
  });

  it('moves through the list with the arrow keys, Home and End — one Tab stop', async () => {
    open();
    await namePair();
    for (const name of ['first', 'second', 'third']) {
      addInteraction();
      set('Description', name);
    }
    const list = screen.getByRole('listbox', { name: 'Interactions' });
    const options = within(list).getAllByRole('option');
    expect(options.map((o) => o.getAttribute('tabindex'))).toEqual(['-1', '-1', '0']);
    expect(options[2]).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(list, { key: 'ArrowUp' });
    expect(within(list).getAllByRole('option')[1]).toHaveAttribute('aria-selected', 'true');
    expect(within(list).getAllByRole('option')[1]).toHaveFocus();
    expect(screen.getByLabelText('Description')).toHaveValue('second');
    fireEvent.keyDown(list, { key: 'Home' });
    expect(screen.getByLabelText('Description')).toHaveValue('first');
    fireEvent.keyDown(list, { key: 'ArrowUp' });
    expect(screen.getByLabelText('Description')).toHaveValue('first');
    fireEvent.keyDown(list, { key: 'End' });
    expect(screen.getByLabelText('Description')).toHaveValue('third');
    fireEvent.keyDown(list, { key: 'ArrowDown' });
    expect(screen.getByLabelText('Description')).toHaveValue('third');
  });

  it('says what stops an interaction, and sends nothing while it does', async () => {
    open();
    await namePair();
    addInteraction();
    set('Path', 'invoices');
    expect(screen.getByTestId('ppub-ix-problems')).toHaveTextContent('Describe the interaction');
    expect(screen.getByTestId('ppub-ix-problems')).toHaveTextContent('The path starts with /.');
    expect(within(screen.getByTestId('ppub-ix-list')).getByText(', cannot be published yet')).toBeInTheDocument();
    expect(screen.getByTestId('ppub-file-written')).toHaveTextContent('Not ready to publish: 2 things need fixing in the editor');
    expect(screen.getByTestId('ppub-download-written')).toBeDisabled();
    set('Consumer version', '3.4.0');
    fireEvent.click(screen.getByTestId('ppub-publish'));
    expect(await screen.findByTestId('ppub-status')).toHaveTextContent('No pact here can be published: each row says why.');
    expect(calls.some((call) => call.method === 'POST')).toBe(false);
  });

  it('adds a field the consumer needs: the value goes in the body and the matcher on the field', async () => {
    open();
    await namePair();
    addInteraction();
    const matchers = screen.getAllByRole('button', { name: 'Field the consumer needs' });
    fireEvent.click(matchers[matchers.length - 1]);
    set('Field path', '$.currency');
    set('Example value', '"EUR"');
    fireEvent.change(screen.getByLabelText('Matcher'), { target: { value: 'regex' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add field' }));
    expect(JSON.parse((screen.getByLabelText('Response body') as HTMLTextAreaElement).value)).toEqual({ currency: 'EUR' });
    set('Pattern for field 1 of the response', '^[A-Z]{3}$');
    expect(screen.getByLabelText('Field 1 of the response')).toHaveValue('$.currency');
  });

  it('holds message, GraphQL and gRPC interactions in the same list', async () => {
    open();
    await namePair();
    addInteraction('Message');
    set('Description', 'invoice paid');
    set('Contents', '{"invoiceId": 42}');
    addInteraction('GraphQL');
    set('Description', 'invoice by graphql');
    set('Operation', 'query { invoice(id: 42) { id } }');
    addInteraction('gRPC');
    set('Description', 'get invoice over grpc');
    set('Service and method', 'billing.Invoices/GetInvoice');
    expect(screen.getByTestId('ppub-grpc-note')).toHaveTextContent('descriptors missing');
    const list = screen.getByTestId('ppub-ix-list');
    expect(within(list).getByText('Message')).toBeInTheDocument();
    expect(within(list).getByText('GraphQL')).toBeInTheDocument();
    expect(within(list).getByText('gRPC')).toBeInTheDocument();
    const row = screen.getByTestId('ppub-file-written');
    expect(row).toHaveTextContent('Message');
    expect(row).toHaveTextContent('GraphQL');
    expect(row).toHaveTextContent('gRPC');
    expect(within(row).getByText('3')).toBeInTheDocument();
  });

  it('opens a pasted pact in the editor and lists what it cannot hold', async () => {
    open({ source: 'paste' });
    const pasted = JSON.stringify({
      consumer: { name: 'Orders UI' },
      provider: { name: 'Billing Service' },
      interactions: [{ description: 'get invoice', pending: true, request: { method: 'GET', path: '/invoices/1' }, response: { status: 200 } }],
      metadata: { pactSpecification: { version: '3.0.0' } },
    });
    fireEvent.change(await screen.findByLabelText('Pact JSON'), { target: { value: pasted } });
    fireEvent.click(screen.getByTestId('ppub-edit-pasted'));
    expect(await screen.findByTestId('ppub-editor')).toBeInTheDocument();
    expect(screen.getByLabelText('Description')).toHaveValue('get invoice');
    expect(screen.getByTestId('ppub-import-notes')).toHaveTextContent('Interaction 1 has pending; the editor does not write it, so it was not read.');
    await waitFor(() => expect(screen.getByTestId('ppub-spec-flag')).toHaveTextContent('Matches GET /invoices/{id}'));
  });

  it('shows a refused spec read, and the editor still works', async () => {
    answers['/api/pact/publish/provider-spec'] = () => ({ status: 403, body: { success: false, error: 'Missing permission pacts:view' } });
    open();
    await namePair();
    expect(await screen.findByText('Missing permission pacts:view')).toBeInTheDocument();
    addInteraction();
    set('Path', '/anything');
    expect(screen.getByTestId('ppub-spec-flag')).toHaveTextContent('No spec to check the path against.');
  });

  it('a read-only role gets no editor', async () => {
    as(VIEWER);
    open();
    await screen.findByTestId('ppub-readonly');
    expect(screen.queryByTestId('ppub-editor')).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Write interactions' })).not.toBeInTheDocument();
    expect(calls.some((call) => call.url.startsWith('/api/pact/publish/provider-spec'))).toBe(false);
  });
});
