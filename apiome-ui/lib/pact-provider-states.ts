/**
 * The provider-state registry in the UI — PFX-3.3 (#6933).
 *
 * The wire shapes of `GET /v1/tenants/{tenant}/pact-verifier/providers/{provider}/provider-states`
 * and `POST …/provider-states/check`, and the pure rules the **Provider states** page draws them
 * with: how a setup reads in one line, which problems block a run, and the REST paths the proxies
 * forward to. A state the pacts name but the provider has not registered is always shown, first —
 * the page never reads "ready" while one interaction would be held back.
 */

import type { BadgeTone } from '@/app/components/ui/Badge';

/** One request of a recorded fixture. */
export interface FixtureRequest {
  method: string;
  path: string;
  headers?: Record<string, string>;
  body?: unknown;
}

/** How a state is set up. */
export interface StateSetup {
  kind: 'state_change' | 'fixture';
  url?: string | null;
  teardown?: boolean;
  requests?: FixtureRequest[];
  teardown_requests?: FixtureRequest[];
}

/** A parameter a state takes. */
export interface StateParameter {
  name: string;
  required?: boolean;
  default?: unknown;
  description?: string | null;
}

/** A per-target setup. */
export interface StateOverride {
  target_id: string;
  target_slug: string;
  setup: StateSetup;
}

/** A registered provider state. */
export interface ProviderState {
  id: string;
  provider: string;
  name: string;
  description?: string | null;
  parameters: StateParameter[];
  setup: StateSetup;
  overrides: StateOverride[];
  created_at: string;
  updated_at: string;
}

/** Severity of a check problem. */
export type ProblemSeverity = 'blocking' | 'warning';

/** One reason a state cannot be set up as an interaction names it. */
export interface StateProblem {
  code: string;
  severity: ProblemSeverity;
  state: string;
  parameter?: string | null;
  message: string;
  consumer?: string | null;
  interaction?: string | null;
}

/** One interaction that names a state. */
export interface StateUse {
  consumer: string;
  pact_version_sha: string;
  interaction: string;
  params: Record<string, unknown>;
}

/** One state the selected pacts name. */
export interface StateCheckEntry {
  name: string;
  registered: boolean;
  state_id?: string | null;
  setup_kind?: StateSetup['kind'] | null;
  overridden: boolean;
  interactions: number;
  uses: StateUse[];
  problems: StateProblem[];
}

/** The answer of `POST …/provider-states/check`. */
export interface StateCheckResponse {
  provider: string;
  target?: string | null;
  ready: boolean;
  pacts: number;
  blocking: number;
  warnings: number;
  states: StateCheckEntry[];
  unused: string[];
}

/** A pacticipant, as the provider picker needs it. */
export interface ProviderOption {
  slug: string;
  name: string;
}

/** The setup kinds, as the page names them. */
export const SETUP_KIND_LABELS: Readonly<Record<StateSetup['kind'], string>> = {
  state_change: 'State-change call',
  fixture: 'Recorded fixture',
};

/** The badge tone of a problem: a blocking one is danger, a warning is warn. */
export const SEVERITY_TONES: Readonly<Record<ProblemSeverity, BadgeTone>> = {
  blocking: 'danger',
  warning: 'warn',
};

/**
 * A setup in one line: `State-change call · POST /_pact/states` or `Recorded fixture · 2 requests`.
 *
 * @param setup - The setup.
 * @returns The line.
 */
export function setupLine(setup: StateSetup): string {
  if (setup.kind === 'state_change') {
    const where = setup.url ? `POST ${setup.url}` : 'no URL';
    return `${SETUP_KIND_LABELS.state_change} · ${where}${setup.teardown === false ? ' · no teardown' : ''}`;
  }
  const count = setup.requests?.length ?? 0;
  if (count === 0) return `${SETUP_KIND_LABELS.fixture} · target already holds the data`;
  return `${SETUP_KIND_LABELS.fixture} · ${count} ${count === 1 ? 'request' : 'requests'}`;
}

/**
 * A state's parameters in one line: `id (required), currency = "EUR"`, or `No parameters`.
 *
 * @param parameters - The declared parameters.
 * @returns The line.
 */
export function parametersLine(parameters: StateParameter[]): string {
  if (parameters.length === 0) return 'No parameters';
  return parameters
    .map((parameter) => {
      if (parameter.default !== undefined && parameter.default !== null) {
        return `${parameter.name} = ${JSON.stringify(parameter.default)}`;
      }
      return parameter.required ? `${parameter.name} (required)` : parameter.name;
    })
    .join(', ');
}

/**
 * The check's headline: whether a run would hold anything back for its provider states.
 *
 * @param check - The check.
 * @returns The sentence.
 */
export function checkStatement(
  check: Pick<StateCheckResponse, 'ready' | 'pacts' | 'blocking' | 'warnings' | 'states' | 'target'>,
): string {
  const on = check.target ? ` on ${check.target}` : '';
  if (check.pacts === 0) return 'No pacts are selected for this provider yet, so there is nothing to check.';
  if (check.states.length === 0) return `None of the ${check.pacts} selected pacts names a provider state.`;
  const warnings = check.warnings
    ? ` ${check.warnings} ${check.warnings === 1 ? 'warning' : 'warnings'} to review.`
    : '';
  if (check.ready) {
    return `Every provider state the ${check.pacts} selected pacts name can be set up${on}.${warnings}`;
  }
  const problems = `${check.blocking} ${check.blocking === 1 ? 'problem' : 'problems'}`;
  return `${problems} would hold interactions back${on}.${warnings}`;
}

/** A pacticipant handle, as the proxies accept (lowercase kebab, the REST handle rule). */
const HANDLE = /^[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?$/;

/**
 * The REST path (below `/v1/tenants/{slug}`) of a provider's states, or `null` for a malformed
 * handle — the proxy then answers 404 without calling apiome-rest.
 *
 * @param provider - The provider's handle.
 * @returns The path, or `null`.
 */
export function statesProxyPath(provider: string): string | null {
  return HANDLE.test(provider) ? `pact-verifier/providers/${provider}/provider-states` : null;
}

/**
 * The REST path of a provider's pre-run check, or `null` for a malformed handle.
 *
 * @param provider - The provider's handle.
 * @returns The path, or `null`.
 */
export function checkProxyPath(provider: string): string | null {
  const base = statesProxyPath(provider);
  return base ? `${base}/check` : null;
}

/** The REST path of the provider picker's list (the first page of pacticipants). */
export const PROVIDERS_PROXY_PATH = 'pacticipants?limit=100';

/**
 * The check body the proxy forwards: only a `target_ref` that is a non-empty string survives, so
 * the browser cannot widen the request beyond "check the default selection".
 *
 * @param body - Whatever the browser posted.
 * @returns `{}` or `{ target_ref }`.
 */
export function checkBody(body: unknown): { target_ref?: string } {
  if (body && typeof body === 'object' && 'target_ref' in body) {
    const ref = (body as { target_ref?: unknown }).target_ref;
    if (typeof ref === 'string' && ref.trim() && ref.length <= 200) return { target_ref: ref.trim() };
  }
  return {};
}
