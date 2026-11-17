/**
 * API plans in the UI — APX-1.2 (#6099).
 *
 * A plan is a tier of an API product (apiome-rest `/v1/tenants/{t}/products/{p}/plans`): how a
 * consumer authenticates, the request limits it promises, whether a subscription is approved
 * automatically, the gateway environments it is provisioned to and its terms. This module holds the
 * wire types, the words the editor uses for each value, the body fields the proxy forwards, and the
 * pure rules the Plans section shares: the draft ↔ wire mapping and the checks that run before a save
 * (limits positive, every window once).
 */

export const PLAN_AUTH_STRATEGIES = ['key_auth', 'oauth2_client_credentials', 'mtls', 'none'] as const;
export type PlanAuthStrategy = (typeof PLAN_AUTH_STRATEGIES)[number];

export const PLAN_LIMIT_WINDOWS = ['second', 'minute', 'hour', 'day', 'month'] as const;
export type PlanLimitWindow = (typeof PLAN_LIMIT_WINDOWS)[number];

export const PLAN_APPROVALS = ['manual', 'auto'] as const;
export type PlanApproval = (typeof PLAN_APPROVALS)[number];

export const PLAN_STATES = ['draft', 'published', 'deprecated', 'retired'] as const;
export type PlanState = (typeof PLAN_STATES)[number];

/** How each auth strategy reads, and what it asks of a consumer. */
export const AUTH_STRATEGY_LABELS: Readonly<Record<PlanAuthStrategy, { label: string; hint: string }>> = {
  key_auth: { label: 'API key', hint: 'Consumers send a key in a header. Members should declare an API key scheme.' },
  oauth2_client_credentials: {
    label: 'OAuth2 client credentials',
    hint: 'Consumers get a client id and secret from your identity provider.',
  },
  mtls: { label: 'Mutual TLS', hint: 'Consumers present a client certificate.' },
  none: { label: 'None', hint: 'Open access. Limits still apply per consumer where the gateway can tell them apart.' },
};

/** How each limit window reads after a count (`100 / minute`). */
export const WINDOW_LABELS: Readonly<Record<PlanLimitWindow, string>> = {
  second: 'second',
  minute: 'minute',
  hour: 'hour',
  day: 'day',
  month: 'month',
};

/** How each approval mode reads, and what it means. */
export const APPROVAL_LABELS: Readonly<Record<PlanApproval, { label: string; hint: string }>> = {
  manual: { label: 'Manual', hint: 'A person approves each subscription request.' },
  auto: { label: 'Automatic', hint: 'Subscription requests are approved at once.' },
};

/** How each plan state reads. */
export const PLAN_STATE_LABELS: Readonly<Record<PlanState, string>> = {
  draft: 'Draft',
  published: 'Published',
  deprecated: 'Deprecated',
  retired: 'Retired',
};

/** One declared limit: `requests` per `window`. */
export interface PlanLimit {
  window: PlanLimitWindow;
  requests: number;
}

/** The strategy's settings — names and ids only. */
export interface PlanAuthConfig {
  header_name?: string | null;
  idp_config_id?: string | null;
  scopes?: string[];
}

/** One gateway environment a plan is provisioned to. */
export interface PlanEnvironment {
  id: string;
  slug: string | null;
  name: string | null;
  environment: string | null;
  connector_kind: string | null;
  can_provision: boolean;
  missing: boolean;
}

/** A notice or warning about a plan. */
export interface PlanNotice {
  code: string;
  message: string;
  member?: { kind: string; ref: string; name: string | null } | null;
}

/** One plan, as REST returns it. */
export interface ApiPlan {
  id: string;
  product: string;
  slug: string;
  name: string;
  description: string | null;
  auth_strategy: PlanAuthStrategy;
  auth_config: PlanAuthConfig;
  limits: PlanLimit[];
  concurrency: number | null;
  approval: PlanApproval;
  environments: PlanEnvironment[];
  declared_only: boolean;
  credential_ttl_days: number | null;
  terms_url: string | null;
  pricing_note: string | null;
  billing_ref: string | null;
  state: PlanState;
  notices: PlanNotice[];
  warnings: PlanNotice[];
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

/** A plan to create, or (without `slug`) the fields a save sends. */
export interface ApiPlanInput {
  name: string;
  slug?: string;
  description: string | null;
  auth_strategy: PlanAuthStrategy;
  auth_config: PlanAuthConfig;
  limits: PlanLimit[];
  concurrency: number | null;
  approval: PlanApproval;
  environments: string[];
  credential_ttl_days: number | null;
  terms_url: string | null;
  pricing_note: string | null;
  billing_ref: string | null;
  state: PlanState;
}

/** The body fields a plan create may carry; a patch carries the same minus `slug`. */
export const PLAN_CREATE_FIELDS = [
  'name',
  'slug',
  'description',
  'auth_strategy',
  'auth_config',
  'limits',
  'concurrency',
  'approval',
  'environments',
  'credential_ttl_days',
  'terms_url',
  'pricing_note',
  'billing_ref',
  'state',
] as const;
export const PLAN_PATCH_FIELDS = PLAN_CREATE_FIELDS.filter((field) => field !== 'slug');

/** One limit row in the editor: the count is what the input holds. */
export interface PlanLimitDraft {
  window: PlanLimitWindow;
  requests: string;
}

/** The editor's values, as the inputs hold them. */
export interface PlanDraft {
  name: string;
  slug: string;
  description: string;
  auth_strategy: PlanAuthStrategy;
  header_name: string;
  idp_config_id: string;
  /** Scopes, separated by spaces or commas. */
  scopes: string;
  limits: PlanLimitDraft[];
  concurrency: string;
  approval: PlanApproval;
  /** Gateway config slugs. */
  environments: string[];
  credential_ttl_days: string;
  terms_url: string;
  pricing_note: string;
  billing_ref: string;
  state: PlanState;
}

/**
 * The editor's values for a new plan: an API key plan, 100 requests a minute, approved by a person.
 *
 * @returns The draft.
 */
export function emptyPlanDraft(): PlanDraft {
  return {
    name: '',
    slug: '',
    description: '',
    auth_strategy: 'key_auth',
    header_name: '',
    idp_config_id: '',
    scopes: '',
    limits: [{ window: 'minute', requests: '100' }],
    concurrency: '',
    approval: 'manual',
    environments: [],
    credential_ttl_days: '',
    terms_url: '',
    pricing_note: '',
    billing_ref: '',
    state: 'draft',
  };
}

/**
 * The editor's values for a stored plan.
 *
 * @param plan - The plan.
 * @returns The draft (environments that are gone are dropped).
 */
export function draftFromPlan(plan: ApiPlan): PlanDraft {
  return {
    name: plan.name,
    slug: plan.slug,
    description: plan.description ?? '',
    auth_strategy: plan.auth_strategy,
    header_name: plan.auth_config.header_name ?? '',
    idp_config_id: plan.auth_config.idp_config_id ?? '',
    scopes: (plan.auth_config.scopes ?? []).join(' '),
    limits: plan.limits.map((limit) => ({ window: limit.window, requests: String(limit.requests) })),
    concurrency: plan.concurrency === null ? '' : String(plan.concurrency),
    approval: plan.approval,
    environments: plan.environments.filter((env) => !env.missing && env.slug).map((env) => env.slug as string),
    credential_ttl_days: plan.credential_ttl_days === null ? '' : String(plan.credential_ttl_days),
    terms_url: plan.terms_url ?? '',
    pricing_note: plan.pricing_note ?? '',
    billing_ref: plan.billing_ref ?? '',
    state: plan.state,
  };
}

/** A whole number of at least 1, as typed. */
const POSITIVE_INT = /^[1-9][0-9]*$/;
/** An absolute http(s) URL. */
const HTTP_URL = /^https?:\/\/[^\s/]+\S*$/i;

/**
 * Check the limit rows: every count a positive whole number and every window once.
 *
 * @param limits - The rows.
 * @returns The message to show, or `null` when they can be sent.
 */
export function planLimitsError(limits: readonly PlanLimitDraft[]): string | null {
  const seen = new Set<PlanLimitWindow>();
  for (const limit of limits) {
    if (!POSITIVE_INT.test(limit.requests.trim())) {
      return `The ${limit.window} limit needs a whole number of requests, at least 1.`;
    }
    if (seen.has(limit.window)) return `The ${limit.window} window is limited twice; give each window one limit.`;
    seen.add(limit.window);
  }
  return null;
}

/**
 * Check the draft before it is sent.
 *
 * @param draft - The editor's values.
 * @returns The message to show, or `null` when the plan can be saved.
 */
export function planDraftError(draft: PlanDraft): string | null {
  if (!draft.name.trim()) return 'A plan needs a name.';
  const limits = planLimitsError(draft.limits);
  if (limits) return limits;
  if (draft.concurrency.trim() && !POSITIVE_INT.test(draft.concurrency.trim())) {
    return 'Concurrency must be a whole number, at least 1.';
  }
  const ttl = draft.credential_ttl_days.trim();
  if (ttl && (!POSITIVE_INT.test(ttl) || Number(ttl) > 3650)) {
    return 'Maximum key age must be a whole number of days, from 1 to 3650.';
  }
  if (draft.terms_url.trim() && !HTTP_URL.test(draft.terms_url.trim())) {
    return 'The terms URL must start with http:// or https://.';
  }
  return null;
}

/**
 * Turn an optional typed number into its wire value.
 *
 * @param value - What the input holds.
 * @returns The number, or `null` when empty.
 */
function optionalNumber(value: string): number | null {
  return value.trim() ? Number(value.trim()) : null;
}

/**
 * The body a save sends: every field, typed, with only the strategy's own auth settings.
 *
 * @param draft - The editor's values (already checked by {@link planDraftError}).
 * @param includeSlug - True for a create (the slug is sent when typed).
 * @returns The body.
 */
export function draftToInput(draft: PlanDraft, includeSlug: boolean): ApiPlanInput {
  const auth_config: PlanAuthConfig = {};
  if (draft.auth_strategy === 'key_auth' && draft.header_name.trim()) auth_config.header_name = draft.header_name.trim();
  if (draft.auth_strategy === 'oauth2_client_credentials') {
    if (draft.idp_config_id.trim()) auth_config.idp_config_id = draft.idp_config_id.trim();
    const scopes = draft.scopes.split(/[\s,]+/).filter(Boolean);
    if (scopes.length) auth_config.scopes = Array.from(new Set(scopes));
  }
  const input: ApiPlanInput = {
    name: draft.name.trim(),
    description: draft.description.trim() || null,
    auth_strategy: draft.auth_strategy,
    auth_config,
    limits: draft.limits.map((limit) => ({ window: limit.window, requests: Number(limit.requests.trim()) })),
    concurrency: optionalNumber(draft.concurrency),
    approval: draft.approval,
    environments: [...draft.environments],
    credential_ttl_days: optionalNumber(draft.credential_ttl_days),
    terms_url: draft.terms_url.trim() || null,
    pricing_note: draft.pricing_note.trim() || null,
    billing_ref: draft.billing_ref.trim() || null,
    state: draft.state,
  };
  if (includeSlug && draft.slug.trim()) input.slug = draft.slug.trim().toLowerCase();
  return input;
}

/**
 * How a plan's limits read: `100 / minute · 50,000 / day · 10 in flight`.
 *
 * @param plan - The plan's limits and concurrency.
 * @returns The text, or `No limits` when there are none.
 */
export function limitsText(plan: Pick<ApiPlan, 'limits' | 'concurrency'>): string {
  const parts = plan.limits.map((limit) => `${limit.requests.toLocaleString('en-US')} / ${WINDOW_LABELS[limit.window]}`);
  if (plan.concurrency) parts.push(`${plan.concurrency.toLocaleString('en-US')} in flight`);
  return parts.length ? parts.join(' · ') : 'No limits';
}

/**
 * The windows a new limit row may take: those not limited yet, shortest first.
 *
 * @param limits - The rows so far.
 * @returns The free windows.
 */
export function freeWindows(limits: readonly PlanLimitDraft[]): PlanLimitWindow[] {
  const used = new Set(limits.map((limit) => limit.window));
  return PLAN_LIMIT_WINDOWS.filter((window) => !used.has(window));
}
