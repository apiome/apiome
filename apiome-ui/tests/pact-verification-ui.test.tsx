/**
 * The **Verification** pages — PFX-5.5 (#6949).
 *
 * Provider page:
 * * the KPI strip, each consumer's newest pact (stale ones marked) with **Re-run**, and the
 *   history with trigger, duration, build and counts; axe passes;
 * * **Load more** pages the history; **Consumer** narrows it through the address;
 * * **Re-run** opens the run dialog prefilled from the newest result, posts the run, shows its
 *   outcome, and refreshes the page on close; a refused run shows REST's message;
 * * **Verify all stale** needs a provider version, and lists what it did not run;
 * * a refused read shows REST's message with **Try again**; a provider with no pact shows the
 *   publish command, and an empty history the verify command.
 *
 * Result page:
 * * the overview, each interaction (failed ones open) with expected and actual side by side, the
 *   evidence run's requests, and the raw log with **Copy** and **Download**; axe passes;
 * * a result without evidence says why; a refused read offers **Try again**.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `pact-verification` and
 * `pact-verification-result`.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const replace = jest.fn();
jest.mock('next/navigation', () => ({ useRouter: () => ({ replace, push: jest.fn() }) }));
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import fixture from './fixtures/pact-verification.json';
import healthFixture from './fixtures/pact-health.json';
import PactVerificationClient from '../src/app/components/ade/pactVerification/PactVerificationClient';
import VerificationResultClient from '../src/app/components/ade/pactVerification/VerificationResultClient';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const BASE = '/api/pact/pacticipants/ledger-api/verification';
const RESULT_ID = fixture.detail.result.id;
/** Ledger API's consumers' contract health (PFX-6.3): failing, and degraded (overdue; never verified). */
const [FAILING, DEGRADED] = healthFixture.overview.pairs;
const HEALTH = {
  ...healthFixture.overview,
  pairs: [
    { ...FAILING, consumer: 'billing-service', consumer_name: 'Billing Service' },
    { ...DEGRADED, consumer: 'reporting-job', consumer_name: 'Reporting Job' },
    { ...DEGRADED, consumer: 'orders-ui', consumer_name: 'Orders UI' },
  ],
};

type Answer = { status: number; body: unknown };
let answers: Record<string, () => Answer>;
let calls: Array<{ url: string; method: string; body?: unknown }>;

/** REST through the proxies: the first route whose key the URL starts with answers. */
function installFetch() {
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const key = Object.keys(answers)
      .sort((a, b) => b.length - a.length)
      .find((candidate) => url.startsWith(candidate));
    const { status, body } = key ? answers[key]() : { status: 404, body: { success: false, error: 'not found' } };
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  replace.mockReset();
  calls = [];
  answers = {
    [`${BASE}/status`]: () => ({ status: 200, body: fixture.status }),
    '/api/pact/health': () => ({ status: 200, body: HEALTH }),
    [`${BASE}/results?cursor=`]: () => ({
      status: 200,
      body: { ...fixture.history, results: [{ ...fixture.history.results[3], id: 'older-1', number: 9 }], next_cursor: null },
    }),
    [`${BASE}/results`]: () => ({ status: 200, body: fixture.history }),
    [`${BASE}/results/${RESULT_ID}`]: () => ({ status: 200, body: fixture.detail }),
    '/api/verification-targets': () => ({ status: 200, body: fixture.targets }),
    [`${BASE}/reverify`]: () => ({ status: 200, body: { ...fixture.run, trigger: 'manual' } }),
    [`${BASE}/verify-stale`]: () => ({
      status: 200,
      body: {
        ...fixture.run,
        skipped: [
          {
            consumer: 'orders-ui',
            consumer_name: 'Orders UI',
            consumer_version: '1.9.2',
            pact_version_sha: 'e'.repeat(64),
            code: 'pact-verify-in-progress',
            reason: 'a verification of Orders UI ↔ Ledger API is already running; wait for it to finish and run again',
          },
        ],
      },
    }),
  };
  installFetch();
});

const gets = () => calls.filter((call) => call.method === 'GET').map((call) => call.url);

describe('PactVerificationClient', () => {
  it('shows the KPI strip, each consumer’s newest pact and the history, and passes axe', async () => {
    const { container } = render(<PactVerificationClient slug="ledger-api" consumer={null} />);
    const table = await screen.findByTestId('pvx-status-table');
    await screen.findByTestId('pvx-history-table');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Ledger API verification');

    expect(screen.getByTestId('pvx-kpi-pacts')).toHaveTextContent('Pacts3');
    expect(screen.getByTestId('pvx-kpi-failing')).toHaveTextContent('Failing1');
    expect(screen.getByTestId('pvx-kpi-stale')).toHaveTextContent('Stale1');
    expect(screen.getByTestId('pvx-kpi-pass-rate')).toHaveTextContent('Interactions passing86%');

    expect(within(table).getAllByRole('row')).toHaveLength(4);
    const billing = screen.getByTestId('pvx-status-billing-service');
    expect(within(billing).getByTestId('pvx-verdict')).toHaveTextContent('Failed');
    expect(within(billing).getByRole('link', { name: 'Result 3' })).toHaveAttribute(
      'href',
      `/ade/dashboard/pacts/pacticipants/ledger-api/verification/results/${RESULT_ID}`,
    );
    expect(within(screen.getByTestId('pvx-status-reporting-job')).getByTestId('pvx-stale')).toHaveTextContent(
      'Stale — not verified',
    );
    expect(screen.getByTestId('pvx-verify-stale')).toHaveTextContent('Verify all stale (1)');

    const history = screen.getByTestId('pvx-history-table');
    expect(within(history).getAllByRole('row')).toHaveLength(5);
    const first = screen.getByTestId(`pvx-history-${RESULT_ID}`);
    expect(first).toHaveTextContent('Re-run');
    expect(first).toHaveTextContent('1.8 s');
    expect(first).toHaveTextContent('2 / 3 passed');
    expect(within(first).getByRole('link', { name: 'Build' })).toHaveAttribute(
      'href',
      'https://ci.example.com/ledger-api/builds/412',
    );
    expect(screen.getByTestId('pvx-history-bb22cc33-dd44-4e55-8f66-778899aabbcc')).toHaveTextContent('Not recorded');
    expect(await screen.findByTestId('pvx-health-billing-service')).toHaveTextContent('Failing');
    expect(screen.getByTestId('pvx-health-orders-ui')).toHaveTextContent('Degraded');
    expect(gets()).toEqual([`${BASE}/status`, `${BASE}/results`, '/api/pact/health?provider=ledger-api']);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-verification', liveMarkup(container.firstElementChild!));
  });

  it('loads more history, and narrows it to one consumer through the address', async () => {
    render(<PactVerificationClient slug="ledger-api" consumer={null} />);
    fireEvent.click(await screen.findByTestId('pvx-history-more'));
    expect(await screen.findByTestId('pvx-history-older-1')).toBeInTheDocument();
    expect(gets()).toContain(`${BASE}/results?cursor=118`);
    expect(screen.queryByTestId('pvx-history-more')).not.toBeInTheDocument();
    fireEvent.change(screen.getByTestId('pvx-consumer-filter'), { target: { value: 'orders-ui' } });
    expect(replace).toHaveBeenCalledWith('/ade/dashboard/pacts/pacticipants/ledger-api/verification?consumer=orders-ui');
  });

  it('asks for the narrowed history', async () => {
    render(<PactVerificationClient slug="ledger-api" consumer="orders-ui" />);
    await screen.findByTestId('pvx-history-table');
    expect(gets()).toContain(`${BASE}/results?consumer=orders-ui`);
    expect(screen.getByTestId('pvx-consumer-filter')).toHaveValue('orders-ui');
    expect(screen.getByRole('link', { name: 'Show every consumer' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/ledger-api/verification',
    );
  });

  it('re-runs one pact prefilled from its newest result, shows the outcome and refreshes on close', async () => {
    render(<PactVerificationClient slug="ledger-api" consumer={null} />);
    fireEvent.click(await screen.findByTestId('pvx-rerun-billing-service'));
    const dialog = await screen.findByTestId('pvx-run-dialog');
    expect(within(dialog).getByRole('heading')).toHaveTextContent("Re-run Billing Service's pact");
    await waitFor(() => expect(within(dialog).getByLabelText('Verification target')).toHaveValue('ledger-staging'));
    expect(within(dialog).getByRole('option', { name: /Ledger old/ })).toBeDisabled();
    expect(within(dialog).getByLabelText(/Provider version/)).toHaveValue('4f1e2d0');
    expect(within(dialog).getByLabelText(/Provider branch/)).toHaveValue('main');
    fireEvent.click(within(dialog).getByLabelText(/Send mutating requests/));
    fireEvent.click(within(dialog).getByTestId('pvx-run-submit'));
    const outcome = await within(dialog).findByTestId('pvx-run-outcome');
    expect(outcome).toHaveTextContent('1 pact verified as 4f1e2d0: 1 passed.');
    const post = calls.find((call) => call.method === 'POST')!;
    expect(post.url).toBe(`${BASE}/reverify?consumer=billing-service&sha=${fixture.status.pacts[0].pact_version_sha}`);
    expect(post.body).toEqual({
      target_ref: 'ledger-staging',
      provider_version: '4f1e2d0',
      provider_branch: 'main',
      verification: { allow_mutating: true },
    });
    const before = gets().length;
    expect(within(dialog).getByTestId('pvx-run-close')).toHaveTextContent('Done');
    fireEvent.click(within(dialog).getByTestId('pvx-run-close'));
    await waitFor(() => expect(screen.queryByTestId('pvx-run-dialog')).not.toBeInTheDocument());
    await waitFor(() =>
      expect(gets().slice(before)).toEqual([`${BASE}/status`, `${BASE}/results`, '/api/pact/health?provider=ledger-api']),
    );
  });

  it('shows REST’s refusal of a run and keeps the dialog open', async () => {
    answers[`${BASE}/reverify`] = () => ({
      status: 409,
      body: { success: false, error: 'a verification of Billing Service ↔ Ledger API is already running' },
    });
    render(<PactVerificationClient slug="ledger-api" consumer={null} />);
    fireEvent.click(await screen.findByTestId('pvx-rerun-billing-service'));
    const dialog = await screen.findByTestId('pvx-run-dialog');
    await waitFor(() => expect(within(dialog).getByTestId('pvx-run-submit')).toBeEnabled());
    fireEvent.click(within(dialog).getByTestId('pvx-run-submit'));
    expect(await within(dialog).findByTestId('pvx-run-error')).toHaveTextContent('already running');
    // Cancelling after a refused run changes nothing, so nothing is read again.
    const before = gets().length;
    fireEvent.click(within(dialog).getByTestId('pvx-run-close'));
    await waitFor(() => expect(screen.queryByTestId('pvx-run-dialog')).not.toBeInTheDocument());
    expect(gets().length).toBe(before);
  });

  it('verifies every stale pact as the version given, and lists what it did not run', async () => {
    render(<PactVerificationClient slug="ledger-api" consumer={null} />);
    fireEvent.click(await screen.findByTestId('pvx-verify-stale'));
    const dialog = await screen.findByTestId('pvx-run-dialog');
    expect(dialog).toHaveAttribute('data-mode', 'stale');
    await waitFor(() => expect(within(dialog).getByLabelText('Verification target')).toHaveValue('ledger-staging'));
    expect(within(dialog).getByTestId('pvx-run-submit')).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText(/Provider version/), { target: { value: ' 9f8e7d6 ' } });
    fireEvent.click(within(dialog).getByTestId('pvx-run-submit'));
    const skipped = await within(dialog).findByTestId('pvx-run-skipped');
    expect(skipped).toHaveTextContent('Orders UI: a verification of Orders UI ↔ Ledger API is already running');
    expect(within(dialog).getByTestId('pvx-run-outcome')).toHaveTextContent('1 not run.');
    expect(calls.find((call) => call.method === 'POST')).toMatchObject({
      url: `${BASE}/verify-stale`,
      body: { target_ref: 'ledger-staging', provider_version: '9f8e7d6' },
    });
  });

  it('says when no verification target is registered', async () => {
    answers['/api/verification-targets'] = () => ({ status: 200, body: { targets: [], count: 0 } });
    render(<PactVerificationClient slug="ledger-api" consumer={null} />);
    fireEvent.click(await screen.findByTestId('pvx-rerun-orders-ui'));
    expect(await screen.findByTestId('pvx-no-targets')).toHaveTextContent('No verification target is registered');
    expect(screen.getByTestId('pvx-run-submit')).toBeDisabled();
  });

  it('shows REST’s refusal of a read with Try again', async () => {
    answers[`${BASE}/status`] = () => ({ status: 403, body: { success: false, error: 'Permission denied' } });
    render(<PactVerificationClient slug="ledger-api" consumer={null} />);
    expect(await screen.findByText('The verification status could not be read')).toBeInTheDocument();
    answers[`${BASE}/status`] = () => ({ status: 200, body: fixture.status });
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId('pvx-status-table')).toBeInTheDocument();
  });

  it('shows the publish and verify commands when there is nothing yet', async () => {
    answers[`${BASE}/status`] = () => ({
      status: 200,
      body: { ...fixture.status, pacts: [], counts: { ...fixture.status.counts, pacts: 0 } },
    });
    answers[`${BASE}/results`] = () => ({ status: 200, body: { ...fixture.history, results: [], next_cursor: null } });
    const { container } = render(<PactVerificationClient slug="ledger-api" consumer={null} />);
    expect(await screen.findByTestId('pvx-empty')).toHaveTextContent('No pacts to verify');
    expect(screen.getByLabelText('Publish a pact')).toHaveTextContent('apiome pact publish');
    expect(await screen.findByLabelText('Verify the pacts of a provider')).toHaveTextContent(
      'apiome pact verify --provider "Ledger API"',
    );
    expect(screen.queryByTestId('pvx-verify-stale')).not.toBeInTheDocument();
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });
});

describe('VerificationResultClient', () => {
  let clipboard: jest.Mock;
  beforeEach(() => {
    clipboard = jest.fn(async () => undefined);
    Object.assign(navigator, { clipboard: { writeText: clipboard } });
  });

  it('shows the result, expected vs actual, the requests and the log, and passes axe', async () => {
    const { container } = render(<VerificationResultClient slug="ledger-api" resultId={RESULT_ID} />);
    await screen.findByTestId('pvx-overview');
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Result 3 — Billing Service');
    expect(screen.getByTestId('pvx-trigger')).toHaveTextContent('Re-run');
    expect(screen.getByRole('link', { name: 'Billing Service → Ledger API' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/billing-service/pacts/ledger-api?version=2.4.0',
    );

    const items = within(screen.getByTestId('pvx-interactions')).getAllByRole('listitem');
    expect(items).toHaveLength(3);
    const failed = items[1].querySelector('details')!;
    const passed = items[0].querySelector('details')!;
    expect(failed).toHaveAttribute('open');
    expect(passed).not.toHaveAttribute('open');
    const mismatches = within(items[1]).getAllByTestId('pvx-mismatch');
    expect(mismatches).toHaveLength(2);
    expect(mismatches[1]).toHaveTextContent('body /entries/0/balance');
    expect(mismatches[1]).toHaveTextContent('Expected1999');
    expect(mismatches[1]).toHaveTextContent('Actual1.5');

    const requests = screen.getByTestId('pvx-evidence-table');
    expect(within(requests).getAllByRole('row')).toHaveLength(4);
    expect(requests).toHaveTextContent('GET /summary');
    expect(requests).toHaveTextContent('1 / 3 passed');

    const log = within(screen.getByTestId('pvx-log')).getByLabelText('Raw verification log');
    expect(log).toHaveTextContent('Mismatch at body /year (rule type)');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-verification-result', liveMarkup(container.firstElementChild!));

    await act(async () => {
      fireEvent.click(screen.getByTestId('pvx-log-copy'));
    });
    expect(clipboard).toHaveBeenCalledWith(expect.stringContaining('Verification result 3 — Billing Service → Ledger API'));
    expect(screen.getByText('The log is copied.')).toBeInTheDocument();
  });

  it('downloads the log as a text file named after the result', async () => {
    const created: Blob[] = [];
    const urls = { createObjectURL: jest.fn((blob: Blob) => (created.push(blob), 'blob:log')), revokeObjectURL: jest.fn() };
    Object.assign(URL, urls);
    const click = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe(
        `verification-ledger-api-billing-service-${fixture.detail.result.pact_version_sha.slice(0, 12)}-3.log`,
      );
    });
    render(<VerificationResultClient slug="ledger-api" resultId={RESULT_ID} />);
    fireEvent.click(await screen.findByTestId('pvx-log-download'));
    expect(click).toHaveBeenCalledTimes(1);
    expect(created[0].type).toBe('text/plain;charset=utf-8');
    expect(urls.revokeObjectURL).toHaveBeenCalledWith('blob:log');
    click.mockRestore();
  });

  it('says why a result has no request log', async () => {
    answers[`${BASE}/results/${RESULT_ID}`] = () => ({
      status: 200,
      body: { ...fixture.detail, evidence: null, evidence_status: 'not-recorded' },
    });
    render(<VerificationResultClient slug="ledger-api" resultId={RESULT_ID} />);
    expect(await screen.findByTestId('pvx-evidence-note')).toHaveTextContent('A Pact verifier published this result');
    expect(screen.queryByTestId('pvx-evidence-table')).not.toBeInTheDocument();
  });

  it('re-runs the result’s pact as the same build', async () => {
    render(<VerificationResultClient slug="ledger-api" resultId={RESULT_ID} />);
    fireEvent.click(await screen.findByTestId('pvx-result-rerun'));
    const dialog = await screen.findByTestId('pvx-run-dialog');
    await waitFor(() => expect(within(dialog).getByTestId('pvx-run-submit')).toBeEnabled());
    fireEvent.click(within(dialog).getByTestId('pvx-run-submit'));
    await within(dialog).findByTestId('pvx-run-outcome');
    expect(calls.find((call) => call.method === 'POST')).toMatchObject({
      url: `${BASE}/reverify?consumer=billing-service&sha=${fixture.detail.result.pact_version_sha}`,
      body: { target_ref: 'ledger-staging', provider_version: '4f1e2d0', provider_branch: 'main' },
    });
  });

  it('shows REST’s refusal with Try again', async () => {
    answers[`${BASE}/results/${RESULT_ID}`] = () => ({
      status: 404,
      body: { success: false, error: "provider 'ledger-api' has no verification result" },
    });
    render(<VerificationResultClient slug="ledger-api" resultId={RESULT_ID} />);
    expect(await screen.findByText('This verification result could not be read')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'All verification results' })).toHaveAttribute(
      'href',
      '/ade/dashboard/pacts/pacticipants/ledger-api/verification',
    );
  });
});
