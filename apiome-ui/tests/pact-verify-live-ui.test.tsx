/**
 * The live run drawer and **Upload verification results** — PFX-8.9 (#7306), built to
 * `docs/mockups/contracts/verify.html`:
 *
 * * **Run verification** opens the drawer: progress, a row per consumer, the failing interaction with
 *   expected beside actual, the log; it follows the run by polling and ends on the verdict;
 * * **Stop run** asks the run to stop; closing the drawer keeps it going, **Show the run** brings it
 *   back, and a toast says when it ends;
 * * once over, **Re-run this interaction** replays it (nothing published); **Reproduce on the mock**
 *   goes to the provider's project;
 * * **Upload results**: consumer and pact version from the provider's pacts, the format the server will
 *   detect, the report sent with its media type, what the server read; an unreadable file is refused
 *   before anything is sent, and a server refusal says nothing was recorded;
 * * axe passes on the drawer and the dialog.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `pact-verify-live` and `pact-verify-upload`.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn() }),
}));
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
const mockToast = Object.assign(jest.fn(), {
  success: jest.fn(),
  error: jest.fn(),
  warning: jest.fn(),
});
jest.mock('@/app/components/ui/toast', () => ({ toast: mockToast }));

import { VerifyRunClient } from '../src/app/components/ade/pactVerifyRun';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const EDITOR = {
  is_admin: false,
  permissions: ['pacts:view', 'pacts:create', 'pacts:edit', 'verification_evidence:create'],
};
const RUN_ID = '6f9c2d1e-0b7a-4c3e-9a51-2f8e7d6c5b4a';
const SHA = '8d2f1c' + 'a'.repeat(58);
const SHA_B = '77c0aa' + 'b'.repeat(58);
const SHA_C = '51ab90' + 'c'.repeat(58);
const SHA_D = 'c07e33' + 'd'.repeat(58);

type Answer = { status: number; body: unknown };
type Call = { url: string; method: string; body: Record<string, unknown> | undefined };
let answers: Record<string, (call: Call) => Answer>;
let calls: Call[];

function installFetch() {
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const call = {
      url,
      method: init?.method ?? 'GET',
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    calls.push(call);
    const key = Object.keys(answers)
      .sort((a, b) => b.length - a.length)
      .find((candidate) => url.startsWith(candidate));
    const { status, body } = key
      ? answers[key](call)
      : { status: 404, body: { success: false, error: 'not found' } };
    return { ok: status < 400, status, json: async () => body } as Response;
  }) as unknown as typeof fetch;
}

const row = (
  name: string,
  version: string,
  sha: string,
  status: string,
  interactions: number,
  done: number,
  passed = done,
) => ({
  consumer: name.toLowerCase().replace(/ /g, '-'),
  consumer_name: name,
  consumer_version: version,
  pact_version_sha: sha,
  status,
  pending: false,
  interactions,
  done,
  passed,
  failed: status === 'failed' ? done - passed : 0,
  skipped: 0,
  errored: 0,
  published: status === 'passed' || status === 'failed' ? true : null,
  not_published_reason: null,
});

const FAILURE = {
  consumer: 'orders-ui',
  consumer_name: 'Orders UI',
  consumer_version: '3.4.0',
  pact_version_sha: SHA,
  interaction: {
    case_id: 'pact:interactions/2',
    description: 'create an invoice',
    pointer: '/interactions/2',
    operation: 'POST /invoices',
    provider_states: ['a customer 7 exists'],
    outcome: 'failed',
    code: 'pact-body-mismatch',
    message: 'the body differs',
    expected_status: '201',
    actual_status: 201,
    duration_ms: 41,
    mismatches: [
      {
        attribute: 'body',
        field: '/currency',
        rule: 'regex',
        expected: '^[A-Z]{3}$',
        actual: null,
        description: '$.currency is missing',
      },
    ],
  },
};

const LOG = [
  {
    seq: 1,
    kind: 'state',
    outcome: 'ok',
    text: '14:02:11 state  “a customer 7 exists”  ok  38 ms',
  },
  {
    seq: 2,
    kind: 'interaction',
    outcome: 'failed',
    text: '14:02:11 POST /invoices  201  body differs at /currency',
  },
  { seq: 3, kind: 'state', outcome: 'ok', text: '14:02:12 state  “an invoice exists”  ok  22 ms' },
  {
    seq: 4,
    kind: 'interaction',
    outcome: 'passed',
    text: '14:02:12 GET /invoices/42  200  ok  12 ms',
  },
];

const RUNNING = {
  run_id: RUN_ID,
  provider: 'billing-service',
  provider_name: 'Billing Service',
  provider_version: '2.7.0+9f31c20',
  provider_branch: 'feature/credit-notes',
  target: 'staging',
  target_base_url: 'https://billing.staging.acme.dev',
  environment: 'staging',
  status: 'running',
  stop_requested: false,
  started_at: '2026-11-29T14:02:11Z',
  finished_at: null,
  interactions: 18,
  done: 13,
  pacts: [
    row('Orders UI', '3.4.0', SHA, 'failed', 6, 6, 5),
    row('Orders UI', '3.3.2', SHA_B, 'passed', 6, 6),
    row('Mobile App', '1.9.2', SHA_C, 'running', 4, 1),
    row('Checkout', '0.8.0', SHA_D, 'queued', 2, 0),
  ],
  skipped: [],
  failure: FAILURE,
  log: LOG,
  log_next: 4,
  log_dropped: 0,
  result: null,
  error: null,
};

const FINISHED = {
  ...RUNNING,
  status: 'finished',
  finished_at: '2026-11-29T14:02:31Z',
  done: 18,
  pacts: [
    row('Orders UI', '3.4.0', SHA, 'failed', 6, 6, 5),
    row('Orders UI', '3.3.2', SHA_B, 'passed', 6, 6),
    row('Mobile App', '1.9.2', SHA_C, 'passed', 4, 4),
    row('Checkout', '0.8.0', SHA_D, 'passed', 2, 2),
  ],
  log: [{ seq: 5, kind: 'run', outcome: 'failed', text: '14:02:31 run    failed' }],
  log_next: 5,
  result: {
    provider: 'billing-service',
    provider_version: '2.7.0+9f31c20',
    provider_branch: 'feature/credit-notes',
    target: {
      slug: 'staging',
      base_url: 'https://billing.staging.acme.dev',
      environment: 'staging',
    },
    success: false,
    outcome: 'failed',
    connection_error: null,
    pacts: [],
    skipped: [],
  },
};

const PREVIEW = {
  provider: 'billing-service',
  provider_name: 'Billing Service',
  provider_version: '2.7.0+9f31c20',
  target: {
    slug: 'staging',
    name: 'staging',
    environment: 'staging',
    production: false,
    allow_mutating_methods: true,
    enabled: true,
  },
  rules: [],
  selected: 4,
  will_run: 4,
  skipped: 0,
  interactions: 18,
  pacts: [],
  truncated: false,
  states: { strategy: 'registry', used: 0, handled: 0, missing: [], registered: 0 },
  max_pacts_per_run: 25,
  refusals: [],
};

const STATUS = {
  provider: 'billing-service',
  provider_name: 'Billing Service',
  counts: {},
  pacts: [
    {
      consumer: 'orders-ui',
      consumer_name: 'Orders UI',
      consumer_version: '3.4.0',
      pact_version_sha: SHA,
      stale: false,
      latest_result: null,
    },
    {
      consumer: 'mobile-app',
      consumer_name: 'Mobile App',
      consumer_version: '1.9.2',
      pact_version_sha: SHA_C,
      stale: false,
      latest_result: null,
    },
  ],
  truncated: false,
};

let poll: Answer;

beforeEach(() => {
  calls = [];
  poll = { status: 200, body: FINISHED };
  mockToast.success.mockReset();
  mockToast.error.mockReset();
  mockToast.warning.mockReset();
  answers = {
    '/api/access/permissions/me': () => ({ status: 200, body: { success: true, data: EDITOR } }),
    '/api/pact/pacticipants/billing-service/verification/status': () => ({
      status: 200,
      body: STATUS,
    }),
    '/api/pact/pacticipants': () => ({
      status: 200,
      body: {
        pacticipants: [
          {
            slug: 'billing-service',
            name: 'Billing Service',
            main_branch: 'main',
            project_id: 'proj-billing',
          },
        ],
        count: 1,
        has_more: false,
      },
    }),
    '/api/verification-targets': () => ({
      status: 200,
      body: {
        targets: [
          {
            slug: 'staging',
            name: 'staging',
            base_url: 'https://billing.staging.acme.dev',
            environment: 'staging',
            auth: { kind: 'none' },
          },
        ],
      },
    }),
    '/api/pact/verification/preview': () => ({ status: 200, body: PREVIEW }),
    '/api/pact/verification/runs': (call) =>
      call.method === 'POST' && call.url === '/api/pact/verification/runs'
        ? { status: 200, body: RUNNING }
        : poll,
    [`/api/pact/verification/runs/${RUN_ID}/stop`]: () => ({
      status: 200,
      body: { ...RUNNING, stop_requested: true, log: [] },
    }),
    [`/api/pact/verification/runs/${RUN_ID}/rerun`]: () => ({
      status: 200,
      body: {
        run_id: RUN_ID,
        pact_version_sha: SHA,
        published: false,
        interaction: { ...FAILURE.interaction, outcome: 'passed', mismatches: [] },
      },
    }),
    '/api/pact/verification/results/upload': () => ({
      status: 200,
      body: {
        success: false,
        ingestion: { format: 'dredd', syntax: 'xml', interactions: 1, notices: [] },
        _links: { self: { href: 'x' } },
      },
    }),
  };
  installFetch();
});

const type = (label: string | RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const posts = (url: string) => calls.filter((c) => c.method !== 'GET' && c.url === url);

async function fill() {
  await screen.findByRole('option', { name: 'Billing Service' });
  type('Provider', 'billing-service');
  type('Version being verified', '2.7.0+9f31c20');
  type('Branch', 'feature/credit-notes');
  await screen.findByRole('option', { name: /^staging — / });
  type('Target', 'staging');
}

describe('the live run drawer', () => {
  it('shows progress per consumer, the failing interaction and the log, then follows the run to its verdict', async () => {
    poll = { status: 200, body: { ...RUNNING, log: [] } };
    render(<VerifyRunClient />);
    await fill();
    fireEvent.click(screen.getByTestId('pvr-run'));
    const drawer = await screen.findByTestId('pvl-drawer');
    expect(within(drawer).getByText('Verifying Billing Service 2.7.0+9f31c20')).toBeInTheDocument();
    expect(screen.getByTestId('pvl-subtitle')).toHaveTextContent(
      /^Against staging · started \d\d:\d\d:\d\d · 13 of 18 interactions$/,
    );
    expect(screen.getByTestId('pvl-progress')).toHaveAttribute('value', '72');
    const rows = screen.getAllByTestId('pvl-pact-row');
    expect(rows.map((r) => within(r).getAllByRole('cell')[2].textContent)).toEqual([
      'Failed',
      'Passed',
      'Running',
      'Queued',
    ]);
    expect(rows[0]).toHaveTextContent('5 / 6');
    expect(rows[2]).toHaveTextContent('1 / 4');
    const failure = screen.getByTestId('pvl-failure');
    expect(failure).toHaveTextContent('Body differs');
    expect(failure).toHaveTextContent('Orders UI 3.4.0 · state “a customer 7 exists”');
    expect(screen.getByTestId('pvl-expected')).toHaveTextContent('/currency: ^[A-Z]{3}$ (regex)');
    expect(screen.getByTestId('pvl-actual')).toHaveTextContent('/currency: (missing)');
    expect(screen.getByTestId('pvl-rerun')).toBeDisabled();
    expect(screen.getByTestId('pvl-mock')).toHaveAttribute(
      'href',
      '/ade/dashboard/versions?projectId=proj-billing',
    );
    fireEvent.click(screen.getByTestId('pvl-show-request'));
    expect(screen.getByTestId('pvl-request')).toHaveTextContent(
      "curl -X POST 'https://billing.staging.acme.dev/invoices'",
    );
    fireEvent.click(screen.getByTestId('pvl-show-request'));
    expect(screen.getByTestId('pvl-log')).toHaveTextContent(
      'POST /invoices 201 body differs at /currency',
    );
    expect(screen.getByTestId('pvl-footer-note')).toHaveTextContent(
      'Closing keeps it running; a toast tells you when it ends.',
    );
    expect(await axe(document.body, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-verify-live', liveMarkup(drawer));

    poll = { status: 200, body: FINISHED };
    await waitFor(
      () => expect(screen.getByTestId('pvl-verdict')).toHaveTextContent('a pact failed'),
      { timeout: 4000 },
    );
    expect(screen.getByTestId('pvl-log')).toHaveTextContent('run failed');
    expect(calls.some((c) => c.url === `/api/pact/verification/runs/${RUN_ID}?log_after=4`)).toBe(
      true,
    );
    // The drawer was open: no toast.
    expect(mockToast.error).not.toHaveBeenCalled();
  });

  it('re-runs the failing interaction once the run is over, publishing nothing', async () => {
    answers['/api/pact/verification/runs'] = (call) =>
      call.method === 'POST' ? { status: 200, body: FINISHED } : { status: 200, body: FINISHED };
    render(<VerifyRunClient />);
    await fill();
    fireEvent.click(screen.getByTestId('pvr-run'));
    await screen.findByTestId('pvl-drawer');
    fireEvent.click(screen.getByTestId('pvl-rerun'));
    expect(await screen.findByTestId('pvl-rerun-result')).toHaveTextContent('Passed');
    expect(screen.getByTestId('pvl-rerun-result')).toHaveTextContent('nothing was published');
    expect(posts(`/api/pact/verification/runs/${RUN_ID}/rerun`)[0].body).toEqual({
      pact_version_sha: SHA,
      case_id: 'pact:interactions/2',
    });
  });

  it('stops a run before its next interaction', async () => {
    poll = { status: 200, body: { ...RUNNING, log: [] } };
    render(<VerifyRunClient />);
    await fill();
    fireEvent.click(screen.getByTestId('pvr-run'));
    await screen.findByTestId('pvl-drawer');
    fireEvent.click(screen.getByTestId('pvl-stop'));
    await waitFor(() => expect(screen.getByTestId('pvl-stop')).toHaveTextContent('Stopping…'));
    expect(posts(`/api/pact/verification/runs/${RUN_ID}/stop`)).toHaveLength(1);
    expect(screen.getByTestId('pvl-footer-note')).toHaveTextContent(
      'Stopping — the run ends before its next interaction.',
    );
  });

  it('keeps running when the drawer closes, offers Show the run, and toasts when it ends', async () => {
    poll = { status: 200, body: { ...RUNNING, log: [] } };
    render(<VerifyRunClient />);
    await fill();
    fireEvent.click(screen.getByTestId('pvr-run'));
    await screen.findByTestId('pvl-drawer');
    fireEvent.keyDown(screen.getByTestId('pvl-drawer'), { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('pvl-drawer')).not.toBeInTheDocument());
    expect(screen.getByTestId('pvl-show')).toHaveTextContent('Show the run');
    expect(posts(`/api/pact/verification/runs/${RUN_ID}/stop`)).toHaveLength(0);
    poll = { status: 200, body: FINISHED };
    await waitFor(() => expect(mockToast.error).toHaveBeenCalled(), { timeout: 4000 });
    expect(mockToast.error.mock.calls[0][0]).toBe('Verification failed');
    expect(mockToast.error.mock.calls[0][1]).toMatchObject({
      description: 'Billing Service 2.7.0+9f31c20: a pact failed.',
    });
    act(() => mockToast.error.mock.calls[0][1].action.onClick());
    expect(await screen.findByTestId('pvl-drawer')).toBeInTheDocument();
  });

  it('says when a poll fails', async () => {
    poll = { status: 500, body: { success: false, error: 'REST is down.' } };
    render(<VerifyRunClient />);
    await fill();
    answers['/api/pact/verification/runs'] = (call) =>
      call.method === 'POST' ? { status: 200, body: { ...RUNNING, log: [] } } : poll;
    fireEvent.click(screen.getByTestId('pvr-run'));
    expect(await screen.findByTestId('pvl-problem', {}, { timeout: 4000 })).toHaveTextContent(
      'Could not read the run: REST is down.',
    );
  });
});

describe('Upload verification results', () => {
  const report =
    '<?xml version="1.0"?>\n<testsuite name="Dredd Tests"><testcase name="GET (200) /invoices/abc1"><failure>body</failure></testcase></testsuite>';

  async function openDialog() {
    render(<VerifyRunClient />);
    await fill();
    fireEvent.click(screen.getByTestId('pvu-open'));
    const dialog = await screen.findByTestId('pvu-dialog');
    await within(dialog).findByRole('option', { name: 'Orders UI' });
    return dialog;
  }

  it('attaches a Dredd report to the pact it verified and says what the server read', async () => {
    const dialog = await openDialog();
    fireEvent.change(within(dialog).getByLabelText('Consumer'), { target: { value: 'orders-ui' } });
    expect(within(dialog).getByLabelText('Pact version')).toHaveValue(SHA);
    expect(within(dialog).getByLabelText('Provider version')).toHaveValue('2.7.0+9f31c20');
    const file = new File([report], 'dredd.xml', { type: 'application/xml' });
    fireEvent.change(screen.getByTestId('pvu-file'), { target: { files: [file] } });
    expect(await screen.findByTestId('pvu-guess')).toHaveTextContent(
      'Looks like a Dredd report (xunit XML).',
    );
    const block = screen.getByTestId('pvu-command');
    expect(block).toHaveTextContent('apiome pact publish-verification-results dredd.xml');
    expect(block).toHaveTextContent(`--pact-version ${SHA}`);
    expect(await axe(document.body, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-verify-upload', liveMarkup(dialog));

    fireEvent.click(screen.getByTestId('pvu-submit'));
    expect(await screen.findByTestId('pvu-headline')).toHaveTextContent(
      'Recorded a failed result from a Dredd report: 1 interaction.',
    );
    expect(posts('/api/pact/verification/results/upload')[0].body).toEqual({
      provider: 'billing-service',
      consumer: 'orders-ui',
      pact_version_sha: SHA,
      provider_version: '2.7.0+9f31c20',
      branch: 'feature/credit-notes',
      format: 'auto',
      report,
      content_type: 'application/xml',
    });
  });

  it('refuses a file no verifier wrote before sending anything', async () => {
    const dialog = await openDialog();
    fireEvent.change(within(dialog).getByLabelText('Consumer'), { target: { value: 'orders-ui' } });
    fireEvent.change(screen.getByTestId('pvu-file'), {
      target: { files: [new File(['TAP version 13'], 'out.tap')] },
    });
    expect(await screen.findByTestId('pvu-guess')).toHaveTextContent(
      'This is neither JSON nor XML',
    );
    fireEvent.click(screen.getByTestId('pvu-submit'));
    expect(posts('/api/pact/verification/results/upload')).toHaveLength(0);
  });

  it('says nothing was recorded when the server refuses the report', async () => {
    answers['/api/pact/verification/results/upload'] = () => ({
      status: 422,
      body: {
        success: false,
        error: '/format: format is dredd but the report is JSON.',
        pointer: '/format',
      },
    });
    const dialog = await openDialog();
    fireEvent.change(within(dialog).getByLabelText('Consumer'), { target: { value: 'orders-ui' } });
    fireEvent.change(within(dialog).getByLabelText('Report format'), {
      target: { value: 'dredd' },
    });
    fireEvent.change(screen.getByTestId('pvu-file'), {
      target: { files: [new File(['{"result": true}'], 'r.json')] },
    });
    expect(await screen.findByTestId('pvu-guess')).toHaveTextContent(
      'You chose Dredd; the server will refuse the report if it is not one.',
    );
    fireEvent.click(screen.getByTestId('pvu-submit'));
    expect(await screen.findByTestId('pvu-refusal')).toHaveTextContent(
      'format is dredd but the report is JSON. (at /format) Nothing was recorded.',
    );
  });

  it('takes a pasted pact version and checks it', async () => {
    const dialog = await openDialog();
    fireEvent.change(within(dialog).getByLabelText('Consumer'), { target: { value: 'orders-ui' } });
    fireEvent.change(within(dialog).getByLabelText('Pact version'), {
      target: { value: '__other' },
    });
    fireEvent.change(screen.getByTestId('pvu-sha-input'), { target: { value: 'abc' } });
    fireEvent.click(screen.getByTestId('pvu-submit'));
    expect(
      await within(dialog).findByText('A pact version is the 64-character SHA-256 of the pact.'),
    ).toBeInTheDocument();
    expect(posts('/api/pact/verification/results/upload')).toHaveLength(0);
  });
});
