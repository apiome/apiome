/**
 * Standing sources on **Publish a provider contract** — PFX-8.7 (#7304), built to
 * `docs/mockups/contracts/provider-contract.html`:
 *
 * * **Do this on every publish** is saved with the publish (the provider is bound to the project
 *   when it is bound to none) and the result dialog says so — or why it could not be;
 * * the **Repository** tab follows a file: nothing is published or compared now, **Compare only**
 *   is off with the reason, the provider version and evidence give way to what a push records, a
 *   repository whose files cannot be read is offered but disabled, and the command block shows the
 *   pipeline's per-push command;
 * * **Published automatically** says where the provider's contract already comes from, repeats
 *   REST's warnings, and stops a source (new publishes only);
 * * axe passes on each.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixture `pact-provider-contract-preview`.
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

import { ProviderContractClient } from '../src/app/components/ade/pactProviderContract';
import { countHeaderActions, pageGateViolations } from './helpers/page-gates';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const EDITOR = { is_admin: false, permissions: ['pacts:view', 'pacts:create', 'pacts:edit', 'versions:view', 'imports:view'] };

type Answer = { status: number; body: unknown };
type Call = { url: string; method: string; body: Record<string, unknown> | undefined };
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

const CHECK = {
  success: true,
  provider: { name: 'Billing Service', exists: true },
  providerVersion: '2.7.0',
  contract: { contractType: 'oas', oasVersion: '3.1.0', operationCount: 12, contentSha: 'ab' },
  selfVerification: { status: 'missing', providerContractVerified: false, reasons: ['no self-verification results were sent'] },
  existing: null,
  summary: { publishable: true },
  results: [
    {
      consumer: 'Orders UI',
      consumerVersion: '3.3.2',
      sha: '8d2f1c0beef',
      environments: ['production'],
      verdict: 'fail',
      success: false,
      interactions: 3,
      failures: [{ interaction: 'create an invoice', operation: 'POST /invoices', code: 'response.body.required', message: 'no longer returns currency' }],
      moreFailures: 0,
    },
    { consumer: 'Mobile App', consumerVersion: '5.1.0', sha: '51ab90aa', environments: [], verdict: 'unverified', success: true, interactions: 4, failures: [], moreFailures: 0 },
    { consumer: 'Checkout', consumerVersion: '1.0.0', sha: 'c07e33bb', environments: [], verdict: 'unverified', success: true, interactions: 2, failures: [], moreFailures: 0 },
  ],
  coverage: { operations: 12, used: 7, unused: [{ method: 'DELETE', path: '/invoices/{id}' }, { method: 'GET', path: '/health' }], unusedMore: 0 },
};

const PUBLISHED = {
  success: true,
  published: true,
  created: true,
  contract: {
    provider: { name: 'Billing Service' },
    providerVersion: '2.7.0',
    selfVerification: { status: 'missing', providerContractVerified: false },
    comparisons: { results: [{ consumer: 'Orders UI', status: 'compared', verdict: 'fail' }] },
  },
};

const FOLLOWED = {
  success: true,
  pacticipant: 'billing-service',
  onProjectPublish: true,
  project: { id: 'p1', slug: 'billing-api', name: 'Billing API' },
  repository: null,
  warnings: [],
};

const REPOSITORIES = {
  success: true,
  repositories: [
    { id: 'r1', full_name: 'acme/billing', provider: 'github', default_branch: 'main' },
    { id: 'r2', full_name: 'acme/ledger', provider: 'gitlab', default_branch: 'trunk' },
  ],
};

/** The sources REST answers a GET with; the default is "not registered yet". */
let stored: Answer;

beforeEach(() => {
  jest.useRealTimers();
  calls = [];
  stored = { status: 404, body: { success: false, error: 'not found' } };
  answers = {
    '/api/access/permissions/me': () => ({ status: 200, body: { success: true, data: EDITOR } }),
    '/api/projects': () => ({ status: 200, body: { success: true, projects: [{ id: 'p1', name: 'Billing API', slug: 'billing-api' }] } }),
    '/api/versions?projectId=p1': () => ({ status: 200, body: { success: true, versions: [{ version_id: '2.7.0', published: true }] } }),
    '/api/repositories': () => ({ status: 200, body: REPOSITORIES }),
    '/api/pact/provider-contracts/check': () => ({ status: 200, body: CHECK }),
    '/api/pact/provider-contracts/sources': (call) => (call.method === 'GET' ? stored : { status: 200, body: FOLLOWED }),
    '/api/pact/provider-contracts': () => ({ status: 200, body: PUBLISHED }),
  };
  installFetch();
});

const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const puts = () => calls.filter((c) => c.method === 'PUT' && c.url === '/api/pact/provider-contracts/sources');

async function fillProjectVersion() {
  await screen.findByRole('option', { name: 'Billing API' });
  type('Project', 'billing-api');
  await screen.findByRole('option', { name: '2.7.0 · published' });
  type('Version', '2.7.0');
  type('Provider', 'Billing Service');
  type('Provider version', '2.7.0');
  type('Branch', 'main');
}

describe('Standing sources of a provider contract', () => {
  it('previews the verdicts for a provider that already publishes each version, and passes axe', async () => {
    stored = { status: 200, body: FOLLOWED };
    const { container } = render(<ProviderContractClient />);
    await fillProjectVersion();
    fireEvent.click(screen.getByRole('checkbox', { name: /Do this on every publish/ }));
    expect(screen.getByTestId('ppc-follow')).toHaveClass('is-active');
    expect(screen.getByTestId('ppc-follow')).toHaveTextContent('Each time a version of Billing API is published, it becomes Billing Service’s provider contract');
    const standing = await screen.findByTestId('ppc-standing', {}, { timeout: 3000 });
    expect(standing).toHaveTextContent('Each published version of Billing API becomes its contract. Drafts never do.');
    expect(within(standing).getByTestId('ppc-stop-project')).toBeInTheDocument();
    expect(await screen.findByTestId('ppc-headline', {}, { timeout: 3000 })).toHaveTextContent('2 of 3 consumers stay compatible');
    expect(screen.getByTestId('ppc-command-block')).toHaveTextContent('Do this on every publish');

    const header = container.querySelector('[data-testid="page-header"]')!;
    expect(countHeaderActions(header)).toEqual({ primary: 1, secondary: 2, overflow: 0, selects: [] });
    expect(pageGateViolations(container)).toEqual([]);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-provider-contract-preview', liveMarkup(container.firstElementChild!));
  });

  it('saves Do this on every publish with the publish, binding the project', async () => {
    render(<ProviderContractClient />);
    await fillProjectVersion();
    fireEvent.click(screen.getByRole('checkbox', { name: /Do this on every publish/ }));
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppc-publish'));
    });
    const dialog = await screen.findByTestId('ppc-result');
    expect(within(dialog).getByTestId('ppc-result-follow')).toHaveTextContent('Each published version of Billing API now becomes Billing Service’s contract.');
    expect(puts()).toHaveLength(1);
    expect(puts()[0].body).toEqual({ provider: 'Billing Service', onProjectPublish: true, bindProject: 'billing-api' });
    // The publish went first: the provider exists by the time the source is saved.
    const order = calls.map((c) => `${c.method} ${c.url}`);
    expect(order.indexOf('POST /api/pact/provider-contracts')).toBeLessThan(order.indexOf('PUT /api/pact/provider-contracts/sources'));
  });

  it('says why the project could not be followed, and still shows the publish', async () => {
    answers['/api/pact/provider-contracts/sources'] = (call) =>
      call.method === 'GET'
        ? stored
        : { status: 409, body: { success: false, error: 'Billing Service is bound to Payments API, so its versions are the ones published.' } };
    render(<ProviderContractClient />);
    await fillProjectVersion();
    fireEvent.click(screen.getByRole('checkbox', { name: /Do this on every publish/ }));
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppc-publish'));
    });
    const dialog = await screen.findByTestId('ppc-result');
    expect(dialog).toHaveTextContent('Provider contract published');
    expect(within(dialog).getByTestId('ppc-result-follow')).toHaveTextContent('Not published on every publish: Billing Service is bound to Payments API');
  });

  it('does not save a source when the box is left unticked', async () => {
    render(<ProviderContractClient />);
    await fillProjectVersion();
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppc-publish'));
    });
    await screen.findByTestId('ppc-result');
    expect(puts()).toHaveLength(0);
    expect(screen.queryByTestId('ppc-result-follow')).toBeNull();
  });

  it('follows a repository file without publishing or comparing anything now', async () => {
    const { container } = render(<ProviderContractClient />);
    fireEvent.mouseDown(await screen.findByRole('tab', { name: /Repository/ }), { button: 0 });
    await screen.findByRole('option', { name: 'acme/billing' });
    expect(screen.getByRole('option', { name: /acme\/ledger — gitlab: only GitHub files can be read on a push/ })).toBeDisabled();
    fireEvent.change(screen.getByRole('combobox', { name: 'Repository' }), { target: { value: 'r1' } });
    type('Path', 'openapi/billing.yaml');
    expect(screen.getByLabelText('Branch')).toHaveValue('main');
    type('Provider', 'Billing Service');

    expect(screen.queryByLabelText('Provider version')).toBeNull();
    expect(screen.queryByTestId('ppc-evidence')).toBeNull();
    expect(screen.getByTestId('ppc-push-version')).toHaveTextContent('Each push is a provider version: its commit');
    expect(screen.getByTestId('ppc-push-evidence')).toHaveTextContent('its verdicts read unverified');
    expect(screen.getByTestId('ppc-aside')).toHaveTextContent('The verdicts appear after the next push');
    expect(screen.getByTestId('ppc-compare')).toBeDisabled();
    const block = screen.getByTestId('ppc-command-block');
    expect(block).toHaveTextContent('apiome pact publish-provider-contract openapi/billing.yaml');
    expect(block).toHaveTextContent("--provider-app-version '<commit sha>'");
    expect(block).toHaveTextContent('Publishing a repository file on every push');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();

    answers['/api/pact/provider-contracts/sources'] = (call) =>
      call.method === 'GET'
        ? stored
        : {
            status: 200,
            body: {
              ...FOLLOWED,
              onProjectPublish: false,
              repository: { repositoryId: 'r1', fullName: 'acme/billing', provider: 'github', path: 'openapi/billing.yaml', branch: 'main', webhook: false },
              warnings: ['acme/billing has no push webhook, so no push reaches Apiome; set one up on the repository’s page.'],
            },
          };
    expect(screen.getByTestId('ppc-publish')).toHaveTextContent('Follow this file');
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppc-publish'));
    });
    expect(puts()[0].body).toEqual({
      provider: 'Billing Service',
      repository: { repositoryId: 'r1', path: 'openapi/billing.yaml', branch: 'main' },
    });
    expect(await screen.findByTestId('ppc-status')).toHaveTextContent(
      'Following openapi/billing.yaml on main of acme/billing: every push publishes it. acme/billing has no push webhook',
    );
    expect(screen.getByTestId('ppc-standing')).toHaveTextContent('Every push to main of acme/billing publishes openapi/billing.yaml');
    expect(calls.some((c) => c.method === 'POST')).toBe(false);
  });

  it('names what is missing before following a file', async () => {
    render(<ProviderContractClient />);
    fireEvent.mouseDown(await screen.findByRole('tab', { name: /Repository/ }), { button: 0 });
    type('Provider', 'Billing Service');
    type('Path', 'docs/README.md');
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppc-publish'));
    });
    expect(screen.getByTestId('ppc-status')).toHaveTextContent('Choose the repository the file is in.');
    expect(screen.getByTestId('ppc-problem-repositoryPath')).toHaveTextContent('.yaml, .yml or .json');
    expect(puts()).toHaveLength(0);
  });

  it('shows REST’s warnings and stops a source, new publishes only', async () => {
    stored = {
      status: 200,
      body: { ...FOLLOWED, warnings: ['Publishing on every project publish is on, but the pacticipant is not bound to a project, so nothing is published.'] },
    };
    answers['/api/pact/provider-contracts/sources'] = (call) =>
      call.method === 'GET' ? stored : { status: 200, body: { ...FOLLOWED, onProjectPublish: false } };
    render(<ProviderContractClient />);
    await screen.findByLabelText('Provider');
    type('Provider', 'Billing Service');
    const standing = await screen.findByTestId('ppc-standing', {}, { timeout: 3000 });
    expect(standing).toHaveTextContent('not bound to a project, so nothing is published');
    expect(standing).toHaveTextContent('Turning a source off stops new publishes only');
    await act(async () => {
      fireEvent.click(within(standing).getByTestId('ppc-stop-project'));
    });
    expect(puts()[0].body).toEqual({ provider: 'Billing Service', onProjectPublish: false });
    await waitFor(() => expect(screen.getByTestId('ppc-status')).toHaveTextContent('Project versions are no longer published as the contract.'));
    expect(screen.queryByTestId('ppc-standing')).toBeNull();
  });
});
