/**
 * The Migration wizard — PFX-8.16 (#7313), `/ade/dashboard/pacts/migrate`.
 *
 * The model behind the wizard and its proxies (`/api/pact/migrations*`). REST owns every rule
 * (`app.pact_migration_job`): it reads the source broker, applies the choices and writes the
 * records. This module names the steps, tiles and choices as the wizard shows them, checks bodies
 * before they are forwarded (nothing unknown is passed on or dropped), turns a run into what each
 * step draws, and writes the wizard's choices as `apiome pact migrate`.
 *
 * * **The source is only read.** Nothing here (or in REST) sends it anything but `GET`.
 * * **The credentials are never stored.** The token or password lives in the wizard's memory and in
 *   the request that starts or resumes a run; opening a past migration asks for it again.
 * * **A run is the server's.** Leaving the page changes nothing about it: the wizard reads it again
 *   when it is opened, from **Past migrations** or because it is still running.
 */

import { tenantPath, type PactAction, type PactOption, type PactUnsupported } from './pact-commands';

/** The wizard's route, and where **Finish**, **Cancel** and **Save & close** go. */
export const MIGRATE_ROUTE = '/ade/dashboard/pacts/migrate';

/** The page's title and description. */
export const MIGRATE_TITLE = 'Migrate from a broker';
export const MIGRATE_DESCRIPTION =
  'Bring a Pact Broker or PactFlow over — pacticipants, versions, pacts, results and environments — and switch pipelines when you are ready.';

/** The BFF below which the wizard's calls go. */
export const MIGRATIONS_API = '/api/pact/migrations';

/** The REST path below `/v1/tenants/{slug}` the proxies forward to. */
export const MIGRATION_PROXY_PATH = 'pact-migration';

/** How often a running migration is read. */
export const MIGRATION_POLL_MS = 1500;

/** The CLI's defaults, so a flag is written only when the wizard's value differs. */
export const DEFAULT_MATRIX_LIMIT = 1000;
export const DEFAULT_BATCH_BYTES = 4 * 1024 * 1024;

/** The limits REST accepts for the two advanced numbers. */
export const MATRIX_LIMIT_RANGE = { min: 1, max: 100_000 } as const;
export const BATCH_BYTES_RANGE = { min: 1024, max: 32 * 1024 * 1024 } as const;

/** The variables `apiome pact migrate` reads the source's credentials from. */
export const SOURCE_VARIABLE_PREFIX = 'PACT_SOURCE_BROKER_';

/** The record kinds, in the order they are copied. */
export const MIGRATION_KINDS = [
  'pacticipant',
  'environment',
  'version',
  'pact',
  'verification',
  'deployment',
  'release',
  'webhook',
] as const;

/** One record kind. */
export type MigrationKind = (typeof MIGRATION_KINDS)[number];

/** How each kind reads in the per-kind table. */
export const KIND_LABELS: Readonly<Record<MigrationKind, string>> = {
  pacticipant: 'Pacticipants',
  environment: 'Environments',
  version: 'Versions',
  pact: 'Pacts',
  verification: 'Verification results',
  deployment: 'Deployments',
  release: 'Releases',
  webhook: 'Webhooks',
};

/** What the **Choose** step decides (REST's `PactMigrationRunOptions`). */
export interface MigrationOptions {
  kinds: MigrationKind[];
  labels_and_tags: boolean;
  results: 'all' | 'latest' | 'none';
  versions: 'all' | 'kept';
  conflicts: 'keep' | 'replace';
  restart: boolean;
  matrix_limit: number;
  batch_bytes: number;
}

/** Everything is copied, Apiome's records win, nothing is thinned. */
export const DEFAULT_OPTIONS: MigrationOptions = {
  kinds: [...MIGRATION_KINDS],
  labels_and_tags: true,
  results: 'all',
  versions: 'all',
  conflicts: 'keep',
  restart: false,
  matrix_limit: DEFAULT_MATRIX_LIMIT,
  batch_bytes: DEFAULT_BATCH_BYTES,
};

/** One record kind of a run. */
export interface KindProgress {
  kind: MigrationKind;
  total: number;
  done: number;
  copied: number;
  unchanged: number;
  skipped: number;
  failed: number;
  exists: number;
  would_create: number;
}

/** Something the source holds that cannot be carried over as it is. */
export interface MigrationFinding {
  kind: string;
  subject: string;
  detail: string;
}

/** A refused record. */
export interface MigrationFailure {
  kind: string;
  key: string;
  code: string;
  message: string;
}

/** One log line. */
export interface MigrationLogLine {
  seq: number;
  text: string;
}

/** A migration run, as REST answers it. */
export interface MigrationRun {
  id: string;
  source: string;
  host: string;
  auth_kind: 'token' | 'basic' | 'none';
  mode: 'dry-run' | 'copy';
  status: 'running' | 'completed' | 'stopped' | 'failed';
  phase: string;
  percent: number;
  options: MigrationOptions;
  kinds: KindProgress[];
  facts: {
    product?: string;
    cleanup_rules_set?: boolean;
    cleanup_would_skip?: number | null;
    results_not_latest?: number;
    labels_and_tags?: number;
    conflicts_kept?: number;
  };
  findings: MigrationFinding[];
  failures: MigrationFailure[];
  failures_dropped: number;
  log: MigrationLogLine[];
  log_seq: number;
  error: string | null;
  stop_requested: boolean;
  can_resume: boolean;
  started_by: string | null;
  created_at: string | null;
  finished_at: string | null;
  not_read: string[];
}

/** The workspace's runs, and whether the viewer may run one. */
export interface MigrationRunList {
  runs: MigrationRun[];
  can_migrate: boolean;
}

/** What **Test connection** found. */
export interface SourceTest {
  host: string;
  product: string;
  pacticipants: number;
}

/** The **Connect** step's fields. The token and password never leave the wizard's memory. */
export interface SourceForm {
  source: string;
  auth: 'token' | 'basic';
  token: string;
  username: string;
  password: string;
}

/** An empty **Connect** step. */
export const EMPTY_SOURCE: SourceForm = { source: '', auth: 'token', token: '', username: '', password: '' };

// ---------------------------------------------------------------------------------------------
// The wizard's steps
// ---------------------------------------------------------------------------------------------

/** The four steps, in order. */
export const WIZARD_STEPS = [
  { id: 'connect', label: 'Connect' },
  { id: 'choose', label: 'Choose' },
  { id: 'copy', label: 'Copy' },
  { id: 'switch', label: 'Switch over' },
] as const;

/** One step. */
export type WizardStep = (typeof WIZARD_STEPS)[number]['id'];

/**
 * Whether a run has ended.
 *
 * @param run - The run.
 * @returns `true` once it is no longer running.
 */
export function runIsOver(run: Pick<MigrationRun, 'status'>): boolean {
  return run.status !== 'running';
}

/**
 * How many records a run could not copy.
 *
 * @param run - The run.
 * @returns The failed count over every kind.
 */
export function failedCount(run: Pick<MigrationRun, 'kinds'>): number {
  return run.kinds.reduce((sum, row) => sum + row.failed, 0);
}

/**
 * The step a run opens on: a dry run fills **Choose**; a copy is watched on **Copy** until it has
 * copied everything, and then **Switch over** is next.
 *
 * @param run - The run.
 * @returns The step.
 */
export function stepForRun(run: MigrationRun): WizardStep {
  if (run.mode === 'dry-run') return 'choose';
  return run.status === 'completed' && failedCount(run) === 0 ? 'switch' : 'copy';
}

/**
 * Why the **Connect** step cannot go on yet, if it cannot.
 *
 * @param form - The step's fields.
 * @returns The sentence to show under the URL, or `null` when the URL can be tested.
 */
export function connectProblem(form: SourceForm): string | null {
  const text = form.source.trim();
  if (!text) return 'Enter the broker’s URL.';
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return 'Enter a full URL, starting with https://.';
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return 'The URL must start with http:// or https://.';
  if (url.username || url.password) return 'Leave the credentials out of the URL; enter them below.';
  return null;
}

/**
 * Whether the wizard holds the credentials a run of this kind was signed in with.
 *
 * @param form - The **Connect** step's fields.
 * @param kind - How the run signs in.
 * @returns `true` when a request can be sent (a source with no sign-in needs none).
 */
export function hasCredentials(form: SourceForm, kind: MigrationRun['auth_kind']): boolean {
  if (kind === 'none') return true;
  return kind === 'token' ? form.token.length > 0 : form.username.length > 0 || form.password.length > 0;
}

/**
 * The credentials part of a request.
 *
 * @param form - The **Connect** step's fields.
 * @returns `{ token }`, `{ username, password }`, or `{}` for a source with no sign-in.
 */
export function credentialsOf(form: SourceForm): { token?: string; username?: string; password?: string } {
  if (form.auth === 'token') return form.token ? { token: form.token } : {};
  if (!form.username && !form.password) return {};
  return { username: form.username, password: form.password };
}

// ---------------------------------------------------------------------------------------------
// The Choose step
// ---------------------------------------------------------------------------------------------

/** One tick box of **What to copy**. */
export interface ChoiceTile {
  id: string;
  label: string;
  /** The record kinds it stands for; none for **Labels and tags**, which is a switch of its own. */
  kinds: readonly MigrationKind[];
  /** A short note under the count. */
  note?: string;
}

/** The eight tiles, as the mockup lays them out. */
export const CHOICE_TILES: readonly ChoiceTile[] = [
  { id: 'pacticipants', label: 'Pacticipants', kinds: ['pacticipant'] },
  { id: 'versions', label: 'Versions', kinds: ['version'] },
  { id: 'pacts', label: 'Pacts', kinds: ['pact'] },
  { id: 'results', label: 'Verification results', kinds: ['verification'] },
  { id: 'environments', label: 'Environments', kinds: ['environment'] },
  { id: 'deployments', label: 'Deployments and releases', kinds: ['deployment', 'release'], note: 'what is current' },
  { id: 'webhooks', label: 'Webhooks', kinds: ['webhook'], note: 'off while a secret is waiting' },
  { id: 'labels', label: 'Labels and tags', kinds: [] },
];

/**
 * Whether a tile is ticked.
 *
 * @param options - The choices.
 * @param tile - The tile.
 * @returns `true` when everything it stands for is chosen.
 */
export function tileChecked(options: MigrationOptions, tile: ChoiceTile): boolean {
  if (tile.kinds.length === 0) return options.labels_and_tags;
  return tile.kinds.every((kind) => options.kinds.includes(kind));
}

/**
 * Tick or untick a tile.
 *
 * @param options - The choices.
 * @param tile - The tile.
 * @param on - Its new state.
 * @returns The new choices, the kinds in copying order.
 */
export function toggleTile(options: MigrationOptions, tile: ChoiceTile, on: boolean): MigrationOptions {
  if (tile.kinds.length === 0) return { ...options, labels_and_tags: on };
  const chosen = new Set(options.kinds);
  for (const kind of tile.kinds) {
    if (on) chosen.add(kind);
    else chosen.delete(kind);
  }
  const kinds = MIGRATION_KINDS.filter((kind) => chosen.has(kind));
  // Thinning versions needs versions; without them the choice falls back to "All".
  return { ...options, kinds, versions: kinds.includes('version') ? options.versions : 'all' };
}

/**
 * The number a tile shows: what the dry run counted at the source.
 *
 * @param run - The dry run (or any run).
 * @param tile - The tile.
 * @returns The count, or `null` when the run did not count it.
 */
export function tileCount(run: MigrationRun | null, tile: ChoiceTile): number | null {
  if (!run) return null;
  if (tile.kinds.length === 0) return run.facts.labels_and_tags ?? null;
  const rows = run.kinds.filter((row) => tile.kinds.includes(row.kind));
  return rows.length ? rows.reduce((sum, row) => sum + row.total, 0) : null;
}

/**
 * What already exists on both sides, from a dry run.
 *
 * @param run - The dry run.
 * @returns The sentence under the conflict policy.
 */
export function existingSentence(run: MigrationRun | null): string {
  if (!run || run.mode !== 'dry-run' || run.status !== 'completed') return '';
  const existing = run.kinds.filter((row) => row.exists > 0);
  if (existing.length === 0) return 'Nothing the source holds is in Apiome yet.';
  const parts = existing.map((row) => `${formatCount(row.exists)} ${KIND_LABELS[row.kind].toLowerCase()}`);
  return `${parts.join(', ')} exist on both sides. What matches is left as it is; the policy decides the rest.`;
}

/**
 * Why **Start copying** cannot be pressed, if it cannot.
 *
 * @param options - The choices.
 * @returns The reason, or `null`.
 */
export function chooseProblem(options: MigrationOptions): string | null {
  if (options.kinds.length === 0) return 'Tick at least one kind to copy.';
  if (!inRange(options.matrix_limit, MATRIX_LIMIT_RANGE)) {
    return `The matrix limit is a whole number from ${MATRIX_LIMIT_RANGE.min} to ${formatCount(MATRIX_LIMIT_RANGE.max)}.`;
  }
  if (!inRange(options.batch_bytes, BATCH_BYTES_RANGE)) {
    return `The batch size is a whole number of bytes from ${formatCount(BATCH_BYTES_RANGE.min)} to ${formatCount(BATCH_BYTES_RANGE.max)}.`;
  }
  return null;
}

/** Whether `value` is a whole number within `range`. */
function inRange(value: unknown, range: { min: number; max: number }): boolean {
  return typeof value === 'number' && Number.isInteger(value) && value >= range.min && value <= range.max;
}

/** One chip of the **Before you copy** strip. */
export interface MigrationWarning {
  id: string;
  tone: 'warn' | 'accent';
  label: string;
  title: string;
  /** The lines of the detail row. */
  lines: string[];
  /** Whether the detail links to **Settings → Secrets**. */
  secrets: boolean;
}

/** How each finding kind is named on its chip. */
const FINDING_LABELS: Readonly<Record<string, [singular: string, plural: string]>> = {
  webhook: ['webhook note', 'webhook notes'],
  secret: ['secret to re-enter', 'secrets to re-enter'],
  pacticipant: ['pacticipant note', 'pacticipant notes'],
  version: ['version note', 'version notes'],
  pact: ['pact note', 'pact notes'],
  verification: ['result note', 'result notes'],
  environment: ['environment note', 'environment notes'],
  deployment: ['deployment note', 'deployment notes'],
  release: ['release note', 'release notes'],
};

/** The most findings one detail row lists; the rest are counted and are in the report. */
export const MAX_WARNING_LINES = 8;

/**
 * The **Before you copy** strip: one chip per kind of finding, and one for what a migration never
 * reads. Every finding is in the downloaded report; a chip lists the first few and counts the rest.
 *
 * @param run - The dry run.
 * @returns The chips, the ones needing action first; empty while the run has nothing to say.
 */
export function migrationWarnings(run: MigrationRun | null): MigrationWarning[] {
  if (!run) return [];
  const byKind = new Map<string, MigrationFinding[]>();
  for (const finding of run.findings) {
    byKind.set(finding.kind, [...(byKind.get(finding.kind) ?? []), finding]);
  }
  const warnings: MigrationWarning[] = [];
  for (const [kind, findings] of byKind) {
    const [singular, plural] = FINDING_LABELS[kind] ?? [`${kind} note`, `${kind} notes`];
    const secrets = kind === 'secret' || findings.some((finding) => /secret|waiting for a value/i.test(finding.detail));
    const lines = findings.slice(0, MAX_WARNING_LINES).map((finding) => `${finding.subject}: ${finding.detail}`);
    if (findings.length > MAX_WARNING_LINES) {
      lines.push(`… and ${formatCount(findings.length - MAX_WARNING_LINES)} more, listed in the report.`);
    }
    warnings.push({
      id: kind,
      tone: secrets ? 'warn' : 'accent',
      label: `${formatCount(findings.length)} ${findings.length === 1 ? singular : plural}`,
      title: secrets ? 'Secrets cannot be read from a broker.' : 'Not carried over as it is.',
      lines,
      secrets,
    });
  }
  warnings.sort((a, b) => Number(b.tone === 'warn') - Number(a.tone === 'warn'));
  if (run.not_read.length) {
    warnings.push({
      id: 'not-read',
      tone: 'accent',
      label: 'Not copied',
      title: 'A migration never reads these from a source.',
      lines: [...run.not_read],
      secrets: false,
    });
  }
  return warnings;
}

// ---------------------------------------------------------------------------------------------
// The Copy step and the drawer
// ---------------------------------------------------------------------------------------------

/**
 * A whole number as the wizard shows it (`3,816`).
 *
 * @param value - The number.
 * @returns It with thousands separators, the same in every locale so fixtures and tests agree.
 */
export function formatCount(value: number): string {
  return Math.trunc(value).toLocaleString('en-US');
}

/**
 * The **Copied** cell of a kind: how many were written, of those the run means to write.
 *
 * @param row - The kind's counts.
 * @param running - Whether the run is still going.
 * @returns E.g. `612 / 1,284`, or `waiting` for a kind not reached yet.
 */
export function copiedCell(row: KindProgress, running: boolean): string {
  const wanted = Math.max(0, row.total - row.skipped - row.unchanged);
  if (running && row.done === 0 && row.total > 0) return 'waiting';
  return `${formatCount(row.copied)} / ${formatCount(wanted)}`;
}

/**
 * The **Skipped** cell of a kind: left behind by a choice or an earlier run, plus what Apiome
 * already has exactly as the source does.
 *
 * @param row - The kind's counts.
 * @returns The number and, when some were already there, how many.
 */
export function skippedCell(row: KindProgress): { count: number; note: string } {
  return {
    count: row.skipped + row.unchanged,
    note: row.unchanged > 0 ? `${formatCount(row.unchanged)} already here` : '',
  };
}

/** A badge: the status vocabulary's status and its label. */
export interface RunBadge {
  status: 'running' | 'passed' | 'failed' | 'warning' | 'neutral';
  label: string;
}

/**
 * How a run reads in **Past migrations** and at the top of the **Copy** step.
 *
 * @param run - The run.
 * @returns The badge.
 */
export function runBadge(run: MigrationRun): RunBadge {
  const dry = run.mode === 'dry-run';
  if (run.status === 'running') {
    const doing = run.stop_requested ? 'stopping' : run.phase === 'reading' ? 'reading' : dry ? 'checking' : 'copying';
    return { status: 'running', label: run.phase === 'reading' ? doing : `${doing} · ${run.percent}%` };
  }
  if (run.status === 'failed') return { status: 'failed', label: 'failed' };
  if (run.status === 'stopped') return { status: 'warning', label: 'stopped' };
  const failed = failedCount(run);
  if (failed > 0) return { status: 'warning', label: `${dry ? 'checked' : 'completed'} · ${formatCount(failed)} failed` };
  return { status: dry ? 'neutral' : 'passed', label: dry ? 'dry run' : 'completed' };
}

/**
 * Add newly read log lines to the ones shown.
 *
 * @param shown - The lines on screen.
 * @param incoming - The lines of the newest read (after the cursor, or the whole kept log).
 * @returns The lines in order, each once.
 */
export function mergeLog(shown: MigrationLogLine[], incoming: MigrationLogLine[]): MigrationLogLine[] {
  const last = shown.length ? shown[shown.length - 1].seq : 0;
  const fresh = incoming.filter((line) => line.seq > last);
  return fresh.length ? [...shown, ...fresh] : shown;
}

/**
 * The headline of the **Switch over** step.
 *
 * @param run - The finished copy.
 * @returns E.g. `Copied 5,202 records from acme.pactflow.io.`
 */
export function copiedHeadline(run: MigrationRun): string {
  const copied = run.kinds.reduce((sum, row) => sum + row.copied, 0);
  const already = run.kinds.reduce((sum, row) => sum + row.unchanged, 0);
  const tail = already > 0 ? ` ${formatCount(already)} were already here.` : '';
  return `Copied ${formatCount(copied)} ${copied === 1 ? 'record' : 'records'} from ${run.host}.${tail}`;
}

/**
 * The report **Download report** saves: the run as REST answered it, with the log on screen.
 *
 * @param run - The run.
 * @param log - The log lines the wizard has read.
 * @returns A JSON document; it holds no credential (a run never does).
 */
export function reportDocument(run: MigrationRun, log: MigrationLogLine[]): Record<string, unknown> {
  return {
    source: run.source,
    mode: run.mode,
    status: run.status,
    started_by: run.started_by,
    created_at: run.created_at,
    finished_at: run.finished_at,
    options: run.options,
    kinds: run.kinds,
    failures: run.failures,
    failures_not_listed: run.failures_dropped,
    not_portable: run.findings,
    not_read: run.not_read,
    log: log.map((line) => line.text),
  };
}

/**
 * The file name of a downloaded report.
 *
 * @param run - The run.
 * @returns E.g. `apiome-migration-acme.pactflow.io.json`.
 */
export function reportFileName(run: Pick<MigrationRun, 'host'>): string {
  return `apiome-migration-${run.host.replace(/[^A-Za-z0-9.-]+/g, '-') || 'report'}.json`;
}

// ---------------------------------------------------------------------------------------------
// The same, from anywhere
// ---------------------------------------------------------------------------------------------

/** Why the command cannot carry a wizard-only choice. */
const WIZARD_ONLY = 'apiome pact migrate copies everything the source returns; this choice is the wizard’s and the REST request’s.';

/**
 * The wizard's choices no `apiome pact migrate` flag carries.
 *
 * @param options - The choices.
 * @returns One entry per choice that differs from what the command does.
 */
function migrateUnsupported(options: MigrationOptions): PactUnsupported[] {
  const items: PactUnsupported[] = [];
  const left = CHOICE_TILES.filter((tile) => !tileChecked(options, tile)).map((tile) => tile.label);
  if (left.length) items.push({ what: `Not copying ${left.join(', ')}`, reason: WIZARD_ONLY, inRest: true });
  if (options.results !== 'all') {
    items.push({
      what: options.results === 'latest' ? 'Only the latest result of each pact' : 'No verification results',
      reason: WIZARD_ONLY,
      inRest: true,
    });
  }
  if (options.versions === 'kept') {
    items.push({ what: 'Only the versions clean-up would keep', reason: WIZARD_ONLY, inRest: true });
  }
  if (options.conflicts === 'replace') {
    items.push({
      what: 'Replace with the source’s on a conflict',
      reason: 'apiome pact migrate always keeps Apiome’s record and reports the conflict.',
      inRest: true,
    });
  }
  return items;
}

/**
 * The wizard as `apiome pact migrate` and as the REST request that starts the run.
 *
 * The source's token and password are written as `$PACT_SOURCE_BROKER_TOKEN` /
 * `$PACT_SOURCE_BROKER_PASSWORD` — the variables the command reads — never as themselves.
 *
 * @param form - The **Connect** step.
 * @param options - The **Choose** step.
 * @param mode - `dry-run` until the copy is started.
 * @param tenant - The workspace's handle, or empty to leave `{tenant}` in the REST path.
 * @returns The action for `pactCommandSurfaces`.
 */
export function migrateCommandAction(
  form: SourceForm,
  options: MigrationOptions,
  mode: MigrationRun['mode'],
  tenant = '',
): PactAction {
  const source = form.source.trim() || 'https://broker.example.com';
  const basic = form.auth === 'basic';
  const flags: PactOption[] = [
    { flag: '--from', value: source },
    ...(basic
      ? [
          { flag: '--username', value: form.username || '<username>' },
          { flag: '--password', value: form.password || 'password', secret: `${SOURCE_VARIABLE_PREFIX}PASSWORD` },
        ]
      : [{ flag: '--token', value: form.token || 'token', secret: `${SOURCE_VARIABLE_PREFIX}TOKEN` }]),
    { flag: '--dry-run', value: mode === 'dry-run' },
    { flag: '--restart', value: mode === 'copy' && options.restart },
    { flag: '--matrix-limit', value: options.matrix_limit === DEFAULT_MATRIX_LIMIT ? '' : String(options.matrix_limit) },
    { flag: '--batch-bytes', value: options.batch_bytes === DEFAULT_BATCH_BYTES ? '' : String(options.batch_bytes) },
  ];
  const body = {
    source,
    ...(basic ? { username: form.username || '<username>', password: form.password || 'password' } : { token: form.token || 'token' }),
    mode,
    options: mode === 'dry-run' ? undefined : options,
  };
  return {
    verb: 'migrate',
    options: flags,
    rest: {
      method: 'POST',
      path: tenantPath(tenant, `/${MIGRATION_PROXY_PATH}/runs`),
      body,
      variablePrefix: SOURCE_VARIABLE_PREFIX,
    },
    unsupported: mode === 'dry-run' ? [] : migrateUnsupported(options),
  };
}

// ---------------------------------------------------------------------------------------------
// Checking bodies before they are forwarded
// ---------------------------------------------------------------------------------------------

/** A checked body, or why it is refused. */
export type Checked = { ok: true; body: Record<string, unknown> } | { ok: false; error: string };

/** A run id as REST writes it. */
const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Whether a route segment can be a run id (anything else is a 404 without calling REST).
 *
 * @param value - The segment.
 * @returns `true` for a uuid.
 */
export function isRunId(value: string): boolean {
  return RUN_ID.test(value);
}

/** The fields that sign in to the source. */
const CREDENTIAL_FIELDS = ['token', 'username', 'password'] as const;
const OPTION_FIELDS: readonly string[] = Object.keys(DEFAULT_OPTIONS);

/** The record of a JSON object body, or `null`. */
function objectOf(body: unknown): Record<string, unknown> | null {
  return body && typeof body === 'object' && !Array.isArray(body) ? (body as Record<string, unknown>) : null;
}

/** Why the credential fields of `record` are refused, or `null`. */
function credentialProblem(record: Record<string, unknown>): string | null {
  for (const field of CREDENTIAL_FIELDS) {
    const value = record[field];
    if (value !== undefined && typeof value !== 'string') return `${field} is text.`;
  }
  if (record.token && (record.username || record.password)) return 'Send a token, or a username and password — not both.';
  return null;
}

/**
 * Check a resume: the source's credentials again, and nothing else.
 *
 * @param body - The parsed JSON.
 * @returns The body, or why it is refused.
 */
export function checkCredentialsBody(body: unknown): Checked {
  const record = objectOf(body);
  if (!record) return { ok: false, error: 'Send the credentials as a JSON object.' };
  const unknown = Object.keys(record).find((key) => !(CREDENTIAL_FIELDS as readonly string[]).includes(key));
  if (unknown !== undefined) return { ok: false, error: `Unsupported field ${unknown}.` };
  const problem = credentialProblem(record);
  return problem ? { ok: false, error: problem } : { ok: true, body: record };
}

/** Why `record.source` is refused, or `null`. */
function sourceProblem(record: Record<string, unknown>): string | null {
  if (typeof record.source !== 'string' || !record.source.trim()) return 'source is the broker’s URL.';
  return connectProblem({ ...EMPTY_SOURCE, source: record.source });
}

/**
 * Check a connection test: the source and its credentials.
 *
 * @param body - The parsed JSON.
 * @returns The body, or why it is refused.
 */
export function checkSourceBody(body: unknown): Checked {
  const record = objectOf(body);
  if (!record) return { ok: false, error: 'Send the source as a JSON object.' };
  const unknown = Object.keys(record).find((key) => key !== 'source' && !(CREDENTIAL_FIELDS as readonly string[]).includes(key));
  if (unknown !== undefined) return { ok: false, error: `Unsupported field ${unknown}.` };
  const problem = sourceProblem(record) ?? credentialProblem(record);
  return problem ? { ok: false, error: problem } : { ok: true, body: record };
}

/**
 * Check a run to start: the source, its credentials, the mode and the choices.
 *
 * @param body - The parsed JSON.
 * @returns The body, or why it is refused. The values of the choices are REST's to judge; a field
 *   REST does not know is refused here by name.
 */
export function checkStartBody(body: unknown): Checked {
  const record = objectOf(body);
  if (!record) return { ok: false, error: 'Send the run as a JSON object.' };
  const allowed = ['source', 'mode', 'options', ...CREDENTIAL_FIELDS];
  const unknown = Object.keys(record).find((key) => !allowed.includes(key));
  if (unknown !== undefined) return { ok: false, error: `Unsupported field ${unknown}.` };
  const problem = sourceProblem(record) ?? credentialProblem(record);
  if (problem) return { ok: false, error: problem };
  if (record.mode !== 'dry-run' && record.mode !== 'copy') return { ok: false, error: 'mode is dry-run or copy.' };
  if (record.options !== undefined) {
    const options = objectOf(record.options);
    if (!options) return { ok: false, error: 'options is a JSON object.' };
    const stray = Object.keys(options).find((key) => !OPTION_FIELDS.includes(key));
    if (stray !== undefined) return { ok: false, error: `Unsupported option ${stray}.` };
  }
  return { ok: true, body: record };
}

/**
 * The `after` cursor of a run read.
 *
 * @param search - The browser's query string.
 * @returns The cursor (0 when absent), or the 400's message for anything else.
 */
export function readCursor(search: URLSearchParams): { ok: true; after: number } | { ok: false; error: string } {
  const [stray] = [...search.keys()].filter((key) => key !== 'after');
  if (stray !== undefined) return { ok: false, error: `Unsupported parameter ${stray}: a run read takes after.` };
  const raw = search.get('after');
  if (raw === null) return { ok: true, after: 0 };
  if (!/^\d{1,9}$/.test(raw)) return { ok: false, error: 'after is a whole number: the last log line you have.' };
  return { ok: true, after: Number(raw) };
}

/**
 * When a run was started, as **Past migrations** shows it.
 *
 * @param iso - The run's `created_at`.
 * @returns E.g. `27 Nov 2026, 14:21 UTC` — in UTC, so everyone in the workspace reads the same time.
 */
export function formatWhen(iso: string | null): string {
  const moment = iso ? new Date(iso) : null;
  if (!moment || Number.isNaN(moment.getTime())) return '—';
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const two = (value: number) => String(value).padStart(2, '0');
  return `${moment.getUTCDate()} ${months[moment.getUTCMonth()]} ${moment.getUTCFullYear()}, ${two(moment.getUTCHours())}:${two(moment.getUTCMinutes())} UTC`;
}
