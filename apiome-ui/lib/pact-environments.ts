/**
 * The **Environments** pages of the Contracts workspace (PFX-5.7, #6951): the shapes REST answers,
 * the routes, the checks the `/api/pact/*` proxies run before forwarding, and the pure helpers the
 * pages draw with.
 *
 * REST (`/v1/tenants/{t}/pact-environments`, OpenAPI 1.684.0):
 * * `GET pact-environments` — every environment with what is deployed and released to it now;
 * * `GET pact-environments/{name}/deployments` — the environment's deployment history;
 * * `GET pact-environments/{name}/simulate` — the deploy simulator (records nothing).
 *
 * Tenant scoping and `pacts:view` are REST's; nothing here widens a request.
 */

import { shellQuote } from '@lib/pact-matrix';
import { MAX_CURSOR_LENGTH, MAX_FILTER_LENGTH } from '@lib/pact-pacticipants';

// --- shapes -------------------------------------------------------------------------------------

/** A pacticipant as REST names it in these documents. */
export interface NamedPacticipant {
  name: string;
  slug: string;
}

/** An environment, without what is in it. */
export interface EnvironmentFacts {
  uuid: string;
  name: string;
  displayName: string;
  production: boolean;
  contractRequired: boolean;
}

/** A version deployed to an environment now. */
export interface CurrentDeployment {
  pacticipant: NamedPacticipant;
  version: string;
  applicationInstance: string | null;
  deployedAt: string | null;
}

/** A release an environment supports now. */
export interface CurrentRelease {
  pacticipant: NamedPacticipant;
  version: string;
  releasedAt: string | null;
}

/** One environment of the topology. */
export interface TopologyEnvironment extends EnvironmentFacts {
  deployed: CurrentDeployment[];
  released: CurrentRelease[];
}

/** `GET pact-environments`. */
export interface Topology {
  environments: TopologyEnvironment[];
  truncated: boolean;
}

/** One deployment of the history. */
export interface HistoryDeployment {
  uuid: string;
  pacticipant: NamedPacticipant;
  version: string;
  applicationInstance: string | null;
  currentlyDeployed: boolean;
  deployedAt: string | null;
  undeployedAt: string | null;
  recordedBy: string | null;
}

/** `GET pact-environments/{name}/deployments`. */
export interface HistoryPage {
  environment: EnvironmentFacts;
  deployments: HistoryDeployment[];
  nextCursor: string | null;
}

/** One line of a verdict. */
export interface SimulationReason {
  type: string;
  code: string;
  text: string;
}

/** A can-i-deploy verdict as the simulator reports it. */
export interface SimulationVerdict {
  deployable: boolean | null;
  reason: string;
  reasons: SimulationReason[];
  counts: Record<string, number>;
}

/** What the candidate does to one counterpart version's verdict. */
export type Effect = 'breaks' | 'fixes' | 'clears' | 'blocks' | 'changes' | 'unchanged';

/** Where a counterpart version is: in the environment, or elsewhere. */
export type Placement = 'running' | 'pending';

/** A counterpart version. */
export interface SimulatedVersion {
  pacticipant: NamedPacticipant;
  version: string;
  placement: Placement;
  environments: string[];
}

/** One checked counterpart version. */
export interface SimulationImpact extends SimulatedVersion {
  roles: string[];
  before: SimulationVerdict;
  after: SimulationVerdict;
  effect: Effect;
}

/** One counterpart version not checked. */
export interface SimulationNotChecked extends SimulatedVersion {
  code: string;
  reason: string;
}

/** `GET pact-environments/{name}/simulate`. */
export interface Simulation {
  environment: EnvironmentFacts;
  pacticipant: NamedPacticipant;
  version: string;
  applicationInstance: string | null;
  replaces: string | null;
  alreadyDeployed: boolean;
  evaluatedAt: string;
  verdict: SimulationVerdict;
  impacts: SimulationImpact[];
  notChecked: SimulationNotChecked[];
  summary: Partial<Record<Effect, number>>;
}

// --- routes and proxy paths ---------------------------------------------------------------------

/** The route of the Environments dashboard. */
export const ENVIRONMENTS_ROUTE = '/ade/dashboard/pacts/environments';

/**
 * The route of one environment's page.
 *
 * @param name - The environment's name (`production`).
 * @returns E.g. `/ade/dashboard/pacts/environments/production`.
 */
export function environmentRoute(name: string): string {
  return `${ENVIRONMENTS_ROUTE}/${encodeURIComponent(name)}`;
}

/**
 * The route of an environment's deploy simulator, with a question when one is given.
 *
 * @param name - The environment's name.
 * @param query - The question (`pacticipant`, `version`, `applicationInstance`), or nothing.
 * @returns E.g. `/ade/dashboard/pacts/environments/production/simulate?pacticipant=ledger-api&version=p-2`.
 */
export function simulatorRoute(name: string, query?: URLSearchParams): string {
  const rendered = query?.toString() ?? '';
  return `${environmentRoute(name)}/simulate${rendered ? `?${rendered}` : ''}`;
}

/** The REST path of the topology. */
export const TOPOLOGY_PROXY_PATH = 'pact-environments';

/** An environment name: what V435 allows — no whitespace or control character, 1–255 characters. */
const ENVIRONMENT_NAME = /^[^\s\u0000-\u001f\u007f]{1,255}$/;

/**
 * Whether a value could be an environment's name (the proxies answer 404 without calling REST
 * otherwise).
 *
 * @param value - The candidate, e.g. a route segment.
 * @returns True when an environment could have this name.
 */
export function isEnvironmentName(value: string): boolean {
  return ENVIRONMENT_NAME.test(value);
}

/**
 * An environment name from a route segment. Next.js may hand the segment over still
 * percent-encoded; a segment that is not valid percent-encoding is kept as it is.
 *
 * @param segment - The `[environment]` segment.
 * @returns The name.
 */
export function environmentFromSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** The REST path of an environment's history (name already checked). */
export function historyProxyPath(name: string): string {
  return `pact-environments/${encodeURIComponent(name)}/deployments`;
}

/** The REST path of an environment's simulator (name already checked). */
export function simulateProxyPath(name: string): string {
  return `pact-environments/${encodeURIComponent(name)}/simulate`;
}

/** The history's page size. */
export const HISTORY_PAGE = 25;

/** The filters the history accepts besides `cursor`. */
export const HISTORY_FILTERS = ['pacticipant'] as const;

/** The parameters the simulator accepts. */
export const SIMULATION_PARAMETERS = ['pacticipant', 'version', 'applicationInstance'] as const;

/** A checked simulator question, or why it is refused. */
export type PickedSimulation = { ok: true; query: URLSearchParams } | { ok: false; error: string };

/**
 * Check a simulator question before forwarding it: `pacticipant` and `version` are required,
 * `applicationInstance` is optional; any other, repeated, empty or over-long parameter is refused
 * with a sentence naming it — nothing is silently dropped.
 *
 * @param params - The browser's query string.
 * @returns The parameters to forward, or the reason for a 400.
 */
export function pickSimulationQuery(params: URLSearchParams): PickedSimulation {
  const query = new URLSearchParams();
  for (const [key, raw] of params.entries()) {
    if (!(SIMULATION_PARAMETERS as readonly string[]).includes(key)) {
      return { ok: false, error: `Unsupported parameter ${key}: the simulator accepts ${SIMULATION_PARAMETERS.join(', ')}.` };
    }
    if (query.has(key)) return { ok: false, error: `The ${key} parameter is given more than once.` };
    const value = key === 'applicationInstance' ? raw : raw.trim();
    if (!value) return { ok: false, error: `The ${key} parameter is empty.` };
    if (value.length > MAX_FILTER_LENGTH) {
      return { ok: false, error: `The ${key} parameter is longer than ${MAX_FILTER_LENGTH} characters.` };
    }
    query.set(key, value);
  }
  for (const required of ['pacticipant', 'version']) {
    if (!query.has(required)) return { ok: false, error: `The ${required} parameter is missing.` };
  }
  return { ok: true, query };
}

/**
 * Check the history's cursor (the rest of the query is checked by `pickListQuery`).
 *
 * @param params - The picked parameters.
 * @returns Why the cursor is refused, or `null`.
 */
export function historyQueryProblem(params: URLSearchParams): string | null {
  const cursor = params.get('cursor');
  if (cursor !== null && (!/^\d+$/.test(cursor) || cursor.length > Math.min(19, MAX_CURSOR_LENGTH))) {
    return 'The cursor is not valid.';
  }
  return null;
}

// --- the simulator form -------------------------------------------------------------------------

/** What the simulator form holds. */
export interface SimulationForm {
  pacticipant: string;
  version: string;
  applicationInstance: string;
}

/**
 * The form an address describes.
 *
 * @param params - The page address's query.
 * @returns The form (empty fields for what the address does not name).
 */
export function simulationFormFrom(params: URLSearchParams): SimulationForm {
  return {
    pacticipant: params.get('pacticipant') ?? '',
    version: params.get('version') ?? '',
    applicationInstance: params.get('applicationInstance') ?? '',
  };
}

/**
 * The query a form asks (blank fields left out; the instance kept exactly as typed).
 *
 * @param form - The form.
 * @returns The parameters.
 */
export function simulationParams(form: SimulationForm): URLSearchParams {
  const params = new URLSearchParams();
  if (form.pacticipant.trim()) params.set('pacticipant', form.pacticipant.trim());
  if (form.version.trim()) params.set('version', form.version.trim());
  if (form.applicationInstance) params.set('applicationInstance', form.applicationInstance);
  return params;
}

/**
 * Why a form cannot be asked yet, or `null`.
 *
 * @param form - The form.
 * @returns The sentence.
 */
export function simulationFormProblem(form: SimulationForm): string | null {
  if (!form.pacticipant.trim()) return 'Name the pacticipant to deploy.';
  if (!form.version.trim()) return 'Name the version to deploy.';
  const instance = form.applicationInstance;
  if (instance && (instance !== instance.trim() || /[\u0000-\u001f\u007f]/.test(instance))) {
    return 'The application instance cannot start or end with a space or hold a control character.';
  }
  const picked = pickSimulationQuery(simulationParams(form));
  return picked.ok ? null : picked.error;
}

// --- drawing ------------------------------------------------------------------------------------

/** One cell of the dashboard grid: what one pacticipant has in one environment. */
export interface GridCell {
  deployed: CurrentDeployment[];
  released: CurrentRelease[];
}

/** One row of the dashboard grid. */
export interface GridRow {
  pacticipant: NamedPacticipant;
  cells: GridCell[];
}

/**
 * The dashboard grid: one row per pacticipant that is in any environment (by name), one cell per
 * environment (in the topology's order).
 *
 * @param topology - The topology.
 * @returns The rows.
 */
export function buildGrid(topology: Topology): GridRow[] {
  const rows = new Map<string, GridRow>();
  const empty = () => topology.environments.map((): GridCell => ({ deployed: [], released: [] }));
  topology.environments.forEach((environment, index) => {
    for (const deployment of environment.deployed) {
      const row = rows.get(deployment.pacticipant.slug) ?? { pacticipant: deployment.pacticipant, cells: empty() };
      row.cells[index].deployed.push(deployment);
      rows.set(deployment.pacticipant.slug, row);
    }
    for (const release of environment.released) {
      const row = rows.get(release.pacticipant.slug) ?? { pacticipant: release.pacticipant, cells: empty() };
      row.cells[index].released.push(release);
      rows.set(release.pacticipant.slug, row);
    }
  });
  return [...rows.values()].sort(
    (a, b) => a.pacticipant.name.localeCompare(b.pacticipant.name) || a.pacticipant.slug.localeCompare(b.pacticipant.slug),
  );
}

/**
 * The pacticipants of one environment's current deployments and releases, by name — the history's
 * **Pacticipant** filter choices.
 *
 * @param environment - The environment.
 * @returns The pacticipants, each once.
 */
export function environmentPacticipants(environment: TopologyEnvironment): NamedPacticipant[] {
  const seen = new Map<string, NamedPacticipant>();
  for (const entry of [...environment.deployed, ...environment.released]) seen.set(entry.pacticipant.slug, entry.pacticipant);
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name));
}

/** A badge's words and tone. */
export interface Tone {
  label: string;
  variant: 'ok' | 'danger' | 'warn' | 'neutral';
}

/** The words and tone of each effect. */
export const EFFECT_LABELS: Record<Effect, Tone> = {
  breaks: { label: 'Breaks', variant: 'danger' },
  blocks: { label: 'Blocks', variant: 'danger' },
  fixes: { label: 'Fixes', variant: 'ok' },
  clears: { label: 'Clears', variant: 'ok' },
  changes: { label: 'Changes', variant: 'warn' },
  unchanged: { label: 'No change', variant: 'neutral' },
};

/**
 * The words and tone of an effect (an effect this page does not know is shown as REST named it).
 *
 * @param effect - The effect.
 * @returns The badge.
 */
export function effectLabel(effect: string): Tone {
  return EFFECT_LABELS[effect as Effect] ?? { label: effect, variant: 'neutral' };
}

/** The order effects are listed in: what needs attention first. */
export const EFFECT_ORDER: readonly Effect[] = ['breaks', 'blocks', 'changes', 'fixes', 'clears', 'unchanged'];

/**
 * A verdict in two words.
 *
 * @param deployable - The verdict.
 * @returns `Deployable`, `Not deployable` or `Not known yet`.
 */
export function verdictWord(deployable: boolean | null): Tone {
  if (deployable === true) return { label: 'Deployable', variant: 'ok' };
  if (deployable === false) return { label: 'Not deployable', variant: 'danger' };
  return { label: 'Not known yet', variant: 'warn' };
}

/**
 * Where a counterpart version is, as a table prints it.
 *
 * @param version - The counterpart version.
 * @param environment - The simulated environment's name.
 * @returns E.g. `Running in production` or `Deployed in staging, qa`.
 */
export function placementLabel(version: SimulatedVersion, environment: string): string {
  if (version.placement === 'running') return `Running in ${environment}`;
  return version.environments.length ? `In ${version.environments.join(', ')}` : 'Elsewhere';
}

/**
 * The effects of a simulation as one line, in {@link EFFECT_ORDER}.
 *
 * @param summary - The simulation's `summary`.
 * @returns E.g. `1 clears · 2 no change`, or `Nothing checked`.
 */
export function summaryLine(summary: Partial<Record<Effect, number>>): string {
  const parts = EFFECT_ORDER.filter((effect) => (summary[effect] ?? 0) > 0).map(
    (effect) => `${summary[effect]} ${EFFECT_LABELS[effect].label.toLowerCase()}`,
  );
  return parts.length ? parts.join(' · ') : 'Nothing checked';
}

/**
 * What the simulated deployment would replace, as a sentence.
 *
 * @param simulation - The simulation.
 * @returns The sentence.
 */
export function replacementSentence(simulation: Simulation): string {
  const instance = simulation.applicationInstance ? `instance ${simulation.applicationInstance}` : 'the unnamed instance';
  const where = `${simulation.environment.name} (${instance})`;
  if (simulation.alreadyDeployed) return `${simulation.pacticipant.name} ${simulation.version} is already deployed to ${where}: nothing would change.`;
  if (simulation.replaces) return `Would replace ${simulation.pacticipant.name} ${simulation.replaces} in ${where}.`;
  return `${simulation.pacticipant.name} has nothing deployed to ${where} yet; this would be its first deployment there.`;
}

/**
 * The pipeline commands for the simulated deployment: ask can-i-deploy, then record it.
 *
 * @param simulation - The simulation.
 * @returns The commands, one flag per line.
 */
export function simulationCommands(simulation: Simulation): string {
  const pacticipant = shellQuote(simulation.pacticipant.slug);
  const version = shellQuote(simulation.version);
  const environment = shellQuote(simulation.environment.name);
  const record = [
    'apiome pact record-deployment',
    `  --pacticipant ${pacticipant}`,
    `  --version ${version}`,
    `  --environment ${environment}`,
    ...(simulation.applicationInstance ? [`  --application-instance ${shellQuote(simulation.applicationInstance)}`] : []),
  ];
  const ask = [
    'apiome pact can-i-deploy',
    `  --pacticipant ${pacticipant}`,
    `  --version ${version}`,
    `  --to-environment ${environment}`,
  ];
  return `${ask.join(' \\\n')} \\\n  && ${record.join(' \\\n')}`;
}

/** The commands an empty workspace shows: create an environment, then record a deployment. */
export const CREATE_ENVIRONMENT_SNIPPET = [
  'apiome pact create-environment --name production --production',
  'apiome pact record-deployment --pacticipant billing-service \\',
  '  --version "$GIT_COMMIT" --environment production',
].join('\n');

/** The command an environment with no deployment shows. */
export function recordDeploymentInto(environment: string): string {
  return `apiome pact record-deployment --pacticipant billing-service \\\n  --version "$GIT_COMMIT" --environment ${shellQuote(environment)}`;
}
