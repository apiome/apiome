/**
 * The matrix and can-i-deploy console — PFX-5.4 (#6948).
 *
 * The pure rules behind two pages of the **Contracts** area:
 *
 * * **Matrix** (`/ade/dashboard/pacts/matrix`) — a query builder for the Pact Broker's
 *   `GET /matrix` (selectors, `latestby`, a row limit), the grid of consumer versions × provider
 *   versions it answers with, every row in a table, and the verdict explained.
 * * **Can I deploy** (`/ade/dashboard/pacts/can-i-deploy`) — `GET /can-i-deploy` (`pacticipant`,
 *   `version`, `toEnvironment` or `to`, `ignore`) with the verdict explained, the rows it was
 *   reached from, and the CLI command that asks the same question in a pipeline.
 *
 * The page address carries the query, so a query can be shared and reloaded. The matrix numbers
 * its selectors (`q[0][pacticipant]=…&q[0][latest]=true`): the broker reads that form exactly as
 * it reads unnumbered `q[][…]`, and it survives a server page's search parameters (which do not
 * keep the order of different keys).
 *
 * The `/api/pact/matrix` and `/api/pact/can-i-deploy` proxies read the browser's query with
 * {@link parseMatrixQuery} / {@link parseCanIDeployQuery} and forward only what those return:
 * an unknown, repeated, empty or oversized parameter, or a selector the broker would refuse, is
 * a 400 that names it — never dropped.
 */

import { MAX_FILTER_LENGTH } from '@lib/pact-pacticipants';
import { lastSegment } from '@lib/pact-detail';

// --- routes ------------------------------------------------------------------------------------

/** The route of the matrix page. */
export const MATRIX_ROUTE = '/ade/dashboard/pacts/matrix';

/** The route of the can-i-deploy page. */
export const CAN_I_DEPLOY_ROUTE = '/ade/dashboard/pacts/can-i-deploy';

/** The REST path of the broker matrix (below `/v1/tenants/{slug}`). */
export const MATRIX_PROXY_PATH = 'pact-broker/matrix';

/** The REST path of the broker can-i-deploy (below `/v1/tenants/{slug}`). */
export const CAN_I_DEPLOY_PROXY_PATH = 'pact-broker/can-i-deploy';

// --- the matrix query ----------------------------------------------------------------------------

/** Which versions of a pacticipant a selector names. */
export type SelectorScope =
  /** Every version. */
  | 'all'
  /** Its latest version. */
  | 'latest'
  /** Exactly one version. */
  | 'version'
  /** Versions recorded on a branch. */
  | 'branch'
  /** Versions with a tag. */
  | 'tag'
  /** Versions deployed to, or released and supported in, an environment. */
  | 'environment'
  /** Versions on its main branch. */
  | 'main-branch';

/** The scopes in the order the builder offers them, with their labels. */
export const SELECTOR_SCOPES: { scope: SelectorScope; label: string }[] = [
  { scope: 'latest', label: 'Latest version' },
  { scope: 'version', label: 'Version' },
  { scope: 'branch', label: 'Branch' },
  { scope: 'main-branch', label: 'Main branch' },
  { scope: 'tag', label: 'Tag' },
  { scope: 'environment', label: 'Environment' },
  { scope: 'all', label: 'All versions' },
];

/** Whether a scope takes a value (the version number, branch, tag or environment). */
export function scopeTakesValue(scope: SelectorScope): boolean {
  return scope === 'version' || scope === 'branch' || scope === 'tag' || scope === 'environment';
}

/** Whether a scope can be narrowed to its latest version (`q[][latest]=true`). */
export function scopeTakesLatest(scope: SelectorScope): boolean {
  return scope === 'branch' || scope === 'tag' || scope === 'main-branch';
}

/** One selector of the builder: a pacticipant and which of its versions. */
export interface MatrixSelector {
  /** The pacticipant's name or handle. */
  pacticipant: string;
  scope: SelectorScope;
  /** The version number, branch, tag or environment; empty for the other scopes. */
  value: string;
  /** Only the latest of the versions on the branch / with the tag / on the main branch. */
  latest: boolean;
}

/** How the matrix collapses rows (`latestby`), or `null` for every result. */
export type LatestBy = 'cvp' | 'cvpv' | 'cp';

/** The `latestby` choices in the order the builder offers them, with their labels. */
export const LATEST_BY_OPTIONS: { value: LatestBy | null; label: string }[] = [
  { value: 'cvp', label: 'Latest result per consumer version and provider' },
  { value: 'cvpv', label: 'Latest result per consumer version and provider version' },
  { value: 'cp', label: 'Latest result per consumer and provider' },
  { value: null, label: 'Every result' },
];

/** A whole matrix query. */
export interface MatrixQuery {
  selectors: MatrixSelector[];
  latestby: LatestBy | null;
  limit: number;
}

/** The most selectors a query may have. */
export const MAX_SELECTORS = 10;

/** The row limits the builder offers (REST's maximum is 1000). */
export const MATRIX_LIMITS = [100, 500, 1000] as const;

/** The row limit when none is given (REST's default). */
export const DEFAULT_MATRIX_LIMIT = 100;

/** The largest row limit REST accepts. */
export const MAX_MATRIX_LIMIT = 1000;

/** A new, empty selector. */
export function emptySelector(): MatrixSelector {
  return { pacticipant: '', scope: 'latest', value: '', latest: false };
}

/** The query a fresh builder starts from. */
export function emptyMatrixQuery(): MatrixQuery {
  return { selectors: [emptySelector()], latestby: 'cvp', limit: DEFAULT_MATRIX_LIMIT };
}

/** The selector keys the broker reads, by the scope they set. */
const SCOPE_KEYS: Record<Exclude<SelectorScope, 'all' | 'latest'>, string> = {
  version: 'version',
  branch: 'branch',
  tag: 'tag',
  environment: 'environment',
  'main-branch': 'mainBranch',
};

/** Every key a selector may carry. */
const SELECTOR_KEYS = [
  'pacticipant',
  'version',
  'latest',
  'branch',
  'tag',
  'environment',
  'mainBranch',
];

/** `q[3][pacticipant]` → index and key. */
const NUMBERED_KEY = /^q\[(\d{1,2})\]\[([A-Za-z]+)\]$/;

/**
 * The broker query of a matrix query, selectors numbered from 0.
 *
 * @param query - The query (its selectors already checked by {@link matrixQueryProblem}).
 * @returns E.g. `q[0][pacticipant]=billing-service&q[0][latest]=true&latestby=cvp&limit=100`.
 */
export function matrixQueryParams(query: MatrixQuery): URLSearchParams {
  const params = new URLSearchParams();
  query.selectors.forEach((selector, index) => {
    const at = (key: string) => `q[${index}][${key}]`;
    params.append(at('pacticipant'), selector.pacticipant.trim());
    if (selector.scope === 'latest') params.append(at('latest'), 'true');
    else if (selector.scope === 'main-branch') params.append(at('mainBranch'), 'true');
    else if (selector.scope !== 'all')
      params.append(at(SCOPE_KEYS[selector.scope]), selector.value.trim());
    if (scopeTakesLatest(selector.scope) && selector.latest) params.append(at('latest'), 'true');
  });
  if (query.latestby) params.append('latestby', query.latestby);
  params.append('limit', String(query.limit));
  return params;
}

/**
 * Why the builder's query cannot be sent yet, or `null` when it can. The same rules the proxy
 * applies, said in the builder's words.
 *
 * @param query - The builder's query.
 * @returns The first problem, e.g. `Selector 2: choose a pacticipant.`
 */
export function matrixQueryProblem(query: MatrixQuery): string | null {
  if (query.selectors.length === 0)
    return 'Add a selector: the matrix needs at least one pacticipant.';
  if (query.selectors.length > MAX_SELECTORS)
    return `A query has at most ${MAX_SELECTORS} selectors.`;
  for (const [index, selector] of query.selectors.entries()) {
    const label = `Selector ${index + 1}`;
    const name = selector.pacticipant.trim();
    if (!name) return `${label}: choose a pacticipant.`;
    if (name.length > MAX_FILTER_LENGTH)
      return `${label}: the pacticipant is longer than ${MAX_FILTER_LENGTH} characters.`;
    if (scopeTakesValue(selector.scope)) {
      const value = selector.value.trim();
      const what = SELECTOR_SCOPES.find(
        (entry) => entry.scope === selector.scope,
      )?.label.toLowerCase();
      if (!value) return `${label}: enter the ${what}.`;
      if (value.length > MAX_FILTER_LENGTH)
        return `${label}: the ${what} is longer than ${MAX_FILTER_LENGTH} characters.`;
    }
  }
  return null;
}

/** A query read from an address, or why it cannot be read. */
export type ParsedMatrixQuery = { ok: true; query: MatrixQuery } | { ok: false; error: string };

/**
 * Read a matrix query from the page address or a proxy request. Strict: every parameter is
 * accounted for or the reason is returned.
 *
 * @param params - The query string.
 * @returns The query (no selectors when the address has none), or the reason it cannot be read.
 */
export function parseMatrixQuery(params: URLSearchParams): ParsedMatrixQuery {
  const entries = new Map<number, Map<string, string>>();
  let latestby: LatestBy | null = null;
  let limit = DEFAULT_MATRIX_LIMIT;
  const seen = new Set<string>();
  for (const [key, raw] of params.entries()) {
    if (seen.has(key)) return { ok: false, error: `The ${key} parameter is given more than once.` };
    seen.add(key);
    const value = raw.trim();
    if (key === 'latestby') {
      if (!LATEST_BY_OPTIONS.some((option) => option.value === value)) {
        return { ok: false, error: 'latestby must be one of cvp, cvpv, cp.' };
      }
      latestby = value as LatestBy;
      continue;
    }
    if (key === 'limit') {
      const number = /^\d{1,4}$/.test(value) ? Number(value) : NaN;
      if (!(number >= 1 && number <= MAX_MATRIX_LIMIT)) {
        return {
          ok: false,
          error: `The limit must be a whole number from 1 to ${MAX_MATRIX_LIMIT}.`,
        };
      }
      limit = number;
      continue;
    }
    const match = NUMBERED_KEY.exec(key);
    if (!match) {
      if (key.startsWith('q[]')) {
        return {
          ok: false,
          error: `Number each selector: ${key.replace('q[]', 'q[0]')}, q[1][…] and so on.`,
        };
      }
      return {
        ok: false,
        error: `Unsupported parameter ${key}: the matrix accepts q[N][pacticipant] (with version, latest, branch, tag, environment or mainBranch), latestby and limit.`,
      };
    }
    const index = Number(match[1]);
    const field = match[2];
    if (index >= MAX_SELECTORS)
      return {
        ok: false,
        error: `A query has at most ${MAX_SELECTORS} selectors (q[0] to q[${MAX_SELECTORS - 1}]).`,
      };
    if (!SELECTOR_KEYS.includes(field)) {
      return {
        ok: false,
        error: `Unsupported selector key ${key}: a selector takes ${SELECTOR_KEYS.join(', ')}.`,
      };
    }
    if (!value) return { ok: false, error: `${key} is empty.` };
    if (value.length > MAX_FILTER_LENGTH)
      return { ok: false, error: `${key} is longer than ${MAX_FILTER_LENGTH} characters.` };
    if (!entries.has(index)) entries.set(index, new Map());
    entries.get(index)!.set(field, value);
  }
  const selectors: MatrixSelector[] = [];
  for (let index = 0; index < entries.size; index += 1) {
    const entry = entries.get(index);
    if (!entry)
      return {
        ok: false,
        error: `Selectors are numbered from 0 without gaps: q[${index}] is missing.`,
      };
    const read = selectorFrom(entry, index);
    if (typeof read === 'string') return { ok: false, error: read };
    selectors.push(read);
  }
  return { ok: true, query: { selectors, latestby, limit } };
}

/**
 * One numbered selector, or why the broker would refuse it.
 *
 * @param entry - Its keys and values.
 * @param index - Its number.
 * @returns The selector, or the reason.
 */
function selectorFrom(entry: Map<string, string>, index: number): MatrixSelector | string {
  const at = (key: string) => `q[${index}][${key}]`;
  const pacticipant = entry.get('pacticipant');
  if (!pacticipant) return `Selector ${index} has no pacticipant (${at('pacticipant')}).`;
  for (const flag of ['latest', 'mainBranch']) {
    const value = entry.get(flag);
    if (value !== undefined && value !== 'true') return `${at(flag)} must be true.`;
  }
  const narrowing = ['version', 'branch', 'tag', 'environment', 'mainBranch'].filter((key) =>
    entry.has(key),
  );
  if (narrowing.length > 1) {
    return `Selector ${index} combines ${narrowing.join(' and ')}: give one of version, branch, tag, environment or mainBranch.`;
  }
  const latest = entry.has('latest');
  const [key] = narrowing;
  if (latest && (key === 'version' || key === 'environment')) {
    return `Selector ${index}: latest cannot be combined with ${key}.`;
  }
  if (!key) return { pacticipant, scope: latest ? 'latest' : 'all', value: '', latest: false };
  const scope = (Object.keys(SCOPE_KEYS) as (keyof typeof SCOPE_KEYS)[]).find(
    (name) => SCOPE_KEYS[name] === key,
  )!;
  return { pacticipant, scope, value: key === 'mainBranch' ? '' : entry.get(key)!, latest };
}

/**
 * Read a server page's search parameters into a `URLSearchParams` (a repeated key keeps every
 * value).
 *
 * @param search - Next's `searchParams` record.
 * @returns The parameters.
 */
export function searchParamsFrom(
  search: Record<string, string | string[] | undefined>,
): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    if (Array.isArray(value)) value.forEach((item) => params.append(key, item));
    else if (value !== undefined) params.append(key, value);
  }
  return params;
}

/**
 * What a selector names, in a sentence fragment.
 *
 * @param selector - The selector.
 * @returns E.g. `the latest version of billing-service on branch main`.
 */
export function describeSelector(selector: MatrixSelector): string {
  const name = selector.pacticipant;
  const latest = selector.latest ? 'the latest version of ' : 'versions of ';
  switch (selector.scope) {
    case 'all':
      return `every version of ${name}`;
    case 'latest':
      return `the latest version of ${name}`;
    case 'version':
      return `${name} ${selector.value}`;
    case 'branch':
      return `${latest}${name} on branch ${selector.value}`;
    case 'tag':
      return `${latest}${name} tagged ${selector.value}`;
    case 'environment':
      return `the versions of ${name} in ${selector.value}`;
    case 'main-branch':
      return `${latest}${name} on its main branch`;
  }
}

// --- the can-i-deploy query ------------------------------------------------------------------------

/** Where a version is being deployed. */
export interface DeployDestination {
  /** `environment` (`toEnvironment`) or `tag` (`to`, the legacy form). */
  kind: 'environment' | 'tag';
  name: string;
}

/** A whole can-i-deploy question. */
export interface CanIDeployQuery {
  pacticipant: string;
  version: string;
  destination: DeployDestination;
  /** Pacticipants whose rows do not count. */
  ignore: string[];
}

/** The most pacticipants a question may ignore. */
export const MAX_IGNORED = 10;

/** The parameters `/can-i-deploy` accepts. */
const CAN_I_DEPLOY_KEYS = ['pacticipant', 'version', 'toEnvironment', 'to', 'ignore'];

/** A question read from an address, or why it cannot be read. */
export type ParsedCanIDeployQuery =
  { ok: true; query: CanIDeployQuery } | { ok: false; error: string };

/** The can-i-deploy form, as far as the address fills it (any field may be empty). */
export interface CanIDeployForm {
  pacticipant: string;
  version: string;
  kind: 'environment' | 'tag';
  destination: string;
  ignore: string[];
}

/**
 * Read a can-i-deploy question. Strict: every parameter is accounted for or the reason is
 * returned.
 *
 * @param params - The query string.
 * @returns The question, or the reason it cannot be asked.
 */
export function parseCanIDeployQuery(params: URLSearchParams): ParsedCanIDeployQuery {
  const single = new Map<string, string>();
  const ignore: string[] = [];
  for (const [key, raw] of params.entries()) {
    const value = raw.trim();
    if (!CAN_I_DEPLOY_KEYS.includes(key)) {
      return {
        ok: false,
        error: `Unsupported parameter ${key}: can-i-deploy accepts ${CAN_I_DEPLOY_KEYS.join(', ')}.`,
      };
    }
    if (!value) return { ok: false, error: `The ${key} parameter is empty.` };
    if (value.length > MAX_FILTER_LENGTH) {
      return {
        ok: false,
        error: `The ${key} parameter is longer than ${MAX_FILTER_LENGTH} characters.`,
      };
    }
    if (key === 'ignore') {
      if (ignore.includes(value))
        return { ok: false, error: `${value} is ignored more than once.` };
      ignore.push(value);
      continue;
    }
    if (single.has(key))
      return { ok: false, error: `The ${key} parameter is given more than once.` };
    single.set(key, value);
  }
  if (ignore.length > MAX_IGNORED)
    return { ok: false, error: `At most ${MAX_IGNORED} pacticipants can be ignored.` };
  const pacticipant = single.get('pacticipant');
  const version = single.get('version');
  if (!pacticipant)
    return { ok: false, error: 'Choose the pacticipant being deployed (pacticipant).' };
  if (!version) return { ok: false, error: 'Enter the version being deployed (version).' };
  const environment = single.get('toEnvironment');
  const tag = single.get('to');
  if (environment && tag)
    return { ok: false, error: 'Give an environment (toEnvironment) or a tag (to), not both.' };
  if (!environment && !tag)
    return {
      ok: false,
      error: 'Choose where it is deployed: an environment (toEnvironment) or a tag (to).',
    };
  if (ignore.includes(pacticipant))
    return {
      ok: false,
      error: `${pacticipant} is the pacticipant being deployed; it cannot be ignored.`,
    };
  return {
    ok: true,
    query: {
      pacticipant,
      version,
      destination: environment
        ? { kind: 'environment', name: environment }
        : { kind: 'tag', name: tag! },
      ignore,
    },
  };
}

/**
 * The form an address fills, leniently: an unknown parameter is left to {@link parseCanIDeployQuery}
 * to report.
 *
 * @param params - The page's query string.
 * @returns The form.
 */
export function canIDeployFormFrom(params: URLSearchParams): CanIDeployForm {
  const tag = params.get('to')?.trim() ?? '';
  const environment = params.get('toEnvironment')?.trim() ?? '';
  return {
    pacticipant: params.get('pacticipant')?.trim() ?? '',
    version: params.get('version')?.trim() ?? '',
    kind: tag && !environment ? 'tag' : 'environment',
    destination: tag && !environment ? tag : environment,
    ignore: params
      .getAll('ignore')
      .map((value) => value.trim())
      .filter(Boolean),
  };
}

/**
 * The query string of a can-i-deploy form (empty fields left out).
 *
 * @param form - The form.
 * @returns E.g. `pacticipant=billing-service&version=2.0.0&toEnvironment=production`.
 */
export function canIDeployParams(form: CanIDeployForm): URLSearchParams {
  const params = new URLSearchParams();
  if (form.pacticipant.trim()) params.append('pacticipant', form.pacticipant.trim());
  if (form.version.trim()) params.append('version', form.version.trim());
  if (form.destination.trim())
    params.append(form.kind === 'environment' ? 'toEnvironment' : 'to', form.destination.trim());
  form.ignore.forEach((name) => params.append('ignore', name));
  return params;
}

/**
 * Quote a value for a POSIX shell.
 *
 * @param value - The value.
 * @returns It unquoted when it is plain (letters, digits, `._-/:@+=`), single-quoted otherwise.
 */
export function shellQuote(value: string): string {
  return /^[A-Za-z0-9._\-/:@+=]+$/.test(value) ? value : `'${value.replace(/'/g, `'\\''`)}'`;
}

/**
 * The `apiome pact can-i-deploy` command that asks the same question in a pipeline. It reads the
 * broker URL and key from `PACT_BROKER_BASE_URL` / `PACT_BROKER_TOKEN` (or `APIOME_*`), and exits
 * like `pact-broker can-i-deploy`.
 *
 * @param query - The question.
 * @returns The command, one flag per line.
 */
export function canIDeployCommand(query: CanIDeployQuery): string {
  const lines = [
    'apiome pact can-i-deploy',
    `  --pacticipant ${shellQuote(query.pacticipant)}`,
    `  --version ${shellQuote(query.version)}`,
    query.destination.kind === 'environment'
      ? `  --to-environment ${shellQuote(query.destination.name)}`
      : `  --to ${shellQuote(query.destination.name)}`,
    ...query.ignore.map((name) => `  --ignore ${shellQuote(name)}`),
  ];
  return lines.join(' \\\n');
}

/** The command an empty can-i-deploy page shows. */
export const CAN_I_DEPLOY_SNIPPET = [
  'apiome pact can-i-deploy \\',
  '  --pacticipant billing-service \\',
  '  --version "$GIT_COMMIT" \\',
  '  --to-environment production',
].join('\n');

// --- the answer -------------------------------------------------------------------------------------

/** `true`, `false`, or `null` while a verification result is missing. */
export type Deployable = boolean | null;

/** The verdict line of a matrix answer. */
export interface MatrixSummary {
  deployable: Deployable;
  /** The broker's sentence. */
  reason: string;
  success: number;
  failed: number;
  unknown: number;
}

/** One notice: why the verdict reads as it does. */
export interface MatrixNotice {
  /** `success`, `error` or `warning` (another type is kept as it came). */
  type: string;
  /** Apiome's code, e.g. `verification-failed`; `null` when REST gave none. */
  code: string | null;
  text: string;
}

/** One side of a matrix row. */
export interface MatrixSide {
  name: string;
  /** The handle (from the row's link), or `null` when the link is missing. */
  slug: string | null;
  /** The version number; a provider has none when the pact has no result. */
  version: string | null;
  branch: string | null;
}

/** One verification result, as a matrix row carries it. */
export interface MatrixVerification {
  success: boolean;
  verifiedAt: string | null;
  /** `native` (a Pact verifier) or `bidirectional` (Apiome's comparison). */
  kind: string;
  pending: boolean | null;
  wip: boolean;
  /** For a bi-directional result: whether the provider contract had passing evidence. */
  providerContractVerified: boolean | null;
}

/** One matrix row. */
export interface MatrixRow {
  consumer: MatrixSide;
  provider: MatrixSide;
  publishedAt: string | null;
  verification: MatrixVerification | null;
  /** Apiome's reason: `verified`, `verification-failed`, `pact-pending` or `no-verification-result`. */
  reason: { code: string; text: string };
  /** An `ignore` selector covered the row: it does not count towards the verdict. */
  ignored: boolean;
}

/** What `/api/pact/matrix` and `/api/pact/can-i-deploy` answer, read. */
export interface MatrixAnswer {
  summary: MatrixSummary;
  notices: MatrixNotice[];
  rows: MatrixRow[];
  /** Seconds REST asks to wait before asking again (only while the verdict is unknown). */
  retryAfterSeconds: number | null;
}

/** A plain object, or an empty one. */
function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** A string field, or `null`. */
function text(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

/** A count field, or 0. */
function count(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/** Read one side of a row. */
function side(value: unknown): MatrixSide {
  const entry = record(value);
  const version = entry.version === null ? null : record(entry.version);
  return {
    name: text(entry.name) ?? '',
    slug: lastSegment(text(record(record(entry._links).self).href)),
    version: version ? text(version.number) : null,
    branch: version ? text(version.branch) : null,
  };
}

/** Read one row; a row without a consumer version is not a row. */
function matrixRow(value: unknown): MatrixRow | null {
  const row = record(value);
  const consumer = side(row.consumer);
  if (consumer.version === null) return null;
  const result = row.verificationResult === null ? null : record(row.verificationResult);
  const verification: MatrixVerification | null =
    result && typeof result.success === 'boolean'
      ? {
          success: result.success,
          verifiedAt: text(result.verifiedAt),
          kind: text(result.kind) ?? 'native',
          pending: typeof result.pending === 'boolean' ? result.pending : null,
          wip: result.wip === true,
          providerContractVerified:
            typeof result.providerContractVerified === 'boolean'
              ? result.providerContractVerified
              : null,
        }
      : null;
  const reason = record(row.reason);
  const fallback =
    verification === null
      ? 'no-verification-result'
      : verification.success
        ? 'verified'
        : 'verification-failed';
  const code = text(reason.code) ?? fallback;
  return {
    consumer,
    provider: side(row.provider),
    publishedAt: text(record(row.pact).createdAt),
    verification,
    reason: { code, text: text(reason.text) ?? code.replace(/-/g, ' ') },
    ignored: row.ignored === true,
  };
}

/**
 * Read a matrix document (and the proxy's `retryAfterSeconds`).
 *
 * @param body - The proxy's answer.
 * @returns The answer; missing fields read as empty, never as a verdict.
 */
export function parseMatrixAnswer(body: unknown): MatrixAnswer {
  const document = record(body);
  const summary = record(document.summary);
  const deployable =
    summary.deployable === true ? true : summary.deployable === false ? false : null;
  const retry = document.retryAfterSeconds;
  return {
    summary: {
      deployable,
      reason: text(summary.reason) ?? '',
      success: count(summary.success),
      failed: count(summary.failed),
      unknown: count(summary.unknown),
    },
    notices: (Array.isArray(document.notices) ? document.notices : []).map((entry) => {
      const notice = record(entry);
      return {
        type: text(notice.type) ?? 'info',
        code: text(notice.code),
        text: text(notice.text) ?? '',
      };
    }),
    rows: (Array.isArray(document.matrix) ? document.matrix : [])
      .map(matrixRow)
      .filter((row): row is MatrixRow => row !== null),
    retryAfterSeconds: typeof retry === 'number' && retry > 0 ? retry : null,
  };
}

/**
 * Read REST's `Retry-After` header (seconds; an HTTP date is not used by REST).
 *
 * @param header - The header's value.
 * @returns The seconds, or `null`.
 */
export function retryAfterSeconds(header: string | null): number | null {
  if (!header || !/^\d{1,6}$/.test(header.trim())) return null;
  const seconds = Number(header.trim());
  return seconds > 0 ? seconds : null;
}

// --- the verdict, explained -------------------------------------------------------------------------

/** How a verdict is drawn. */
export type VerdictTone = 'ok' | 'danger' | 'warn';

/**
 * The headline of a verdict.
 *
 * @param deployable - `summary.deployable`.
 * @returns The words and the tone.
 */
export function verdictHeadline(deployable: Deployable): { label: string; tone: VerdictTone } {
  if (deployable === true) return { label: 'Yes — deployable', tone: 'ok' };
  if (deployable === false) return { label: 'No — not deployable', tone: 'danger' };
  return { label: 'Not known yet', tone: 'warn' };
}

/**
 * The counts of a verdict as a line.
 *
 * @param summary - The verdict.
 * @returns E.g. `2 verified · 1 failed · 0 unknown`.
 */
export function countsLine(summary: MatrixSummary): string {
  return `${summary.success} verified · ${summary.failed} failed · ${summary.unknown} unknown`;
}

/** What to do about each notice (by code); a code not listed has no hint. */
export const NOTICE_HINTS: Record<string, string> = {
  'verification-failed':
    'Fix the provider or change the consumer’s pact, then verify again. Open the row’s pact to see which interactions it holds.',
  'pact-pending':
    'A pending pact never failed the provider’s build. Verify it successfully on the provider’s branch to take it out of pending.',
  'no-verification-result':
    'Run the provider’s verification against this pact and publish the result (apiome pact verify, or a Pact verifier with publishVerificationResult).',
  'no-pact':
    'The environment requires a contract: publish a pact for this version (apiome pact publish) before deploying it.',
  'version-not-found':
    'Record the version first — publishing a pact or a verification result records it — or check its number.',
  'provider-contract-unverified':
    'Publish passing self-verification evidence for the provider contract (apiome pact publish-provider-contract --evidence …).',
  'cannot-ignore': 'Check the ignored pacticipant’s name: nothing it names is in the matrix.',
};

/** The notices grouped by what they mean for the verdict. */
export interface VerdictExplanation {
  /** Errors: each one blocks or leaves the verdict unknown. */
  blocking: MatrixNotice[];
  warnings: MatrixNotice[];
  /** Success notices (why it is deployable). */
  passing: MatrixNotice[];
  /** Notices of a type the page does not know — kept, never dropped. */
  other: MatrixNotice[];
  /** Rows that count towards the verdict. */
  considered: number;
  /** Rows an `ignore` covered. */
  ignored: number;
}

/**
 * Group an answer's notices and count its rows.
 *
 * @param answer - The answer.
 * @returns The explanation.
 */
export function explainVerdict(answer: MatrixAnswer): VerdictExplanation {
  const of = (type: string) => answer.notices.filter((notice) => notice.type === type);
  return {
    blocking: of('error'),
    warnings: of('warning'),
    passing: of('success'),
    other: answer.notices.filter(
      (notice) => !['error', 'warning', 'success'].includes(notice.type),
    ),
    considered: answer.rows.filter((row) => !row.ignored).length,
    ignored: answer.rows.filter((row) => row.ignored).length,
  };
}

/**
 * Whether the answer holds as many rows as were asked for, so some may be missing.
 *
 * @param answer - The answer.
 * @param limit - The row limit the query was sent with.
 * @returns True when the rows may be cut short.
 */
export function rowsMayBeTruncated(answer: MatrixAnswer, limit: number): boolean {
  return answer.rows.length >= limit;
}

// --- the grid -------------------------------------------------------------------------------------

/** How a row's reason is drawn: a mark, a tone and a short label. */
export interface ReasonLook {
  mark: string;
  tone: 'ok' | 'danger' | 'warn' | 'muted';
  label: string;
}

/** The look of each row reason; {@link reasonLook} covers a code not listed. */
const REASON_LOOKS: Record<string, ReasonLook> = {
  verified: { mark: '✓', tone: 'ok', label: 'Verified' },
  'verification-failed': { mark: '✕', tone: 'danger', label: 'Failed' },
  'pact-pending': { mark: '!', tone: 'warn', label: 'Pending' },
  'no-verification-result': { mark: '?', tone: 'muted', label: 'No result' },
};

/**
 * How a row reason is drawn.
 *
 * @param code - The row's reason code.
 * @returns Its look; an unknown code is a muted `•` labelled with the code.
 */
export function reasonLook(code: string): ReasonLook {
  return REASON_LOOKS[code] ?? { mark: '•', tone: 'muted', label: code };
}

/** One column (provider version) or row (consumer version) of the grid. */
export interface GridAxisEntry {
  key: string;
  name: string;
  slug: string | null;
  /** `null` for the provider column of pacts without a result. */
  version: string | null;
}

/** One cell: the newest row of its pair, and how many rows the pair has. */
export interface GridCell {
  row: MatrixRow;
  count: number;
}

/** The grid of consumer versions × provider versions. */
export interface MatrixGrid {
  consumers: GridAxisEntry[];
  providers: GridAxisEntry[];
  /** By {@link gridCellKey}. */
  cells: Map<string, GridCell>;
  /** Consumer versions past the grid's limit (every row is still in the table). */
  hiddenConsumers: number;
  /** Provider versions past the grid's limit. */
  hiddenProviders: number;
}

/** How many consumer versions, and how many provider versions, the grid draws at most. */
export const GRID_AXIS_LIMIT = 20;

/** The key of an axis entry. */
function axisKey(side: MatrixSide): string {
  return `${side.slug ?? side.name}@${side.version ?? ''}`;
}

/** The key of a cell. */
export function gridCellKey(consumer: GridAxisEntry, provider: GridAxisEntry): string {
  return `${consumer.key}→${provider.key}`;
}

/**
 * Lay the rows out as a grid: consumer versions down, provider versions across, in the order the
 * matrix returned them. Each cell is the newest result of its pair (by `verifiedAt`); a pact
 * without a result sits in its provider's *no result* column.
 *
 * @param rows - The rows (considered and ignored).
 * @param axisLimit - The most entries per axis.
 * @returns The grid.
 */
export function buildMatrixGrid(rows: MatrixRow[], axisLimit = GRID_AXIS_LIMIT): MatrixGrid {
  const consumers = new Map<string, GridAxisEntry>();
  const providers = new Map<string, GridAxisEntry>();
  const cells = new Map<string, GridCell>();
  for (const row of rows) {
    const consumer = {
      key: axisKey(row.consumer),
      name: row.consumer.name,
      slug: row.consumer.slug,
      version: row.consumer.version,
    };
    const provider = {
      key: axisKey(row.provider),
      name: row.provider.name,
      slug: row.provider.slug,
      version: row.provider.version,
    };
    if (!consumers.has(consumer.key)) consumers.set(consumer.key, consumer);
    if (!providers.has(provider.key)) providers.set(provider.key, provider);
    const key = gridCellKey(consumer, provider);
    const cell = cells.get(key);
    if (!cell) {
      cells.set(key, { row, count: 1 });
      continue;
    }
    cell.count += 1;
    if ((row.verification?.verifiedAt ?? '') > (cell.row.verification?.verifiedAt ?? ''))
      cell.row = row;
  }
  const allConsumers = [...consumers.values()];
  const allProviders = [...providers.values()];
  return {
    consumers: allConsumers.slice(0, axisLimit),
    providers: allProviders.slice(0, axisLimit),
    cells,
    hiddenConsumers: Math.max(0, allConsumers.length - axisLimit),
    hiddenProviders: Math.max(0, allProviders.length - axisLimit),
  };
}

/**
 * The accessible name of a cell.
 *
 * @param cell - The cell.
 * @returns E.g. `Billing Service 2.0.0 → Ledger API 5.1.0: Failed (verification failed), 2 results. Open the pact.`
 */
export function cellLabel(cell: GridCell): string {
  const { row } = cell;
  const look = reasonLook(row.reason.code);
  const provider = row.provider.version
    ? `${row.provider.name} ${row.provider.version}`
    : `${row.provider.name} (no result)`;
  const results = cell.count > 1 ? `, ${cell.count} results` : '';
  const ignored = row.ignored ? ', ignored' : '';
  return `${row.consumer.name} ${row.consumer.version} → ${provider}: ${look.label} (${row.reason.text})${results}${ignored}. Open the pact.`;
}
