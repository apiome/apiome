/**
 * The Contracts guided set-up — PFX-8.20 (#7317), `/ade/dashboard/pacts/setup`
 * (docs/mockups/contracts/setup.html).
 *
 * The page's types, constants and pure rules, shared by the page, its `/api/pact/setup*` proxies and
 * their tests. REST owns every decision (`GET /v1/tenants/{t}/pact-setup`): which section is done,
 * next or to do, which pacticipants are proposed, and which repositories a linked GitHub account can
 * write to. This module only reads that answer defensively, checks what the browser sends before it
 * is forwarded, and builds the snippets the page shows when GitHub cannot be written to.
 */

import type { PactAction } from '@lib/pact-commands';
import { tenantPath } from '@lib/pact-commands';

/** The page. */
export const SETUP_ROUTE = '/ade/dashboard/pacts/setup';

/** REST paths below `/v1/tenants/{slug}`. */
export const SETUP_PROXY_PATH = 'pact-setup';
export const SETUP_SECRETS_PROXY_PATH = 'pact-setup/github/secrets';
export const SETUP_PULL_REQUESTS_PROXY_PATH = 'pact-setup/github/pull-requests';

/** The six sections, in order. */
export const SETUP_SECTION_IDS = ['pacticipants', 'environments', 'pipelines', 'first-pact', 'provider', 'gates'] as const;
export type SetupSectionId = (typeof SETUP_SECTION_IDS)[number];

/** A section's state. */
export type SetupSectionState = 'done' | 'next' | 'todo';

/** What each state is called on the page. */
export const SECTION_STATE_LABELS: Record<SetupSectionState, string> = { done: 'Done', next: 'Next', todo: 'To do' };

/** The ways to the first pact. */
export const FIRST_PACT_PATHS = ['tests', 'spec'] as const;
export type FirstPactPath = (typeof FIRST_PACT_PATHS)[number];

/** The first-pact cards: what each path is, and where its button goes. */
export const FIRST_PACT_CARDS: Record<FirstPactPath, { title: string; description: string; action: string; route: string }> = {
  tests: {
    title: 'We already write Pact tests',
    description: 'Publish the files your tests produce.',
    action: 'Publish a pact',
    route: '/ade/dashboard/pacts/publish',
  },
  spec: {
    title: 'Start from the spec',
    description: 'Tick the operations the consumer calls.',
    action: 'Derive a pact',
    route: '/ade/dashboard/pacts/export?kind=pact',
  },
};

/** The two variables every Pact tool reads. */
export const SECRET_NAMES = ['PACT_BROKER_BASE_URL', 'PACT_BROKER_TOKEN'] as const;

/** What the page asks someone without the Contracts admin permission to do. */
export const ASK_AN_ADMIN = 'Ask a Contracts admin to do this step (it needs the pacts:delete permission).';

/** Roughly how long each section takes, for "About N minutes left". */
export const SECTION_MINUTES: Record<SetupSectionId, number> = {
  pacticipants: 1,
  environments: 1,
  pipelines: 2,
  'first-pact': 3,
  provider: 2,
  gates: 1,
};

/** One section of the answer. */
export interface SetupSection {
  id: SetupSectionId;
  title: string;
  state: SetupSectionState;
  summary: string;
  marked: boolean;
}

/** A proposed pacticipant. */
export interface SetupCandidate {
  name: string;
  slug: string;
  source: 'project' | 'repository';
  source_label: string;
  role: 'provider' | 'consumer';
  project: string | null;
  repository_id: string | null;
  repository_url: string | null;
  main_branch: string | null;
  owner: string | null;
  /** The handle of the pacticipant that already exists for it. */
  pacticipant: string | null;
  pacticipant_name: string | null;
  contract_source: boolean;
}

/** A registered GitHub repository. */
export interface SetupRepository {
  id: string;
  full_name: string;
  default_branch: string | null;
  linked: boolean;
  pacticipant: string | null;
  pacticipant_name: string | null;
  secrets_written_at: string | null;
  pull_request_url: string | null;
}

/** `GET /api/pact/setup`. */
export interface SetupState {
  sections: SetupSection[];
  done: number;
  total: number;
  complete: boolean;
  facts: {
    pacticipants: number;
    environments: string[];
    production_environment: boolean;
    pacts: number;
    contract_sources: number;
    verification_results: number;
    webhooks: number;
    migrated: boolean;
  };
  saved: {
    marked: SetupSectionId[];
    first_pact_path: FirstPactPath | null;
    ci_key: { id: string; prefix: string } | null;
  };
  candidates: SetupCandidate[];
  candidates_omitted: number;
  github: { linked: boolean; reason: string | null; repositories: SetupRepository[] };
  workflow_path: string;
  can_edit: boolean;
  updated_at: string | null;
  updated_by: string | null;
}

/** One repository's result of writing the secrets. */
export interface SecretsResult {
  repository_id: string;
  full_name: string | null;
  status: 'written' | 'skipped';
  reason: string | null;
  names: string[];
}

/** One repository's result of opening the pull request. */
export interface PullRequestResult {
  repository_id: string;
  full_name: string | null;
  status: 'opened' | 'exists' | 'preview' | 'skipped';
  reason: string | null;
  url: string | null;
  number: number | null;
  path: string;
  content: string;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value !== '' ? value : null;
}

function count(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}

function isSection(value: unknown): value is SetupSectionId {
  return typeof value === 'string' && (SETUP_SECTION_IDS as readonly string[]).includes(value);
}

/**
 * Read REST's answer into the page's shape, or `null` when it is not one. Anything missing reads as
 * empty rather than throwing, so a partial answer still draws the sections it has.
 *
 * @param raw - The proxy's JSON body.
 * @returns The state, or `null` when there are not six known sections.
 */
export function readSetupState(raw: unknown): SetupState | null {
  const body = record(raw);
  if (!body || !Array.isArray(body.sections)) return null;
  const sections: SetupSection[] = [];
  for (const item of body.sections) {
    const row = record(item);
    if (!row || !isSection(row.id)) return null;
    const state = row.state === 'done' || row.state === 'next' ? row.state : 'todo';
    sections.push({ id: row.id, title: text(row.title) ?? row.id, state, summary: text(row.summary) ?? '', marked: row.marked === true });
  }
  if (sections.length !== SETUP_SECTION_IDS.length) return null;
  const facts = record(body.facts) ?? {};
  const saved = record(body.saved) ?? {};
  const key = record(saved.ci_key);
  const github = record(body.github) ?? {};
  const path = saved.first_pact_path;
  const done = sections.filter((section) => section.state === 'done').length;
  return {
    sections,
    done,
    total: sections.length,
    complete: done === sections.length,
    facts: {
      pacticipants: count(facts.pacticipants),
      environments: Array.isArray(facts.environments) ? facts.environments.filter((name): name is string => typeof name === 'string') : [],
      production_environment: facts.production_environment === true,
      pacts: count(facts.pacts),
      contract_sources: count(facts.contract_sources),
      verification_results: count(facts.verification_results),
      webhooks: count(facts.webhooks),
      migrated: facts.migrated === true,
    },
    saved: {
      marked: Array.isArray(saved.marked) ? saved.marked.filter(isSection) : [],
      first_pact_path: path === 'tests' || path === 'spec' ? path : null,
      ci_key: key && text(key.id) && text(key.prefix) ? { id: key.id as string, prefix: key.prefix as string } : null,
    },
    candidates: (Array.isArray(body.candidates) ? body.candidates : []).flatMap((item) => {
      const row = record(item);
      const name = row ? text(row.name) : null;
      if (!row || !name) return [];
      return [
        {
          name,
          slug: text(row.slug) ?? name,
          source: row.source === 'repository' ? 'repository' : 'project',
          source_label: text(row.source_label) ?? '',
          role: row.role === 'consumer' ? 'consumer' : 'provider',
          project: text(row.project),
          repository_id: text(row.repository_id),
          repository_url: text(row.repository_url),
          main_branch: text(row.main_branch),
          owner: text(row.owner),
          pacticipant: text(row.pacticipant),
          pacticipant_name: text(row.pacticipant_name),
          contract_source: row.contract_source === true,
        } satisfies SetupCandidate,
      ];
    }),
    candidates_omitted: count(body.candidates_omitted),
    github: {
      linked: github.linked === true,
      reason: text(github.reason),
      repositories: (Array.isArray(github.repositories) ? github.repositories : []).flatMap((item) => {
        const row = record(item);
        const id = row ? text(row.id) : null;
        const fullName = row ? text(row.full_name) : null;
        if (!row || !id || !fullName) return [];
        return [
          {
            id,
            full_name: fullName,
            default_branch: text(row.default_branch),
            linked: row.linked === true,
            pacticipant: text(row.pacticipant),
            pacticipant_name: text(row.pacticipant_name),
            secrets_written_at: text(row.secrets_written_at),
            pull_request_url: text(row.pull_request_url),
          } satisfies SetupRepository,
        ];
      }),
    },
    workflow_path: text(body.workflow_path) ?? '.github/workflows/apiome-contracts.yml',
    can_edit: body.can_edit === true,
    updated_at: text(body.updated_at),
    updated_by: text(body.updated_by),
  };
}

/**
 * The section that is open when the page loads: the one REST calls next, or none when all are done.
 *
 * @param state - The set-up.
 * @returns Its id, or `null`.
 */
export function openSection(state: SetupState): SetupSectionId | null {
  return state.sections.find((section) => section.state === 'next')?.id ?? null;
}

/**
 * "About N minutes left" for the sections not done.
 *
 * @param state - The set-up.
 * @returns The minutes, 0 when everything is done.
 */
export function minutesLeft(state: SetupState): number {
  return state.sections.reduce((sum, section) => (section.state === 'done' ? sum : sum + SECTION_MINUTES[section.id]), 0);
}

/** The candidates not yet pacticipants: what **Create pacticipants** would create. */
export function newCandidates(state: SetupState): SetupCandidate[] {
  return state.candidates.filter((candidate) => candidate.pacticipant === null);
}

/**
 * What `POST /api/pact/pacticipants` takes for a candidate.
 *
 * @param candidate - The proposal.
 * @returns The create body: its name, and the branch, repository and project when known.
 */
export function candidateCreateBody(candidate: SetupCandidate): { name: string; main_branch?: string; repository_url?: string; project?: string } {
  const body: { name: string; main_branch?: string; repository_url?: string; project?: string } = { name: candidate.name };
  if (candidate.main_branch) body.main_branch = candidate.main_branch;
  if (candidate.repository_url) body.repository_url = candidate.repository_url;
  if (candidate.project) body.project = candidate.project;
  return body;
}

/** The environments the page offers before any exists. */
export const ENVIRONMENT_PRESETS: ReadonlyArray<{ name: string; displayName: string; production: boolean }> = [
  { name: 'production', displayName: 'Production', production: true },
  { name: 'staging', displayName: 'Staging', production: false },
  { name: 'development', displayName: 'Development', production: false },
];

/**
 * Why a typed environment name cannot be added, or `null` when it can.
 *
 * @param name - The name as typed.
 * @param taken - Names already chosen or existing.
 * @returns The problem.
 */
export function environmentNameProblem(name: string, taken: readonly string[]): string | null {
  const trimmed = name.trim();
  if (!trimmed) return 'Give the environment a name.';
  if (/\s/.test(trimmed)) return 'An environment name is one word: no spaces.';
  if (trimmed.length > 255) return 'An environment name is at most 255 characters.';
  if (taken.some((other) => other.toLowerCase() === trimmed.toLowerCase())) return `${trimmed} is already there.`;
  return null;
}

/**
 * What `POST /api/pact/environments` takes for a chosen name.
 *
 * @param name - The environment's name.
 * @param requireContract - Whether production environments require a verified contract.
 * @returns The create body.
 */
export function environmentCreateBody(name: string, requireContract: boolean) {
  const preset = ENVIRONMENT_PRESETS.find((item) => item.name === name);
  const production = preset?.production ?? false;
  return {
    name,
    displayName: preset?.displayName ?? name,
    production,
    contractRequired: production && requireContract,
    contacts: [],
  };
}

/** The two variables as a pipeline sets them; the key is never written out. */
export function variablesText(brokerBaseUrl: string | null): string {
  return `PACT_BROKER_BASE_URL=${brokerBaseUrl ?? 'https://<api>/v1/tenants/<workspace>/pact-broker'}\nPACT_BROKER_TOKEN=<the key above>`;
}

/**
 * The GitHub CLI commands that set the two secrets by hand, shown when no linked account can.
 *
 * @param brokerBaseUrl - The workspace's broker address, when known.
 * @param repository - `owner/repo`, when one is known.
 * @returns Two `gh secret set` lines; the key is read from `$APIOME_API_KEY`, never written out.
 */
export function secretsSnippet(brokerBaseUrl: string | null, repository: string | null = null): string {
  const repo = repository ?? '<owner>/<repository>';
  const address = brokerBaseUrl ?? 'https://<api>/v1/tenants/<workspace>/pact-broker';
  return [
    `gh secret set PACT_BROKER_BASE_URL --repo ${repo} --body "${address}"`,
    `gh secret set PACT_BROKER_TOKEN --repo ${repo} --body "$APIOME_API_KEY"`,
  ].join('\n');
}

/** A name for the CI key that says where it came from and does not collide with an earlier one. */
export function ciKeyName(now: Date): string {
  return `Contracts CI (set-up ${now.toISOString().slice(0, 16).replace('T', ' ')})`;
}

/** A checked request body, or why it is refused. */
export type Checked<T> = { ok: true; body: T } | { ok: false; error: string };

function unknownKey(body: Record<string, unknown>, allowed: readonly string[]): string | null {
  return Object.keys(body).find((key) => !allowed.includes(key)) ?? null;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** What `PUT /api/pact/setup` forwards. */
export interface SetupSaveBody {
  mark?: Partial<Record<SetupSectionId, boolean>>;
  first_pact_path?: FirstPactPath;
  ci_key?: { id: string; prefix: string };
  forget_ci_key?: boolean;
}

/**
 * Check a save before it is forwarded: only known fields, sections and paths.
 *
 * @param raw - The browser's JSON body.
 * @returns The body to forward, or the refusal naming what is wrong.
 */
export function checkSaveBody(raw: unknown): Checked<SetupSaveBody> {
  const body = record(raw);
  if (!body) return { ok: false, error: 'Send a JSON object.' };
  const extra = unknownKey(body, ['mark', 'first_pact_path', 'ci_key', 'forget_ci_key']);
  if (extra) return { ok: false, error: `Unknown field: ${extra}.` };
  const out: SetupSaveBody = {};
  if (body.mark !== undefined) {
    const mark = record(body.mark);
    if (!mark) return { ok: false, error: 'mark must be an object of section: true | false.' };
    out.mark = {};
    for (const [section, on] of Object.entries(mark)) {
      if (!isSection(section)) return { ok: false, error: `Unknown section: ${section}.` };
      if (typeof on !== 'boolean') return { ok: false, error: `mark.${section} must be true or false.` };
      out.mark[section] = on;
    }
  }
  if (body.first_pact_path !== undefined) {
    if (body.first_pact_path !== 'tests' && body.first_pact_path !== 'spec') return { ok: false, error: 'first_pact_path must be tests or spec.' };
    out.first_pact_path = body.first_pact_path;
  }
  if (body.ci_key !== undefined) {
    const key = record(body.ci_key);
    const id = key ? text(key.id) : null;
    const prefix = key ? text(key.prefix) : null;
    if (!key || !id || !prefix || !UUID.test(id) || unknownKey(key, ['id', 'prefix'])) {
      return { ok: false, error: 'ci_key must be { id, prefix } of the key just created.' };
    }
    out.ci_key = { id, prefix: prefix.slice(0, 64) };
  }
  if (body.forget_ci_key !== undefined) {
    if (typeof body.forget_ci_key !== 'boolean') return { ok: false, error: 'forget_ci_key must be true or false.' };
    if (body.forget_ci_key && out.ci_key) return { ok: false, error: 'Send ci_key or forget_ci_key, not both.' };
    if (body.forget_ci_key) out.forget_ci_key = true;
  }
  if (Object.keys(out).length === 0) return { ok: false, error: 'Nothing to save.' };
  return { ok: true, body: out };
}

function repositoryIds(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length === 0 || value.length > 50) return null;
  if (!value.every((id) => typeof id === 'string' && UUID.test(id))) return null;
  return [...new Set(value as string[])];
}

/**
 * Check a write-secrets request. The broker address is not the browser's to choose: the proxy adds
 * the workspace's own.
 *
 * @param raw - The browser's JSON body: `{ repository_ids, token }`.
 * @returns The body to forward (without the address), or the refusal.
 */
export function checkSecretsBody(raw: unknown): Checked<{ repository_ids: string[]; token: string }> {
  const body = record(raw);
  if (!body) return { ok: false, error: 'Send a JSON object.' };
  const extra = unknownKey(body, ['repository_ids', 'token']);
  if (extra) return { ok: false, error: `Unknown field: ${extra}.` };
  const ids = repositoryIds(body.repository_ids);
  if (!ids) return { ok: false, error: 'repository_ids must be 1 to 50 repository ids.' };
  const token = typeof body.token === 'string' ? body.token.trim() : '';
  if (token.length < 8 || token.length > 512) return { ok: false, error: 'token must be the API key: 8 to 512 characters.' };
  return { ok: true, body: { repository_ids: ids, token } };
}

/** What `POST /api/pact/setup/github/pull-requests` forwards. */
export interface PullRequestsBody {
  repositories: Array<{ repository_id: string; pacticipant: string }>;
  environment: string;
  can_i_deploy: boolean;
  record_deployment: boolean;
  preview: boolean;
}

/**
 * Check an open-pull-requests (or preview) request.
 *
 * @param raw - The browser's JSON body.
 * @returns The body to forward, or the refusal.
 */
export function checkPullRequestsBody(raw: unknown): Checked<PullRequestsBody> {
  const body = record(raw);
  if (!body) return { ok: false, error: 'Send a JSON object.' };
  const extra = unknownKey(body, ['repositories', 'environment', 'can_i_deploy', 'record_deployment', 'preview']);
  if (extra) return { ok: false, error: `Unknown field: ${extra}.` };
  if (!Array.isArray(body.repositories) || body.repositories.length === 0 || body.repositories.length > 50) {
    return { ok: false, error: 'repositories must list 1 to 50 repositories.' };
  }
  const repositories: PullRequestsBody['repositories'] = [];
  for (const item of body.repositories) {
    const row = record(item);
    const id = row ? text(row.repository_id) : null;
    const pacticipant = row && typeof row.pacticipant === 'string' ? row.pacticipant.trim() : '';
    if (!row || !id || !UUID.test(id) || unknownKey(row, ['repository_id', 'pacticipant'])) {
      return { ok: false, error: 'Each repository is { repository_id, pacticipant }.' };
    }
    if (!pacticipant || pacticipant.length > 255 || /[\r\n]/.test(pacticipant)) {
      return { ok: false, error: 'Each repository needs its pacticipant: one line, at most 255 characters.' };
    }
    repositories.push({ repository_id: id, pacticipant });
  }
  const environment = typeof body.environment === 'string' ? body.environment.trim() : '';
  if (!environment || /\s/.test(environment) || environment.length > 255) return { ok: false, error: 'environment must be one environment name.' };
  for (const key of ['can_i_deploy', 'record_deployment', 'preview'] as const) {
    if (body[key] !== undefined && typeof body[key] !== 'boolean') return { ok: false, error: `${key} must be true or false.` };
  }
  const canIDeploy = body.can_i_deploy !== false;
  const recordDeployment = body.record_deployment !== false;
  if (!canIDeploy && !recordDeployment) return { ok: false, error: 'Choose at least one of can-i-deploy and record-deployment.' };
  return {
    ok: true,
    body: { repositories, environment, can_i_deploy: canIDeploy, record_deployment: recordDeployment, preview: body.preview === true },
  };
}

/** What the page's choices are, for **The same, from anywhere**. */
export interface SetupCommandChoices {
  fromProjects: boolean;
  environments: string[];
  ci: boolean;
  tenant?: string;
}

/**
 * The `apiome pact setup` command that does what the page's first sections and its pull requests do.
 *
 * @param choices - Whether pacticipants come from projects, which environments, and whether CI is wired.
 * @returns The action a {@link CommandBlock} renders.
 */
export function setupCommandAction(choices: SetupCommandChoices): PactAction {
  return {
    verb: 'setup',
    options: [
      { flag: '--from-projects', value: choices.fromProjects },
      { flag: '--environments', value: choices.environments.join(',') },
      { flag: '--ci', value: choices.ci ? 'github' : '' },
    ],
    rest: { method: 'GET', path: tenantPath(choices.tenant ?? '', `/${SETUP_PROXY_PATH}`) },
    unsupported: [
      {
        what: 'Creating the CI key',
        reason: 'A command runs with a key already; create the first one on this page or under API keys.',
        inRest: false,
      },
    ],
  };
}
