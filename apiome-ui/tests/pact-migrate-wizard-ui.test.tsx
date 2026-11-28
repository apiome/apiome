/**
 * **Migrate from a broker** — the Migration wizard, PFX-8.16 (#7313).
 *
 * Connect: **Continue** waits for a passed **Test connection**; a refused sign-in says why and
 * changing a field asks for a new test; nothing is sent while the URL is not a URL.
 *
 * Choose: a dry run is started and followed; its counts fill the tiles; ticking, history depth and
 * the conflict policy travel with **Start copying**; findings are one strip; unticking everything, or
 * a refusal from REST, says why and starts nothing.
 *
 * Copy: progress, the per-kind table, the failures with their reasons and the log; **Stop**;
 * **Retry the N that failed** replaces **Continue** until retried or set aside; a stopped run is
 * resumed — after asking for the credentials again when the wizard has none.
 *
 * Switch over: the two variables and the report. Past migrations reopens a run on its step; a run
 * still going is reopened on arrival. Without the permission the wizard is read-only and says who to
 * ask. The token never appears in the page. axe passes on every step.
 *
 * Switch over (PFX-8.17, #7314): the agreement check — all agree, or “38 of 40 agree.” with each
 * difference and its cause; who has moved; keep-in-sync switched on with the credentials (asked for
 * first when the wizard has none) and off, a sync that stopped itself, REST's refusal, and the switch
 * read-only without the permission.
 *
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `pact-migrate-choose`, `pact-migrate-copy`
 * and `pact-migrate-switch`.
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

import fixture from './fixtures/pact-migration.json';
import MigrateWizardClient, {
  ASK_AN_ADMIN,
  ENTER_CREDENTIALS_AGAIN,
} from '../src/app/components/ade/pactMigrate/MigrateWizardClient';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } };
const API = '/api/pact/migrations';
const TOKEN = 's3cr3t-read-token';
const SOURCE = 'https://acme.pactflow.io';
const { dry: DRY, dryRunning: DRY_RUNNING, copy: COPY, copyFailed: COPY_FAILED, copyDone: COPY_DONE, copyStopped: COPY_STOPPED, older: OLDER } = fixture;

type Answer = { status: number; body: unknown };
type Call = { url: string; method: string; body?: Record<string, unknown> };

/** What the BFF answers; a test replaces the entries it cares about. */
let rest: {
  list: () => Answer;
  test: (body: Record<string, unknown>) => Answer;
  start: (body: Record<string, unknown>) => Answer;
  read: (id: string) => Answer;
  stop: (id: string) => Answer;
  resume: (id: string, body: Record<string, unknown>) => Answer;
  sync: (id: string, method: string, body?: Record<string, unknown>) => Answer;
};
let calls: Call[];

const ok = (body: unknown): Answer => ({ status: 200, body });
const refused = (status: number, error: string): Answer => ({ status, body: { success: false, error } });

function installFetch() {
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined;
    calls.push({ url, method, body });
    let answer: Answer = refused(404, 'not found');
    const run = /^\/api\/pact\/migrations\/([0-9a-f-]{36})(\/stop|\/resume|\/sync)?/.exec(url);
    if (url === '/api/pact/broker-address') answer = ok({ broker_base_url: fixture.broker });
    else if (url === API && method === 'GET') answer = rest.list();
    else if (url === API) answer = rest.start(body ?? {});
    else if (url === `${API}/test`) answer = rest.test(body ?? {});
    else if (run && run[2] === '/stop') answer = rest.stop(run[1]);
    else if (run && run[2] === '/resume') answer = rest.resume(run[1], body ?? {});
    else if (run && run[2] === '/sync') answer = rest.sync(run[1], method, body);
    else if (run) answer = rest.read(run[1]);
    return { ok: answer.status < 400, status: answer.status, json: async () => answer.body } as Response;
  }) as unknown as typeof fetch;
}

/** Keep-in-sync off, as REST answers a run never kept in sync. */
function syncOff(id: string, extra: Record<string, unknown> = {}) {
  return {
    run_id: id,
    enabled: false,
    interval_minutes: 15,
    next_run_at: null,
    last_pass_at: null,
    last_success_at: null,
    unreachable_since: null,
    passes: 0,
    last_error: null,
    stopped_reason: null,
    enabled_by: null,
    available: true,
    unreachable_limit_hours: 24,
    ...extra,
  };
}

/** Keep-in-sync on, its next pass due. */
function syncOn(id: string) {
  return syncOff(id, { enabled: true, next_run_at: '2026-11-27T14:45:00Z', enabled_by: 'ada@acme.example' });
}

const minutesAgo = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();

/** A finished copy with the switch-over facts: every answer agrees, two of three have moved. */
function agreedCopy() {
  return {
    ...COPY_DONE,
    facts: {
      ...COPY_DONE.facts,
      agreement: { asked: 40, agree: 40, not_asked: 0, differences: [], differences_dropped: 0, checked_at: minutesAgo(1) },
      moved: {
        total: 3,
        moved: 2,
        dropped: 0,
        checked_at: minutesAgo(1),
        pacticipants: [
          { name: 'Mobile App', last: 'source', apiome_at: null, source_at: minutesAgo(26 * 60) },
          { name: 'Orders UI', last: 'apiome', apiome_at: minutesAgo(12), source_at: minutesAgo(3 * 24 * 60) },
          { name: 'Billing Service', last: 'apiome', apiome_at: minutesAgo(60), source_at: minutesAgo(5 * 24 * 60) },
        ],
      },
    },
  };
}

/** The same copy where two answers differ. */
function disagreedCopy() {
  const run = agreedCopy();
  return {
    ...run,
    facts: {
      ...run.facts,
      agreement: {
        ...run.facts.agreement,
        agree: 38,
        differences: [
          {
            question: 'Legacy Cart 4.2.0 → production',
            pacticipant: 'Legacy Cart',
            version: '4.2.0',
            environment: 'production',
            source: 'yes',
            apiome: 'unknown',
            cause: 'the verification result of Legacy Cart 4.2.0 by Payments API 9.1.0 was not copied: consumer version missing at source',
          },
          {
            question: 'Orders UI 7.0.1 → production',
            pacticipant: 'Orders UI',
            version: '7.0.1',
            environment: 'production',
            source: 'no answer',
            apiome: 'yes',
            cause: 'acme.pactflow.io could not answer it — a selector it does not support? (acme.pactflow.io answered HTTP 400 for /matrix.)',
          },
        ],
      },
    },
  };
}

const puts = (suffix: string) => calls.filter((call) => call.method === 'PUT' && call.url === `${API}${suffix}`);

const posts = (suffix = '') => calls.filter((call) => call.method === 'POST' && call.url === `${API}${suffix}`);

beforeEach(() => {
  calls = [];
  rest = {
    list: () => ok({ runs: [], can_migrate: true }),
    test: () => ok(fixture.test),
    start: (body) => ok(body.mode === 'copy' ? COPY : DRY),
    read: (id) => ok([DRY, COPY, COPY_FAILED, COPY_DONE, COPY_STOPPED, OLDER].find((run) => run.id === id) ?? DRY),
    stop: () => ok({ ...COPY, stop_requested: true }),
    resume: () => ok(COPY),
    sync: (id, method, body) => ok(method === 'PUT' && body?.enabled ? syncOn(id) : syncOff(id)),
  };
  installFetch();
});

async function mount() {
  const view = render(<MigrateWizardClient pollMs={5} />);
  await waitFor(() => expect(calls.some((call) => call.url === API)).toBe(true));
  await act(async () => {});
  return view;
}

/** Fill Connect, pass the test and continue to Choose (a finished dry run). */
async function toChoose() {
  const view = await mount();
  fireEvent.change(screen.getByTestId('pmg-source'), { target: { value: SOURCE } });
  fireEvent.change(screen.getByTestId('pmg-token'), { target: { value: TOKEN } });
  fireEvent.click(screen.getByTestId('pmg-test'));
  await waitFor(() => expect(screen.getByTestId('pmg-test-result')).toHaveTextContent('PactFlow · 42 pacticipants found'));
  fireEvent.click(screen.getByTestId('pmg-continue'));
  await screen.findByTestId('pmg-choose');
  await waitFor(() => expect(screen.getByTestId('pmg-count-note')).toHaveTextContent('Counted by a dry run'));
  return view;
}

/** Open a past run from the drawer. */
async function openPast(run: { id: string; host: string }) {
  fireEvent.click(screen.getByTestId('pmg-past'));
  const drawer = await screen.findByTestId('pmg-drawer');
  const row = within(drawer)
    .getAllByTestId('pmg-run-row')
    .find((candidate) => within(candidate).queryByText(run.host));
  fireEvent.click(within(row!).getByRole('button', { name: /^Open the migration/ }));
  await waitFor(() => expect(calls.some((call) => call.url.startsWith(`${API}/${run.id}`))).toBe(true));
  await act(async () => {});
}

// ---------------------------------------------------------------------------------------------
// Connect
// ---------------------------------------------------------------------------------------------

describe('Connect', () => {
  it('keeps Continue disabled until the connection test passes, and passes axe', async () => {
    const { container } = await mount();
    expect(screen.getByRole('heading', { level: 1, name: 'Migrate from a broker' })).toBeInTheDocument();
    expect(screen.getByTestId('pmg-continue')).toBeDisabled();
    expect(screen.getByTestId('pmg-test')).toBeDisabled();

    fireEvent.change(screen.getByTestId('pmg-source'), { target: { value: 'acme.pactflow.io' } });
    expect(screen.getByText('Enter a full URL, starting with https://.')).toBeInTheDocument();
    expect(screen.getByTestId('pmg-test')).toBeDisabled();

    fireEvent.change(screen.getByTestId('pmg-source'), { target: { value: SOURCE } });
    fireEvent.change(screen.getByTestId('pmg-token'), { target: { value: TOKEN } });
    fireEvent.click(screen.getByTestId('pmg-test'));
    await waitFor(() => expect(screen.getByTestId('pmg-continue')).toBeEnabled());
    expect(posts('/test')[0].body).toEqual({ source: SOURCE, token: TOKEN });
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();

    // Changing a field asks for a new test.
    fireEvent.change(screen.getByTestId('pmg-token'), { target: { value: `${TOKEN}-2` } });
    expect(screen.getByTestId('pmg-continue')).toBeDisabled();
  });

  it('says why a sign-in was refused and stays on the step', async () => {
    rest.test = () => refused(422, 'Could not sign in to acme.pactflow.io (401). Check the token.');
    await mount();
    fireEvent.change(screen.getByTestId('pmg-source'), { target: { value: SOURCE } });
    fireEvent.change(screen.getByTestId('pmg-token'), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByTestId('pmg-test'));
    expect(await screen.findByTestId('pmg-test-error')).toHaveTextContent(
      'Could not sign in to acme.pactflow.io (401). Check the token.',
    );
    expect(screen.getByTestId('pmg-continue')).toBeDisabled();
    expect(posts()).toEqual([]);
  });

  it('signs in with a username and password', async () => {
    await mount();
    fireEvent.change(screen.getByTestId('pmg-source'), { target: { value: 'https://broker.internal.example' } });
    fireEvent.click(screen.getByTestId('pmg-auth-basic'));
    fireEvent.change(screen.getByTestId('pmg-username'), { target: { value: 'ci' } });
    fireEvent.change(screen.getByTestId('pmg-password'), { target: { value: 'hunter2-pw' } });
    fireEvent.click(screen.getByTestId('pmg-test'));
    await waitFor(() => expect(posts('/test')).toHaveLength(1));
    expect(posts('/test')[0].body).toEqual({ source: 'https://broker.internal.example', username: 'ci', password: 'hunter2-pw' });
  });

  it('writes the wizard as apiome pact migrate, the token as a variable', async () => {
    await mount();
    fireEvent.change(screen.getByTestId('pmg-source'), { target: { value: SOURCE } });
    fireEvent.change(screen.getByTestId('pmg-token'), { target: { value: TOKEN } });
    const block = screen.getByTestId('pmg-command-block');
    expect(block).toHaveTextContent('apiome pact migrate');
    expect(block).toHaveTextContent('--from https://acme.pactflow.io');
    expect(block).toHaveTextContent('--token "$PACT_SOURCE_BROKER_TOKEN"');
    expect(block).toHaveTextContent('--dry-run');
    expect(block).not.toHaveTextContent(TOKEN);
  });

  it('is read-only without the permission and says who to ask', async () => {
    rest.list = () => ok({ runs: [OLDER], can_migrate: false });
    await mount();
    expect(await screen.findByTestId('pmg-read-only')).toHaveTextContent(ASK_AN_ADMIN);
    expect(screen.getByTestId('pmg-source')).toBeDisabled();
    expect(screen.getByTestId('pmg-token')).toBeDisabled();
    expect(screen.getByTestId('pmg-test')).toBeDisabled();
    expect(screen.getByTestId('pmg-continue')).toBeDisabled();
    // Past migrations can still be read.
    await openPast(OLDER);
    expect(await screen.findByTestId('pmg-switch')).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------------
// Choose
// ---------------------------------------------------------------------------------------------

describe('Choose', () => {
  it('follows the dry run while it reads the source, then shows its counts', async () => {
    let reads = 0;
    rest.start = () => ok(DRY_RUNNING);
    rest.read = () => ok(++reads < 2 ? DRY_RUNNING : DRY);
    await mount();
    fireEvent.change(screen.getByTestId('pmg-source'), { target: { value: SOURCE } });
    fireEvent.change(screen.getByTestId('pmg-token'), { target: { value: TOKEN } });
    fireEvent.click(screen.getByTestId('pmg-test'));
    await waitFor(() => expect(screen.getByTestId('pmg-continue')).toBeEnabled());
    fireEvent.click(screen.getByTestId('pmg-continue'));

    expect(await screen.findByTestId('pmg-counting')).toHaveTextContent('Counting what is at acme.pactflow.io');
    expect(screen.getByTestId('pmg-start')).toBeDisabled();
    expect(posts()[0].body).toEqual({ source: SOURCE, token: TOKEN, mode: 'dry-run' });

    await waitFor(() => expect(screen.queryByTestId('pmg-counting')).not.toBeInTheDocument());
    expect(screen.getByTestId('pmg-tile-versions')).toHaveTextContent('3,816');
    expect(screen.getByTestId('pmg-start')).toBeEnabled();
  });

  it('shows the counts, the history hints, what exists and one strip — and passes axe', async () => {
    const { container } = await toChoose();
    expect(screen.getByTestId('pmg-tile-pacticipants')).toHaveTextContent('42');
    expect(screen.getByTestId('pmg-tile-pacts')).toHaveTextContent('1,284');
    expect(screen.getByTestId('pmg-tile-results')).toHaveTextContent('9,402');
    expect(screen.getByTestId('pmg-tile-deployments')).toHaveTextContent('57');
    expect(screen.getByTestId('pmg-tile-labels')).toHaveTextContent('318');
    expect(screen.getByTestId('pmg-versions-hint')).toHaveTextContent('Would skip 1,912 versions');
    expect(screen.getByTestId('pmg-existing')).toHaveTextContent('6 pacticipants exist on both sides.');

    const strip = screen.getByRole('group', { name: 'Before you copy' });
    expect(within(strip).getAllByRole('button').map((chip) => chip.textContent)).toEqual(
      expect.arrayContaining([expect.stringContaining('11 webhook notes'), expect.stringContaining('Not copied')]),
    );
    expect(screen.getByText('Secrets cannot be read from a broker.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Secrets' })).toHaveAttribute('href', '/ade/dashboard/pacts/settings?tab=secrets');

    fireEvent.click(screen.getByTestId('pmg-versions-kept'));
    expect(screen.getByTestId('pmg-versions-hint')).toHaveTextContent('Skips 1,912 versions');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-migrate-choose', liveMarkup(container.firstElementChild!));
  });

  it('starts the copy with exactly what was chosen', async () => {
    await toChoose();
    fireEvent.click(within(screen.getByTestId('pmg-tile-webhooks')).getByRole('checkbox'));
    fireEvent.click(within(screen.getByTestId('pmg-tile-labels')).getByRole('checkbox'));
    fireEvent.click(screen.getByTestId('pmg-results-latest'));
    expect(screen.getByTestId('pmg-results-hint')).toHaveTextContent('Skips 8,118 older results.');
    fireEvent.click(screen.getByTestId('pmg-versions-kept'));
    fireEvent.click(screen.getByTestId('pmg-conflicts-replace'));
    fireEvent.click(screen.getByTestId('pmg-restart'));
    fireEvent.change(screen.getByTestId('pmg-matrix-limit'), { target: { value: '5000' } });

    const block = screen.getByTestId('pmg-command-block');
    expect(block).toHaveTextContent('--restart');
    expect(block).toHaveTextContent('--matrix-limit 5000');
    expect(block).toHaveTextContent('Not copying Webhooks, Labels and tags');

    fireEvent.click(screen.getByTestId('pmg-start'));
    await screen.findByTestId('pmg-copy');
    expect(posts()[1].body).toEqual({
      source: SOURCE,
      token: TOKEN,
      mode: 'copy',
      options: {
        kinds: ['pacticipant', 'environment', 'version', 'pact', 'verification', 'deployment', 'release'],
        labels_and_tags: false,
        results: 'latest',
        versions: 'kept',
        conflicts: 'replace',
        restart: true,
        matrix_limit: 5000,
        batch_bytes: 4194304,
        agreement_questions: 40,
      },
    });
  });

  it('does not offer thinning versions without keep-rules', async () => {
    rest.start = () => ok({ ...DRY, facts: { ...DRY.facts, cleanup_rules_set: false, cleanup_would_skip: null } });
    await toChoose();
    expect(screen.getByTestId('pmg-versions-kept')).toBeDisabled();
    expect(screen.getByTestId('pmg-versions-hint')).toHaveTextContent('Save keep-rules to copy only what clean-up would keep.');
  });

  it('says why nothing can be copied, and sends nothing', async () => {
    await toChoose();
    for (const tile of ['pacticipants', 'versions', 'pacts', 'results', 'environments', 'deployments', 'webhooks']) {
      fireEvent.click(within(screen.getByTestId(`pmg-tile-${tile}`)).getByRole('checkbox'));
    }
    expect(screen.getByTestId('pmg-choose-problem')).toHaveTextContent('Tick at least one kind to copy.');
    expect(screen.getByTestId('pmg-start')).toBeDisabled();
    expect(posts()).toHaveLength(1);
  });

  it('shows REST’s refusal and stays on the step', async () => {
    await toChoose();
    rest.start = () => refused(409, 'this workspace already has a migration running; stop it or wait for it');
    fireEvent.click(screen.getByTestId('pmg-start'));
    expect(await screen.findByTestId('pmg-choose-error')).toHaveTextContent('already has a migration running');
    expect(screen.getByTestId('pmg-choose')).toBeInTheDocument();
  });

  it('says so when the source could not be counted, and counts again', async () => {
    rest.start = () => ok({ ...DRY_RUNNING, status: 'failed', error: 'Could not reach acme.pactflow.io (ConnectTimeout). Check the URL.' });
    await mount();
    fireEvent.change(screen.getByTestId('pmg-source'), { target: { value: SOURCE } });
    fireEvent.click(screen.getByTestId('pmg-test'));
    await waitFor(() => expect(screen.getByTestId('pmg-continue')).toBeEnabled());
    fireEvent.click(screen.getByTestId('pmg-continue'));
    const failed = await screen.findByTestId('pmg-count-failed');
    expect(failed).toHaveTextContent('Could not reach acme.pactflow.io (ConnectTimeout). Check the URL.');
    rest.start = () => ok(DRY);
    fireEvent.click(within(failed).getByRole('button', { name: 'Count again' }));
    await waitFor(() => expect(screen.getByTestId('pmg-tile-pacts')).toHaveTextContent('1,284'));
    expect(posts()).toHaveLength(2);
  });

  it('goes back to Connect and returns without counting again', async () => {
    await toChoose();
    fireEvent.click(screen.getByTestId('pmg-back'));
    expect(screen.getByTestId('pmg-source')).toHaveValue(SOURCE);
    fireEvent.click(screen.getByTestId('pmg-continue'));
    await screen.findByTestId('pmg-choose');
    expect(posts()).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------------------------
// Copy
// ---------------------------------------------------------------------------------------------

describe('Copy', () => {
  async function toCopy() {
    const view = await toChoose();
    fireEvent.click(screen.getByTestId('pmg-start'));
    await screen.findByTestId('pmg-copy');
    return view;
  }

  it('shows progress, each kind, the failures with their reasons and the log — and passes axe', async () => {
    rest.read = () => ok(COPY);
    const { container } = await toCopy();
    expect(screen.getByTestId('pmg-copy-state')).toHaveTextContent('copying · 31%');
    expect(screen.getByTestId('pmg-progress')).toHaveAttribute('value', '31');
    expect(screen.getByTestId('pmg-kind-pacticipant')).toHaveTextContent('36 / 36');
    expect(screen.getByTestId('pmg-kind-pacticipant')).toHaveTextContent('6 already here');
    expect(screen.getByTestId('pmg-kind-version')).toHaveTextContent('1,912');
    expect(screen.getByTestId('pmg-kind-pact')).toHaveTextContent('612 / 1,284');
    expect(screen.getByTestId('pmg-kind-verification')).toHaveTextContent('waiting');
    const failures = screen.getByTestId('pmg-failures');
    expect(failures).toHaveTextContent('2 records could not be copied');
    expect(failures).toHaveTextContent('consumer version missing at source');
    expect(failures).toHaveTextContent('source-unreadable');
    expect(screen.getByTestId('pmg-log')).toHaveTextContent('… 39 earlier lines are not kept');
    expect(screen.getByTestId('pmg-log')).toHaveTextContent('14:21:08 pact 614 of 1284');
    expect(screen.getByTestId('pmg-copy-note')).toHaveTextContent('You can leave this page.');
    expect(screen.getByTestId('pmg-continue')).toBeDisabled();
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    expect(container).not.toHaveTextContent(TOKEN);
    writeA11yFixture('pact-migrate-copy', liveMarkup(container.firstElementChild!));
  });

  it('stops the copy when asked', async () => {
    rest.read = () => ok(COPY);
    await toCopy();
    rest.read = () => ok(COPY_STOPPED);
    fireEvent.click(screen.getByTestId('pmg-stop'));
    await waitFor(() => expect(posts(`/${COPY.id}/stop`)).toHaveLength(1));
    await waitFor(() => expect(screen.getByTestId('pmg-copy-state')).toHaveTextContent('stopped'));
    expect(screen.getByTestId('pmg-run-error')).toHaveTextContent('Resume it to carry on where it stopped.');
    expect(screen.getByTestId('pmg-resume')).toHaveTextContent('Resume');
  });

  it('resumes a stopped copy with the credentials it still holds', async () => {
    rest.read = () => ok(COPY_STOPPED);
    await toCopy();
    await waitFor(() => expect(screen.getByTestId('pmg-resume')).toBeEnabled());
    expect(screen.queryByTestId('pmg-credentials')).not.toBeInTheDocument();
    rest.read = () => ok(COPY);
    fireEvent.click(screen.getByTestId('pmg-resume'));
    await waitFor(() => expect(posts(`/${COPY.id}/resume`)).toHaveLength(1));
    expect(posts(`/${COPY.id}/resume`)[0].body).toEqual({ token: TOKEN });
    await waitFor(() => expect(screen.getByTestId('pmg-copy-state')).toHaveTextContent('copying'));
  });

  it('offers a retry in place of Continue until the failures are retried or set aside', async () => {
    rest.read = () => ok(COPY_FAILED);
    await toCopy();
    const retry = await screen.findByTestId('pmg-resume');
    expect(retry).toHaveTextContent('Retry the 2 that failed');
    expect(screen.queryByTestId('pmg-continue')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '2' })).toHaveAttribute('href', '#pmg-failures');

    fireEvent.click(screen.getByTestId('pmg-dismiss-failures'));
    expect(screen.queryByTestId('pmg-resume')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('pmg-continue'));
    expect(await screen.findByTestId('pmg-switch')).toHaveTextContent('2 records were not copied');
  });

  it('shows why a resume was refused', async () => {
    rest.read = () => ok(COPY_STOPPED);
    await toCopy();
    rest.resume = () => refused(422, 'Could not sign in to acme.pactflow.io (401). Check the token.');
    fireEvent.click(await screen.findByTestId('pmg-resume'));
    expect(await screen.findByTestId('pmg-copy-error')).toHaveTextContent('Check the token.');
  });

  it('moves on to Switch over when everything was copied', async () => {
    rest.read = () => ok(COPY_DONE);
    await toCopy();
    await waitFor(() => expect(screen.getByTestId('pmg-continue')).toBeEnabled());
    fireEvent.click(screen.getByTestId('pmg-continue'));
    const step = await screen.findByTestId('pmg-switch');
    expect(screen.getByTestId('pmg-headline')).toHaveTextContent('Copied 12,698 records from acme.pactflow.io. 6 were already here.');
    expect(screen.getByTestId('pmg-variables')).toHaveTextContent(`PACT_BROKER_BASE_URL=${fixture.broker}`);
    expect(screen.getByTestId('pmg-variables')).toHaveTextContent('PACT_BROKER_TOKEN=<an Apiome API key>');
    expect(screen.getByTestId('pmg-finish')).toHaveAttribute('href', '/ade/dashboard/pacts');
    expect(await axe(step, AXE_OPTIONS)).toHaveNoViolations();
  });

  it('downloads the report as JSON without any credential', async () => {
    const blobs: Blob[] = [];
    Object.assign(URL, { createObjectURL: (blob: Blob) => (blobs.push(blob), 'blob:report'), revokeObjectURL: () => undefined });
    rest.read = () => ok(COPY_DONE);
    await toCopy();
    await waitFor(() => expect(screen.getByTestId('pmg-continue')).toBeEnabled());
    fireEvent.click(screen.getByTestId('pmg-continue'));
    fireEvent.click(await screen.findByTestId('pmg-download'));
    expect(blobs).toHaveLength(1);
    expect(blobs[0].type).toBe('application/json');
    const text = await new Promise<string>((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(blobs[0]);
    });
    expect(JSON.parse(text)).toMatchObject({ source: SOURCE, mode: 'copy', status: 'completed' });
    expect(text).not.toContain(TOKEN);
  });
});

// ---------------------------------------------------------------------------------------------
// Past migrations
// ---------------------------------------------------------------------------------------------

describe('Past migrations', () => {
  it('lists every run with its state and reopens a finished copy on Switch over', async () => {
    rest.list = () => ok({ runs: [COPY_FAILED, DRY, OLDER], can_migrate: true });
    await mount();
    fireEvent.click(screen.getByTestId('pmg-past'));
    const drawer = await screen.findByTestId('pmg-drawer');
    const rows = within(drawer).getAllByTestId('pmg-run-row');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('acme.pactflow.io');
    expect(rows[0]).toHaveTextContent('completed · 2 failed');
    expect(rows[1]).toHaveTextContent('dry run');
    expect(rows[2]).toHaveTextContent('broker.internal.example');
    expect(rows[2]).toHaveTextContent('13 Nov 2026, 09:12 UTC · grace@acme.example');
    expect(await axe(drawer, AXE_OPTIONS)).toHaveNoViolations();

    fireEvent.click(within(rows[2]).getByRole('button', { name: /^Open the migration/ }));
    expect(await screen.findByTestId('pmg-switch')).toBeInTheDocument();
    expect(screen.getByTestId('pmg-headline')).toHaveTextContent('from broker.internal.example');
  });

  it('says so when no migration has been run', async () => {
    await mount();
    fireEvent.click(screen.getByTestId('pmg-past'));
    expect(await screen.findByText('No migration has been run in this workspace yet.')).toBeInTheDocument();
  });

  it('reopens a stopped copy and asks for the credentials again before resuming', async () => {
    rest.list = () => ok({ runs: [COPY_STOPPED], can_migrate: true });
    rest.read = () => ok(COPY_STOPPED);
    await mount();
    await openPast(COPY_STOPPED);
    const again = await screen.findByTestId('pmg-credentials');
    expect(again).toHaveTextContent('Sign in to acme.pactflow.io again');
    expect(screen.getByTestId('pmg-resume')).toBeDisabled();
    fireEvent.change(screen.getByTestId('pmg-again-token'), { target: { value: TOKEN } });
    rest.read = () => ok(COPY);
    fireEvent.click(screen.getByTestId('pmg-resume'));
    await waitFor(() => expect(posts(`/${COPY.id}/resume`)).toHaveLength(1));
    expect(posts(`/${COPY.id}/resume`)[0].body).toEqual({ token: TOKEN });
  });

  it('reopens a dry run on Choose, where starting the copy needs the credentials again', async () => {
    rest.list = () => ok({ runs: [DRY], can_migrate: true });
    await mount();
    await openPast(DRY);
    expect(await screen.findByTestId('pmg-choose')).toBeInTheDocument();
    expect(screen.getByTestId('pmg-tile-pacts')).toHaveTextContent('1,284');
    expect(screen.getByTestId('pmg-choose-problem')).toHaveTextContent(ENTER_CREDENTIALS_AGAIN);
    expect(screen.getByTestId('pmg-start')).toBeDisabled();
    fireEvent.click(screen.getByTestId('pmg-back'));
    expect(screen.getByTestId('pmg-source')).toHaveValue(SOURCE);
    expect(screen.getByTestId('pmg-token')).toHaveValue('');
  });

  it('opens the copy that is still running on arrival', async () => {
    rest.list = () => ok({ runs: [COPY, OLDER], can_migrate: true });
    rest.read = () => ok(COPY);
    await mount();
    expect(await screen.findByTestId('pmg-copy')).toBeInTheDocument();
    expect(screen.getByTestId('pmg-copy-state')).toHaveTextContent('copying · 31%');
  });
});

// ---------------------------------------------------------------------------------------------
// Switch over — PFX-8.17 (#7314)
// ---------------------------------------------------------------------------------------------

describe('Switch over: agreement, who has moved, keep-in-sync', () => {
  /** Copy with a token in hand, then continue to Switch over on `run`. */
  async function toSwitch(run: ReturnType<typeof agreedCopy>) {
    rest.read = () => ok(run);
    const view = await toChoose();
    fireEvent.click(screen.getByTestId('pmg-start'));
    await screen.findByTestId('pmg-copy');
    await waitFor(() => expect(screen.getByTestId('pmg-continue')).toBeEnabled());
    fireEvent.click(screen.getByTestId('pmg-continue'));
    await screen.findByTestId('pmg-switch');
    await waitFor(() => expect(calls.some((call) => call.url === `${API}/${run.id}/sync`)).toBe(true));
    await act(async () => {});
    return view;
  }

  it('says both brokers agree, lists who has moved, and passes axe', async () => {
    const run = agreedCopy();
    const { container } = await toSwitch(run);
    expect(screen.getByTestId('pmg-agreement')).toHaveAttribute('data-tone', 'ok');
    expect(screen.getByTestId('pmg-headline')).toHaveTextContent('Copied. Apiome and acme.pactflow.io give the same answers.');
    expect(screen.getByTestId('pmg-agreement-detail')).toHaveTextContent(
      'Checked 40 can-i-deploy questions on both sides: 40 agree.',
    );
    expect(screen.queryByTestId('pmg-differences')).not.toBeInTheDocument();
    expect(screen.getByTestId('pmg-moved-summary')).toHaveTextContent('2 of 3 have moved. The rest last published to acme.pactflow.io.');
    const rows = within(screen.getByTestId('pmg-moved')).getAllByRole('row').slice(1);
    expect(rows.map((row) => row.textContent)).toEqual([
      'Mobile AppOld brokeryesterday',
      'Orders UIApiome12 min ago',
      'Billing ServiceApiome1 h ago',
    ]);
    expect(screen.getByTestId('pmg-sync-switch')).not.toBeChecked();
    expect(screen.getByTestId('pmg-sync')).toHaveTextContent('Every 15 minutes, anything new at the old broker is brought over');

    fireEvent.click(screen.getByTestId('pmg-sync-switch'));
    await waitFor(() => expect(puts(`/${run.id}/sync`)).toHaveLength(1));
    expect(puts(`/${run.id}/sync`)[0].body).toEqual({ enabled: true, token: TOKEN });
    await waitFor(() => expect(screen.getByTestId('pmg-sync-switch')).toBeChecked());
    expect(screen.getByTestId('pmg-sync-note')).toHaveTextContent('Next pass 27 Nov 2026, 14:45 UTC.');
    const block = screen.getByTestId('pmg-command-block');
    expect(block).toHaveTextContent('--follow');
    expect(block).not.toHaveTextContent(TOKEN);
    expect(container).not.toHaveTextContent(TOKEN);
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('pact-migrate-switch', liveMarkup(container.firstElementChild!));

    fireEvent.click(screen.getByTestId('pmg-sync-switch'));
    await waitFor(() => expect(puts(`/${run.id}/sync`)).toHaveLength(2));
    expect(puts(`/${run.id}/sync`)[1].body).toEqual({ enabled: false });
    await waitFor(() => expect(screen.getByTestId('pmg-sync-switch')).not.toBeChecked());
  });

  it('lists each difference with its cause when the answers disagree', async () => {
    const run = disagreedCopy();
    const { container } = await toSwitch(run);
    expect(screen.getByTestId('pmg-agreement')).toHaveAttribute('data-tone', 'warn');
    expect(screen.getByTestId('pmg-headline')).toHaveTextContent('38 of 40 agree.');
    expect(screen.getByTestId('pmg-agreement-detail')).toHaveTextContent('2 answers differ, each listed with why.');
    const table = screen.getByTestId('pmg-differences');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Legacy Cart 4.2.0 → production');
    expect(rows[0]).toHaveTextContent('was not copied: consumer version missing at source');
    expect(rows[1]).toHaveTextContent('no answer');
    expect(rows[1]).toHaveTextContent('a selector it does not support?');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
  });

  it('asks for the credentials before keeping a reopened copy in sync', async () => {
    const run = agreedCopy();
    rest.list = () => ok({ runs: [run], can_migrate: true });
    rest.read = () => ok(run);
    await mount();
    await openPast(run);
    await screen.findByTestId('pmg-switch');
    await act(async () => {});
    fireEvent.click(screen.getByTestId('pmg-sync-switch'));
    const ask = await screen.findByTestId('pmg-sync-credentials');
    expect(ask).toHaveTextContent('Sign in to acme.pactflow.io to keep copying');
    expect(ask).toHaveTextContent('Kept encrypted while keep-in-sync is on; deleted when it is off.');
    expect(puts(`/${run.id}/sync`)).toHaveLength(0);
    expect(screen.getByTestId('pmg-sync-on')).toBeDisabled();
    fireEvent.change(screen.getByTestId('pmg-sync-token'), { target: { value: TOKEN } });
    fireEvent.click(screen.getByTestId('pmg-sync-on'));
    await waitFor(() => expect(puts(`/${run.id}/sync`)).toHaveLength(1));
    expect(puts(`/${run.id}/sync`)[0].body).toEqual({ enabled: true, token: TOKEN });
    await waitFor(() => expect(screen.queryByTestId('pmg-sync-credentials')).not.toBeInTheDocument());
  });

  it('says why a sync stopped itself', async () => {
    const run = agreedCopy();
    const reason =
      'Keep-in-sync stopped itself: acme.pactflow.io could not be read for 24 hours (last: Could not reach acme.pactflow.io (ConnectError). Check the URL.). Nothing was lost; switch it on again once the old broker answers.';
    rest.sync = (id) => ok(syncOff(id, { stopped_reason: reason, unreachable_since: '2026-11-26T09:00:00Z' }));
    await toSwitch(run);
    const note = await screen.findByTestId('pmg-sync-note');
    expect(note).toHaveTextContent(reason);
    expect(note).toHaveAttribute('role', 'alert');
    expect(screen.getByTestId('pmg-sync-switch')).not.toBeChecked();
    expect(screen.getByTestId('pmg-sync-switch')).toBeEnabled();
  });

  it('warns while the old broker has not answered', async () => {
    const run = agreedCopy();
    rest.sync = (id) => ok({ ...syncOn(id), unreachable_since: '2026-11-27T09:00:00Z', last_error: 'acme.pactflow.io answered HTTP 503 for /.' });
    await toSwitch(run);
    expect(await screen.findByTestId('pmg-sync-note')).toHaveTextContent(
      'acme.pactflow.io has not answered since 27 Nov 2026, 09:00 UTC (acme.pactflow.io answered HTTP 503 for /.). Keep-in-sync stops itself after 24 hours of that.',
    );
  });

  it('shows REST’s refusal and leaves the switch off', async () => {
    const run = agreedCopy();
    rest.sync = (id, method) =>
      method === 'PUT'
        ? refused(503, 'this server cannot keep credentials: set APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS to keep a migration in sync')
        : ok(syncOff(id));
    await toSwitch(run);
    fireEvent.click(screen.getByTestId('pmg-sync-switch'));
    expect(await screen.findByTestId('pmg-sync-error')).toHaveTextContent('APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS');
    expect(screen.getByTestId('pmg-sync-switch')).not.toBeChecked();
  });

  it('cannot be switched without the permission and says who to ask', async () => {
    const run = agreedCopy();
    rest.list = () => ok({ runs: [run], can_migrate: false });
    rest.read = () => ok(run);
    await mount();
    await openPast(run);
    await screen.findByTestId('pmg-switch');
    await act(async () => {});
    expect(screen.getByTestId('pmg-sync-switch')).toBeDisabled();
    expect(screen.getByTestId('pmg-sync')).toHaveTextContent('Ask a workspace admin to keep this migration in sync.');
  });

  it('says what could not be worked out instead of hiding it', async () => {
    const run = { ...COPY_DONE, facts: { ...COPY_DONE.facts, agreement: { error: 'the agreement check could not run (RuntimeError)' }, moved: { error: 'who has moved could not be read (RuntimeError)' } } };
    await toSwitch(run as ReturnType<typeof agreedCopy>);
    expect(screen.getByTestId('pmg-agreement')).toHaveAttribute('data-tone', 'danger');
    expect(screen.getByTestId('pmg-headline')).toHaveTextContent('The agreement check could not run.');
    expect(screen.getByTestId('pmg-moved-error')).toHaveTextContent('who has moved could not be read (RuntimeError).');
  });
});
