/**
 * Stale-pact remediation and Pact verification scheduling — PFX-6.2 (#6954): the shared model of
 * the **Verification settings** page, the **Re-publish requests** pages, their `/api/pact/*`
 * proxies, and what the **Verification** page shows of them.
 *
 * Everything here is pure: types mirroring apiome-rest (`app.pact_remediation`), the wording of
 * cadences, request states and notification outcomes, routes and proxy paths, and the checks the
 * proxies run on a body or query before anything reaches REST (an unknown field is a 400 naming it).
 */

import { isPacticipantHandle } from '@lib/pact-pacticipants';

// --- types ----------------------------------------------------------------------------------------

/** When Apiome's hosted verifier runs a pair on its own. */
export type Cadence = 'on-publish' | 'hourly' | 'nightly' | 'manual-only';

/** Where a re-publish request stands. */
export type RequestState = 'requested' | 'acknowledged' | 'republished' | 'cleared' | 'expired';

/** The workspace's verification settings. */
export interface VerificationSettings {
  cadence: Cadence;
  stale_threshold_hours: number;
  max_concurrent_runs: number;
  request_window_hours: number;
  republish_requests_enabled: boolean;
  /** False while the workspace uses the defaults. */
  customised: boolean;
  updated_at: string | null;
}

/** The settings as saved (every field). */
export type SettingsBody = Omit<VerificationSettings, 'customised' | 'updated_at'>;

/** A provider-wide (no consumer) or per-pair override. */
export interface OverrideRecord {
  id: string;
  provider: string;
  provider_name: string;
  consumer: string | null;
  consumer_name: string | null;
  cadence: Cadence | null;
  stale_threshold_hours: number | null;
  target: string | null;
  target_name: string | null;
  target_deleted: boolean;
  updated_at: string | null;
}

/** An override as saved. */
export interface OverrideBody {
  provider: string;
  consumer?: string;
  cadence?: Cadence;
  stale_threshold_hours?: number;
  target_ref?: string;
}

/** What applies to a pair, and where each value came from. */
export interface EffectiveSettings {
  cadence: Cadence;
  cadence_source: 'workspace' | 'provider' | 'pair';
  stale_threshold_hours: number;
  stale_threshold_source: 'workspace' | 'provider' | 'pair';
  target: string | null;
  target_source: 'provider' | 'pair' | null;
}

/** A pair's last scheduled verification attempt. */
export interface ScheduledAttempt {
  pact_version_sha: string;
  attempted_at: string | null;
  status: 'verified' | 'failed' | 'skipped' | 'errored';
  code: string | null;
  reason: string | null;
}

/** A request to a consumer to re-publish a stale pact. */
export interface RepublishRequest {
  id: string;
  provider: string;
  provider_name: string;
  consumer: string;
  consumer_name: string;
  pact_version_sha: string;
  consumer_version: string;
  state: RequestState;
  threshold_hours: number;
  reference_at: string | null;
  requested_at: string | null;
  expires_at: string | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  note: string | null;
  resolved_at: string | null;
  resolved_consumer_version: string | null;
  notification_status: string | null;
  escalation_status: string | null;
  webhook_deliveries: number;
}

/** One page of re-publish requests. */
export interface RepublishRequestPage {
  requests: RepublishRequest[];
  next_cursor: string | null;
}

// --- vocabulary and wording ---------------------------------------------------------------------------

/** Every cadence, in the order the settings list them. */
export const CADENCES: readonly Cadence[] = ['on-publish', 'hourly', 'nightly', 'manual-only'];

/** What each cadence is called, and what it does. */
export const CADENCE_TEXT: Record<Cadence, { label: string; description: string }> = {
  'on-publish': { label: 'On publish', description: 'A newly published pact is verified on the next sweep.' },
  hourly: { label: 'Hourly', description: 'Every hour, and a newly published pact on the next sweep.' },
  nightly: { label: 'Nightly', description: 'Every 24 hours, and a newly published pact on the next sweep.' },
  'manual-only': {
    label: 'Manual only',
    description: 'Apiome never verifies on its own: CI, Re-run and Verify all stale do.',
  },
};

/**
 * A cadence as the page names it.
 *
 * @param cadence - The stored cadence.
 * @returns E.g. `Nightly`.
 */
export function cadenceLabel(cadence: string | null | undefined): string {
  if (!cadence) return 'Inherited';
  return CADENCE_TEXT[cadence as Cadence]?.label ?? cadence;
}

/** Every request state, in lifecycle order. */
export const REQUEST_STATES: readonly RequestState[] = [
  'requested',
  'acknowledged',
  'republished',
  'cleared',
  'expired',
];

/** The states of a request still waiting on the consumer. */
export const OPEN_STATES: readonly RequestState[] = ['requested', 'acknowledged'];

/** Badge variants the request state maps to. */
export type StateVariant = 'warn' | 'accent' | 'ok' | 'neutral' | 'danger';

/** What each state is called and how it is shown. */
export const STATE_TEXT: Record<RequestState, { label: string; variant: StateVariant; description: string }> = {
  requested: { label: 'Requested', variant: 'warn', description: 'Waiting for the consumer to re-publish the pact.' },
  acknowledged: {
    label: 'Acknowledged',
    variant: 'accent',
    description: 'The consumer acknowledged it and will re-publish.',
  },
  republished: { label: 'Re-published', variant: 'ok', description: 'The consumer published the pact again.' },
  cleared: { label: 'Cleared', variant: 'ok', description: 'The provider verified the pact meanwhile.' },
  expired: { label: 'Expired', variant: 'danger', description: 'Its window passed unanswered; it was escalated.' },
};

/**
 * A request state as the page shows it.
 *
 * @param state - The stored state.
 * @returns Its label and badge variant.
 */
export function stateText(state: string): { label: string; variant: StateVariant; description: string } {
  return STATE_TEXT[state as RequestState] ?? { label: state, variant: 'neutral', description: '' };
}

/**
 * Whether a request is still open.
 *
 * @param state - The stored state.
 * @returns True for requested and acknowledged.
 */
export function isOpen(state: string): boolean {
  return (OPEN_STATES as readonly string[]).includes(state);
}

/** What notifying (or escalating) did, as a sentence. */
export const NOTIFICATION_TEXT: Record<string, string> = {
  routed: "Sent to the owner team's inbox.",
  throttled: 'Not sent again: the owner team was notified of this within the hour.',
  unowned: 'No owner team on the pacticipant or what it is bound to: recorded in the Unowned findings report.',
  catch_all: "No confirmed owner: sent to the workspace's catch-all team.",
  // Written before PFX-6.4 gave pacticipants owners; an ownerless pacticipant is now `unowned`.
  unlinked: 'Nobody to notify: the pacticipant is linked to no consumer or project with owners. Webhooks still fired.',
  failed: 'The notification could not be written; see the server log.',
};

/**
 * A notification outcome as a sentence.
 *
 * @param status - The stored outcome, or `null` while it has none.
 * @returns The sentence.
 */
export function notificationText(status: string | null | undefined): string {
  if (!status) return 'Not sent yet.';
  return NOTIFICATION_TEXT[status] ?? status;
}

/** Where an effective value came from. */
export const SOURCE_TEXT: Record<string, string> = {
  workspace: 'workspace default',
  provider: 'provider override',
  pair: 'pair override',
};

/**
 * A threshold in hours as people say it.
 *
 * @param hours - The threshold.
 * @returns `72 h (3 days)`, `12 h`.
 */
export function formatHours(hours: number): string {
  if (hours >= 24 && hours % 24 === 0) {
    const days = hours / 24;
    return `${hours} h (${days} ${days === 1 ? 'day' : 'days'})`;
  }
  return `${hours} h`;
}

// --- routes and proxy paths ------------------------------------------------------------------------

/** The Verification settings page. */
export const SETTINGS_ROUTE = '/ade/dashboard/pacts/settings';
/** The Re-publish requests page. */
export const REQUESTS_ROUTE = '/ade/dashboard/pacts/republish-requests';

/**
 * The Re-publish requests page, optionally narrowed.
 *
 * @param filters - `state` (a state or `open`) and `provider`.
 * @returns The route.
 */
export function requestsRoute(filters: { state?: string | null; provider?: string | null } = {}): string {
  const query = new URLSearchParams();
  if (filters.state) query.set('state', filters.state);
  if (filters.provider) query.set('provider', filters.provider);
  const rendered = query.toString();
  return rendered ? `${REQUESTS_ROUTE}?${rendered}` : REQUESTS_ROUTE;
}

/**
 * One re-publish request's page.
 *
 * @param id - The request's id.
 * @returns The route.
 */
export function requestRoute(id: string): string {
  return `${REQUESTS_ROUTE}/${encodeURIComponent(id)}`;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const CURSOR = /^[0-9]{1,19}$/;

/**
 * Whether a value is a request or override id (a UUID).
 *
 * @param value - The value.
 * @returns True for a UUID.
 */
export function isRecordId(value: string): boolean {
  return UUID.test(value);
}

/** The REST paths below `/v1/tenants/{slug}/` (no leading slash). */
export const SETTINGS_PROXY_PATH = 'pact-verification-settings';
export const OVERRIDES_PROXY_PATH = 'pact-verification-settings/overrides';
export const REQUESTS_PROXY_PATH = 'pact-republish-requests';

/**
 * The REST path of one override.
 *
 * @param id - The override's id (already checked).
 * @returns The path.
 */
export function overrideProxyPath(id: string): string {
  return `${OVERRIDES_PROXY_PATH}/${encodeURIComponent(id)}`;
}

/**
 * The REST path of one request, or of one of its actions.
 *
 * @param id - The request's id (already checked).
 * @param action - E.g. `acknowledge`.
 * @returns The path.
 */
export function requestProxyPath(id: string, action?: string): string {
  const path = `${REQUESTS_PROXY_PATH}/${encodeURIComponent(id)}`;
  return action ? `${path}/${action}` : path;
}

// --- proxy checks -------------------------------------------------------------------------------------

/** A checked body, or why it was refused. */
export type Picked<T> = { ok: true; body: T } | { ok: false; error: string };

/** The numeric settings fields and their ranges. */
export const SETTINGS_RANGES = {
  stale_threshold_hours: [1, 2160],
  max_concurrent_runs: [1, 10],
  request_window_hours: [1, 720],
} as const;

function isRecord(raw: unknown): raw is Record<string, unknown> {
  return typeof raw === 'object' && raw !== null && !Array.isArray(raw);
}

function unknownField(raw: Record<string, unknown>, allowed: readonly string[], what: string): string | null {
  const extra = Object.keys(raw).find((key) => !allowed.includes(key));
  return extra ? `Unsupported field ${extra}: ${what} accepts ${allowed.join(', ')}.` : null;
}

function intIn(value: unknown, [min, max]: readonly [number, number]): boolean {
  return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max;
}

/**
 * Check the body of **Save** on the settings page: every field, in range.
 *
 * @param raw - The parsed JSON body.
 * @returns The body, or the 400's message.
 */
export function pickSettingsBody(raw: unknown): Picked<SettingsBody> {
  if (!isRecord(raw)) return { ok: false, error: 'The body must be a JSON object.' };
  const fields = ['cadence', ...Object.keys(SETTINGS_RANGES), 'republish_requests_enabled'];
  const extra = unknownField(raw, fields, 'the settings');
  if (extra) return { ok: false, error: extra };
  if (!CADENCES.includes(raw.cadence as Cadence)) {
    return { ok: false, error: `cadence must be one of ${CADENCES.join(', ')}.` };
  }
  for (const [key, range] of Object.entries(SETTINGS_RANGES)) {
    if (!intIn(raw[key], range))
      return { ok: false, error: `${key} must be a whole number from ${range[0]} to ${range[1]}.` };
  }
  if (typeof raw.republish_requests_enabled !== 'boolean') {
    return { ok: false, error: 'republish_requests_enabled must be true or false.' };
  }
  return { ok: true, body: raw as unknown as SettingsBody };
}

/**
 * Check the body of **Save override**: a provider handle, an optional consumer handle, and at
 * least one of cadence, threshold and target.
 *
 * @param raw - The parsed JSON body.
 * @returns The body, or the 400's message.
 */
export function pickOverrideBody(raw: unknown): Picked<OverrideBody> {
  if (!isRecord(raw)) return { ok: false, error: 'The body must be a JSON object.' };
  const extra = unknownField(
    raw,
    ['provider', 'consumer', 'cadence', 'stale_threshold_hours', 'target_ref'],
    'an override',
  );
  if (extra) return { ok: false, error: extra };
  if (typeof raw.provider !== 'string' || !isPacticipantHandle(raw.provider)) {
    return { ok: false, error: 'provider must be a pacticipant handle.' };
  }
  const body: OverrideBody = { provider: raw.provider };
  if (raw.consumer !== undefined && raw.consumer !== null) {
    if (typeof raw.consumer !== 'string' || !isPacticipantHandle(raw.consumer)) {
      return { ok: false, error: 'consumer must be a pacticipant handle.' };
    }
    if (raw.consumer === raw.provider) return { ok: false, error: 'A pacticipant cannot be its own consumer.' };
    body.consumer = raw.consumer;
  }
  if (raw.cadence !== undefined && raw.cadence !== null) {
    if (!CADENCES.includes(raw.cadence as Cadence))
      return { ok: false, error: `cadence must be one of ${CADENCES.join(', ')}.` };
    body.cadence = raw.cadence as Cadence;
  }
  if (raw.stale_threshold_hours !== undefined && raw.stale_threshold_hours !== null) {
    if (!intIn(raw.stale_threshold_hours, SETTINGS_RANGES.stale_threshold_hours)) {
      return { ok: false, error: 'stale_threshold_hours must be a whole number from 1 to 2160.' };
    }
    body.stale_threshold_hours = raw.stale_threshold_hours as number;
  }
  if (raw.target_ref !== undefined && raw.target_ref !== null) {
    if (typeof raw.target_ref !== 'string' || !raw.target_ref.trim() || raw.target_ref.length > 200) {
      return { ok: false, error: 'target_ref must be a verification target handle.' };
    }
    body.target_ref = raw.target_ref.trim();
  }
  if (!body.cadence && !body.stale_threshold_hours && !body.target_ref) {
    return { ok: false, error: 'An override sets at least one of cadence, stale_threshold_hours, target_ref.' };
  }
  return { ok: true, body };
}

/** The longest acknowledgement note. */
export const MAX_NOTE_LENGTH = 1000;

/**
 * Check the body of **Acknowledge**: an optional note.
 *
 * @param raw - The parsed JSON body.
 * @returns The body, or the 400's message.
 */
export function pickAcknowledgeBody(raw: unknown): Picked<{ note?: string }> {
  if (!isRecord(raw)) return { ok: false, error: 'The body must be a JSON object.' };
  const extra = unknownField(raw, ['note'], 'an acknowledgement');
  if (extra) return { ok: false, error: extra };
  if (raw.note === undefined || raw.note === null || raw.note === '') return { ok: true, body: {} };
  if (typeof raw.note !== 'string' || raw.note.length > MAX_NOTE_LENGTH) {
    return { ok: false, error: `note must be text of at most ${MAX_NOTE_LENGTH} characters.` };
  }
  return { ok: true, body: { note: raw.note } };
}

/** The filters the request list takes besides `cursor`. */
export const REQUEST_FILTERS = ['provider', 'consumer', 'state'] as const;
/** The page size of the request list. */
export const REQUESTS_PAGE = 25;

/**
 * What is wrong with the request list's query, or `null`.
 *
 * @param params - The browser's query string.
 * @returns The 400's message, or `null`.
 */
export function requestQueryProblem(params: URLSearchParams): string | null {
  const allowed = [...REQUEST_FILTERS, 'cursor'];
  for (const key of new Set(params.keys())) {
    if (!allowed.includes(key)) return `Unsupported parameter ${key}: the list accepts ${allowed.join(', ')}.`;
    if (params.getAll(key).length > 1) return `The ${key} parameter is given more than once.`;
    const value = params.get(key) ?? '';
    if (!value) return `The ${key} parameter is empty.`;
    if ((key === 'provider' || key === 'consumer') && !isPacticipantHandle(value)) {
      return `The ${key} parameter is not a pacticipant handle.`;
    }
    if (key === 'state' && value !== 'open' && !(REQUEST_STATES as readonly string[]).includes(value)) {
      return `The state parameter must be open or one of ${REQUEST_STATES.join(', ')}.`;
    }
    if (key === 'cursor' && !CURSOR.test(value)) return 'The cursor parameter is not one this list handed out.';
  }
  return null;
}

/**
 * The REST path of one page of the request list.
 *
 * @param params - The checked query.
 * @returns The path with the filters, the cursor and the page size.
 */
export function requestsListPath(params: URLSearchParams): string {
  const query = new URLSearchParams();
  for (const key of [...REQUEST_FILTERS, 'cursor']) {
    const value = params.get(key);
    if (value) query.set(key, value);
  }
  query.set('limit', String(REQUESTS_PAGE));
  return `${REQUESTS_PROXY_PATH}?${query.toString()}`;
}
