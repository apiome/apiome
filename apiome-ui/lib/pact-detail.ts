/**
 * A pact in the UI — PFX-5.2 (#6946).
 *
 * The pure rules of the **Pact** page (`/ade/dashboard/pacts/pacticipants/{consumer}/pacts/{provider}`)
 * and of the **Pacts** section of a pacticipant's page:
 *
 * * **Reading a pact** ({@link parsePact}): the Pact Broker document of one consumer version, in any
 *   specification (V2 `providerState`, V3 `providerStates` and `messages`, V4 typed `interactions`),
 *   turned into one list of interactions. An interaction type Apiome does not draw is kept, marked
 *   `unknown`, and shown as its JSON — never dropped.
 * * **Diff vs previous** ({@link diffPacts}): interactions matched by kind, description and provider
 *   states; each is added, removed, changed (with the paths that changed) or unchanged.
 * * **History and verification status** ({@link parsePairHistory}, {@link parsePacticipantPacts}):
 *   the broker's matrix rows, grouped per consumer version (and per integration).
 * * **The previous different pact** ({@link findPreviousDistinct}): the walk back through the
 *   integration's consumer versions to the first one whose pact content differs, as the Pact
 *   Broker's `previous-distinct` resource answers it. Apiome's broker does not serve that resource,
 *   so the `/api/pact/*` proxy does the walk (see `pact_broker_compat.py`).
 *
 * The browser only ever reaches REST through the `/api/pact/*` proxies, which forward the query
 * parameters named here and nothing else: anything else is refused with the reason.
 */

import {
  ENVIRONMENT_READ_BATCH,
  MAX_FILTER_LENGTH,
  RollupError,
  isPacticipantHandle,
  pacticipantRoute,
  type RestReader,
} from '@lib/pact-pacticipants';

// --- wire helpers ------------------------------------------------------------------------------

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

/** An array field, or an empty array. */
function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/** `_links[rel].name` of a HAL document, or `null`. */
function linkName(body: unknown, rel: string): string | null {
  return text(record(record(record(body)._links)[rel]).name);
}

/** The last path segment of a link (a pacticipant's handle in a broker URL), or `null`. */
function lastSegment(href: string | null): string | null {
  if (!href) return null;
  const segment = href.replace(/\/+$/, '').split('/').pop();
  if (!segment) return null;
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

/** REST's message from a failed read, or the fallback. */
function failureMessage(body: unknown, fallback: string): string {
  const detail = record(body).detail;
  if (typeof detail === 'string' && detail) return detail;
  const message = text(record(detail).message);
  return message || fallback;
}

// --- routes and paths ----------------------------------------------------------------------------

/**
 * The route of one integration's pact page.
 *
 * @param consumer - The consumer's handle.
 * @param provider - The provider's handle.
 * @param version - A consumer version to open; the latest pact when absent.
 * @returns E.g. `/ade/dashboard/pacts/pacticipants/billing-service/pacts/ledger-api?version=1.4.0`.
 */
export function pactRoute(consumer: string, provider: string, version?: string | null): string {
  const base = `${pacticipantRoute(consumer)}/pacts/${encodeURIComponent(provider)}`;
  return version ? `${base}?version=${encodeURIComponent(version)}` : base;
}

/** The longest consumer version number the pact page accepts (the REST rule). */
export const MAX_VERSION_LENGTH = MAX_FILTER_LENGTH;

/**
 * Why a consumer version number cannot be asked for, or `null` when it can.
 *
 * A `/` cannot travel in the broker's `…/version/{v}` path segment, so such a version is refused
 * with the reason rather than read as a different one.
 *
 * @param version - The candidate.
 * @returns The reason, or `null`.
 */
export function versionProblem(version: string): string | null {
  if (!version.trim()) return 'The version is empty.';
  if (version.length > MAX_VERSION_LENGTH)
    return `The version is longer than ${MAX_VERSION_LENGTH} characters.`;
  if (/[\u0000-\u001f\u007f]/.test(version)) return 'The version contains a control character.';
  if (version.includes('/')) return 'A version containing "/" cannot be opened here.';
  return null;
}

/** The query parameters a pact proxy forwards, or why the request is refused. */
export type PickedPactQuery = { ok: true; version: string | null } | { ok: false; error: string };

/**
 * Read the one parameter a pact proxy accepts (`version`, when `allowVersion`), refusing anything
 * else with the reason — a parameter is never silently ignored.
 *
 * @param params - The browser's query string.
 * @param allowVersion - Whether this proxy accepts `version`.
 * @returns The version (or `null`), or the reason for a 400.
 */
export function pickPactQuery(params: URLSearchParams, allowVersion: boolean): PickedPactQuery {
  let version: string | null = null;
  for (const [key, value] of params.entries()) {
    if (key !== 'version' || !allowVersion) {
      const accepted = allowVersion ? 'version' : 'no parameters';
      return { ok: false, error: `Unsupported parameter ${key}: this read accepts ${accepted}.` };
    }
    if (version !== null)
      return { ok: false, error: 'The version parameter is given more than once.' };
    const problem = versionProblem(value);
    if (problem) return { ok: false, error: problem };
    version = value;
  }
  return { ok: true, version };
}

/** The handles of an integration, or `null` when either is malformed. */
export function pairHandles(
  provider: string,
  consumer: string,
): { provider: string; consumer: string } | null {
  return isPacticipantHandle(provider) && isPacticipantHandle(consumer)
    ? { provider, consumer }
    : null;
}

/**
 * The broker path of one pact (below `/v1/tenants/{slug}`).
 *
 * @param provider - The provider's handle (already checked).
 * @param consumer - The consumer's handle (already checked).
 * @param version - The consumer version; the latest pact when `null`.
 * @returns E.g. `pact-broker/pacts/provider/ledger-api/consumer/billing-service/version/1.4.0`.
 */
export function pactProxyPath(provider: string, consumer: string, version: string | null): string {
  const pair = `pact-broker/pacts/provider/${encodeURIComponent(provider)}/consumer/${encodeURIComponent(consumer)}`;
  return version === null ? `${pair}/latest` : `${pair}/version/${encodeURIComponent(version)}`;
}

/** How many matrix rows the integration history reads (one per verification of each version). */
export const HISTORY_ROW_LIMIT = 500;

/** How many matrix rows the pacticipant's **Pacts** section reads (the latest per version and provider). */
export const PACTICIPANT_PACTS_ROW_LIMIT = 1000;

/**
 * The matrix query of one integration's history: every consumer version of the pair with each
 * verification result.
 *
 * @param provider - The provider's handle.
 * @param consumer - The consumer's handle.
 * @returns The path, e.g. `pact-broker/matrix?q%5B%5D%5Bpacticipant%5D=…`.
 */
export function pairHistoryProxyPath(provider: string, consumer: string): string {
  const query = new URLSearchParams();
  query.append('q[][pacticipant]', consumer);
  query.append('q[][pacticipant]', provider);
  query.set('limit', String(HISTORY_ROW_LIMIT));
  return `pact-broker/matrix?${query.toString()}`;
}

/**
 * The matrix query of every integration a pacticipant is in, one row per consumer version and
 * provider (its latest verification).
 *
 * @param slug - The pacticipant's handle.
 * @returns The path.
 */
export function pacticipantPactsProxyPath(slug: string): string {
  const query = new URLSearchParams();
  query.append('q[][pacticipant]', slug);
  query.set('latestby', 'cvp');
  query.set('limit', String(PACTICIPANT_PACTS_ROW_LIMIT));
  return `pact-broker/matrix?${query.toString()}`;
}

// --- reading a pact ------------------------------------------------------------------------------

/** One provider state an interaction needs. */
export interface ProviderState {
  name: string;
  params: Record<string, unknown> | null;
}

/** What an interaction is: HTTP, an asynchronous message, a synchronous message, or something else. */
export type InteractionKind = 'http' | 'message' | 'sync-message' | 'unknown';

/** One interaction of a pact, in whatever specification it was written. */
export interface PactInteraction {
  /** The identity it is matched on across versions: kind, description, provider states. */
  key: string;
  kind: InteractionKind;
  /** The V4 `type` as written, or the kind's name; for an unknown kind, why it is not drawn. */
  typeLabel: string;
  description: string;
  states: ProviderState[];
  /** V4 `pending`: a failure of this interaction does not fail the verification. */
  pending: boolean;
  /** The interaction as published. */
  raw: Record<string, unknown>;
}

/** A pact, as the page draws it. */
export interface PactView {
  consumerName: string;
  providerName: string;
  consumerVersion: string | null;
  /** The content address (`pb:pact-version`): the same for every version that published this content. */
  sha: string | null;
  specification: string | null;
  publishedAt: string | null;
  interactions: PactInteraction[];
}

/** The V4 interaction types Apiome draws. */
const V4_KINDS: Record<string, InteractionKind> = {
  'Synchronous/HTTP': 'http',
  'Asynchronous/Messages': 'message',
  'Synchronous/Messages': 'sync-message',
};

/** What each kind is called on the page. */
export const KIND_LABELS: Record<InteractionKind, string> = {
  http: 'HTTP',
  message: 'Message',
  'sync-message': 'Synchronous message',
  unknown: 'Not drawn',
};

/**
 * The provider states of an interaction: V2 `providerState`, V3/V4 `providerStates` (objects or
 * plain names).
 *
 * @param raw - The interaction.
 * @returns The states, in the order written.
 */
export function readProviderStates(raw: Record<string, unknown>): ProviderState[] {
  const states: ProviderState[] = [];
  const single = text(raw.providerState);
  if (single) states.push({ name: single, params: null });
  for (const entry of list(raw.providerStates)) {
    if (typeof entry === 'string') {
      states.push({ name: entry, params: null });
      continue;
    }
    const state = record(entry);
    const name = text(state.name);
    if (!name) continue;
    const params = record(state.params);
    states.push({ name, params: Object.keys(params).length > 0 ? params : null });
  }
  return states;
}

/** Turn one published entry into an interaction (without its key). */
function readInteraction(entry: unknown, fromMessages: boolean): Omit<PactInteraction, 'key'> {
  if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
    return {
      kind: 'unknown',
      typeLabel: 'Not an object, so it is shown as published',
      description: '(an entry that is not an interaction)',
      states: [],
      pending: false,
      raw: { value: entry as unknown },
    };
  }
  const raw = entry as Record<string, unknown>;
  const type = text(raw.type);
  let kind: InteractionKind;
  let typeLabel: string;
  if (type !== null) {
    kind = V4_KINDS[type] ?? 'unknown';
    typeLabel =
      kind === 'unknown'
        ? `${type} — Apiome does not draw this type, so it is shown as published`
        : type;
  } else if (fromMessages) {
    kind = 'message';
    typeLabel = KIND_LABELS.message;
  } else if (raw.request !== undefined || raw.response !== undefined) {
    kind = 'http';
    typeLabel = KIND_LABELS.http;
  } else {
    kind = 'unknown';
    typeLabel = 'No type, request or response — shown as published';
  }
  return {
    kind,
    typeLabel,
    description: text(raw.description) ?? '(no description)',
    states: readProviderStates(raw),
    pending: raw.pending === true,
    raw,
  };
}

/**
 * The identity an interaction is matched on across versions: its kind, its description and its
 * provider states (names, sorted). Two interactions with the same identity get `#2`, `#3`….
 *
 * @param interactions - The interactions, in pact order.
 * @returns The same interactions with their `key`.
 */
function withKeys(interactions: Omit<PactInteraction, 'key'>[]): PactInteraction[] {
  const seen = new Map<string, number>();
  return interactions.map((interaction) => {
    const states = interaction.states.map((state) => state.name).sort();
    const base = `${interaction.kind}|${interaction.description}|${states.join('|')}`;
    const count = (seen.get(base) ?? 0) + 1;
    seen.set(base, count);
    return { ...interaction, key: count === 1 ? base : `${base}#${count}` };
  });
}

/**
 * Read a Pact Broker pact document.
 *
 * @param body - The document `GET …/pacts/provider/{p}/consumer/{c}/version/{v}` returns.
 * @returns The pact as the page draws it.
 */
export function parsePact(body: unknown): PactView {
  const doc = record(body);
  const metadata = record(doc.metadata);
  const specification =
    text(record(metadata.pactSpecification).version) ??
    text(record(metadata.pactSpecificationVersion).version) ??
    text(metadata.pactSpecificationVersion) ??
    text(record(metadata['pact-specification']).version);
  const interactions = [
    ...list(doc.interactions).map((entry) => readInteraction(entry, false)),
    ...list(doc.messages).map((entry) => readInteraction(entry, true)),
  ];
  return {
    consumerName: text(record(doc.consumer).name) ?? linkName(doc, 'pb:consumer') ?? '',
    providerName: text(record(doc.provider).name) ?? linkName(doc, 'pb:provider') ?? '',
    consumerVersion: linkName(doc, 'pb:consumer-version'),
    sha: linkName(doc, 'pb:pact-version'),
    specification,
    publishedAt: text(doc.createdAt),
    interactions: withKeys(interactions),
  };
}

/** One HTTP request or response, as the page draws it. */
export interface HttpPart {
  /** `GET /invoices?status=open`, or `200`. */
  line: string;
  headers: Record<string, unknown> | null;
  body: unknown;
  hasBody: boolean;
}

/** A query as written: a V2 string, or a V3/V4 map of names to one value or several. */
function renderQuery(query: unknown): string {
  if (typeof query === 'string') return query;
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(record(query))) {
    for (const item of Array.isArray(value) ? value : [value]) params.append(name, String(item));
  }
  return params.toString();
}

/** The body of a request or response: V4 wraps it as `{ content, contentType }`. */
function readBody(part: Record<string, unknown>): { body: unknown; hasBody: boolean } {
  if (!('body' in part)) return { body: null, hasBody: false };
  const body = part.body;
  const wrapped = record(body);
  if ('content' in wrapped && ('contentType' in wrapped || 'encoded' in wrapped)) {
    return { body: wrapped.content, hasBody: true };
  }
  return { body, hasBody: true };
}

/**
 * An HTTP interaction's request: method, path and query on one line; headers; body.
 *
 * @param raw - The interaction.
 * @returns The request.
 */
export function httpRequest(raw: Record<string, unknown>): HttpPart {
  const request = record(raw.request);
  const method = (text(request.method) ?? 'GET').toUpperCase();
  const path = text(request.path) ?? '/';
  const query = renderQuery(request.query);
  const headers = record(request.headers);
  return {
    line: `${method} ${path}${query ? `?${query}` : ''}`,
    headers: Object.keys(headers).length > 0 ? headers : null,
    ...readBody(request),
  };
}

/**
 * An HTTP interaction's expected response: status; headers; body.
 *
 * @param raw - The interaction.
 * @returns The response.
 */
export function httpResponse(raw: Record<string, unknown>): HttpPart {
  const response = record(raw.response);
  const status = response.status;
  const headers = record(response.headers);
  return {
    line: typeof status === 'number' || typeof status === 'string' ? String(status) : '—',
    headers: Object.keys(headers).length > 0 ? headers : null,
    ...readBody(response),
  };
}

/** A message's contents and metadata, as the page draws them. */
export interface MessagePart {
  contents: unknown;
  metadata: Record<string, unknown> | null;
}

/** One message (V3 `contents`/`metadata`; V4 the same, or `contents` wrapped with its type). */
function readMessage(raw: Record<string, unknown>): MessagePart {
  const metadata = record(raw.metadata);
  const contents = record(raw.contents);
  const unwrapped =
    'content' in contents && 'contentType' in contents ? contents.content : raw.contents;
  return {
    contents: unwrapped ?? null,
    metadata: Object.keys(metadata).length > 0 ? metadata : null,
  };
}

/**
 * A message interaction's parts: the message, or — for a synchronous message — the request and
 * each expected response.
 *
 * @param interaction - The interaction.
 * @returns `request` (the message itself for an asynchronous one) and `responses`.
 */
export function messageParts(interaction: PactInteraction): {
  request: MessagePart;
  responses: MessagePart[];
} {
  if (interaction.kind === 'sync-message') {
    return {
      request: readMessage(record(interaction.raw.request)),
      responses: list(interaction.raw.response).map((entry) => readMessage(record(entry))),
    };
  }
  return { request: readMessage(interaction.raw), responses: [] };
}

/** One line of an interaction list: `GET /invoices → 200`, or the kind of message. */
export function interactionSummary(interaction: PactInteraction): string {
  if (interaction.kind === 'http') {
    return `${httpRequest(interaction.raw).line} → ${httpResponse(interaction.raw).line}`;
  }
  if (interaction.kind === 'sync-message') {
    const count = list(interaction.raw.response).length;
    return `Request with ${count} ${count === 1 ? 'response' : 'responses'}`;
  }
  return KIND_LABELS[interaction.kind];
}

/**
 * A value as the page prints it: strings as they are, everything else as indented JSON.
 *
 * @param value - The value.
 * @returns The text.
 */
export function formatValue(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === undefined) return '';
  return JSON.stringify(value, null, 2) ?? String(value);
}

/** How many interactions of each kind a pact has, as a sentence: `3 HTTP, 1 message`. */
export function interactionCounts(interactions: PactInteraction[]): string {
  if (interactions.length === 0) return 'No interactions';
  const counts = new Map<InteractionKind, number>();
  for (const interaction of interactions)
    counts.set(interaction.kind, (counts.get(interaction.kind) ?? 0) + 1);
  const names: Record<InteractionKind, [string, string]> = {
    http: ['HTTP', 'HTTP'],
    message: ['message', 'messages'],
    'sync-message': ['synchronous message', 'synchronous messages'],
    unknown: ['not drawn', 'not drawn'],
  };
  return (['http', 'message', 'sync-message', 'unknown'] as InteractionKind[])
    .filter((kind) => counts.has(kind))
    .map((kind) => {
      const count = counts.get(kind) ?? 0;
      return `${count} ${names[kind][count === 1 ? 0 : 1]}`;
    })
    .join(', ');
}

// --- diff vs previous ------------------------------------------------------------------------------

/** One value that changed between two versions of an interaction. */
export interface ValueChange {
  /** Where, e.g. `response.body.amount` or `request.headers.Accept`. */
  path: string;
  /** Absent when the value was added. */
  before?: unknown;
  /** Absent when the value was removed. */
  after?: unknown;
}

/** An interaction both pacts have, with what changed in it. */
export interface ChangedInteraction {
  current: PactInteraction;
  previous: PactInteraction;
  changes: ValueChange[];
  /** True when there were more changes than {@link MAX_CHANGES_PER_INTERACTION}. */
  truncated: boolean;
}

/** What changed between two pacts of an integration. */
export interface PactDiff {
  added: PactInteraction[];
  removed: PactInteraction[];
  changed: ChangedInteraction[];
  unchanged: number;
}

/** The most changed values listed for one interaction. */
export const MAX_CHANGES_PER_INTERACTION = 50;

/** The fields that make an interaction's identity — compared through its key, not as values. */
const IDENTITY_FIELDS = new Set([
  'description',
  'providerState',
  'providerStates',
  'type',
  '_id',
  'key',
]);

/** A JSON path step: `.name`, or `["odd name"]`, or `[3]`. */
function step(path: string, name: string | number): string {
  if (typeof name === 'number') return `${path}[${name}]`;
  if (/^[A-Za-z_$][\w$-]*$/.test(name)) return path ? `${path}.${name}` : name;
  return `${path}[${JSON.stringify(name)}]`;
}

/** Collect the differences between two JSON values into `out` (stops at `limit`). */
function collectChanges(
  before: unknown,
  after: unknown,
  path: string,
  out: ValueChange[],
  limit: number,
): void {
  if (out.length > limit) return;
  if (Object.is(before, after)) return;
  const bothArrays = Array.isArray(before) && Array.isArray(after);
  const bothObjects =
    before !== null &&
    after !== null &&
    typeof before === 'object' &&
    typeof after === 'object' &&
    !Array.isArray(before) &&
    !Array.isArray(after);
  if (bothArrays) {
    const a = before as unknown[];
    const b = after as unknown[];
    for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
      if (index >= a.length) out.push({ path: step(path, index), after: b[index] });
      else if (index >= b.length) out.push({ path: step(path, index), before: a[index] });
      else collectChanges(a[index], b[index], step(path, index), out, limit);
      if (out.length > limit) return;
    }
    return;
  }
  if (bothObjects) {
    const a = before as Record<string, unknown>;
    const b = after as Record<string, unknown>;
    const names = [...new Set([...Object.keys(a), ...Object.keys(b)])].sort();
    for (const name of names) {
      if (!(name in b)) out.push({ path: step(path, name), before: a[name] });
      else if (!(name in a)) out.push({ path: step(path, name), after: b[name] });
      else collectChanges(a[name], b[name], step(path, name), out, limit);
      if (out.length > limit) return;
    }
    return;
  }
  out.push({ path: path || '(the interaction)', before, after });
}

/**
 * The values that differ between two versions of one interaction, its identity fields aside.
 *
 * @param previous - The interaction in the previous pact.
 * @param current - The interaction in this pact.
 * @returns The changes (at most {@link MAX_CHANGES_PER_INTERACTION}) and whether there were more.
 */
export function interactionChanges(
  previous: PactInteraction,
  current: PactInteraction,
): { changes: ValueChange[]; truncated: boolean } {
  const strip = (raw: Record<string, unknown>) =>
    Object.fromEntries(Object.entries(raw).filter(([name]) => !IDENTITY_FIELDS.has(name)));
  const out: ValueChange[] = [];
  collectChanges(strip(previous.raw), strip(current.raw), '', out, MAX_CHANGES_PER_INTERACTION);
  // Provider state parameters are not part of the identity (only the names are), so they are compared here.
  const params = (interaction: PactInteraction) =>
    Object.fromEntries(interaction.states.map((state) => [state.name, state.params]));
  collectChanges(
    params(previous),
    params(current),
    'providerStates',
    out,
    MAX_CHANGES_PER_INTERACTION,
  );
  const truncated = out.length > MAX_CHANGES_PER_INTERACTION;
  return { changes: out.slice(0, MAX_CHANGES_PER_INTERACTION), truncated };
}

/**
 * What changed from the previous pact of an integration to this one.
 *
 * Interactions are matched on kind, description and provider state names; renaming one or
 * changing its states reads as one removed and one added.
 *
 * @param current - This pact.
 * @param previous - The previous different pact.
 * @returns The added, removed and changed interactions (in this pact's order; removed in the
 *   previous pact's order) and how many are unchanged.
 */
export function diffPacts(current: PactView, previous: PactView): PactDiff {
  const before = new Map(
    previous.interactions.map((interaction) => [interaction.key, interaction]),
  );
  const afterKeys = new Set(current.interactions.map((interaction) => interaction.key));
  const diff: PactDiff = { added: [], removed: [], changed: [], unchanged: 0 };
  for (const interaction of current.interactions) {
    const old = before.get(interaction.key);
    if (!old) {
      diff.added.push(interaction);
      continue;
    }
    const { changes, truncated } = interactionChanges(old, interaction);
    if (changes.length === 0) diff.unchanged += 1;
    else diff.changed.push({ current: interaction, previous: old, changes, truncated });
  }
  diff.removed = previous.interactions.filter((interaction) => !afterKeys.has(interaction.key));
  return diff;
}

/** The sentence above the changes: `1 added, 2 changed, 1 removed, 4 unchanged`. */
export function diffSummary(diff: PactDiff): string {
  return [
    `${diff.added.length} added`,
    `${diff.changed.length} changed`,
    `${diff.removed.length} removed`,
    `${diff.unchanged} unchanged`,
  ].join(', ');
}

/** How each interaction of this pact compares with the previous one, by key. */
export type InteractionStatus = 'added' | 'changed';

/**
 * The status badge of each interaction that is new or changed since the previous pact.
 *
 * @param diff - The diff, or `null` when there is no previous pact.
 * @returns Status by interaction key (unchanged interactions are absent).
 */
export function interactionStatuses(diff: PactDiff | null): Map<string, InteractionStatus> {
  const statuses = new Map<string, InteractionStatus>();
  if (!diff) return statuses;
  for (const interaction of diff.added) statuses.set(interaction.key, 'added');
  for (const change of diff.changed) statuses.set(change.current.key, 'changed');
  return statuses;
}

// --- history and verification status ---------------------------------------------------------------

/** One verification result of a consumer version's pact, as a matrix row carries it. */
export interface VerificationRow {
  providerVersion: string | null;
  providerBranch: string | null;
  success: boolean;
  verifiedAt: string | null;
  /** `native` (a Pact verifier) or `bidirectional` (Apiome's comparison). */
  kind: string;
  /** Whether the verifier was told the pact was pending (a failure did not fail its build). */
  pending: boolean | null;
  wip: boolean;
}

/** One consumer version of an integration, with its verification results. */
export interface PactHistoryEntry {
  consumerVersion: string;
  branch: string | null;
  tags: string[];
  publishedAt: string | null;
  /** Newest provider version first. */
  verifications: VerificationRow[];
}

/** An integration's history, newest consumer version first. */
export interface PactHistory {
  entries: PactHistoryEntry[];
  /** True when the matrix returned as many rows as asked for, so older versions may be missing. */
  truncated: boolean;
}

/** One matrix row, as the history reads it. */
interface MatrixRowView {
  consumerSlug: string | null;
  consumerName: string;
  providerSlug: string | null;
  providerName: string;
  consumerVersion: string;
  branch: string | null;
  tags: string[];
  publishedAt: string | null;
  verification: VerificationRow | null;
}

/** Read one matrix row. */
function readMatrixRow(entry: unknown): MatrixRowView | null {
  const row = record(entry);
  const consumer = record(row.consumer);
  const provider = record(row.provider);
  const consumerVersion = record(consumer.version);
  const number = text(consumerVersion.number);
  if (number === null) return null;
  const result = row.verificationResult === null ? null : record(row.verificationResult);
  const providerVersion = provider.version === null ? null : record(provider.version);
  const verification: VerificationRow | null =
    result && typeof result.success === 'boolean'
      ? {
          providerVersion: providerVersion ? text(providerVersion.number) : null,
          providerBranch: providerVersion ? text(providerVersion.branch) : null,
          success: result.success,
          verifiedAt: text(result.verifiedAt),
          kind: text(result.kind) ?? 'native',
          pending: typeof result.pending === 'boolean' ? result.pending : null,
          wip: result.wip === true,
        }
      : null;
  return {
    consumerSlug: lastSegment(text(record(record(consumer._links).self).href)),
    consumerName: text(consumer.name) ?? '',
    providerSlug: lastSegment(text(record(record(provider._links).self).href)),
    providerName: text(provider.name) ?? '',
    consumerVersion: number,
    branch: text(consumerVersion.branch),
    tags: list(consumerVersion.tags)
      .map((tag) => text(record(tag).name))
      .filter((name): name is string => name !== null),
    publishedAt: text(record(row.pact).createdAt),
    verification,
  };
}

/** The matrix rows of a matrix document (considered and ignored alike). */
function matrixRows(body: unknown): MatrixRowView[] {
  return list(record(body).matrix)
    .map(readMatrixRow)
    .filter((row): row is MatrixRowView => row !== null);
}

/**
 * One integration's history from its matrix: each consumer version that published a pact for
 * the provider, newest first, with every verification result of it.
 *
 * Rows of the other direction (the provider as a consumer of the consumer) are left out: they are
 * another integration.
 *
 * @param body - The matrix document of the pair.
 * @param consumer - The consumer's handle.
 * @param provider - The provider's handle.
 * @param rowLimit - The `limit` the query was sent with.
 * @returns The history.
 */
export function parsePairHistory(
  body: unknown,
  consumer: string,
  provider: string,
  rowLimit = HISTORY_ROW_LIMIT,
): PactHistory {
  const all = list(record(body).matrix);
  const entries = new Map<string, PactHistoryEntry>();
  for (const row of matrixRows(body)) {
    if (row.consumerSlug !== consumer || row.providerSlug !== provider) continue;
    let entry = entries.get(row.consumerVersion);
    if (!entry) {
      entry = {
        consumerVersion: row.consumerVersion,
        branch: row.branch,
        tags: row.tags,
        publishedAt: row.publishedAt,
        verifications: [],
      };
      entries.set(row.consumerVersion, entry);
    }
    if (row.verification) entry.verifications.push(row.verification);
  }
  return { entries: [...entries.values()], truncated: all.length >= rowLimit };
}

/** A pact's verification status, from its results. */
export type VerificationVerdict = 'verified' | 'failed' | 'failed-pending' | 'unverified';

/**
 * The newest verification result of a consumer version's pact (by `verifiedAt`), or `null`.
 *
 * @param verifications - The version's results.
 * @returns The newest.
 */
export function latestVerification(verifications: VerificationRow[]): VerificationRow | null {
  let latest: VerificationRow | null = null;
  for (const row of verifications) {
    if (!latest || (row.verifiedAt ?? '') > (latest.verifiedAt ?? '')) latest = row;
  }
  return latest;
}

/**
 * The verdict a pact's newest result gives.
 *
 * @param latest - The newest result, or `null`.
 * @returns `verified`, `failed`, `failed-pending` (failed while pending, so it did not fail the
 *   provider's build) or `unverified`.
 */
export function verificationVerdict(latest: VerificationRow | null): VerificationVerdict {
  if (!latest) return 'unverified';
  if (latest.success) return 'verified';
  return latest.pending ? 'failed-pending' : 'failed';
}

/** What each verdict is called on the page. */
export const VERDICT_LABELS: Record<VerificationVerdict, string> = {
  verified: 'Verified',
  failed: 'Failed',
  'failed-pending': 'Failed (pending)',
  unverified: 'Not verified yet',
};

/** The badge variant of each verdict. */
export const VERDICT_BADGES: Record<
  VerificationVerdict,
  'success' | 'danger' | 'warn' | 'neutral'
> = {
  verified: 'success',
  failed: 'danger',
  'failed-pending': 'warn',
  unverified: 'neutral',
};

/** One integration a pacticipant is in, with its newest pact. */
export interface PacticipantPact {
  consumer: { name: string; slug: string };
  provider: { name: string; slug: string };
  latestVersion: string;
  publishedAt: string | null;
  latestVerification: VerificationRow | null;
}

/** The integrations a pacticipant is in, and whether the matrix may have left some out. */
export interface PacticipantPacts {
  pacts: PacticipantPact[];
  truncated: boolean;
}

/**
 * The integrations a pacticipant is in, from its matrix: one per consumer and provider, with the
 * newest consumer version and that version's latest verification. Ordered as the matrix orders
 * them (by consumer, then provider).
 *
 * @param body - The matrix document of the pacticipant.
 * @param rowLimit - The `limit` the query was sent with.
 * @returns The integrations.
 */
export function parsePacticipantPacts(
  body: unknown,
  rowLimit = PACTICIPANT_PACTS_ROW_LIMIT,
): PacticipantPacts {
  const pairs = new Map<string, PacticipantPact & { verifications: VerificationRow[] }>();
  for (const row of matrixRows(body)) {
    if (!row.consumerSlug || !row.providerSlug) continue;
    const key = `${row.consumerSlug}|${row.providerSlug}`;
    const pair = pairs.get(key);
    if (!pair) {
      pairs.set(key, {
        consumer: { name: row.consumerName, slug: row.consumerSlug },
        provider: { name: row.providerName, slug: row.providerSlug },
        latestVersion: row.consumerVersion,
        publishedAt: row.publishedAt,
        latestVerification: null,
        verifications: row.verification ? [row.verification] : [],
      });
    } else if (pair.latestVersion === row.consumerVersion && row.verification) {
      pair.verifications.push(row.verification);
    }
  }
  const pacts = [...pairs.values()].map(({ verifications, ...pact }) => ({
    ...pact,
    latestVerification: latestVerification(verifications),
  }));
  return { pacts, truncated: list(record(body).matrix).length >= rowLimit };
}

// --- the previous different pact -------------------------------------------------------------------

/** How many earlier consumer versions are read, at most, looking for a different pact. */
export const PREVIOUS_SCAN_LIMIT = 20;

/** Why there is (or is not) a previous different pact. */
export type PreviousOutcome =
  /** Found. */
  | 'found'
  /** This is the integration's first pact. */
  | 'first'
  /** Every earlier version published this same content. */
  | 'unchanged'
  /** {@link PREVIOUS_SCAN_LIMIT} earlier versions had this same content; older ones were not read. */
  | 'scan-limit'
  /** The version is not in the history the matrix returned (it is older than the rows read). */
  | 'not-in-history';

/** What `GET /api/pact/pacts/{provider}/{consumer}/previous` answers. */
export interface PreviousPactResponse {
  outcome: PreviousOutcome;
  /** The consumer version this is the previous pact *of*. */
  consumerVersion: string | null;
  /** How many earlier versions were read. */
  scanned: number;
  previous: {
    consumerVersion: string;
    sha: string | null;
    publishedAt: string | null;
    document: unknown;
  } | null;
}

/** What each outcome without a previous pact means, as the page says it. */
export const PREVIOUS_OUTCOME_TEXT: Record<Exclude<PreviousOutcome, 'found'>, string> = {
  first: 'This is the first pact of this integration, so there is nothing to compare it with.',
  unchanged: 'Every earlier version published this same pact, so nothing has changed.',
  'scan-limit': `The ${PREVIOUS_SCAN_LIMIT} versions before this one published this same pact; older versions were not compared.`,
  'not-in-history':
    'This version is older than the history read here, so its previous pact could not be found.',
};

/**
 * Find the previous different pact of a consumer version: walk back through the integration's
 * consumer versions (newest first) until one published different content.
 *
 * Earlier versions are read {@link ENVIRONMENT_READ_BATCH} at a time and at most
 * {@link PREVIOUS_SCAN_LIMIT} in all. An earlier version whose pact is gone (404) is skipped; any
 * other failure is reported, never taken for "no previous pact".
 *
 * @param read - Reads a path below `/v1/tenants/{slug}` as the signed-in user.
 * @param provider - The provider's handle (already checked).
 * @param consumer - The consumer's handle (already checked).
 * @param version - The consumer version; the latest pact when `null`.
 * @returns The outcome, and the previous pact when found.
 * @throws RollupError when the pact or the history cannot be read (REST's status kept).
 */
export async function findPreviousDistinct(
  read: RestReader,
  provider: string,
  consumer: string,
  version: string | null,
): Promise<PreviousPactResponse> {
  const current = await read(pactProxyPath(provider, consumer, version));
  if (!current.ok)
    throw new RollupError(
      current.status,
      failureMessage(current.body, 'The pact could not be read.'),
    );
  const sha = linkName(current.body, 'pb:pact-version');
  const consumerVersion = linkName(current.body, 'pb:consumer-version') ?? version;
  const history = await read(pairHistoryProxyPath(provider, consumer));
  if (!history.ok) {
    throw new RollupError(
      history.status,
      failureMessage(history.body, 'The history could not be read.'),
    );
  }
  const versions = parsePairHistory(history.body, consumer, provider).entries;
  const index = versions.findIndex((entry) => entry.consumerVersion === consumerVersion);
  const base = { consumerVersion, scanned: 0, previous: null };
  if (index === -1) return { ...base, outcome: 'not-in-history' };
  const earlier = versions.slice(index + 1);
  if (earlier.length === 0) return { ...base, outcome: 'first' };
  const candidates = earlier.slice(0, PREVIOUS_SCAN_LIMIT);
  let scanned = 0;
  for (let start = 0; start < candidates.length; start += ENVIRONMENT_READ_BATCH) {
    const batch = candidates.slice(start, start + ENVIRONMENT_READ_BATCH);
    const reads = await Promise.all(
      batch.map((entry) => read(pactProxyPath(provider, consumer, entry.consumerVersion))),
    );
    for (let offset = 0; offset < batch.length; offset += 1) {
      const answer = reads[offset];
      scanned += 1;
      if (answer.status === 404) continue;
      if (!answer.ok) {
        throw new RollupError(
          answer.status,
          failureMessage(answer.body, 'An earlier pact could not be read.'),
        );
      }
      const otherSha = linkName(answer.body, 'pb:pact-version');
      if (otherSha !== sha) {
        return {
          outcome: 'found',
          consumerVersion,
          scanned,
          previous: {
            consumerVersion: batch[offset].consumerVersion,
            sha: otherSha,
            publishedAt: text(record(answer.body).createdAt),
            document: answer.body,
          },
        };
      }
    }
  }
  return {
    ...base,
    scanned,
    outcome: earlier.length > PREVIOUS_SCAN_LIMIT ? 'scan-limit' : 'unchanged',
  };
}

/**
 * A pact version (content SHA) as the page prints it: the first 12 characters.
 *
 * @param sha - The SHA.
 * @returns The short form, or an em dash.
 */
export function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 12) : '—';
}
