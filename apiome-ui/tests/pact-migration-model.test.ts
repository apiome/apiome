/**
 * The Migration wizard's model — PFX-8.16 (#7313), `lib/pact-migration.ts`.
 *
 * * a run opens on the step it belongs to, and the tiles tick record kinds (in copying order);
 * * the Choose step refuses nothing silently: no kind, or a limit out of range, says why;
 * * findings become one strip, the ones about secrets first, with nothing dropped;
 * * the per-kind cells, the badges and the log read as the mockup shows them;
 * * the wizard is written as `apiome pact migrate` with the credentials as variables, and every
 *   choice the command cannot carry is listed with its reason;
 * * the proxies' body checks name what they refuse.
 */

import fixture from './fixtures/pact-migration.json';
import { pactCommandSurfaces, unsupportedLines } from '../lib/pact-commands';
import {
  CHOICE_TILES,
  DEFAULT_OPTIONS,
  EMPTY_SOURCE,
  MAX_WARNING_LINES,
  MIGRATION_KINDS,
  checkCredentialsBody,
  checkSourceBody,
  checkStartBody,
  chooseProblem,
  connectProblem,
  copiedCell,
  copiedHeadline,
  credentialsOf,
  existingSentence,
  failedCount,
  formatWhen,
  hasCredentials,
  isRunId,
  mergeLog,
  migrateCommandAction,
  migrationWarnings,
  readCursor,
  reportDocument,
  reportFileName,
  runBadge,
  skippedCell,
  stepForRun,
  tileChecked,
  tileCount,
  toggleTile,
  type MigrationRun,
  type SourceForm,
} from '../lib/pact-migration';

const DRY = fixture.dry as unknown as MigrationRun;
const COPY = fixture.copy as unknown as MigrationRun;
const COPY_FAILED = fixture.copyFailed as unknown as MigrationRun;
const COPY_DONE = fixture.copyDone as unknown as MigrationRun;
const COPY_STOPPED = fixture.copyStopped as unknown as MigrationRun;
const TOKEN = 's3cr3t-read-token';
const FORM: SourceForm = { ...EMPTY_SOURCE, source: 'https://acme.pactflow.io', token: TOKEN };
const tile = (id: string) => CHOICE_TILES.find((candidate) => candidate.id === id)!;

describe('steps', () => {
  it('opens a run on the step it belongs to', () => {
    expect(stepForRun(DRY)).toBe('choose');
    expect(stepForRun(COPY)).toBe('copy');
    expect(stepForRun(COPY_STOPPED)).toBe('copy');
    expect(stepForRun(COPY_FAILED)).toBe('copy');
    expect(stepForRun(COPY_DONE)).toBe('switch');
    expect(failedCount(COPY_FAILED)).toBe(2);
  });

  it('says why the URL cannot be tested', () => {
    expect(connectProblem(EMPTY_SOURCE)).toBe('Enter the broker’s URL.');
    expect(connectProblem({ ...FORM, source: 'acme.pactflow.io' })).toMatch(/full URL/);
    expect(connectProblem({ ...FORM, source: 'ftp://acme.pactflow.io' })).toMatch(/http:\/\/ or https:\/\//);
    expect(connectProblem({ ...FORM, source: 'https://ci:pw@acme.pactflow.io' })).toMatch(/credentials out of the URL/);
    expect(connectProblem(FORM)).toBeNull();
  });

  it('sends a token, or a username and password, or nothing', () => {
    expect(credentialsOf(FORM)).toEqual({ token: TOKEN });
    expect(credentialsOf({ ...FORM, auth: 'basic', username: 'ci', password: 'pw' })).toEqual({ username: 'ci', password: 'pw' });
    expect(credentialsOf({ ...FORM, token: '' })).toEqual({});
    expect(credentialsOf({ ...FORM, auth: 'basic' })).toEqual({});
    expect(hasCredentials(FORM, 'token')).toBe(true);
    expect(hasCredentials({ ...FORM, token: '' }, 'token')).toBe(false);
    expect(hasCredentials({ ...FORM, token: '' }, 'none')).toBe(true);
    expect(hasCredentials({ ...FORM, username: 'ci' }, 'basic')).toBe(true);
  });
});

describe('the Choose step', () => {
  it('ticks kinds through the tiles, in copying order', () => {
    expect(CHOICE_TILES.every((candidate) => tileChecked(DEFAULT_OPTIONS, candidate))).toBe(true);
    const without = toggleTile(DEFAULT_OPTIONS, tile('deployments'), false);
    expect(without.kinds).toEqual(MIGRATION_KINDS.filter((kind) => kind !== 'deployment' && kind !== 'release'));
    expect(tileChecked(without, tile('deployments'))).toBe(false);
    expect(toggleTile(without, tile('deployments'), true).kinds).toEqual([...MIGRATION_KINDS]);
    expect(toggleTile(DEFAULT_OPTIONS, tile('labels'), false).labels_and_tags).toBe(false);
  });

  it('falls back to every version when versions are unticked', () => {
    const kept = { ...DEFAULT_OPTIONS, versions: 'kept' as const };
    expect(toggleTile(kept, tile('versions'), false).versions).toBe('all');
    expect(toggleTile(kept, tile('pacts'), false).versions).toBe('kept');
  });

  it('shows what the dry run counted', () => {
    expect(tileCount(DRY, tile('versions'))).toBe(3816);
    expect(tileCount(DRY, tile('deployments'))).toBe(57);
    expect(tileCount(DRY, tile('labels'))).toBe(318);
    expect(tileCount(null, tile('pacts'))).toBeNull();
    expect(existingSentence(DRY)).toMatch(/^6 pacticipants exist on both sides\./);
    expect(existingSentence(COPY)).toBe('');
  });

  it('says why the copy cannot start', () => {
    expect(chooseProblem(DEFAULT_OPTIONS)).toBeNull();
    expect(chooseProblem({ ...DEFAULT_OPTIONS, kinds: [] })).toBe('Tick at least one kind to copy.');
    expect(chooseProblem({ ...DEFAULT_OPTIONS, matrix_limit: 0 })).toMatch(/matrix limit/);
    expect(chooseProblem({ ...DEFAULT_OPTIONS, matrix_limit: Number.NaN })).toMatch(/matrix limit/);
    expect(chooseProblem({ ...DEFAULT_OPTIONS, batch_bytes: 12 })).toMatch(/batch size/);
  });

  it('turns findings into one strip, secrets first, counting what it does not list', () => {
    const warnings = migrationWarnings(DRY);
    expect(warnings.map((warning) => warning.id)).toEqual(['webhook', 'pacticipant', 'pact', 'not-read']);
    const [webhooks] = warnings;
    expect(webhooks).toMatchObject({ tone: 'warn', label: '11 webhook notes', secrets: true });
    expect(webhooks.lines).toHaveLength(MAX_WARNING_LINES + 1);
    expect(webhooks.lines[MAX_WARNING_LINES]).toBe('… and 3 more, listed in the report.');
    expect(warnings[1]).toMatchObject({ tone: 'accent', label: '1 pacticipant note', secrets: false });
    expect(warnings[3].lines).toEqual(DRY.not_read);
    expect(migrationWarnings(null)).toEqual([]);
  });
});

describe('the Copy step', () => {
  const row = (kind: string) => COPY.kinds.find((candidate) => candidate.kind === kind)!;

  it('reads each kind as copied of what it means to copy, skipped and failed', () => {
    expect(copiedCell(row('pacticipant'), true)).toBe('36 / 36');
    expect(skippedCell(row('pacticipant'))).toEqual({ count: 6, note: '6 already here' });
    expect(copiedCell(row('version'), true)).toBe('1,904 / 1,904');
    expect(skippedCell(row('version'))).toEqual({ count: 1912, note: '' });
    expect(copiedCell(row('pact'), true)).toBe('612 / 1,284');
    expect(copiedCell(row('verification'), true)).toBe('waiting');
    expect(copiedCell(row('verification'), false)).toBe('0 / 9,402');
  });

  it('badges a run by where it is', () => {
    expect(runBadge(COPY)).toEqual({ status: 'running', label: 'copying · 31%' });
    expect(runBadge({ ...COPY, phase: 'reading' })).toEqual({ status: 'running', label: 'reading' });
    expect(runBadge({ ...COPY, stop_requested: true }).label).toBe('stopping · 31%');
    expect(runBadge(COPY_STOPPED)).toEqual({ status: 'warning', label: 'stopped' });
    expect(runBadge({ ...COPY_STOPPED, status: 'failed' })).toEqual({ status: 'failed', label: 'failed' });
    expect(runBadge(COPY_FAILED)).toEqual({ status: 'warning', label: 'completed · 2 failed' });
    expect(runBadge(COPY_DONE)).toEqual({ status: 'passed', label: 'completed' });
    expect(runBadge(DRY)).toEqual({ status: 'neutral', label: 'dry run' });
    expect(runBadge(fixture.dryRunning as unknown as MigrationRun).label).toBe('checking · 31%');
  });

  it('adds each log line once', () => {
    const shown = COPY.log.slice(0, 2);
    expect(mergeLog(shown, COPY.log).map((line) => line.seq)).toEqual([40, 41, 42, 43]);
    expect(mergeLog(shown, shown)).toBe(shown);
    expect(mergeLog([], [])).toEqual([]);
  });

  it('writes the headline and the report', () => {
    expect(copiedHeadline(COPY_DONE)).toBe('Copied 12,698 records from acme.pactflow.io. 6 were already here.');
    const report = reportDocument(COPY_FAILED, COPY_FAILED.log);
    expect(report).toMatchObject({ source: 'https://acme.pactflow.io', mode: 'copy', failures_not_listed: 0 });
    expect(report.failures).toHaveLength(2);
    expect(report.not_portable).toHaveLength(13);
    expect(report.log).toHaveLength(4);
    expect(Object.keys(report).filter((key) => /token|password|credential/i.test(key))).toEqual([]);
    expect(reportFileName(COPY_DONE)).toBe('apiome-migration-acme.pactflow.io.json');
    expect(reportFileName({ host: 'a b/c' })).toBe('apiome-migration-a-b-c.json');
    expect(formatWhen('2026-11-27T14:17:00Z')).toBe('27 Nov 2026, 14:17 UTC');
    expect(formatWhen(null)).toBe('—');
  });
});

describe('the same, from anywhere', () => {
  const apiome = (action: ReturnType<typeof migrateCommandAction>) =>
    pactCommandSurfaces(action).find((surface) => surface.id === 'apiome')!.text;
  const rest = (action: ReturnType<typeof migrateCommandAction>) =>
    pactCommandSurfaces(action).find((surface) => surface.id === 'rest')!.text;

  it('writes a dry run with the token as its variable, never as itself', () => {
    const action = migrateCommandAction(FORM, DEFAULT_OPTIONS, 'dry-run');
    const text = apiome(action);
    expect(text).toContain('apiome pact migrate');
    expect(text).toContain('--from https://acme.pactflow.io');
    expect(text).toContain('--token "$PACT_SOURCE_BROKER_TOKEN"');
    expect(text).toContain('--dry-run');
    expect(text).not.toContain('--restart');
    expect(text).not.toContain('--matrix-limit');
    expect(text).not.toContain(TOKEN);
    expect(rest(action)).toContain('/v1/tenants/{tenant}/pact-migration/runs');
    expect(rest(action)).not.toContain(TOKEN);
    expect(unsupportedLines(action)).toEqual([]);
  });

  it('writes the copy with its flags, and a username and password', () => {
    const form: SourceForm = { ...FORM, auth: 'basic', token: '', username: 'ci', password: 'hunter2-pw' };
    const options = { ...DEFAULT_OPTIONS, restart: true, matrix_limit: 5000, batch_bytes: 1048576 };
    const text = apiome(migrateCommandAction(form, options, 'copy'));
    expect(text).toContain('--username ci');
    expect(text).toContain('--password "$PACT_SOURCE_BROKER_PASSWORD"');
    expect(text).toContain('--restart');
    expect(text).toContain('--matrix-limit 5000');
    expect(text).toContain('--batch-bytes 1048576');
    expect(text).not.toContain('--dry-run');
    expect(text).not.toContain('hunter2-pw');
  });

  it('lists every choice the command cannot carry, with why', () => {
    const options = {
      ...toggleTile(toggleTile(DEFAULT_OPTIONS, tile('webhooks'), false), tile('labels'), false),
      results: 'latest' as const,
      versions: 'kept' as const,
      conflicts: 'replace' as const,
    };
    const action = migrateCommandAction(FORM, options, 'copy');
    const lines = unsupportedLines(action);
    expect(lines).toHaveLength(4);
    expect(lines[0]).toContain('Not copying Webhooks, Labels and tags');
    expect(lines.join('\n')).toMatch(/latest result of each pact/);
    expect(lines.join('\n')).toMatch(/clean-up would keep/);
    expect(lines.join('\n')).toMatch(/always keeps Apiome’s record/);
    expect(rest(action)).toContain('"conflicts": "replace"');
  });
});

describe('the proxies’ checks', () => {
  it('accepts a source with one way of signing in', () => {
    expect(checkSourceBody({ source: 'https://acme.pactflow.io', token: TOKEN }).ok).toBe(true);
    expect(checkSourceBody({ source: 'https://b.example', username: 'ci', password: 'pw' }).ok).toBe(true);
    expect(checkSourceBody({ source: 'https://b.example' }).ok).toBe(true);
  });

  it.each([
    [null, 'Send the source as a JSON object.'],
    [[], 'Send the source as a JSON object.'],
    [{ token: TOKEN }, 'source is the broker’s URL.'],
    [{ source: 'ftp://b.example' }, 'The URL must start with http:// or https://.'],
    [{ source: 'https://b.example', token: 7 }, 'token is text.'],
    [{ source: 'https://b.example', token: 't', username: 'u' }, 'Send a token, or a username and password — not both.'],
    [{ source: 'https://b.example', mode: 'copy' }, 'Unsupported field mode.'],
  ])('refuses %j naming the problem', (body, error) => {
    expect(checkSourceBody(body)).toEqual({ ok: false, error });
  });

  it('checks a run to start', () => {
    const body = { source: 'https://b.example', token: TOKEN, mode: 'copy', options: { ...DEFAULT_OPTIONS } };
    expect(checkStartBody(body)).toEqual({ ok: true, body });
    expect(checkStartBody({ ...body, mode: 'sync' })).toEqual({ ok: false, error: 'mode is dry-run or copy.' });
    expect(checkStartBody({ ...body, options: [] })).toEqual({ ok: false, error: 'options is a JSON object.' });
    expect(checkStartBody({ ...body, options: { teams: true } })).toEqual({ ok: false, error: 'Unsupported option teams.' });
    expect(checkStartBody({ ...body, dry_run: true })).toEqual({ ok: false, error: 'Unsupported field dry_run.' });
    expect(checkStartBody({ token: TOKEN, mode: 'copy' }).ok).toBe(false);
  });

  it('checks a resume, which carries credentials and nothing else', () => {
    expect(checkCredentialsBody({ token: TOKEN })).toEqual({ ok: true, body: { token: TOKEN } });
    expect(checkCredentialsBody({})).toEqual({ ok: true, body: {} });
    expect(checkCredentialsBody({ source: 'https://b.example' })).toEqual({ ok: false, error: 'Unsupported field source.' });
    expect(checkCredentialsBody('x')).toEqual({ ok: false, error: 'Send the credentials as a JSON object.' });
  });

  it('reads a run id and a log cursor', () => {
    expect(isRunId(COPY.id)).toBe(true);
    expect(isRunId('../runs')).toBe(false);
    expect(readCursor(new URLSearchParams(''))).toEqual({ ok: true, after: 0 });
    expect(readCursor(new URLSearchParams('after=41'))).toEqual({ ok: true, after: 41 });
    expect(readCursor(new URLSearchParams('after=-1')).ok).toBe(false);
    expect(readCursor(new URLSearchParams('limit=5'))).toEqual({
      ok: false,
      error: 'Unsupported parameter limit: a run read takes after.',
    });
  });
});

// ---------------------------------------------------------------------------------------------
// Switch over — PFX-8.17 (#7314)
// ---------------------------------------------------------------------------------------------

describe('switch over', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const model = require('../lib/pact-migration') as typeof import('../lib/pact-migration');
  const NOW = new Date('2026-11-27T15:00:00Z');
  const done = fixture.copyDone as unknown as import('../lib/pact-migration').MigrationRun;
  const withFacts = (facts: Record<string, unknown>) => ({ ...done, facts: { ...done.facts, ...facts } });
  const agreement = { asked: 40, agree: 40, not_asked: 0, differences: [], differences_dropped: 0, checked_at: null };

  it('reads the agreement check as the mockup does', () => {
    expect(model.agreementSummary(withFacts({ agreement }))).toEqual({
      tone: 'ok',
      title: 'Copied. Apiome and acme.pactflow.io give the same answers.',
      detail: 'Checked 40 can-i-deploy questions on both sides: 40 agree.',
    });
    const differ = model.agreementSummary(withFacts({ agreement: { ...agreement, agree: 38, not_asked: 12 } }));
    expect(differ.tone).toBe('warn');
    expect(differ.title).toBe('38 of 40 agree.');
    expect(differ.detail).toBe(
      'Checked 40 can-i-deploy questions on both sides: 2 answers differ, each listed with why. 12 more were not asked.',
    );
    expect(model.agreementSummary(withFacts({ agreement: { ...agreement, asked: 0, agree: 0 } })).detail).toContain(
      'no can-i-deploy question to ask',
    );
    expect(model.agreementSummary(withFacts({ agreement: { error: 'it broke' } }))).toMatchObject({
      tone: 'danger',
      detail: 'it broke. The copy stands.',
    });
    expect(model.agreementSummary(done).detail).toBe('The agreement check was not run for this copy.');
  });

  it('lists the differences and how many were not listed', () => {
    const difference = { question: 'Web 2 → production', pacticipant: 'Web', version: '2', environment: 'production', source: 'yes', apiome: 'unknown', cause: 'x' };
    expect(model.agreementDifferences(withFacts({ agreement: { ...agreement, differences: [difference], differences_dropped: 3 } }))).toEqual({
      rows: [difference],
      more: 3,
    });
    expect(model.agreementDifferences(withFacts({ agreement: { error: 'x' } }))).toEqual({ rows: [], more: 0 });
  });

  it('says how long ago, in words', () => {
    expect(model.sinceWhen(null, NOW)).toBe('');
    expect(model.sinceWhen('2026-11-27T14:59:40Z', NOW)).toBe('just now');
    expect(model.sinceWhen('2026-11-27T14:48:00Z', NOW)).toBe('12 min ago');
    expect(model.sinceWhen('2026-11-27T12:00:00Z', NOW)).toBe('3 h ago');
    expect(model.sinceWhen('2026-11-26T10:00:00Z', NOW)).toBe('yesterday');
    expect(model.sinceWhen('2026-11-22T10:00:00Z', NOW)).toBe('5 days ago');
    expect(model.sinceWhen('2026-09-01T10:00:00Z', NOW)).toBe('1 Sep 2026, 10:00 UTC');
  });

  it('lists who has moved, stragglers as REST orders them', () => {
    const moved = {
      total: 3,
      moved: 1,
      dropped: 2,
      checked_at: null,
      pacticipants: [
        { name: 'Mobile App', last: 'source', apiome_at: null, source_at: '2026-11-26T10:00:00Z' },
        { name: 'Orders UI', last: 'apiome', apiome_at: '2026-11-27T14:48:00Z', source_at: null },
        { name: 'Ledger', last: 'none', apiome_at: null, source_at: null },
      ],
    };
    const read = model.movedRows(withFacts({ moved }), NOW);
    expect(read.rows).toEqual([
      { name: 'Mobile App', label: 'Old broker', status: 'warning', when: 'yesterday' },
      { name: 'Orders UI', label: 'Apiome', status: 'passed', when: '12 min ago' },
      { name: 'Ledger', label: 'Nothing published', status: 'neutral', when: '' },
    ]);
    expect(read.summary).toBe('1 of 3 have moved. The rest last published to acme.pactflow.io.');
    expect(read.more).toBe(2);
    expect(model.movedRows(withFacts({ moved: { ...moved, moved: 3 } }), NOW).summary).toBe(
      'All 3 have moved: each last published to Apiome.',
    );
    expect(model.movedRows(withFacts({ moved: { error: 'no' } }), NOW).error).toBe('no.');
  });

  it('says what keep-in-sync is doing', () => {
    const off = {
      run_id: done.id,
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
    };
    expect(model.syncNote(null, 'h')).toBeNull();
    expect(model.syncNote(off, 'h')).toBeNull();
    expect(model.syncNote({ ...off, available: false }, 'h')?.text).toContain('apiome pact migrate --follow');
    expect(model.syncNote({ ...off, stopped_reason: 'Stopped: gone.' }, 'h')).toEqual({ tone: 'danger', text: 'Stopped: gone.' });
    const on = { ...off, enabled: true, next_run_at: '2026-11-27T15:15:00Z', last_success_at: '2026-11-27T14:48:00Z' };
    expect(model.syncNote(on, 'h', NOW)).toEqual({ tone: 'info', text: 'Last copied 12 min ago. Next pass 27 Nov 2026, 15:15 UTC.' });
    expect(model.syncNote({ ...on, unreachable_since: '2026-11-27T09:00:00Z' }, 'acme.pactflow.io', NOW)?.text).toBe(
      'acme.pactflow.io has not answered since 27 Nov 2026, 09:00 UTC. Keep-in-sync stops itself after 24 hours of that.',
    );
    expect(model.syncNote({ ...on, last_error: 'A migration was running.' }, 'h', NOW)).toEqual({
      tone: 'warn',
      text: 'The last pass did not finish: A migration was running.',
    });
    expect(model.syncSentence(null)).toContain('Every 15 minutes, anything new at the old broker is brought over');
  });

  it('checks a keep-in-sync switch and names what it refuses', () => {
    expect(model.checkSyncBody({ enabled: true, token: 't', interval_minutes: 30 })).toEqual({
      ok: true,
      body: { enabled: true, token: 't', interval_minutes: 30 },
    });
    expect(model.checkSyncBody({ enabled: false })).toEqual({ ok: true, body: { enabled: false } });
    expect(model.checkSyncBody({ enabled: 1 })).toEqual({ ok: false, error: 'enabled is true or false.' });
    expect(model.checkSyncBody({ enabled: true, every: 5 })).toEqual({ ok: false, error: 'Unsupported field every.' });
    expect(model.checkSyncBody({ enabled: true, token: 't', password: 'p' })).toMatchObject({ ok: false });
    expect(model.checkSyncBody([])).toMatchObject({ ok: false });
  });

  it('writes keep-in-sync as apiome pact migrate --follow and the REST PUT, the token as a variable', () => {
    const form = { ...EMPTY_SOURCE, source: 'https://acme.pactflow.io', token: 's3cr3t' };
    const action = model.syncCommandAction(form, done.id, 'acme');
    const surfaces = pactCommandSurfaces(action);
    const text = JSON.stringify(surfaces);
    expect(text).toContain('--from https://acme.pactflow.io');
    expect(text).toContain('--follow');
    expect(text).toContain('$PACT_SOURCE_BROKER_TOKEN');
    expect(text).not.toContain('s3cr3t');
    expect(action.rest).toMatchObject({ method: 'PUT', path: `/v1/tenants/acme/pact-migration/runs/${done.id}/sync` });
    expect(unsupportedLines(action)).toEqual([]);
  });

  it('badges a copy that is asking both brokers, and reports the switch-over facts', () => {
    expect(runBadge({ ...done, status: 'running', phase: 'checking' })).toEqual({ status: 'running', label: 'asking both brokers' });
    const report = reportDocument(withFacts({ agreement }), []);
    expect(report.agreement).toEqual(agreement);
    expect(report.moved).toBeNull();
    expect(DEFAULT_OPTIONS.agreement_questions).toBe(40);
  });
});
