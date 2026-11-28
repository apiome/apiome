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
 * `A11Y_FIXTURE_DUMP=1` writes the docs-screenshot fixtures `pact-migrate-choose` and `pact-migrate-copy`.
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
    const run = /^\/api\/pact\/migrations\/([0-9a-f-]{36})(\/stop|\/resume)?/.exec(url);
    if (url === '/api/pact/broker-address') answer = ok({ broker_base_url: fixture.broker });
    else if (url === API && method === 'GET') answer = rest.list();
    else if (url === API) answer = rest.start(body ?? {});
    else if (url === `${API}/test`) answer = rest.test(body ?? {});
    else if (run && run[2] === '/stop') answer = rest.stop(run[1]);
    else if (run && run[2] === '/resume') answer = rest.resume(run[1], body ?? {});
    else if (run) answer = rest.read(run[1]);
    return { ok: answer.status < 400, status: answer.status, json: async () => answer.body } as Response;
  }) as unknown as typeof fetch;
}

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
