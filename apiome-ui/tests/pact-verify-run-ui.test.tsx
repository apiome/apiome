/**
 * The **Run a verification** page — PFX-8.8 (#7305), built to `docs/mockups/contracts/verify.html`
 * (Notes → States):
 *
 * * the provider, the version, a target and how it signs in; the rules as sentences with a pact
 *   count each; the aside previews what will run (and what is skipped as already verified); the
 *   header keeps the action cap; the Verification tab is the page's; axe passes;
 * * **No target yet**: the Target select offers “Add a target…”, which saves a target (read-only
 *   when it is production) and chooses it;
 * * **Production and mutating**: blocked — the rule is said and Run is disabled;
 * * **Nothing to verify**: every pact already verified for this version, with **Run anyway**;
 * * **Unreachable target**: the run ends “Could not connect …” — not a failed verification;
 * * Custom adds a rule; a self-run shows the Pact verifier command and no Run; a read-only role
 *   sees no Run; **Save as a schedule** saves the provider's cadence and target.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixture `pact-verify-run`.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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

import { VerifyRunClient } from '../src/app/components/ade/pactVerifyRun';
import { countHeaderActions, pageGateViolations } from './helpers/page-gates';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const EDITOR = { is_admin: false, permissions: ['pacts:view', 'pacts:create', 'pacts:edit', 'verification_evidence:create'] };
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

const pact = (name: string, version: string, extra: Record<string, unknown> = {}) => ({
  consumer: name.toLowerCase().replace(/ /g, '-'),
  consumer_name: name,
  consumer_version: version,
  pact_version_sha: `${version}-sha`,
  short_description: 'latest from main',
  branches: ['main'],
  deployed_to: [],
  released_in: [],
  pending: false,
  wip: false,
  interactions: 6,
  mutating_interactions: 1,
  state_interactions: 2,
  held_back: 0,
  last_result: null,
  already_verified: false,
  will_run: true,
  ...extra,
});

const PREVIEW = {
  provider: 'billing-service',
  provider_name: 'Billing Service',
  provider_version: '2.7.0+9f31c20',
  target: { slug: 'staging', name: 'staging', environment: 'staging', production: false, allow_mutating_methods: true, enabled: true },
  rules: [
    { index: 0, selector: { mainBranch: true }, pacts: 4 },
    { index: 1, selector: { deployedOrReleased: true }, pacts: 5 },
    { index: 2, selector: { matchingBranch: true }, pacts: 1 },
  ],
  selected: 10,
  will_run: 8,
  skipped: 2,
  interactions: 61,
  pacts: [
    pact('Orders UI', '3.4.0', { last_result: { number: 4, success: false, provider_version: '2.6.0', verified_at: null } }),
    pact('Orders UI', '3.3.2', { deployed_to: ['production'], last_result: { number: 3, success: true, provider_version: '2.6.0', verified_at: null } }),
    pact('Mobile App', '1.9.2', { deployed_to: ['production'], interactions: 4 }),
    pact('Checkout', '0.8.0', { branches: ['feature/credit-notes'], pending: true, interactions: 2 }),
  ],
  truncated: true,
  states: { strategy: 'registry', used: 11, handled: 9, missing: ['an invoice exists', 'a refund exists'], registered: 9 },
  max_pacts_per_run: 25,
  refusals: [],
};

const RUN = {
  provider: 'billing-service',
  provider_version: '2.7.0+9f31c20',
  provider_branch: 'feature/credit-notes',
  target: { slug: 'staging', base_url: 'https://billing.staging.acme.dev', environment: 'staging' },
  success: false,
  outcome: 'could-not-connect',
  connection_error: 'Could not connect to billing.staging.acme.dev (timeout)',
  pacts: [],
  skipped: [],
};

const TARGETS = [
  { slug: 'staging', name: 'staging', base_url: 'https://billing.staging.acme.dev', environment: 'staging', auth: { kind: 'secret', scheme: 'bearer', ref: 'billing-staging-token' } },
  { slug: 'prod', name: 'prod', base_url: 'https://billing.acme.dev', environment: 'production', auth: { kind: 'none' } },
];

beforeEach(() => {
  calls = [];
  answers = {
    '/api/access/permissions/me': () => ({ status: 200, body: { success: true, data: EDITOR } }),
    '/api/pact/pacticipants': () => ({
      status: 200,
      body: { pacticipants: [{ slug: 'billing-service', name: 'Billing Service', main_branch: 'main' }], count: 1, has_more: false },
    }),
    '/api/verification-targets': (call) =>
      call.method === 'POST'
        ? { status: 201, body: { ...call.body, enabled: true } }
        : { status: 200, body: { targets: TARGETS } },
    '/api/pact/verification/preview': () => ({ status: 200, body: PREVIEW }),
    '/api/pact/verification/run': () => ({ status: 200, body: RUN }),
    '/api/pact/verification-settings/overrides': () => ({ status: 200, body: { id: 'o-1' } }),
  };
  installFetch();
});

const type = (label: string | RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } });
const posts = (url: string) => calls.filter((c) => c.method !== 'GET' && c.url === url);

/** Billing Service 2.7.0+9f31c20 on feature/credit-notes, against staging. */
async function fill() {
  await screen.findByRole('option', { name: 'Billing Service' });
  type('Provider', 'billing-service');
  type('Version being verified', '2.7.0+9f31c20');
  type('Branch', 'feature/credit-notes');
  await screen.findByRole('option', { name: /^staging — / });
  type('Target', 'staging');
}

describe('Run a verification', () => {
  it('previews what will run, writes the rules as sentences, keeps the header cap and passes axe', async () => {
    const { container } = render(<VerifyRunClient />);
    await fill();
    const headline = await screen.findByTestId('pvr-headline', {}, { timeout: 3000 });
    await waitFor(() => expect(headline).toHaveTextContent('This run will verify 8 pacts · 61 interactions'));
    expect(screen.getAllByTestId('pvr-pact')).toHaveLength(4);
    expect(screen.getByTestId('pvr-more')).toHaveTextContent('+ 6 more · 2 already verified for this exact version are skipped');
    expect(screen.getAllByTestId('pvr-pact')[3]).toHaveTextContent('Pending');

    const rules = screen.getAllByTestId('pvr-rule');
    expect(rules[0]).toHaveTextContent('Each consumer’s latest pact on its main branch');
    expect(rules[0]).toHaveTextContent('4 pacts');
    expect(rules[2]).toHaveTextContent('Pacts on a consumer branch named like this one — feature/credit-notes');
    expect(rules[2]).toHaveTextContent('1 pact');
    expect(screen.getByTestId('pvr-states-sentence')).toHaveTextContent('9 of the 11 states these pacts use have a handler. 2 are missing');
    expect(screen.getByTestId('pvr-sign-in')).toHaveTextContent('Secret · billing-staging-token');

    const preview = calls.filter((c) => c.url === '/api/pact/verification/preview').at(-1)!;
    expect(preview.body).toEqual({
      provider: 'billing-service',
      body: {
        target_ref: 'staging',
        provider_version: '2.7.0+9f31c20',
        provider_branch: 'feature/credit-notes',
        selection: {
          consumerVersionSelectors: [{ mainBranch: true }, { deployedOrReleased: true }, { matchingBranch: true }],
          includePendingStatus: true,
        },
        skip_already_verified: true,
      },
    });
    expect(posts('/api/pact/verification/run')).toHaveLength(0);

    const block = screen.getByTestId('pvr-command-block');
    expect(block).toHaveTextContent('apiome pact verify');
    expect(block).toHaveTextContent('--target staging');
    expect(within(block).getByRole('tab', { name: 'Pact verifier' })).toBeInTheDocument();

    expect(within(screen.getByTestId('contracts-tabs')).getByRole('link', { name: /Verification/ })).toHaveAttribute('aria-current', 'page');
    const header = container.querySelector('[data-testid="page-header"]')!;
    expect(countHeaderActions(header)).toEqual({ primary: 1, secondary: 1, overflow: 0, selects: [] });
    expect(pageGateViolations(container)).toEqual([]);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-verify-run', liveMarkup(container.firstElementChild!));
  });

  it('never sends requests that change data to a production target', async () => {
    render(<VerifyRunClient />);
    await fill();
    type('Target', 'prod');
    expect(screen.getByTestId('pvr-production-note')).toHaveTextContent('prod is a production target.');
    fireEvent.click(screen.getByLabelText('Allow requests that change data'));
    expect(screen.getByTestId('pvr-problem-allowMutating')).toHaveTextContent(
      'Requests that change data are never sent to a production target.',
    );
    expect(screen.getByTestId('pvr-run')).toBeDisabled();
  });

  it('ends an unreachable run as “could not connect”, not as a failed verification', async () => {
    render(<VerifyRunClient />);
    await fill();
    fireEvent.click(screen.getByTestId('pvr-run'));
    const result = await screen.findByTestId('pvr-result');
    expect(within(result).getByText('Could not connect')).toBeInTheDocument();
    expect(screen.getByTestId('pvr-result-headline')).toHaveTextContent(
      'Could not connect to billing.staging.acme.dev (timeout) — not a failed verification; nothing was published.',
    );
    expect(posts('/api/pact/verification/run')[0].body).toMatchObject({
      provider: 'billing-service',
      body: { target_ref: 'staging', provider_version: '2.7.0+9f31c20', skip_already_verified: true, publish: true },
    });
  });

  it('says when every pact is already verified, and Run anyway verifies them again', async () => {
    answers['/api/pact/verification/preview'] = () => ({
      status: 200,
      body: { ...PREVIEW, will_run: 0, skipped: 10, interactions: 0, pacts: PREVIEW.pacts.map((p) => ({ ...p, already_verified: true, will_run: false })) },
    });
    render(<VerifyRunClient />);
    await fill();
    expect(await screen.findByTestId('pvr-nothing', {}, { timeout: 3000 })).toHaveTextContent(
      'Every selected pact is already verified for 2.7.0+9f31c20.',
    );
    expect(screen.getByTestId('pvr-run')).toBeDisabled();
    fireEvent.click(screen.getByTestId('pvr-run-anyway'));
    await screen.findByTestId('pvr-result');
    expect(posts('/api/pact/verification/run')[0].body?.body).not.toHaveProperty('skip_already_verified');
  });

  it('adds a target from the Target select and chooses it', async () => {
    answers['/api/verification-targets'] = (call) =>
      call.method === 'POST' ? { status: 201, body: { ...call.body, enabled: true } } : { status: 200, body: { targets: [] } };
    render(<VerifyRunClient />);
    await screen.findByRole('option', { name: 'No target yet' });
    type('Target', '__add');
    const dialog = await screen.findByTestId('pvr-add-target');
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Billing prod' } });
    fireEvent.change(within(dialog).getByLabelText('Base URL'), { target: { value: 'https://billing.acme.dev' } });
    fireEvent.click(within(dialog).getByLabelText('This is production'));
    fireEvent.click(within(dialog).getByTestId('pvr-add-target-save'));
    await waitFor(() => expect(screen.queryByTestId('pvr-add-target')).not.toBeInTheDocument());
    expect(posts('/api/verification-targets')[0].body).toMatchObject({
      slug: 'billing-prod',
      environment: 'production',
      policy: { allow_mutating_methods: false },
    });
    expect(screen.getByLabelText('Target')).toHaveValue('billing-prod');
  });

  it('adds a custom rule as a sentence', async () => {
    render(<VerifyRunClient />);
    await fill();
    fireEvent.click(screen.getByTestId('pvr-preset-custom'));
    type('Add a rule', 'tag');
    type('Tag', 'prod');
    fireEvent.click(screen.getByTestId('pvr-add-rule-button'));
    expect(screen.getAllByTestId('pvr-rule').at(-1)).toHaveTextContent('The latest pact tagged prod');
    expect(screen.getByTestId('pvr-command-block')).toHaveTextContent(`--consumer-version-selector '{"tag":"prod","latest":true}'`);
  });

  it('a self-run shows the Pact verifier command and no Run', async () => {
    render(<VerifyRunClient />);
    await fill();
    fireEvent.click(within(screen.getByTestId('pvr-mode-self')).getByRole('radio'));
    expect(screen.queryByTestId('pvr-run')).not.toBeInTheDocument();
    expect(screen.getByTestId('pvr-self-run-note')).toHaveTextContent('publishes its results back');
    expect(screen.getByTestId('pvr-command-block')).toHaveTextContent('pact-provider-verifier');
  });

  it('saves the provider’s schedule with the chosen target', async () => {
    render(<VerifyRunClient />);
    await fill();
    fireEvent.click(screen.getByTestId('pvr-save-schedule'));
    const dialog = await screen.findByTestId('pvr-schedule');
    fireEvent.click(within(dialog).getByTestId('pvr-schedule-save'));
    await screen.findByTestId('pvr-schedule-saved');
    expect(posts('/api/pact/verification-settings/overrides')[0]).toMatchObject({
      method: 'PUT',
      body: { provider: 'billing-service', cadence: 'nightly', target_ref: 'staging' },
    });
  });

  it('a read-only role previews but cannot run', async () => {
    answers['/api/access/permissions/me'] = () => ({ status: 200, body: { success: true, data: VIEWER } });
    render(<VerifyRunClient initialProvider="billing-service" />);
    await screen.findByTestId('pvr-command-block');
    await waitFor(() => expect(calls.some((c) => c.url === '/api/access/permissions/me')).toBe(true));
    expect(screen.queryByTestId('pvr-run')).not.toBeInTheDocument();
    expect(screen.queryByTestId('pvr-save-schedule')).not.toBeInTheDocument();
  });
});
