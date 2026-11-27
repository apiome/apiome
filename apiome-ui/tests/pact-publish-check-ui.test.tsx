/**
 * **Check it before it counts** on the Publish page — PFX-8.4 (#7301), built to
 * `docs/mockups/contracts/publish-pact.html`:
 *
 * * **Compare with** starts on the provider's main branch and the production environment, offers
 *   every environment and the latest draft, and takes any version typed into **+ Another version**
 *   (a bad one is refused with the reason, never dropped);
 * * **Check only** sends each pact with the chosen selectors to the compare proxy (nothing is
 *   published) and the aside shows one pill per provider version with match / differs / not in spec
 *   per interaction; axe passes in light and dark;
 * * **See the difference** opens the drawer: what the pact needs beside what the spec declares,
 *   and the spec change;
 * * selectors that named nothing are listed; nothing to compare with reads the mockup's sentence;
 * * **Re-check** compares one pact again; the check's own command block is `apiome pact check`.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixture `pact-publish-check`.
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

type Call = { url: string; method: string; body: unknown };
type Answer = { status: number; body: unknown };
let answers: Record<string, (call: Call) => Answer>;
let calls: Call[];

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

const PACT = JSON.stringify({
  consumer: { name: 'Orders UI' },
  provider: { name: 'Billing Service' },
  interactions: [
    { description: 'an invoice', providerState: 'an invoice exists', request: { method: 'GET', path: '/invoices/{id}' }, response: { status: 200 } },
    { description: 'a customer', request: { method: 'GET', path: '/customers/{id}' }, response: { status: 200 } },
    { description: 'create', request: { method: 'POST', path: '/invoices' }, response: { status: 201, body: { id: 1, amount: 1200, currency: 'EUR' } } },
    { description: 'pdf', request: { method: 'GET', path: '/invoices/{id}/pdf' }, response: { status: 200 } },
    { description: 'list', request: { method: 'GET', path: '/invoices' }, response: { status: 200 } },
    { description: 'delete', request: { method: 'DELETE', path: '/invoices/{id}' }, response: { status: 204 } },
  ],
  metadata: { pactSpecification: { version: '3.0.0' } },
});

const match = (index: number, method: string, path: string, status: number, providerStates: string[] = []) => ({
  index,
  method,
  path,
  status,
  providerStates,
  outcome: 'match',
  verdict: 'pass',
  failures: [],
});

/** REST's answer: main (2.7.0) has a difference and an unknown operation; production (2.6.1) matches. */
const ANSWER = {
  consumer: { name: 'Orders UI' },
  provider: { name: 'Billing Service', slug: 'billing-service', registered: true },
  summary: { versions: 2, passed: 1, failed: 1, unresolved: 1, skipped: 0, success: false },
  results: [
    {
      selectors: ['main'],
      reasons: ['main branch main'],
      providerVersion: '2.7.0',
      draft: false,
      verdict: 'fail',
      comparisonVerdict: 'fail',
      success: false,
      selfVerification: 'verified',
      source: { projectId: 'p-billing', projectSlug: 'billing-api', versionLabel: '2.7.0' },
      counts: { match: 4, differs: 1, notInSpec: 1 },
      interactions: [
        match(0, 'GET', '/invoices/{id}', 200, ['an invoice exists']),
        match(1, 'GET', '/customers/{id}', 200),
        {
          index: 2,
          method: 'POST',
          path: '/invoices',
          status: 201,
          providerStates: [],
          outcome: 'differs',
          verdict: 'fail',
          failures: [
            {
              code: 'response.body.unknown-property',
              message: 'Needs currency in the 201 body; 2.7.0 does not declare it.',
              pactPointer: '/interactions/2/response/body/currency',
              oasPointer: '#/paths/~1invoices/post/responses/201',
            },
          ],
          expected: { value: { status: 201, body: { id: 1, amount: 1200, currency: 'EUR' } } },
          declared: {
            pointer: '#/paths/~1invoices/post/responses/201',
            value: { description: 'Created', content: { 'application/json': { schema: { properties: { id: {}, amount: {}, money: {} } } } } },
          },
        },
        {
          index: 3,
          method: 'GET',
          path: '/invoices/{id}/pdf',
          status: 200,
          providerStates: [],
          outcome: 'not-in-spec',
          verdict: 'fail',
          failures: [{ code: 'request.operation.unknown', message: 'The provider declares no operation on /invoices/{id}/pdf.' }],
          expected: { value: { status: 200 } },
          declared: { value: null },
        },
        match(4, 'GET', '/invoices', 200),
        match(5, 'DELETE', '/invoices/{id}', 204),
      ],
    },
    {
      selectors: ['deployed:production'],
      reasons: ['deployed to production'],
      providerVersion: '2.6.1',
      draft: false,
      verdict: 'pass',
      comparisonVerdict: 'pass',
      success: true,
      selfVerification: 'verified',
      source: null,
      counts: { match: 6, differs: 0, notInSpec: 0 },
      interactions: [0, 1, 2, 3, 4, 5].map((i) => match(i, 'GET', `/x/${i}`, 200)),
    },
  ],
  unresolved: [{ selector: 'draft:latest', reason: 'Billing Service is not bound to an Apiome project, so it has no draft to compare with' }],
  skipped: [],
};

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
  answers = {
    '/api/access/permissions/me': () => ({ status: 200, body: { success: true, data: EDITOR } }),
    '/api/pact/environments': () => ({
      status: 200,
      body: { _embedded: { environments: [{ name: 'staging', production: false }, { name: 'production', production: true }] } },
    }),
    '/api/pact/publish/check': () => ({ status: 404, body: { success: false, error: 'No pact' } }),
    '/api/pact/publish/compare': () => ({ status: 200, body: ANSWER }),
  };
  installFetch();
});

const open = () => render(<PublishPactClient prefill={readPublishPrefill({ version: '3.4.0+a1c9e02', branch: 'feature/credit-notes' })} />);

async function upload(name: string, text: string) {
  const input = await screen.findByTestId('ppub-file-input');
  await act(async () => {
    fireEvent.change(input, { target: { files: [new File([text], name, { type: 'application/json' })] } });
  });
  await screen.findByTestId('ppub-files');
}

/** Wait for the environment chips. */
async function chipsReady() {
  await screen.findByTestId('ppub-chip-deployed:production');
}

describe('Check it before it counts', () => {
  it('starts on main and production, offers every environment and the latest draft', async () => {
    open();
    await chipsReady();
    expect(screen.getByTestId('ppub-chip-main')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('ppub-chip-deployed:production')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('ppub-chip-deployed:staging')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByTestId('ppub-chip-draft:latest')).toHaveAttribute('aria-pressed', 'false');
    const command = screen.getByTestId('ppub-check-command');
    expect(command).toHaveTextContent('apiome pact check pacts/');
    expect(command).toHaveTextContent('--against main');
    expect(command).toHaveTextContent('--against deployed:production');
  });

  it('compares each pact with the chosen versions, one pill each, and publishes nothing', async () => {
    const { container } = open();
    await chipsReady();
    fireEvent.click(screen.getByTestId('ppub-chip-draft:latest'));
    await upload('orders-ui-billing-service.json', PACT);
    fireEvent.click(screen.getByTestId('ppub-check'));

    const card = await screen.findByTestId('ppub-check-result');
    await within(card).findAllByTestId('ppub-check-pill');
    const compare = calls.filter((call) => call.url === '/api/pact/publish/compare');
    expect(compare).toHaveLength(1);
    expect(compare[0].body).toEqual({ pact: JSON.parse(PACT), against: ['main', 'deployed:production', 'draft:latest'] });
    expect(calls.some((call) => call.url === '/api/pact/publish' && call.method === 'POST')).toBe(false);

    expect(card).toHaveTextContent('Orders UI → Billing Service');
    const pills = within(card).getAllByTestId('ppub-check-pill');
    expect(pills.map((pill) => pill.textContent)).toEqual(['main · 2.7.04/6', 'production · 2.6.16/6']);
    const rows = within(card).getAllByTestId('ppub-ix');
    // What needs attention first, then two of the matches; the rest behind Show all.
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent('POST /invoices');
    expect(rows[0]).toHaveTextContent('Differs');
    expect(rows[1]).toHaveTextContent('Not in spec');
    expect(rows[2]).toHaveTextContent('“an invoice exists” · 200');
    expect(card).toHaveTextContent('2 more match');
    fireEvent.click(within(card).getByRole('button', { name: 'Show all 6' }));
    expect(within(card).getAllByTestId('ppub-ix')).toHaveLength(6);
    expect(screen.getByTestId('ppub-check-unresolved')).toHaveTextContent('draft:latest — not compared: Billing Service is not bound');

    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-publish-check', liveMarkup(container.firstElementChild!));
  });

  it('shows every interaction matching on the production pill', async () => {
    open();
    await chipsReady();
    await upload('billing.json', PACT);
    fireEvent.click(screen.getByTestId('ppub-check'));
    const card = await screen.findByTestId('ppub-check-result');
    const pills = await within(card).findAllByTestId('ppub-check-pill');
    await act(async () => {
      fireEvent.mouseDown(pills[1]);
      fireEvent.click(pills[1]);
    });
    await waitFor(() => expect(card).toHaveTextContent('All 6 interactions match 2.6.1'));
  });

  it('opens the difference drawer: the pact beside the spec, and the spec change', async () => {
    open();
    await chipsReady();
    await upload('billing.json', PACT);
    fireEvent.click(screen.getByTestId('ppub-check'));
    const card = await screen.findByTestId('ppub-check-result');
    await within(card).findAllByTestId('ppub-ix');
    fireEvent.click(within(card).getAllByRole('button', { name: 'See the difference' })[0]);
    const drawer = await screen.findByTestId('ppub-difference');
    expect(drawer).toHaveTextContent('POST /invoices — 201');
    expect(drawer).toHaveTextContent('What the pact needs, beside what Billing Service 2.7.0 declares');
    expect(within(drawer).getByLabelText('Pact expects')).toHaveTextContent('"currency": "EUR"');
    expect(within(drawer).getByLabelText('Spec declares')).toHaveTextContent('"money"');
    expect(drawer).toHaveTextContent('response.body.unknown-property');
    expect(within(drawer).getByRole('link', { name: 'Open billing-api 2.7.0' })).toHaveAttribute(
      'href',
      '/ade/dashboard/versions?projectId=p-billing',
    );
    expect(await axe(drawer, AXE_OPTIONS)).toHaveNoViolations();
  });

  it('takes another version, refuses a bad one with the reason, and re-checks', async () => {
    open();
    await chipsReady();
    fireEvent.click(screen.getByTestId('ppub-chip-add'));
    fireEvent.change(screen.getByTestId('ppub-chip-input'), { target: { value: 'tag:prod' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(screen.getByRole('alert')).toHaveTextContent('tag:prod is not a provider version');
    fireEvent.change(screen.getByTestId('ppub-chip-input'), { target: { value: '2.8.0' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(screen.getByTestId('ppub-chip-version:2.8.0')).toHaveAttribute('aria-pressed', 'true');

    await upload('billing.json', PACT);
    fireEvent.click(screen.getByTestId('ppub-compare'));
    const card = await screen.findByTestId('ppub-check-result');
    await within(card).findAllByTestId('ppub-check-pill');
    expect(calls.filter((call) => call.url === '/api/pact/publish/compare')[0].body).toMatchObject({
      against: ['main', 'deployed:production', 'version:2.8.0'],
    });
    fireEvent.click(within(card).getByRole('button', { name: 'Re-check' }));
    await waitFor(() => expect(calls.filter((call) => call.url === '/api/pact/publish/compare')).toHaveLength(2));
  });

  it('says so when the provider has nothing to compare with', async () => {
    answers['/api/pact/publish/compare'] = () => ({
      status: 200,
      body: {
        ...ANSWER,
        provider: { name: 'Billing Service', slug: null, registered: false },
        results: [],
        unresolved: [{ selector: 'main', reason: 'Billing Service is not registered in this workspace yet' }],
      },
    });
    open();
    await chipsReady();
    await upload('billing.json', PACT);
    fireEvent.click(screen.getByTestId('ppub-check'));
    expect(await screen.findByTestId('ppub-check-nothing')).toHaveTextContent(
      'Billing Service has no contract or deployed version yet. Publish anyway — the verdict appears when the provider shows up.',
    );
  });

  it('shows REST’s refusal in the card', async () => {
    answers['/api/pact/publish/compare'] = () => ({ status: 429, body: { success: false, error: 'this workspace may run 60 checks per 60 seconds; retry later' } });
    open();
    await chipsReady();
    await upload('billing.json', PACT);
    fireEvent.click(screen.getByTestId('ppub-check'));
    const card = await screen.findByTestId('ppub-check-result');
    await waitFor(() => expect(card).toHaveTextContent('retry later'));
  });

  it('still offers main and typing a version when the environments cannot be read', async () => {
    answers['/api/pact/environments'] = () => ({ status: 403, body: { success: false, error: 'Missing permission' } });
    open();
    await screen.findByText(/Type a provider version with \+ Another version/);
    expect(screen.getByTestId('ppub-chip-main')).toHaveAttribute('aria-pressed', 'true');
  });
});
