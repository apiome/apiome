/**
 * The **Publish a consumer pact** page — PFX-8.3 (#7300), built to
 * `docs/mockups/contracts/publish-pact.html` (Notes → States):
 *
 * * several files at once: each row shows its pair, spec and count; an invalid file marks its row
 *   (“Not a pact: missing consumer”) and the others still publish; the header keeps the action cap;
 *   axe passes;
 * * Check only writes nothing and marks rows new, unchanged (“Unchanged since …”) or a conflict;
 * * publishing sends one request per consumer, and the result dialog says which pacts are new and
 *   pending, which were unchanged, and what was not sent; REST's refusal of one contract marks that
 *   row and the rest are re-sent; a version conflict is explained;
 * * Merge is refused with the reason and sends nothing; Fill from the linked repository sets the
 *   branch;
 * * Paste (and the import dialog's hand-off), Derive from a project;
 * * read-only role: the explanation and the command block only;
 * * anything in the address the page cannot use is reported.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixture `pact-publish`.
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
import { PUBLISH_HANDOFF_KEY, readPublishPrefill } from '../lib/pact-publish-page';
import { countHeaderActions, pageGateViolations } from './helpers/page-gates';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const EDITOR = { is_admin: false, permissions: ['pacts:view', 'pacts:create', 'consumer_contracts:view'] };
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

/** A valid pact document. */
function pact(consumer: string, provider: string, interactions = 2, spec = '3.0.0') {
  return JSON.stringify({
    consumer: { name: consumer },
    provider: { name: provider },
    interactions: Array.from({ length: interactions }, (_, i) => ({
      description: `call ${i}`,
      request: { method: 'GET', path: `/things/${i}` },
      response: { status: 200 },
    })),
    metadata: { pactSpecification: { version: spec } },
  });
}

const BILLING = pact('Orders UI', 'Billing Service', 6);
const ORDERS = pact('Orders UI', 'Orders API', 11, '4.0');
const BROKEN = JSON.stringify({ provider: { name: 'Ledger' }, interactions: [] });

/** REST's answer to a publish of `providers`, each with its state. */
function published(consumer: string, version: string, providers: Array<[string, 'new' | 'unchanged']>) {
  return {
    notices: [
      { type: 'debug', text: `Created ${consumer} version ${version}` },
      ...providers.map(([provider, state]) => ({
        type: 'success',
        text:
          state === 'new'
            ? `Pact successfully published for ${consumer} version ${version} and provider ${provider}.`
            : `Pact successfully republished for ${consumer} version ${version} and provider ${provider} with no content changes.`,
      })),
    ],
    _links: { 'pb:contracts': providers.map(([, state], i) => ({ pactVersionSha: state === 'new' ? `aaaa${i}` : '8d2f1c0beef' })) },
  };
}

// jsdom's Blob/File lack the standard `.text()`; back it with FileReader (as schema-suites-panel does).
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
  calls = [];
  window.sessionStorage.clear();
  answers = {};
  as(EDITOR);
  installFetch();
});

const open = (query: Record<string, string | string[]> = {}) => render(<PublishPactClient prefill={readPublishPrefill(query)} />);

/** Add files through the picker. */
async function upload(files: Array<[string, string]>) {
  const input = await screen.findByTestId('ppub-file-input');
  await act(async () => {
    fireEvent.change(input, { target: { files: files.map(([name, text]) => new File([text], name, { type: 'application/json' })) } });
  });
  await screen.findByTestId('ppub-files');
}

/** Type into a labelled field. */
function type(label: string, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

describe('Publish a consumer pact', () => {
  it('reads several files, marks the invalid one, keeps the header cap and passes axe', async () => {
    const { container } = open({ version: '3.4.0+a1c9e02', branch: 'feature/credit-notes', tag: 'dev' });
    await upload([
      ['orders-ui-billing-service.json', BILLING],
      ['orders-ui-orders-api.json', ORDERS],
      ['ledger.json', BROKEN],
    ]);
    const table = screen.getByTestId('ppub-files');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('Orders UI → Billing Service');
    expect(rows[0]).toHaveTextContent('Pact v3');
    expect(rows[0]).toHaveTextContent('6');
    expect(rows[1]).toHaveTextContent('Pact v4');
    expect(rows[1]).toHaveTextContent('11');
    expect(rows[2]).toHaveClass('ppub-row--invalid');
    expect(rows[2]).toHaveTextContent('Not a pact: missing consumer.');
    expect(screen.getByTestId('ppub-consumer')).toHaveTextContent('Orders UI');

    // The command block follows the form.
    const block = screen.getByTestId('ppub-command-block');
    expect(block).toHaveTextContent('apiome pact publish pacts/');
    expect(block).toHaveTextContent('--consumer-app-version 3.4.0+a1c9e02');

    const header = container.querySelector('[data-testid="page-header"]')!;
    expect(countHeaderActions(header)).toEqual({ primary: 1, secondary: 2, overflow: 0, selects: [] });
    expect(pageGateViolations(container)).toEqual([]);
    expect(screen.getByTestId('contracts-tabs')).toBeInTheDocument();

    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-publish', liveMarkup(container.firstElementChild!));
  });

  it('checks only: reads each version’s pact and writes nothing', async () => {
    answers['/api/pact/publish/check'] = (call) =>
      call.url.includes('Billing')
        ? { status: 404, body: { success: false, error: 'No pact' } }
        : {
            status: 200,
            body: { ...JSON.parse(ORDERS), createdAt: 'x', _links: { 'pb:pact-version': { href: 'http://x/pact-version/8d2f1c0beef' } } },
          };
    open({ version: '3.4.0' });
    await upload([
      ['billing.json', BILLING],
      ['orders.json', ORDERS],
    ]);
    fireEvent.click(screen.getByTestId('ppub-check'));
    const verdicts = await screen.findAllByTestId('ppub-row-verdict');
    expect(verdicts[0]).toHaveTextContent('Nothing is published for 3.4.0 yet: this pact will be new.');
    expect(verdicts[1]).toHaveTextContent('Unchanged since 8d2f1c0: its verification results still apply.');
    expect(calls.filter((call) => call.method !== 'GET')).toEqual([]);
    expect(calls.map((call) => call.url)).toContain('/api/pact/publish/check?consumer=Orders+UI&provider=Billing+Service&version=3.4.0');
  });

  it('explains a version conflict found by a check', async () => {
    answers['/api/pact/publish/check'] = () => ({ status: 200, body: { ...JSON.parse(pact('Orders UI', 'Billing Service', 1)), _links: {} } });
    open({ version: '3.4.0' });
    await upload([['billing.json', BILLING]]);
    fireEvent.click(screen.getByTestId('ppub-check'));
    expect(await screen.findByTestId('ppub-row-verdict')).toHaveTextContent('3.4.0 already has a different pact. Use a new version');
  });

  it('publishes the valid files, one request per consumer, and says what happened', async () => {
    answers['/api/pact/publish'] = (call) => {
      const body = call.body as { consumerName: string; version: string };
      return body.consumerName === 'Orders UI'
        ? { status: 200, body: published('Orders UI', body.version, [['Billing Service', 'new'], ['Orders API', 'unchanged']]) }
        : { status: 200, body: published('Checkout', body.version, [['Payments', 'new']]) };
    };
    open({ version: '3.4.0', branch: 'feature/credit-notes' });
    await upload([
      ['billing.json', BILLING],
      ['orders.json', ORDERS],
      ['checkout.json', pact('Checkout', 'Payments')],
      ['ledger.json', BROKEN],
    ]);
    fireEvent.click(screen.getByTestId('ppub-publish'));
    const dialog = await screen.findByTestId('ppub-result');
    const posts = calls.filter((call) => call.method === 'POST');
    expect(posts.map((call) => (call.body as { consumerName: string }).consumerName)).toEqual(['Orders UI', 'Checkout']);
    expect((posts[0].body as { pacts: unknown[]; branch: string }).pacts).toHaveLength(2);
    expect((posts[0].body as { branch: string }).branch).toBe('feature/credit-notes');
    expect(within(dialog).getByText('3 pacts published')).toBeInTheDocument();
    expect(dialog).toHaveTextContent('Billing Service — new content, pending for Billing Service until they pass it once');
    expect(dialog).toHaveTextContent('Orders API — unchanged since 8d2f1c0: its verification results still apply, nothing to do.');
    expect(screen.getByTestId('ppub-result-skipped')).toHaveTextContent('ledger.json — not sent: Not a pact: missing consumer.');
    expect(screen.getByTestId('ppub-result-follow-up')).toHaveTextContent('notified the contract webhooks');
    expect(within(dialog).getByRole('link', { name: 'Can I deploy?' })).toHaveAttribute('href', '/ade/dashboard/pacts/can-i-deploy');

    fireEvent.click(within(dialog).getByRole('button', { name: 'Publish another' }));
    await waitFor(() => expect(screen.queryByTestId('ppub-result')).toBeNull());
    expect(screen.queryByTestId('ppub-files')).toBeNull();
  });

  it('marks the contract REST refuses and sends the rest again', async () => {
    let attempt = 0;
    answers['/api/pact/publish'] = (call) => {
      attempt += 1;
      const pacts = (call.body as { pacts: Array<{ providerName: string }> }).pacts;
      if (pacts.length === 2) return { status: 422, body: { success: false, error: 'contract 1 (Orders API): the request method must be a non-empty string' } };
      return { status: 200, body: published('Orders UI', '3.4.0', [[pacts[0].providerName, 'new']]) };
    };
    open({ version: '3.4.0' });
    await upload([
      ['billing.json', BILLING],
      ['orders.json', ORDERS],
    ]);
    fireEvent.click(screen.getByTestId('ppub-publish'));
    const dialog = await screen.findByTestId('ppub-result');
    expect(attempt).toBe(2);
    expect(within(dialog).getByText('1 pact published')).toBeInTheDocument();
    expect(screen.getByTestId('ppub-result-skipped')).toHaveTextContent('orders.json — not sent: contract 1 (Orders API)');
    fireEvent.click(within(dialog).getAllByRole('button', { name: 'Close' })[0]);
    await waitFor(() => expect(screen.queryByTestId('ppub-result')).toBeNull());
    expect(screen.getAllByTestId('ppub-row-problem')[0]).toHaveTextContent('contract 1 (Orders API)');
  });

  it('explains a version conflict REST refuses', async () => {
    answers['/api/pact/publish'] = () => ({ status: 409, body: { success: false, error: 'pact-content-conflict' } });
    open({ version: '3.4.0' });
    await upload([['billing.json', BILLING]]);
    fireEvent.click(screen.getByTestId('ppub-publish'));
    const failures = await screen.findByTestId('ppub-result-failures');
    expect(failures).toHaveTextContent('Orders UI — not published: 3.4.0 already has a different pact. Use a new version');
    expect(screen.getByText('Nothing was published')).toBeInTheDocument();
  });

  it('refuses Merge with the reason and sends nothing', async () => {
    open({ version: '3.4.0' });
    await upload([['billing.json', BILLING]]);
    fireEvent.click(screen.getByText('More options'));
    fireEvent.click(screen.getByLabelText('Merge with the pact already published for this version'));
    expect(screen.getByTestId('ppub-command-block')).toHaveTextContent('Merge is not carried by the command');
    fireEvent.click(screen.getByTestId('ppub-publish'));
    expect(await screen.findByTestId('ppub-status')).toHaveTextContent('does not merge interactions');
    expect(calls.filter((call) => call.method === 'POST')).toEqual([]);
  });

  it('asks for a version before anything is sent', async () => {
    open();
    await upload([['billing.json', BILLING]]);
    fireEvent.click(screen.getByTestId('ppub-publish'));
    expect(await screen.findByTestId('ppub-status')).toHaveTextContent('Give the consumer version');
    fireEvent.click(screen.getByTestId('ppub-check'));
    expect(calls.filter((call) => call.url.startsWith('/api/pact/publish'))).toEqual([]);
  });

  it('fills the branch from the consumer’s linked repository', async () => {
    answers['/api/pact/pacticipants/orders-ui'] = () => ({
      status: 200,
      body: { id: '1', slug: 'orders-ui', name: 'Orders UI', main_branch: 'main', repository_url: 'https://github.com/acme/orders-ui', labels: [] },
    });
    open({ version: '3.4.0' });
    await upload([['billing.json', BILLING]]);
    fireEvent.click(screen.getByRole('button', { name: /Fill from the linked repository/ }));
    expect(await screen.findByTestId('ppub-repo-note')).toHaveTextContent('Branch set to main');
    expect(screen.getByLabelText('Branch')).toHaveValue('main');
  });

  it('says when the consumer has no pacticipant to read a repository from', async () => {
    open();
    await upload([['billing.json', BILLING]]);
    fireEvent.click(screen.getByRole('button', { name: /Fill from the linked repository/ }));
    expect(await screen.findByTestId('ppub-repo-note')).toHaveTextContent('Orders UI is not a pacticipant yet');
  });

  it('takes a pasted pact, and the one the import dialog hands over', async () => {
    window.sessionStorage.setItem(PUBLISH_HANDOFF_KEY, JSON.stringify({ pact: BILLING }));
    answers['/api/pact/publish'] = () => ({ status: 200, body: published('Orders UI', '1.0', [['Billing Service', 'new']]) });
    open({ source: 'paste', version: '1.0' });
    expect(await screen.findByLabelText('Pact JSON')).toHaveValue(BILLING);
    expect(window.sessionStorage.getItem(PUBLISH_HANDOFF_KEY)).toBeNull();
    expect(screen.getByTestId('ppub-paste-detected')).toHaveTextContent('Pact v3 detected');
    fireEvent.click(screen.getByTestId('ppub-publish'));
    await screen.findByTestId('ppub-result');
    const post = calls.find((call) => call.method === 'POST')!;
    expect(post.body).toEqual({ consumerName: 'Orders UI', version: '1.0', pacts: [{ providerName: 'Billing Service', pact: BILLING }] });
  });

  it('marks a pasted document that is not a pact', async () => {
    open({ source: 'paste' });
    await screen.findByLabelText('Pact JSON');
    type('Pact JSON', '{"interactions": []}');
    expect(await screen.findByTestId('ppub-row-problem')).toHaveTextContent('Not a pact: missing consumer.');
  });

  it('derives a pact from a project and lists its findings', async () => {
    answers['/api/projects'] = () => ({ status: 200, body: { success: true, projects: [{ id: 'p1', slug: 'billing', name: 'Billing API' }] } });
    answers['/api/consumers/billing'] = () => ({
      status: 200,
      body: {
        success: true,
        data: {
          consumers: [
            { consumer: { slug: 'orders-ui', name: 'Orders UI' }, contract: { source: 'manual' } },
            { consumer: { slug: 'legacy', name: 'Legacy' }, contract: { source: 'pact' } },
          ],
        },
      },
    });
    answers['/api/pact/publish/consumer-contract'] = () => ({
      status: 200,
      body: {
        consumer_name: 'Orders UI',
        revision: 2,
        findings: [{ outcome: 'placeholder', message: 'No example for amount', method: 'POST', path: '/invoices' }],
        pact: { consumer: { name: 'Orders UI' } },
        publish: published('Orders UI', '3.4.0', [['Billing API', 'new']]),
      },
    });
    open({ source: 'derive', version: '3.4.0' });
    await waitFor(() => expect(screen.getByLabelText('Project')).toHaveTextContent('Billing API'));
    fireEvent.change(screen.getByLabelText('Project'), { target: { value: 'billing' } });
    await waitFor(() => expect(screen.getByLabelText('Consumer')).toHaveTextContent('Orders UI'));
    expect(within(screen.getByLabelText('Consumer')).getByRole('option', { name: /Legacy — was imported from a Pact file/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Consumer'), { target: { value: 'orders-ui' } });
    type('Revision (optional)', '2');
    expect(screen.getByTestId('ppub-command-block')).toHaveTextContent('apiome pact publish-consumer-contract');
    fireEvent.click(screen.getByTestId('ppub-publish'));
    const derived = await screen.findByTestId('ppub-result-derived');
    expect(calls.find((call) => call.method === 'POST')!.body).toEqual({ project: 'billing', consumer: 'orders-ui', version: '3.4.0', revision: 2 });
    expect(derived).toHaveTextContent('Generated from contract revision 2: 1 finding');
    expect(derived).toHaveTextContent('POST /invoices No example for amount');
    expect(within(derived).getByRole('button', { name: 'Download the published pact' })).toBeInTheDocument();
  });

  it('shows a read-only role the explanation and the command block only', async () => {
    as(VIEWER);
    const { container } = open();
    expect(await screen.findByTestId('ppub-readonly')).toHaveTextContent('Your role cannot publish pacts');
    expect(screen.getByTestId('ppub-command-block')).toHaveTextContent('apiome pact publish pacts/');
    expect(screen.queryByTestId('ppub-file-input')).toBeNull();
    const header = container.querySelector('[data-testid="page-header"]')!;
    expect(countHeaderActions(header)).toEqual({ primary: 0, secondary: 0, overflow: 0, selects: [] });
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });

  it('reports what in the address it cannot use', async () => {
    open({ source: 'record', colour: 'blue' });
    expect(await screen.findByTestId('ppub-status')).toHaveTextContent('?colour= is not something this page reads.');
    expect(screen.getByTestId('ppub-status')).toHaveTextContent('?source=record is not a way in');
  });

  it('reports a non-JSON file in a folder instead of dropping it', async () => {
    open();
    await upload([
      ['pacts/billing.json', BILLING],
      ['pacts/README.md', '# notes'],
    ]);
    expect(screen.getByTestId('ppub-row-problem')).toHaveTextContent('Not a .json file');
  });
});
