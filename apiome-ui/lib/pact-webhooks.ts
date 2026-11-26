/**
 * Webhooks UI and execution log — PFX-5.6 (#6950).
 *
 * The model of the **Webhooks** pages: the shapes REST answers with (the Pact Broker's webhook
 * routes under `/v1/tenants/{t}/pact-broker/webhooks`, PFX-1.9, and Apiome's delivery log under
 * `/v1/tenants/{t}/pact-webhook-deliveries`), the paths the `/api/pact/webhooks/*` proxies forward
 * to, the checks those proxies run on what the browser sends, the editor's form and the webhook
 * body it becomes, and the wording the pages show — events, statuses, scopes, targets and the
 * plain-text log a reader copies.
 *
 * **Secrets never leave REST.** A stored password, token, secret header or signing secret reads
 * as {@link REDACTED}; the editor shows that placeholder and sends it back unchanged to keep the
 * stored value. Typing a new value replaces it; clearing it removes it.
 *
 * Everything here is pure, so the proxies, the pages and the tests share it.
 */

import { MAX_CURSOR_LENGTH, RollupError, type RestReader } from '@lib/pact-pacticipants';

// --- shapes REST answers with -----------------------------------------------------------------------

/** What a stored secret reads as, and what is sent back to keep it. */
export const REDACTED = '**********';

/** The target type of a GitHub Actions `repository_dispatch` webhook. */
export const GITHUB_TARGET = 'github_repository_dispatch';

/** The methods a webhook may use. */
export const WEBHOOK_METHODS = ['POST', 'PUT', 'PATCH'] as const;

/** A webhook, as the Pact Broker's routes render it (no secret in it). */
export interface WebhookDocument {
  uuid: string;
  description: string;
  consumer?: { name: string };
  provider?: { name: string };
  enabled: boolean;
  request: {
    method: string;
    url: string;
    headers?: Record<string, string>;
    body?: unknown;
    username?: string;
    password?: string;
  };
  target?: {
    type: string;
    repository: string;
    eventType?: string;
    clientPayload?: Record<string, unknown>;
    apiUrl?: string;
    token?: string;
  };
  events: Array<{ name: string }>;
  signed: boolean;
  createdAt?: string | null;
  updatedAt?: string | null;
}

/** How a firing stands. */
export type DeliveryStatus = 'success' | 'failure' | 'retrying' | 'not_run';

/** One firing of a webhook, as the delivery log lists it. */
export interface WebhookDelivery {
  id: string;
  webhookId: string;
  name: string;
  status: DeliveryStatus | string;
  attemptsMade: number;
  attemptsRemaining: number;
  triggerType: string;
  eventName: string;
  consumer: { name: string; slug: string };
  provider: { name: string; slug: string };
  consumerVersionNumber: string | null;
  pactVersionSha: string | null;
  verificationNumber: number | null;
  triggeredAt: string | null;
}

/** One attempt of a firing. */
export interface DeliveryExecution {
  attempt: number;
  success: boolean;
  status: number | null;
  logs: string;
  createdAt: string | null;
}

/** One firing and its attempts. */
export interface DeliveryDetail extends WebhookDelivery {
  executions: DeliveryExecution[];
}

/** One page of a delivery log. */
export interface DeliveryPage {
  deliveries: WebhookDelivery[];
  nextCursor: string | null;
}

/** The Webhooks page's read: every webhook and the newest firing of each. */
export interface WebhooksOverview {
  webhooks: WebhookDocument[];
  latest: Record<string, WebhookDelivery>;
}

/** The outcome of a test run (`…/execute`), as the Pact Broker renders it. */
export interface ExecutionResult {
  request: { headers?: Record<string, string>; body?: unknown; url?: string };
  response?: { status: number; headers?: Record<string, string>; body?: unknown };
  error?: { message: string };
  logs: string;
  success: boolean;
}

// --- routes and proxy paths -------------------------------------------------------------------------

/** The route of the Webhooks page. */
export const WEBHOOKS_ROUTE = '/ade/dashboard/pacts/webhooks';

/**
 * The route of one webhook's page.
 *
 * @param id - The webhook's `uuid`.
 * @returns E.g. `/ade/dashboard/pacts/webhooks/4444…`.
 */
export function webhookRoute(id: string): string {
  return `${WEBHOOKS_ROUTE}/${encodeURIComponent(id)}`;
}

/**
 * The route of one delivery's page.
 *
 * @param id - The firing's `uuid`.
 * @returns E.g. `/ade/dashboard/pacts/webhooks/deliveries/5555…`.
 */
export function deliveryRoute(id: string): string {
  return `${WEBHOOKS_ROUTE}/deliveries/${encodeURIComponent(id)}`;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Whether a value is a webhook or delivery id (a UUID). A proxy answers 404 for anything else
 * without calling REST.
 *
 * @param value - The candidate.
 * @returns True for a UUID.
 */
export function isWebhookId(value: string): boolean {
  return UUID.test(value);
}

/** The REST path of the webhook collection (the broker surface). */
export const WEBHOOKS_PROXY_PATH = 'pact-broker/webhooks';

/** The REST path that runs an unsaved webhook once. */
export const UNSAVED_EXECUTE_PROXY_PATH = 'pact-broker/webhooks/execute';

/** The REST path of the newest firing of each webhook. */
export const LATEST_PROXY_PATH = 'pact-webhook-deliveries/latest';

/** The REST path of the delivery log. */
export const DELIVERIES_PROXY_PATH = 'pact-webhook-deliveries';

/** The REST path of one webhook (an already checked id). */
export function webhookProxyPath(id: string): string {
  return `${WEBHOOKS_PROXY_PATH}/${id.toLowerCase()}`;
}

/** The REST path that runs a saved webhook once. */
export function executeProxyPath(id: string): string {
  return `${webhookProxyPath(id)}/execute`;
}

/** The REST path of one firing. */
export function deliveryProxyPath(id: string): string {
  return `${DELIVERIES_PROXY_PATH}/${id.toLowerCase()}`;
}

/** The REST path that sends a firing again. */
export function redeliverProxyPath(id: string): string {
  return `${deliveryProxyPath(id)}/redeliver`;
}

/** The delivery log's page size. */
export const DELIVERY_PAGE = 25;

/** Every status, in the order the filter lists them. */
export const DELIVERY_STATUSES: readonly DeliveryStatus[] = ['failure', 'retrying', 'not_run', 'success'];

/** The filters the delivery-log proxy accepts besides `cursor`. */
export const DELIVERY_FILTERS = ['webhook', 'status'] as const;

/**
 * Why a delivery-log query cannot be forwarded, or `null` when it can. Unknown, repeated and empty
 * parameters are refused by `pickListQuery`; this checks the values.
 *
 * @param params - The picked parameters.
 * @returns The reason for a 400, or `null`.
 */
export function deliveryQueryProblem(params: URLSearchParams): string | null {
  const webhook = params.get('webhook');
  if (webhook !== null && !isWebhookId(webhook)) return 'The webhook parameter is not a webhook id.';
  const status = params.get('status');
  if (status !== null && !(DELIVERY_STATUSES as readonly string[]).includes(status)) {
    return `The status parameter must be one of ${DELIVERY_STATUSES.join(', ')}.`;
  }
  const cursor = params.get('cursor');
  if (cursor !== null && cursor.length > MAX_CURSOR_LENGTH) return 'The cursor is not valid.';
  return null;
}

// --- the proxies' body check ------------------------------------------------------------------------

/** The top-level fields of a webhook body. */
export const WEBHOOK_FIELDS = [
  'description',
  'consumer',
  'provider',
  'enabled',
  'events',
  'request',
  'target',
  'signingSecret',
] as const;

/** A body to forward, or why it is refused. */
export type PickedWebhookBody = { ok: true; body: Record<string, unknown> } | { ok: false; error: string };

/**
 * Check what the browser sends to create, replace or test a webhook. The body must be a JSON
 * object of {@link WEBHOOK_FIELDS} — any other field is refused with its name, never dropped.
 * The values are REST's to check (a `422` names the field).
 *
 * @param raw - The parsed body.
 * @returns The body to forward, or the reason for a 400.
 */
export function pickWebhookBody(raw: unknown): PickedWebhookBody {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return { ok: false, error: 'The body must be a JSON object describing the webhook.' };
  }
  const body = raw as Record<string, unknown>;
  for (const key of Object.keys(body)) {
    if (!(WEBHOOK_FIELDS as readonly string[]).includes(key)) {
      return { ok: false, error: `Unsupported field ${key}: a webhook takes ${WEBHOOK_FIELDS.join(', ')}.` };
    }
  }
  if (body.request === undefined && body.target === undefined) {
    return { ok: false, error: 'A webhook needs a request or a target.' };
  }
  return { ok: true, body };
}

// --- events, statuses and labels --------------------------------------------------------------------

/** One event a webhook can fire on. */
export interface EventOption {
  name: string;
  label: string;
  description: string;
}

/** Every event, in the order the editor lists them. */
export const EVENT_OPTIONS: readonly EventOption[] = [
  {
    name: 'contract_requiring_verification_published',
    label: 'Contract requiring verification published',
    description: 'Once per provider version that has to verify a new pact: the main branch head and what is deployed.',
  },
  {
    name: 'contract_content_changed',
    label: 'Contract content changed',
    description: 'A pact whose content differs from the previous one on its branch.',
  },
  { name: 'contract_published', label: 'Contract published', description: 'Every pact publication.' },
  {
    name: 'provider_verification_published',
    label: 'Provider verification published',
    description: 'Every verification result.',
  },
  {
    name: 'provider_verification_succeeded',
    label: 'Provider verification succeeded',
    description: 'A verification result that passed.',
  },
  {
    name: 'provider_verification_failed',
    label: 'Provider verification failed',
    description: 'A verification result that failed.',
  },
  {
    name: 'consumer_version_branch_created',
    label: 'Consumer version branch created',
    description: 'A publication on a branch the consumer did not have before.',
  },
  {
    name: 'contract_became_stale',
    label: 'Contract became stale',
    description: 'A pact went unverified for longer than its stale threshold.',
  },
  {
    name: 'contract_no_longer_stale',
    label: 'Contract no longer stale',
    description: 'A stale pact was verified, or a newer one replaced it.',
  },
  {
    name: 'contract_republish_requested',
    label: 'Re-publish requested',
    description: 'The consumer of a stale pact was asked to re-publish it.',
  },
  {
    name: 'contract_republish_request_expired',
    label: 'Re-publish request expired',
    description: 'A re-publish request went unanswered for its window and was escalated.',
  },
];

/**
 * An event's label.
 *
 * @param name - The event name.
 * @returns E.g. `Contract published`; an unknown name as it is.
 */
export function eventLabel(name: string): string {
  return EVENT_OPTIONS.find((option) => option.name === name)?.label ?? name;
}

/** How each status reads, and the badge tone it is shown in. */
export const DELIVERY_STATUS_LABELS: Record<DeliveryStatus, { label: string; variant: 'ok' | 'danger' | 'warn' | 'neutral' }> = {
  success: { label: 'Delivered', variant: 'ok' },
  failure: { label: 'Failed', variant: 'danger' },
  retrying: { label: 'Retrying', variant: 'warn' },
  not_run: { label: 'Queued', variant: 'neutral' },
};

/**
 * A status's label and tone.
 *
 * @param status - The status REST gave.
 * @returns The label and tone; an unknown status as it is, neutral.
 */
export function deliveryStatus(status: string): { label: string; variant: 'ok' | 'danger' | 'warn' | 'neutral' } {
  return DELIVERY_STATUS_LABELS[status as DeliveryStatus] ?? { label: status, variant: 'neutral' };
}

/**
 * How a firing was triggered.
 *
 * @param triggerType - `resource_creation` or `user`.
 * @returns `Event` or `Redelivery`.
 */
export function triggerTypeLabel(triggerType: string): string {
  if (triggerType === 'user') return 'Redelivery';
  if (triggerType === 'resource_creation') return 'Event';
  return triggerType;
}

/**
 * Whether a firing can be sent again: only a finished one (delivered or failed).
 *
 * @param status - Its status.
 * @returns True when **Redeliver** applies.
 */
export function canRedeliver(status: string): boolean {
  return status === 'success' || status === 'failure';
}

/**
 * Which pacts a webhook is for.
 *
 * @param webhook - The webhook.
 * @returns `All pacts`, `Consumer X`, `Provider Y` or `X → Y`.
 */
export function scopeLabel(webhook: Pick<WebhookDocument, 'consumer' | 'provider'>): string {
  const consumer = webhook.consumer?.name;
  const provider = webhook.provider?.name;
  if (consumer && provider) return `${consumer} → ${provider}`;
  if (consumer) return `Consumer ${consumer}`;
  if (provider) return `Provider ${provider}`;
  return 'All pacts';
}

/**
 * Where a webhook sends.
 *
 * @param webhook - The webhook.
 * @returns `GitHub Actions · owner/name`, or `POST ci.example.com`.
 */
export function targetLabel(webhook: Pick<WebhookDocument, 'target' | 'request'>): string {
  if (webhook.target?.type === GITHUB_TARGET) return `GitHub Actions · ${webhook.target.repository}`;
  let host = webhook.request.url;
  try {
    host = new URL(webhook.request.url).host;
  } catch {
    // Keep the URL as given.
  }
  return `${webhook.request.method} ${host}`;
}

/**
 * The plain-text log of a firing, every attempt in order, for **Copy**.
 *
 * @param detail - The firing.
 * @returns The text.
 */
export function renderDeliveryLog(detail: DeliveryDetail): string {
  const head = [
    `${eventLabel(detail.eventName)} — ${detail.consumer.name} → ${detail.provider.name}`,
    `Webhook ${detail.name} · ${deliveryStatus(detail.status).label} · ${detail.attemptsMade} attempt${detail.attemptsMade === 1 ? '' : 's'}`,
  ];
  if (detail.executions.length === 0) return [...head, '', 'Not sent yet.'].join('\n');
  const attempts = detail.executions.map((execution) =>
    [`--- Attempt ${execution.attempt}${execution.status ? ` · HTTP ${execution.status}` : ''} ---`, execution.logs].join('\n'),
  );
  return [...head, '', ...attempts].join('\n');
}

/** The CLI command an empty Webhooks page shows. */
export const CREATE_WEBHOOK_SNIPPET = [
  'apiome pact create-webhook https://ci.example.com/hooks/verify-pact \\',
  '  --request POST --provider "Ledger API" \\',
  '  --contract-requiring-verification-published \\',
  '  --header "Content-Type: application/json" \\',
  `  --data '{"pactUrl": "\${pactbroker.pactUrl}"}'`,
].join('\n');

// --- the editor -------------------------------------------------------------------------------------

/** What the editor holds. Text fields hold what the person typed; secrets may hold {@link REDACTED}. */
export interface WebhookForm {
  description: string;
  consumer: string;
  provider: string;
  events: string[];
  enabled: boolean;
  kind: 'http' | 'github';
  method: string;
  url: string;
  /** One `Name: value` per line. */
  headers: string;
  /** JSON (sent as JSON) or text (sent as text). */
  body: string;
  username: string;
  password: string;
  repository: string;
  eventType: string;
  apiUrl: string;
  token: string;
  signingSecret: string;
}

/** The editor for a new webhook. */
export function emptyWebhookForm(): WebhookForm {
  return {
    description: '',
    consumer: '',
    provider: '',
    events: ['contract_requiring_verification_published'],
    enabled: true,
    kind: 'http',
    method: 'POST',
    url: '',
    headers: 'Content-Type: application/json',
    body: '{\n  "pactUrl": "${pactbroker.pactUrl}"\n}',
    username: '',
    password: '',
    repository: '',
    eventType: '',
    apiUrl: '',
    token: '',
    signingSecret: '',
  };
}

/**
 * What REST names a webhook without a description: `POST host` (template parameters in the URL
 * read as `placeholder`, as REST does).
 *
 * @param request - The webhook's method and URL.
 * @returns The name.
 */
export function requestDescription(request: { method: string; url: string }): string {
  let host = '';
  try {
    host = new URL(request.url.replace(/\$\{pactbroker\.[A-Za-z]+\}/g, 'placeholder')).hostname;
  } catch {
    host = '';
  }
  return `${request.method.toUpperCase()} ${host}`.trim();
}

/** A body as the editor shows it: JSON pretty-printed, text as it is. */
function bodyText(body: unknown): string {
  if (body === undefined || body === null) return '';
  return typeof body === 'string' ? body : JSON.stringify(body, null, 2);
}

/**
 * The editor for an existing webhook. Secrets read {@link REDACTED}, so saving without touching
 * them keeps the stored values.
 *
 * @param webhook - The webhook as REST rendered it.
 * @returns The form.
 */
export function formFromWebhook(webhook: WebhookDocument): WebhookForm {
  const form = emptyWebhookForm();
  const github = webhook.target?.type === GITHUB_TARGET;
  // A webhook saved without a description reads as its request (`POST host`); saving that back
  // would store it as one, so it starts empty.
  const described = webhook.description && webhook.description !== requestDescription(webhook.request);
  return {
    ...form,
    description: described ? webhook.description : '',
    consumer: webhook.consumer?.name ?? '',
    provider: webhook.provider?.name ?? '',
    events: webhook.events.map((event) => event.name),
    enabled: webhook.enabled,
    kind: github ? 'github' : 'http',
    method: webhook.request.method,
    url: github ? '' : webhook.request.url,
    headers: github
      ? ''
      : Object.entries(webhook.request.headers ?? {})
          .map(([name, value]) => `${name}: ${value}`)
          .join('\n'),
    body: github ? '' : bodyText(webhook.request.body),
    username: webhook.request.username ?? '',
    password: webhook.request.password ? REDACTED : '',
    repository: webhook.target?.repository ?? '',
    eventType: webhook.target?.eventType ?? '',
    apiUrl: webhook.target?.apiUrl ?? '',
    token: github ? REDACTED : '',
    signingSecret: webhook.signed ? REDACTED : '',
  };
}

/** The headers of the form, or why a line cannot be read. */
export function parseHeaders(text: string): { ok: true; headers: Record<string, string> } | { ok: false; error: string } {
  const headers: Record<string, string> = {};
  const lines = text.split('\n').map((line) => line.trim());
  for (const [index, line] of lines.entries()) {
    if (!line) continue;
    const colon = line.indexOf(':');
    const name = colon > 0 ? line.slice(0, colon).trim() : '';
    if (!name) return { ok: false, error: `Header line ${index + 1} is not "Name: value".` };
    if (Object.keys(headers).some((existing) => existing.toLowerCase() === name.toLowerCase())) {
      return { ok: false, error: `The header ${name} is given more than once.` };
    }
    headers[name] = line.slice(colon + 1).trim();
  }
  return { ok: true, headers };
}

/** The body of the form: JSON when it parses as JSON, the text otherwise, nothing when empty. */
export function parseBody(text: string): unknown {
  const trimmed = text.trim();
  if (!trimmed) return undefined;
  try {
    return JSON.parse(trimmed);
  } catch {
    return text;
  }
}

const REPOSITORY = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9._-]{1,100}$/;

/**
 * Why the form cannot be saved yet, or `null`. REST checks everything again (and more — the host
 * must be public); this catches what a person can fix before sending.
 *
 * @param form - The form.
 * @returns The first problem, or `null`.
 */
export function webhookFormProblem(form: WebhookForm): string | null {
  if (form.events.length === 0) return 'Choose at least one event.';
  if (form.kind === 'http') {
    let url: URL | null = null;
    try {
      url = new URL(form.url.trim());
    } catch {
      url = null;
    }
    if (!url || (url.protocol !== 'http:' && url.protocol !== 'https:')) return 'Enter the http(s) URL to send to.';
    if (!(WEBHOOK_METHODS as readonly string[]).includes(form.method)) return 'Choose POST, PUT or PATCH.';
    const headers = parseHeaders(form.headers);
    if (!headers.ok) return headers.error;
    if (form.password && !form.username.trim()) return 'A password needs a username.';
  } else {
    if (!REPOSITORY.test(form.repository.trim())) return 'Enter the GitHub repository as owner/name.';
    if (!form.token) return 'Enter a GitHub token that may dispatch events to the repository.';
  }
  if (form.signingSecret && form.signingSecret !== REDACTED && form.signingSecret.length < 16) {
    return 'A signing secret has at least 16 characters.';
  }
  return null;
}

/**
 * The webhook body the form stands for — the Pact Broker's shape, with Apiome's `target` for a
 * GitHub dispatch and `signingSecret`.
 *
 * @param form - A form {@link webhookFormProblem} accepts.
 * @returns The body to `POST` or `PUT`.
 */
export function webhookBodyFromForm(form: WebhookForm): Record<string, unknown> {
  const body: Record<string, unknown> = {
    events: form.events.map((name) => ({ name })),
    enabled: form.enabled,
  };
  if (form.description.trim()) body.description = form.description.trim();
  if (form.consumer.trim()) body.consumer = { name: form.consumer.trim() };
  if (form.provider.trim()) body.provider = { name: form.provider.trim() };
  if (form.kind === 'github') {
    const target: Record<string, unknown> = {
      type: GITHUB_TARGET,
      repository: form.repository.trim(),
      token: form.token,
    };
    if (form.eventType.trim()) target.eventType = form.eventType.trim();
    if (form.apiUrl.trim()) target.apiUrl = form.apiUrl.trim();
    body.target = target;
  } else {
    const parsed = parseHeaders(form.headers);
    const request: Record<string, unknown> = { method: form.method, url: form.url.trim() };
    if (parsed.ok && Object.keys(parsed.headers).length > 0) request.headers = parsed.headers;
    const content = parseBody(form.body);
    if (content !== undefined) request.body = content;
    if (form.username.trim()) request.username = form.username.trim();
    if (form.password) request.password = form.password;
    body.request = request;
  }
  if (form.signingSecret) body.signingSecret = form.signingSecret;
  return body;
}

/**
 * The body that turns a webhook on or off and keeps everything else, secrets included (each
 * redacted secret is sent back as {@link REDACTED}).
 *
 * @param webhook - The webhook as REST rendered it.
 * @param enabled - The new state.
 * @returns The body to `PUT`.
 */
export function toggleBody(webhook: WebhookDocument, enabled: boolean): Record<string, unknown> {
  return webhookBodyFromForm({ ...formFromWebhook(webhook), enabled });
}

// --- the overview roll-up ---------------------------------------------------------------------------

/** REST's message from a refusal (`detail` string or `detail.message`), or the fallback. */
function refusal(body: unknown, fallback: string): string {
  const detail = body && typeof body === 'object' ? (body as Record<string, unknown>).detail : undefined;
  if (typeof detail === 'string' && detail) return detail;
  if (detail && typeof detail === 'object') {
    const message = (detail as Record<string, unknown>).message;
    if (typeof message === 'string' && message) return message;
  }
  return fallback;
}

/**
 * The Webhooks page's read: every webhook (the broker's list) and the newest firing of each.
 * Both reads must succeed — a list without its deliveries would claim webhooks never fired.
 *
 * @param read - Reads a path below `/v1/tenants/{slug}` as the signed-in user.
 * @returns The webhooks, oldest first, and `latest` keyed by webhook `uuid`.
 * @throws RollupError with REST's status and message when either read is refused.
 */
export async function collectWebhooks(read: RestReader): Promise<WebhooksOverview> {
  const [list, latest] = await Promise.all([read(WEBHOOKS_PROXY_PATH), read(LATEST_PROXY_PATH)]);
  if (!list.ok) throw new RollupError(list.status, refusal(list.body, `HTTP ${list.status}`));
  if (!latest.ok) throw new RollupError(latest.status, refusal(latest.body, `HTTP ${latest.status}`));
  const embedded = (list.body as { _embedded?: { webhooks?: unknown } } | null)?._embedded?.webhooks;
  const newest = (latest.body as { latest?: unknown } | null)?.latest;
  return {
    webhooks: Array.isArray(embedded) ? (embedded as WebhookDocument[]) : [],
    latest: newest && typeof newest === 'object' ? (newest as Record<string, WebhookDelivery>) : {},
  };
}
