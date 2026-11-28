/**
 * The Contracts landing and the area's tab row — PFX-8.1 (#7298): the shared model of
 * `/ade/dashboard/pacts`, its `/api/pact/integrations` proxy and the tab row every Contracts page
 * draws in its header.
 *
 * Everything here is pure: types mirroring apiome-rest (`app.pact_integrations`), the tab row's
 * destinations, the landing's query (search, filter chip, page — kept in the address), the checks the
 * proxy runs before anything reaches REST (an unknown, repeated, empty or out-of-range parameter is a
 * 400 naming it), the status strip's statuses, the "Start something" entry points, and the network
 * the table's second view draws.
 */

import type { PactNetwork } from '@lib/pact-network';
import type { VerificationVerdict } from '@lib/pact-detail';
import { PACTICIPANTS_ROUTE } from '@lib/pact-pacticipants';
import { CAN_I_DEPLOY_ROUTE, MATRIX_ROUTE } from '@lib/pact-matrix';
import { ENVIRONMENTS_ROUTE } from '@lib/pact-environments';
import { WEBHOOKS_ROUTE } from '@lib/pact-webhooks';
import { HEALTH_ROUTE } from '@lib/pact-health';
import { SETTINGS_ROUTE } from '@lib/pact-remediation';
import { PUBLISH_ROUTE } from '@lib/pact-publish-page';
import { PROVIDER_CONTRACT_ROUTE } from '@lib/pact-provider-contract';
import { VERIFY_RUN_ROUTE } from '@lib/pact-verify-run';
import { MIGRATE_ROUTE } from '@lib/pact-migration';

// --- types ------------------------------------------------------------------------------------------

/** How an integration is checked. */
export type IntegrationKind = 'pact' | 'bidirectional';

/** An integration's verdict, worst first in {@link VERDICTS}. */
export type IntegrationVerdict =
  | 'failing'
  | 'stale'
  | 'no-provider-contract'
  | 'unverified'
  | 'verified';

/** One row of the integrations table. */
export interface PactIntegration {
  consumer: string;
  consumer_name: string;
  provider: string;
  provider_name: string;
  consumer_version: string;
  provider_version: string | null;
  pact_version_sha: string;
  published_at: string | null;
  kind: IntegrationKind;
  verdict: IntegrationVerdict;
  /** A Pact-kind pact the provider has never passed (PFX-1.7). */
  pending: boolean;
  /** The environments both sides are deployed in now. */
  environments: string[];
  verified_at: string | null;
  /** A team the viewer is on owns the consumer or the provider. */
  mine: boolean;
}

/** A pair the status strip names. */
export interface PactIntegrationRef {
  consumer: string;
  consumer_name: string;
  provider: string;
  provider_name: string;
  consumer_version: string;
  provider_version: string | null;
  verified_at: string | null;
  published_at: string | null;
}

/** Up to three named pairs per status-strip category. */
export interface PactIntegrationAttention {
  failing: PactIntegrationRef[];
  stale: PactIntegrationRef[];
  no_provider_contract: PactIntegrationRef[];
  pending: PactIntegrationRef[];
}

/** Counts over every pair (the search and filter do not narrow them). */
export interface PactIntegrationCounts {
  integrations: number;
  verified: number;
  failing: number;
  stale: number;
  no_provider_contract: number;
  unverified: number;
  pending: number;
  bidirectional: number;
  mine: number;
}

/** What `GET /api/pact/integrations` answers. */
export interface PactIntegrationsPage {
  integrations: PactIntegration[];
  total: number;
  offset: number;
  limit: number;
  filter: string;
  search: string | null;
  counts: PactIntegrationCounts;
  attention: PactIntegrationAttention;
  pacticipants: number;
  environments: number;
  truncated: boolean;
  omitted_integrations: number;
  mine_available: boolean;
}

// --- the tab row ---------------------------------------------------------------------------------------

/** The Contracts landing. */
export const CONTRACTS_ROUTE = '/ade/dashboard/pacts';

/** The id of one tab of the Contracts area. */
export type ContractsTabId =
  | 'overview'
  | 'pacticipants'
  | 'matrix'
  | 'can-i-deploy'
  | 'verification'
  | 'environments'
  | 'webhooks'
  | 'health'
  | 'settings';

/** One tab of the Contracts area. */
export interface ContractsTab {
  id: ContractsTabId;
  label: string;
  href: string;
  /** The tab's `title`: what the page is for. */
  description: string;
}

/**
 * The area's tabs, in the mockup's order. Only shipped screens are tabs (DESIGN.md §10):
 * **Verification** leads to **Run a verification** (PFX-8.8, #7305); a provider's own Verification
 * page stays under Pacticipants.
 */
export const CONTRACTS_TABS: readonly ContractsTab[] = [
  {
    id: 'overview',
    label: 'Overview',
    href: CONTRACTS_ROUTE,
    description: 'What needs attention, and every integration',
  },
  {
    id: 'pacticipants',
    label: 'Pacticipants',
    href: PACTICIPANTS_ROUTE,
    description: 'The applications that take part in pacts',
  },
  { id: 'matrix', label: 'Matrix', href: MATRIX_ROUTE, description: 'Which versions were verified together' },
  {
    id: 'can-i-deploy',
    label: 'Can I deploy',
    href: CAN_I_DEPLOY_ROUTE,
    description: 'Whether a version is safe to deploy',
  },
  {
    id: 'verification',
    label: 'Verification',
    href: VERIFY_RUN_ROUTE,
    description: 'Run a verification against a provider',
  },
  {
    id: 'environments',
    label: 'Environments',
    href: ENVIRONMENTS_ROUTE,
    description: 'What is deployed where',
  },
  { id: 'webhooks', label: 'Webhooks', href: WEBHOOKS_ROUTE, description: 'Calls made when contracts change' },
  { id: 'health', label: 'Health', href: HEALTH_ROUTE, description: 'Each pair rolled up into one state' },
  {
    id: 'settings',
    label: 'Settings',
    href: SETTINGS_ROUTE,
    description: 'Verification schedules and stale thresholds',
  },
];

/** The breadcrumb every Contracts page starts with: `Home › Contracts`. */
export const CONTRACTS_CRUMBS = [
  { label: 'Home', href: '/ade/dashboard' },
  { label: 'Contracts', href: CONTRACTS_ROUTE },
] as const;

// --- the landing's query ---------------------------------------------------------------------------------

/** The table's filter chips, in the order they are drawn. */
export const INTEGRATION_FILTERS = ['all', 'failing', 'stale', 'bidirectional', 'mine'] as const;

/** One filter chip. */
export type IntegrationFilter = (typeof INTEGRATION_FILTERS)[number];

/** How each chip reads. */
export const FILTER_LABEL: Record<IntegrationFilter, string> = {
  all: 'All',
  failing: 'Failing',
  stale: 'Stale',
  bidirectional: 'Bi-directional',
  mine: 'Mine',
};

/** Rows per page. */
export const INTEGRATIONS_PAGE_SIZE = 25;

/** The longest search text REST accepts. */
export const MAX_SEARCH_LENGTH = 100;

/** The most pairs REST classifies (the largest offset it accepts). */
export const MAX_INTEGRATIONS = 1000;

/** The landing's state, as the address carries it. */
export interface OverviewQuery {
  q: string;
  filter: IntegrationFilter;
  /** 1-based. */
  page: number;
  /** The table, or the network graph. */
  view: 'table' | 'network';
  /** What in the address could not be used, worded for a notice (never dropped silently). */
  problems: string[];
}

/** The last page the offset cap allows. */
export const MAX_PAGE = Math.floor(MAX_INTEGRATIONS / INTEGRATIONS_PAGE_SIZE) + 1;

/**
 * Read the landing's address.
 *
 * An unknown filter, page or view falls back to its default **and says so** in `problems`; an
 * over-long search is cut to {@link MAX_SEARCH_LENGTH} and says so too.
 *
 * @param query - The page's search parameters.
 * @returns The query.
 */
export function readOverviewQuery(
  query: Record<string, string | string[] | undefined>,
): OverviewQuery {
  const problems: string[] = [];
  const one = (key: string): string | null => {
    const value = query[key];
    if (Array.isArray(value)) {
      problems.push(`The ${key} parameter was given more than once; the first one is used.`);
      return value[0] ?? null;
    }
    return typeof value === 'string' ? value : null;
  };
  let q = (one('q') ?? '').trim();
  if (q.length > MAX_SEARCH_LENGTH) {
    problems.push(`The search is longer than ${MAX_SEARCH_LENGTH} characters, so it was shortened.`);
    q = q.slice(0, MAX_SEARCH_LENGTH);
  }
  const rawFilter = one('filter');
  let filter: IntegrationFilter = 'all';
  if (rawFilter !== null && rawFilter !== '') {
    if ((INTEGRATION_FILTERS as readonly string[]).includes(rawFilter)) filter = rawFilter as IntegrationFilter;
    else problems.push(`There is no filter called “${rawFilter}”, so every integration is shown.`);
  }
  const rawPage = one('page');
  let page = 1;
  if (rawPage !== null && rawPage !== '') {
    const parsed = Number(rawPage);
    if (Number.isInteger(parsed) && parsed >= 1 && parsed <= MAX_PAGE) page = parsed;
    else problems.push(`Page “${rawPage}” does not exist, so the first page is shown.`);
  }
  const rawView = one('view');
  let view: OverviewQuery['view'] = 'table';
  if (rawView === 'network') view = 'network';
  else if (rawView !== null && rawView !== '' && rawView !== 'table') {
    problems.push(`There is no “${rawView}” view, so the table is shown.`);
  }
  return { q, filter, page, view, problems };
}

/**
 * The landing's address for a state (defaults left out).
 *
 * @param state - The search, filter, page and view.
 * @returns The route.
 */
export function overviewRoute(state: Partial<Omit<OverviewQuery, 'problems'>> = {}): string {
  const query = new URLSearchParams();
  if (state.q) query.set('q', state.q);
  if (state.filter && state.filter !== 'all') query.set('filter', state.filter);
  if (state.page && state.page > 1) query.set('page', String(state.page));
  if (state.view === 'network') query.set('view', 'network');
  const rendered = query.toString();
  return rendered ? `${CONTRACTS_ROUTE}?${rendered}` : CONTRACTS_ROUTE;
}

// --- the proxy --------------------------------------------------------------------------------------------

/** The REST path below `/v1/tenants/{slug}/` (no leading slash). */
export const INTEGRATIONS_PROXY_PATH = 'pact-integrations';

/** The parameters the proxy passes on. */
export const INTEGRATIONS_PARAMETERS = ['q', 'filter', 'limit', 'offset'] as const;

/**
 * What is wrong with a proxy query, or `null`.
 *
 * @param params - The browser's query string.
 * @returns The 400's message, or `null`.
 */
export function integrationsQueryProblem(params: URLSearchParams): string | null {
  const allowed: readonly string[] = INTEGRATIONS_PARAMETERS;
  for (const key of new Set(params.keys())) {
    if (!allowed.includes(key)) {
      return `Unsupported parameter ${key}: this read accepts ${allowed.join(', ')}.`;
    }
    if (params.getAll(key).length > 1) return `The ${key} parameter is given more than once.`;
    const value = params.get(key) ?? '';
    if (!value) return `The ${key} parameter is empty.`;
    if (key === 'q' && value.length > MAX_SEARCH_LENGTH) {
      return `The q parameter is longer than ${MAX_SEARCH_LENGTH} characters.`;
    }
    if (key === 'filter' && !(INTEGRATION_FILTERS as readonly string[]).includes(value)) {
      return `The filter parameter must be one of ${INTEGRATION_FILTERS.join(', ')}.`;
    }
    if (key === 'limit' && !isIntegerIn(value, 1, 100)) {
      return 'The limit parameter must be a whole number from 1 to 100.';
    }
    if (key === 'offset' && !isIntegerIn(value, 0, MAX_INTEGRATIONS)) {
      return `The offset parameter must be a whole number from 0 to ${MAX_INTEGRATIONS}.`;
    }
  }
  return null;
}

/** Whether a string is a whole number in a range. */
function isIntegerIn(value: string, min: number, max: number): boolean {
  if (!/^\d+$/.test(value)) return false;
  const parsed = Number(value);
  return parsed >= min && parsed <= max;
}

/**
 * The REST path of a checked query, parameters in a fixed order.
 *
 * @param params - The checked query.
 * @returns The path with its query.
 */
export function integrationsProxyPath(params: URLSearchParams): string {
  const query = new URLSearchParams();
  for (const key of INTEGRATIONS_PARAMETERS) {
    const value = params.get(key);
    if (value) query.set(key, value);
  }
  const rendered = query.toString();
  return rendered ? `${INTEGRATIONS_PROXY_PATH}?${rendered}` : INTEGRATIONS_PROXY_PATH;
}

/**
 * The browser's query for one state of the landing.
 *
 * @param state - The search, filter and page.
 * @returns The proxy's query string (no `?`).
 */
export function integrationsQuery(state: Pick<OverviewQuery, 'q' | 'filter' | 'page'>): string {
  const query = new URLSearchParams();
  if (state.q) query.set('q', state.q);
  if (state.filter !== 'all') query.set('filter', state.filter);
  query.set('limit', String(INTEGRATIONS_PAGE_SIZE));
  const offset = (state.page - 1) * INTEGRATIONS_PAGE_SIZE;
  if (offset > 0) query.set('offset', String(Math.min(offset, MAX_INTEGRATIONS)));
  return query.toString();
}

// --- wording ------------------------------------------------------------------------------------------------

/** How each verdict reads, and the badge status that colours it. */
export const VERDICT_TEXT: Record<IntegrationVerdict, { label: string; status: string }> = {
  failing: { label: 'Failing', status: 'failed' },
  stale: { label: 'Stale', status: 'warn' },
  'no-provider-contract': { label: 'No provider contract', status: 'unknown' },
  unverified: { label: 'Not verified yet', status: 'pending' },
  verified: { label: 'Verified', status: 'passed' },
};

/**
 * How a verdict reads; an unknown value reads as **Not verified yet**.
 *
 * @param verdict - The verdict.
 * @returns The label and badge status.
 */
export function verdictText(verdict: string): { label: string; status: string } {
  return VERDICT_TEXT[verdict as IntegrationVerdict] ?? VERDICT_TEXT.unverified;
}

/** How each kind reads. */
export const KIND_LABEL: Record<IntegrationKind, string> = {
  pact: 'Pact',
  bidirectional: 'Bi-directional',
};

/**
 * Two initials for a pacticipant's avatar.
 *
 * @param name - The display name.
 * @returns E.g. `OU` for `Orders UI`, `C` for `Checkout`.
 */
export function initials(name: string): string {
  const words = name.trim().split(/[\s_-]+/).filter(Boolean);
  if (words.length === 0) return '?';
  if (words.length === 1) return words[0].slice(0, 1).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

/** `Orders UI → Billing Service`. */
export function pairLabel(ref: Pick<PactIntegrationRef, 'consumer_name' | 'provider_name'>): string {
  return `${ref.consumer_name} → ${ref.provider_name}`;
}

/**
 * A list of pairs as a sentence: `A → B`, `A → B and C → D`, `A → B, C → D and 2 more`.
 *
 * @param refs - The named pairs.
 * @param total - How many pairs the category holds.
 * @returns The sentence fragment.
 */
export function pairList(refs: PactIntegrationRef[], total: number): string {
  const names = refs.map(pairLabel);
  const more = total - names.length;
  if (more > 0) return `${names.join(', ')} and ${more} more`;
  if (names.length <= 1) return names.join('');
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`;
}

// --- the status strip ------------------------------------------------------------------------------------------

/** One status of the strip, before it is drawn. */
export interface OverviewStatus {
  id: 'failing' | 'stale' | 'no-provider-contract' | 'pending';
  tone: 'danger' | 'warn' | 'accent';
  label: string;
  detail?: string;
  title: string;
  body: string;
  /** Where the detail row's action goes, and what it says. */
  action?: { label: string; href: string };
}

/**
 * The strip's statuses: failing, stale, provider-less and pending integrations, each only when
 * there is one. An empty list means the strip is absent.
 *
 * @param page - The landing's read.
 * @returns The statuses, in reading order.
 */
export function overviewStatuses(page: PactIntegrationsPage): OverviewStatus[] {
  const { counts, attention } = page;
  const out: OverviewStatus[] = [];
  if (counts.failing > 0) {
    out.push({
      id: 'failing',
      tone: 'danger',
      label: `${counts.failing} failing`,
      detail: attention.failing[0] ? pairLabel(attention.failing[0]) : undefined,
      title:
        counts.failing === 1
          ? `${pairList(attention.failing, 1)} failed its newest verification.`
          : `${counts.failing} integrations failed their newest verification.`,
      body:
        counts.failing === 1
          ? 'Open its health page to see which interaction failed and since when.'
          : `${pairList(attention.failing, counts.failing)}. Open each pair's health page to see which interactions failed.`,
      action: { label: 'Show the failing ones', href: overviewRoute({ filter: 'failing' }) },
    });
  }
  if (counts.stale > 0) {
    out.push({
      id: 'stale',
      tone: 'warn',
      label: `${counts.stale} stale`,
      detail: 'past their threshold',
      title: `${counts.stale} ${counts.stale === 1 ? 'pact has' : 'pacts have'} not been verified within the stale threshold.`,
      body: `${pairList(attention.stale, counts.stale)}. Their consumers can be asked to re-publish from Health.`,
      action: { label: 'Show the stale ones', href: overviewRoute({ filter: 'stale' }) },
    });
  }
  if (counts.no_provider_contract > 0) {
    out.push({
      id: 'no-provider-contract',
      tone: 'warn',
      label: `${counts.no_provider_contract} without a provider contract`,
      title: `${pairList(attention.no_provider_contract, counts.no_provider_contract)} ${
        counts.no_provider_contract === 1 ? 'has' : 'have'
      } a pact but nothing to compare it with.`,
      body: 'Publish the provider’s spec as a provider contract, or run a verification against the provider.',
    });
  }
  if (counts.pending > 0) {
    out.push({
      id: 'pending',
      tone: 'accent',
      label: `${counts.pending} pending`,
      detail: 'not yet passed',
      title: `${counts.pending} ${counts.pending === 1 ? 'pact is' : 'pacts are'} pending.`,
      body: 'A pending pact cannot fail the provider’s build until the provider has passed it once.',
    });
  }
  return out;
}

// --- "Start something" ----------------------------------------------------------------------------------------

/** One entry point. A shipped screen has a `route`; an action with no screen yet has its `command`. */
export interface WayIn {
  id: string;
  title: string;
  description: string;
  /** The screen it opens. */
  route?: string;
  /** The `apiome pact` command, for an action whose screen ships later in PFX-8. */
  command?: string;
}

/** One group of entry points, by who is asking. */
export interface WayInGroup {
  id: 'consumer' | 'provider' | 'pipeline';
  title: string;
  ways: WayIn[];
}

/**
 * The entry points, grouped by who is asking. Recording a pact from a hosted mock and serving pacts
 * as a mock join the consumer and provider groups with PFX-9; every other action the CLI has is
 * here, with its screen when it has one.
 */
export const WAYS_IN: readonly WayInGroup[] = [
  {
    id: 'consumer',
    title: 'I consume an API',
    ways: [
      {
        id: 'publish-pact',
        title: 'Publish a pact',
        description: 'Send the pacts your tests wrote: upload, paste or derive them.',
        route: PUBLISH_ROUTE,
      },
      {
        id: 'export-consumer-contract',
        title: 'Derive a pact from a project',
        description: 'Start from the operations you call.',
        command: 'apiome pact export-consumer-contract --project <project> --consumer "Orders UI" --output ./pacts',
      },
    ],
  },
  {
    id: 'provider',
    title: 'I provide an API',
    ways: [
      {
        id: 'publish-provider-contract',
        title: 'Publish a provider contract',
        description: 'Your OpenAPI or AsyncAPI, compared with every consumer’s pact.',
        route: PROVIDER_CONTRACT_ROUTE,
      },
      {
        id: 'verify',
        title: 'Run a verification',
        description: 'Replay consumers’ pacts against a running provider.',
        route: VERIFY_RUN_ROUTE,
      },
    ],
  },
  {
    id: 'pipeline',
    title: 'I run the pipeline',
    ways: [
      {
        id: 'environments',
        title: 'Environments and releases',
        description: 'Record what is deployed where.',
        route: ENVIRONMENTS_ROUTE,
      },
      {
        id: 'can-i-deploy',
        title: 'Ask whether a version can deploy',
        description: 'The same question your pipeline asks before it deploys.',
        route: CAN_I_DEPLOY_ROUTE,
      },
      {
        id: 'migrate',
        title: 'Migrate from a broker',
        description: 'Pact Broker or PactFlow, read-only at the source.',
        route: MIGRATE_ROUTE,
      },
      {
        id: 'settings',
        title: 'Verification settings',
        description: 'Stale thresholds, schedules and overrides.',
        route: SETTINGS_ROUTE,
      },
    ],
  },
];

/** The first-run checklist, shown until one integration is verified. */
export interface FirstRunStep {
  id: string;
  label: string;
  done: boolean;
}

/**
 * The first-run checklist's steps and whether each is done.
 *
 * @param page - The landing's read, or `null` before it arrives.
 * @returns The steps.
 */
export function firstRunSteps(page: PactIntegrationsPage | null): FirstRunStep[] {
  const counts = page?.counts;
  return [
    { id: 'publish', label: 'Publish a pact from a consumer', done: Boolean(counts && counts.integrations > 0) },
    {
      id: 'provider',
      label: 'Publish a provider contract or verify the provider',
      done: Boolean(counts && counts.integrations > counts.no_provider_contract),
    },
    { id: 'environment', label: 'Add an environment', done: Boolean(page && page.environments > 0) },
    { id: 'verified', label: 'Get one integration verified', done: Boolean(counts && counts.verified > 0) },
  ];
}

// --- the network view ---------------------------------------------------------------------------------------

/** The network graph's verdict for an integration's verdict. */
const NETWORK_VERDICT: Record<IntegrationVerdict, VerificationVerdict> = {
  failing: 'failed',
  stale: 'verified',
  'no-provider-contract': 'unverified',
  unverified: 'unverified',
  verified: 'verified',
};

/**
 * The listed integrations as the network graph (PFX-5.3) draws them: every pacticipant on the page
 * and one edge per integration, centred on the pacticipant with the most integrations.
 *
 * @param rows - The table's rows.
 * @returns The network, or `null` for no rows.
 */
export function integrationsNetwork(rows: PactIntegration[]): PactNetwork | null {
  if (rows.length === 0) return null;
  const names = new Map<string, string>();
  const degree = new Map<string, number>();
  for (const row of rows) {
    names.set(row.consumer, row.consumer_name);
    names.set(row.provider, row.provider_name);
    for (const slug of [row.consumer, row.provider]) degree.set(slug, (degree.get(slug) ?? 0) + 1);
  }
  const centre = [...degree.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0][0];
  // Hops from the centre, breadth first; a pacticipant not connected to it sits one hop further out
  // than the furthest connected one.
  const distance = new Map<string, number>([[centre, 0]]);
  const queue = [centre];
  while (queue.length > 0) {
    const slug = queue.shift() as string;
    for (const row of rows) {
      const next = row.consumer === slug ? row.provider : row.provider === slug ? row.consumer : null;
      if (next && !distance.has(next)) {
        distance.set(next, (distance.get(slug) ?? 0) + 1);
        queue.push(next);
      }
    }
  }
  const furthest = Math.max(...distance.values()) + 1;
  const pacticipants = [...names.entries()]
    .map(([slug, name]) => ({ slug, name, distance: distance.get(slug) ?? furthest }))
    .sort((a, b) => a.distance - b.distance || a.name.localeCompare(b.name));
  const integrations = rows
    .map((row) => ({
      consumer: { slug: row.consumer, name: row.consumer_name },
      provider: { slug: row.provider, name: row.provider_name },
      latestVersion: row.consumer_version,
      publishedAt: row.published_at,
      latestVerification: null,
      verdict: NETWORK_VERDICT[row.verdict] ?? 'unverified',
    }))
    .sort(
      (a, b) =>
        a.consumer.name.localeCompare(b.consumer.name) || a.provider.name.localeCompare(b.provider.name),
    );
  return { centre, pacticipants, integrations };
}
