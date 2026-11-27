/**
 * The **Publish a provider contract** page — PFX-8.6 (#7303), built to
 * `docs/mockups/contracts/provider-contract.html` (Notes → States):
 *
 * * a project version and graded evidence: five option cards each with its strength; the aside
 *   shows the verdict per consumer before anything is saved (a breaking consumer in production,
 *   Nobody uses); the header keeps the action cap; axe passes;
 * * **No consumers yet**: the aside says the verdicts appear when a consumer publishes;
 * * **Unreadable document**: “Could not read this file: line …”, and Publish is disabled;
 * * **Evidence run fails**: nothing is published and the failing operations are listed;
 * * **409**: the version already has a different contract — said, and nothing is sent;
 * * **Unverified**: the rule is shown under None yet and in the result dialog;
 * * a URL is read by **Compare only** and published as those bytes; the result dialog links to
 *   can-i-deploy; a read-only role sees the explanation and the command block only.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixture `pact-provider-contract`.
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
const EDITOR = { is_admin: false, permissions: ['pacts:view', 'pacts:create', 'versions:view', 'verification_evidence:view'] };
const VIEWER = { is_admin: false, permissions: ['pacts:view'] };

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
  providerVersion: '2.7.0+9f31c20',
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
    providerVersion: '2.7.0+9f31c20',
    selfVerification: { status: 'verified', providerContractVerified: true, tool: 'apiome-provider-verifier', summary: { tests: 412, passed: 412, failed: 0 } },
    comparisons: {
      results: [
        { consumer: 'Orders UI', status: 'compared', verdict: 'fail' },
        { consumer: 'Mobile App', status: 'compared', verdict: 'pass' },
        { consumer: 'Checkout', status: 'compared', verdict: 'pass' },
      ],
    },
  },
};

const OAS = 'openapi: 3.1.0\ninfo:\n  title: Billing\n  version: 2.7.0\npaths: {}\n';

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
  jest.useRealTimers();
  calls = [];
  answers = {
    '/api/access/permissions/me': () => ({ status: 200, body: { success: true, data: EDITOR } }),
    '/api/projects': () => ({ status: 200, body: { success: true, projects: [{ id: 'p1', name: 'Billing API', slug: 'billing-api' }] } }),
    '/api/versions?projectId=p1': () => ({
      status: 200,
      body: { success: true, versions: [{ version_id: '2.7.0', published: true }, { version_id: '2.8.0-rc1', published: false }] },
    }),
    '/api/verification-targets': () => ({
      status: 200,
      body: { targets: [{ slug: 'staging', name: 'Staging', base_url: 'https://billing.staging.example.com', environment: 'staging' }] },
    }),
    '/api/pact/provider-contracts/check': () => ({ status: 200, body: CHECK }),
    '/api/pact/provider-contracts': () => ({ status: 200, body: PUBLISHED }),
  };
  installFetch();
});

const type = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });

/** Fill the form for Billing API 2.7.0 as Billing Service 2.7.0+9f31c20 on main. */
async function fillProjectVersion() {
  await screen.findByRole('option', { name: 'Billing API' });
  type('Project', 'billing-api');
  await screen.findByRole('option', { name: '2.7.0 · published' });
  type('Version', '2.7.0');
  type('Provider', 'Billing Service');
  type('Provider version', '2.7.0+9f31c20');
  type('Branch', 'main');
}

const posts = (suffix: string) => calls.filter((c) => c.method === 'POST' && c.url === suffix);

describe('Publish a provider contract', () => {
  it('shows the verdict per consumer before anything is saved, keeps the header cap and passes axe', async () => {
    const { container } = render(<ProviderContractClient />);
    await fillProjectVersion();
    const aside = await screen.findByTestId('ppc-headline', {}, { timeout: 3000 });
    expect(aside).toHaveTextContent('2 of 3 consumers stay compatible');
    const consumers = screen.getAllByTestId('ppc-consumer');
    expect(consumers[0]).toHaveTextContent('Orders UI');
    expect(consumers[0]).toHaveTextContent('POST /invoices: no longer returns currency. Orders UI 3.3.2 is in production.');
    expect(consumers[0]).toHaveTextContent('Breaks');
    expect(consumers[1]).toHaveTextContent('Unverified');
    expect(screen.getByTestId('ppc-nobody-uses')).toHaveTextContent('5 of 12 operations appear in no pact — including DELETE /invoices/{id}');
    expect(screen.getByTestId('ppc-aside-callout')).toHaveTextContent('You can still publish.');
    expect(screen.getByTestId('ppc-format')).toHaveTextContent('OpenAPI 3.1');
    expect(posts('/api/pact/provider-contracts/check')[0].body).toEqual({
      provider: 'Billing Service',
      providerVersion: '2.7.0+9f31c20',
      body: { apiomeVersion: 'billing-api@2.7.0', branch: 'main' },
    });
    // The check stores nothing; no publish was sent.
    expect(posts('/api/pact/provider-contracts')).toHaveLength(0);

    // Five option cards, each with its strength; None yet states the rule.
    const evidence = screen.getByTestId('ppc-evidence');
    expect(within(evidence).getAllByRole('radio')).toHaveLength(5);
    expect(screen.getByTestId('ppc-evidence-run')).toHaveTextContent('Strong');
    expect(screen.getByTestId('ppc-evidence-exit')).toHaveTextContent('Weak');
    expect(screen.getByTestId('ppc-evidence-none')).toHaveTextContent('None');
    expect(screen.getByTestId('ppc-unverified-rule')).toHaveTextContent('nothing is unblocked either');

    const block = screen.getByTestId('ppc-command-block');
    expect(block).toHaveTextContent('apiome pact publish-provider-contract');
    expect(block).toHaveTextContent('--apiome-version billing-api@2.7.0');

    const header = container.querySelector('[data-testid="page-header"]')!;
    expect(countHeaderActions(header)).toEqual({ primary: 1, secondary: 2, overflow: 0, selects: [] });
    expect(pageGateViolations(container)).toEqual([]);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-provider-contract', liveMarkup(container.firstElementChild!));
  });

  it('says so when no consumer has a pact yet', async () => {
    answers['/api/pact/provider-contracts/check'] = () => ({ status: 200, body: { ...CHECK, results: [], coverage: { operations: 2, used: 0, unused: [], unusedMore: 0 } } });
    render(<ProviderContractClient />);
    await fillProjectVersion();
    expect(await screen.findByTestId('ppc-headline', {}, { timeout: 3000 })).toHaveTextContent('No consumers yet');
    expect(screen.getByTestId('ppc-aside')).toHaveTextContent('No pacts to compare with. The verdicts appear the moment a consumer publishes.');
  });

  it('marks an unreadable upload and disables Publish', async () => {
    render(<ProviderContractClient />);
    fireEvent.mouseDown(await screen.findByRole('tab', { name: /Upload/ }), { button: 0 });
    const input = await screen.findByTestId('ppc-file-input');
    await act(async () => {
      fireEvent.change(input, { target: { files: [new File(['openapi: 3.1.0\ninfo:\n  bad: value: here\n'], 'openapi.yaml')] } });
    });
    await waitFor(() => expect(screen.getByTestId('ppc-problem-file')).toHaveTextContent(/^Could not read this file: line 3, /));
    expect(screen.queryByTestId('ppc-format')).not.toBeInTheDocument();
    expect(screen.getByTestId('ppc-publish')).toBeDisabled();
  });

  it('runs the verifier first and publishes nothing when it fails, listing the failing operations', async () => {
    answers['/api/pact/provider-contracts'] = () => ({
      status: 200,
      body: {
        success: true,
        published: false,
        run: {
          outcome: 'failed',
          reportId: 'report-9',
          runId: 'run-9',
          failing: [{ operation: 'POST /invoices', outcome: 'failed', detail: 'currency is missing from the response' }],
          message: 'The provider did not pass (failed). Nothing was published.',
        },
      },
    });
    render(<ProviderContractClient />);
    await fillProjectVersion();
    fireEvent.click(screen.getByLabelText(/Run it now against a provider/));
    await screen.findByRole('option', { name: 'staging — https://billing.staging.example.com' });
    type('Target', 'staging');
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppc-publish'));
    });
    const card = await screen.findByTestId('ppc-failed-run');
    expect(card).toHaveTextContent('Nothing was published');
    expect(within(card).getByTestId('ppc-failing-operations')).toHaveTextContent('POST /invoices');
    expect(card).toHaveTextContent('report-9');
    expect(screen.getByTestId('ppc-status')).toHaveTextContent('The provider did not pass (failed). Nothing was published');
    expect(screen.queryByTestId('ppc-result')).not.toBeInTheDocument();
    expect(posts('/api/pact/provider-contracts')[0].body).toMatchObject({ run: { versionRef: 'project/billing-api/2.7.0', target: 'staging' } });
  });

  it('publishes, lists the verdicts and notifications, and links to can-i-deploy', async () => {
    render(<ProviderContractClient />);
    await fillProjectVersion();
    fireEvent.click(screen.getByLabelText(/My pipeline vouches for it/));
    type('Verifier', 'schemathesis');
    type('Exit code', '0');
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppc-publish'));
    });
    const dialog = await screen.findByTestId('ppc-result');
    expect(dialog).toHaveTextContent('Provider contract published');
    expect(dialog).toHaveTextContent('2 verdicts recorded as compatible');
    expect(dialog).toHaveTextContent('1 recorded as incompatible — Orders UI');
    expect(within(dialog).getByTestId('ppc-result-notifications')).toHaveTextContent('No webhooks or commit statuses');
    expect(within(dialog).getByRole('link', { name: 'Can I deploy 2.7.0+9f31c20?' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/can-i-deploy?pacticipant=Billing+Service&version=2.7.0%2B9f31c20',
    );
    expect(posts('/api/pact/provider-contracts')[0].body).toEqual({
      provider: 'Billing Service',
      providerVersion: '2.7.0+9f31c20',
      body: { apiomeVersion: 'billing-api@2.7.0', branch: 'main', verificationResults: { success: true, verifier: 'schemathesis' } },
    });
  });

  it('refuses to publish over a different contract for the same version', async () => {
    answers['/api/pact/provider-contracts/check'] = () => ({ status: 200, body: { ...CHECK, existing: { contentSha: 'ff', sameContent: false }, summary: { publishable: false } } });
    render(<ProviderContractClient />);
    await fillProjectVersion();
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppc-compare'));
    });
    expect(await screen.findByTestId('ppc-status')).toHaveTextContent('2.7.0+9f31c20 already has a different contract — use the new commit’s version.');
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppc-publish'));
    });
    expect(posts('/api/pact/provider-contracts')).toHaveLength(0);
  });

  it('says the same for REST’s 409, and marks an unverified publish', async () => {
    answers['/api/pact/provider-contracts'] = () => ({ status: 409, body: { success: false, error: 'different contract', code: 'provider-contract-conflict' } });
    render(<ProviderContractClient />);
    await fillProjectVersion();
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppc-publish'));
    });
    expect(await screen.findByTestId('ppc-status')).toHaveTextContent('already has a different contract');

    answers['/api/pact/provider-contracts'] = () => ({
      status: 200,
      body: { ...PUBLISHED, contract: { ...PUBLISHED.contract, selfVerification: { status: 'missing' } } },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppc-publish'));
    });
    expect(await screen.findByTestId('ppc-result-unverified')).toHaveTextContent('never unblock a deploy');
  });

  it('reads a URL with Compare only and publishes those bytes', async () => {
    answers['/api/pact/provider-contracts/check'] = () => ({
      status: 200,
      body: { ...CHECK, fetched: { url: 'https://api.example.com/openapi.yaml', bytes: 54, content: 'b3BlbmFwaTogMy4xLjA=' } },
    });
    render(<ProviderContractClient />);
    fireEvent.mouseDown(await screen.findByRole('tab', { name: /URL/ }), { button: 0 });
    type('Specification URL', 'https://api.example.com/openapi.yaml');
    type('Provider', 'Billing Service');
    type('Provider version', '2.7.0+9f31c20');
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppc-compare'));
    });
    expect(await screen.findByTestId('ppc-fetched')).toHaveTextContent('Read 54 bytes from https://api.example.com/openapi.yaml.');
    expect(posts('/api/pact/provider-contracts/check')[0].body).toMatchObject({ body: { contentUrl: 'https://api.example.com/openapi.yaml' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppc-publish'));
    });
    await screen.findByTestId('ppc-result');
    expect(posts('/api/pact/provider-contracts')[0].body).toMatchObject({ body: { content: 'b3BlbmFwaTogMy4xLjA=' } });
    expect(screen.getByTestId('ppc-command-block')).toHaveTextContent('download it first');
  });

  it('shows a read-only role the explanation and the command block only', async () => {
    answers['/api/access/permissions/me'] = () => ({ status: 200, body: { success: true, data: VIEWER } });
    render(<ProviderContractClient />);
    expect(await screen.findByTestId('ppc-readonly')).toHaveTextContent('Your role cannot publish provider contracts');
    expect(screen.getByTestId('ppc-command-block')).toBeInTheDocument();
    expect(screen.queryByTestId('ppc-publish')).not.toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.url.startsWith('/api/projects'))).toBe(false));
  });

  it('reads an upload’s format and sends it inline', async () => {
    render(<ProviderContractClient />);
    fireEvent.mouseDown(await screen.findByRole('tab', { name: /Upload/ }), { button: 0 });
    await act(async () => {
      fireEvent.change(await screen.findByTestId('ppc-file-input'), { target: { files: [new File([OAS], 'openapi.yaml')] } });
    });
    expect(await screen.findByTestId('ppc-format')).toHaveTextContent('OpenAPI 3.1');
    type('Provider', 'Billing Service');
    type('Provider version', '2.7.0+9f31c20');
    await act(async () => {
      fireEvent.click(screen.getByTestId('ppc-publish'));
    });
    await screen.findByTestId('ppc-result');
    expect(posts('/api/pact/provider-contracts')[0].body).toMatchObject({ body: { contentType: 'application/yaml', contractType: 'oas' } });
  });
});
