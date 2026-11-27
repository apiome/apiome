/**
 * The **Write interactions** editor on the Publish page — PFX-8.5 (#7302).
 *
 * A team with no Pact tests yet writes its contract here instead of by hand in JSON. The editor
 * holds an {@link EditorDraft} — the pair and a list of {@link InteractionDraft}s of four kinds
 * (HTTP, message, GraphQL, gRPC) — and this module is everything it decides without the network:
 *
 * * {@link buildPact} turns a draft into a **Pact v4** document, or lists what stops it
 *   ({@link draftProblems}); the document then goes through the page's normal publish path.
 * * {@link readPactIntoEditor} reads a pact back into a draft. A pact written here round-trips
 *   without loss; anything a foreign pact carries that the editor cannot hold is listed in
 *   `unsupported` with the reason, never dropped quietly.
 * * Matchers are chips ({@link MATCHERS}): each body field the consumer relies on has a rule —
 *   `integer`, `regex ^[A-Z]{3}$` — written as Pact v4 `matchingRules`.
 * * {@link specFlag} says whether an interaction's path is in the provider's spec. A path that is
 *   not is **flagged, never blocked**: the pact still builds and publishes.
 * * {@link fillFromSpec} fills a response from the spec's example and draws a matcher per field.
 * * Provider-state parameters are typed `id = 42, kind = paid` ({@link parseStateParams}).
 */

import type { SpecOperation, SpecResponse } from './pact-provider-spec';
import { findOperation } from './pact-provider-spec';

// --- the draft -----------------------------------------------------------------------------------

/** The kinds of interaction the editor writes. */
export const INTERACTION_KINDS = ['http', 'message', 'graphql', 'grpc'] as const;

/** One kind. */
export type InteractionKind = (typeof INTERACTION_KINDS)[number];

/** How a kind reads. */
export const KIND_LABELS: Readonly<Record<InteractionKind, string>> = {
  http: 'HTTP',
  message: 'Message',
  graphql: 'GraphQL',
  grpc: 'gRPC',
};

/** A header, query parameter or message-metadata row. */
export interface KeyValue {
  name: string;
  value: string;
}

/** One provider state: its name and its parameters as typed (`id = 42, kind = paid`). */
export interface StateDraft {
  name: string;
  params: string;
}

/** The matchers the editor offers, in the order the chip menu lists them. */
export const MATCHERS = [
  'type',
  'equality',
  'integer',
  'decimal',
  'number',
  'boolean',
  'regex',
  'date',
  'time',
  'datetime',
  'include',
  'notEmpty',
  'null',
  'semver',
  'minType',
  'maxType',
] as const;

/** One matcher kind. */
export type MatcherKind = (typeof MATCHERS)[number];

/** The matchers that take an argument, and what it is. */
export const MATCHER_ARGUMENT: Readonly<Partial<Record<MatcherKind, string>>> = {
  regex: 'Pattern',
  date: 'Format',
  time: 'Format',
  datetime: 'Format',
  include: 'Text',
  minType: 'Least items',
  maxType: 'Most items',
};

/** A matcher on one body field: `$.currency` → `regex ^[A-Z]{3}$`. */
export interface MatcherDraft {
  /** The field, as a Pact path: `$.id`, `$.items[*].id`. */
  path: string;
  match: MatcherKind;
  /** The pattern, format, text or count; empty for matchers that take none. */
  argument: string;
}

/** A body: its text as typed and its content type. An empty text is no body. */
export interface BodyDraft {
  text: string;
  contentType: string;
}

/**
 * One interaction. Every kind uses the same record so switching kind keeps what was typed:
 *
 * * **HTTP** — method, path, query, request headers / body, status, response headers / body.
 * * **GraphQL** — an HTTP `POST` of `{ query, variables, operationName }` to `path`.
 * * **Message** — the message's contents are `responseBody`, its metadata `metadata`.
 * * **gRPC** — `service` (`package.Service/Method`), the request message `requestBody`, the
 *   reply `responseBody`.
 */
export interface InteractionDraft {
  /** Unique within the editor (not written to the pact). */
  id: string;
  kind: InteractionKind;
  description: string;
  states: StateDraft[];
  method: string;
  path: string;
  query: KeyValue[];
  requestHeaders: KeyValue[];
  requestBody: BodyDraft;
  requestMatchers: MatcherDraft[];
  status: string;
  responseHeaders: KeyValue[];
  responseBody: BodyDraft;
  responseMatchers: MatcherDraft[];
  graphqlQuery: string;
  graphqlVariables: string;
  operationName: string;
  metadata: KeyValue[];
  service: string;
}

/** The whole editor: the pair and its interactions. */
export interface EditorDraft {
  consumer: string;
  provider: string;
  interactions: InteractionDraft[];
}

/** The JSON content type. */
export const JSON_TYPE = 'application/json';

/** Most interactions one written pact holds. */
export const MAX_INTERACTIONS = 200;

/**
 * A new, empty interaction of a kind.
 *
 * @param id - Its id.
 * @param kind - Its kind.
 * @returns The interaction, with the kind's usual defaults (`GET`, `200`, `/graphql`).
 */
export function newInteraction(id: string, kind: InteractionKind): InteractionDraft {
  return {
    id,
    kind,
    description: '',
    states: [],
    method: kind === 'graphql' ? 'POST' : 'GET',
    path: kind === 'graphql' ? '/graphql' : '',
    query: [],
    requestHeaders: [],
    requestBody: { text: '', contentType: JSON_TYPE },
    requestMatchers: [],
    status: '200',
    responseHeaders: [],
    responseBody: { text: '', contentType: JSON_TYPE },
    responseMatchers: [],
    graphqlQuery: '',
    graphqlVariables: '',
    operationName: '',
    metadata: [],
    service: '',
  };
}

/** An empty editor. */
export const EMPTY_EDITOR: EditorDraft = { consumer: '', provider: '', interactions: [] };

/** Whether a value is a plain JSON object. */
function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Whether a content type is JSON (`application/json`, `application/hal+json`). */
export function isJsonType(contentType: string): boolean {
  return /(^|\/|\+)json(\s*;|$)/i.test(contentType.trim());
}

/**
 * How an interaction reads in the list.
 *
 * @param ix - The interaction.
 * @returns E.g. `{ badge: 'GET', title: 'get invoice 42' }`.
 */
export function listLabel(ix: InteractionDraft): { badge: string; title: string } {
  const badge = ix.kind === 'http' ? ix.method.trim().toUpperCase() || 'HTTP' : KIND_LABELS[ix.kind];
  const fallback = ix.kind === 'grpc' ? ix.service : ix.kind === 'message' ? 'A message' : ix.path;
  return { badge, title: ix.description.trim() || fallback.trim() || 'Untitled interaction' };
}

// --- provider-state parameters -------------------------------------------------------------------

/**
 * Split a parameter list on the commas that are not inside quotes or brackets.
 *
 * @param text - E.g. `id = 42, tags = ["a", "b"]`.
 * @returns The parts, trimmed, empty ones left out.
 */
function splitTopLevel(text: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let quote = false;
  let current = '';
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quote) {
      if (ch === '\\') {
        current += ch + (text[i + 1] ?? '');
        i += 1;
        continue;
      }
      if (ch === '"') quote = false;
    } else if (ch === '"') quote = true;
    else if (ch === '[' || ch === '{') depth += 1;
    else if (ch === ']' || ch === '}') depth -= 1;
    else if (ch === ',' && depth === 0) {
      parts.push(current.trim());
      current = '';
      continue;
    }
    current += ch;
  }
  parts.push(current.trim());
  return parts.filter(Boolean);
}

/**
 * Read a state's parameters: `id = 42, kind = paid` → `{ id: 42, kind: "paid" }`. A value that is
 * JSON (a number, `true`, `"quoted"`, `[…]`) is read as JSON; anything else is text.
 *
 * @param text - The parameters as typed.
 * @returns The parameters, or the problem with the first part that is not `name = value`.
 */
export function parseStateParams(text: string): { params: Record<string, unknown> } | { error: string } {
  const params: Record<string, unknown> = {};
  for (const part of splitTopLevel(text)) {
    const at = part.indexOf('=');
    if (at <= 0) return { error: `“${part}” is not name = value.` };
    const name = part.slice(0, at).trim();
    const raw = part.slice(at + 1).trim();
    if (name in params) return { error: `${name} is given twice.` };
    try {
      params[name] = JSON.parse(raw);
    } catch {
      params[name] = raw;
    }
  }
  return { params };
}

/**
 * Write parameters back as they are typed. Text that would read as something else (`"42"`, a
 * value with a comma, an empty one) is quoted, so reading it again gives the same value.
 *
 * @param params - The parameters.
 * @returns E.g. `id = 42, kind = paid`.
 */
export function formatStateParams(params: Record<string, unknown>): string {
  return Object.entries(params)
    .map(([name, value]) => {
      if (typeof value !== 'string') return `${name} = ${JSON.stringify(value)}`;
      let plain = value !== '' && value === value.trim() && !/[,"[\]{}]/.test(value);
      if (plain) {
        try {
          JSON.parse(value);
          plain = false;
        } catch {
          // Not JSON: reads back as this text.
        }
      }
      return `${name} = ${plain ? value : JSON.stringify(value)}`;
    })
    .join(', ');
}

// --- matchers ------------------------------------------------------------------------------------

/**
 * How a matcher reads on its chip.
 *
 * @param matcher - The matcher.
 * @returns E.g. `regex ^[A-Z]{3}$`, `min 1`.
 */
export function matcherLabel(matcher: MatcherDraft): string {
  const argument = matcher.argument.trim();
  if (matcher.match === 'minType') return `min ${argument || '?'}`;
  if (matcher.match === 'maxType') return `max ${argument || '?'}`;
  return argument && MATCHER_ARGUMENT[matcher.match] ? `${matcher.match} ${argument}` : matcher.match;
}

/** A Pact v4 matcher object. */
type PactMatcher = Record<string, unknown> & { match: string };

/**
 * One matcher as Pact v4 writes it.
 *
 * @param matcher - The matcher (already valid).
 * @returns E.g. `{ match: 'regex', regex: '^[A-Z]{3}$' }`.
 */
function toPactMatcher(matcher: MatcherDraft): PactMatcher {
  const argument = matcher.argument.trim();
  switch (matcher.match) {
    case 'regex':
      return { match: 'regex', regex: argument };
    case 'date':
    case 'time':
    case 'datetime':
      return { match: matcher.match, format: argument };
    case 'include':
      return { match: 'include', value: matcher.argument };
    case 'minType':
      return { match: 'type', min: Number(argument) };
    case 'maxType':
      return { match: 'type', max: Number(argument) };
    default:
      return { match: matcher.match };
  }
}

/**
 * What is wrong with one matcher.
 *
 * @param matcher - The matcher.
 * @returns The problem, or `null`.
 */
export function matcherProblem(matcher: MatcherDraft): string | null {
  const path = matcher.path.trim();
  if (!/^\$(\.[A-Za-z_][A-Za-z0-9_-]*|\[\*\]|\[\d+\]|\['[^']*'\])*$/.test(path)) {
    return `${path || 'An empty path'} is not a field path such as $.id or $.items[*].id.`;
  }
  const argument = matcher.argument.trim();
  if (matcher.match === 'regex') {
    if (!argument) return `${path}: a regex matcher needs a pattern.`;
    try {
      new RegExp(argument);
    } catch {
      return `${path}: ${argument} is not a valid pattern.`;
    }
  }
  if (['date', 'time', 'datetime'].includes(matcher.match) && !argument) return `${path}: a ${matcher.match} matcher needs a format, e.g. yyyy-MM-dd.`;
  if (matcher.match === 'include' && !matcher.argument) return `${path}: an include matcher needs the text to look for.`;
  if ((matcher.match === 'minType' || matcher.match === 'maxType') && !/^\d{1,6}$/.test(argument)) {
    return `${path}: ${matcher.match === 'minType' ? 'min' : 'max'} needs a whole number of items.`;
  }
  return null;
}

/**
 * The `matchingRules.body` block for a list of matchers: rows on the same path are combined.
 *
 * @param matchers - The matchers (already valid).
 * @returns The block, or `null` when there are none.
 */
function bodyRules(matchers: MatcherDraft[]): Record<string, { combine: 'AND'; matchers: PactMatcher[] }> | null {
  if (!matchers.length) return null;
  const rules: Record<string, { combine: 'AND'; matchers: PactMatcher[] }> = {};
  for (const matcher of matchers) {
    const path = matcher.path.trim();
    rules[path] = rules[path] ?? { combine: 'AND', matchers: [] };
    rules[path].matchers.push(toPactMatcher(matcher));
  }
  return rules;
}

/**
 * Read a `matchingRules.body` block into matcher rows.
 *
 * @param block - The block (Pact v3 / v4: `{ "$.id": { matchers: [...] } }`).
 * @param where - E.g. `Interaction 2’s response`, for the sentences.
 * @param unsupported - Where what cannot be held is reported.
 * @returns The rows.
 */
function readBodyRules(block: unknown, where: string, unsupported: string[]): MatcherDraft[] {
  if (!isObject(block)) return [];
  const rows: MatcherDraft[] = [];
  for (const [path, entry] of Object.entries(block)) {
    const list = isObject(entry) && Array.isArray(entry.matchers) ? entry.matchers : null;
    if (!list) {
      unsupported.push(`${where}: the rule on ${path} has no matchers list and was not read.`);
      continue;
    }
    if (isObject(entry) && entry.combine === 'OR' && list.length > 1) {
      unsupported.push(`${where}: the rules on ${path} are combined with OR; the editor combines with AND.`);
    }
    for (const raw of list) {
      const row = readMatcher(path, raw);
      if (typeof row === 'string') unsupported.push(`${where}: ${row}`);
      else rows.push(row);
    }
  }
  return rows;
}

/**
 * Read one Pact matcher.
 *
 * @param path - Its field.
 * @param raw - The matcher object.
 * @returns The row, or why it cannot be held.
 */
function readMatcher(path: string, raw: unknown): MatcherDraft | string {
  if (!isObject(raw) || typeof raw.match !== 'string') return `a rule on ${path} has no match kind and was not read.`;
  const text = (value: unknown) => (typeof value === 'string' ? value : '');
  switch (raw.match) {
    case 'type':
      if (raw.min !== undefined && raw.max !== undefined) return `the type rule on ${path} sets both min and max; add them as two rules.`;
      if (raw.min !== undefined) return { path, match: 'minType', argument: String(raw.min) };
      if (raw.max !== undefined) return { path, match: 'maxType', argument: String(raw.max) };
      return { path, match: 'type', argument: '' };
    case 'regex':
      return { path, match: 'regex', argument: text(raw.regex) };
    case 'date':
    case 'time':
    case 'datetime':
      return { path, match: raw.match, argument: text(raw.format) };
    case 'timestamp':
      return { path, match: 'datetime', argument: text(raw.format) };
    case 'include':
      return { path, match: 'include', argument: text(raw.value) };
    default:
      if ((MATCHERS as readonly string[]).includes(raw.match) && Object.keys(raw).length === 1) {
        return { path, match: raw.match as MatcherKind, argument: '' };
      }
      return `the ${raw.match} rule on ${path} is not one the editor writes, so it was not read.`;
  }
}

// --- bodies --------------------------------------------------------------------------------------

/**
 * A body as Pact v4 writes it.
 *
 * @param body - The body as typed.
 * @returns `{ content, contentType, encoded: false }`, `null` for no body, or the problem.
 */
function toPactBody(body: BodyDraft): { body: Record<string, unknown> | null } | { error: string } {
  if (!body.text.trim()) return { body: null };
  const contentType = body.contentType.trim() || JSON_TYPE;
  if (!isJsonType(contentType)) return { body: { content: body.text, contentType, encoded: false } };
  try {
    return { body: { content: JSON.parse(body.text), contentType, encoded: false } };
  } catch {
    return { error: 'is not valid JSON' };
  }
}

/**
 * Read a Pact body (v4 `{ content, contentType }`, or a v2 / v3 body itself).
 *
 * @param raw - The body.
 * @param headers - The headers, for a v2 / v3 body's content type.
 * @param where - For the sentences.
 * @param unsupported - Where what cannot be held is reported.
 * @returns The body as typed.
 */
function readPactBody(raw: unknown, headers: KeyValue[], where: string, unsupported: string[]): BodyDraft {
  if (raw === undefined || raw === null) return { text: '', contentType: JSON_TYPE };
  const header = headers.find((h) => h.name.toLowerCase() === 'content-type')?.value;
  if (isObject(raw) && 'content' in raw && (typeof raw.contentType === 'string' || 'encoded' in raw)) {
    const contentType = typeof raw.contentType === 'string' ? raw.contentType : header ?? JSON_TYPE;
    if (raw.encoded && raw.encoded !== false) {
      unsupported.push(`${where}: the body is ${typeof raw.encoded === 'string' ? raw.encoded : 'encoded'} binary content; it is shown as text and written back as text.`);
    }
    const content = raw.content;
    if (content === null || content === undefined) return { text: '', contentType };
    return { text: typeof content === 'string' && !isJsonType(contentType) ? content : JSON.stringify(content, null, 2), contentType };
  }
  const contentType = header ?? (typeof raw === 'string' ? 'text/plain' : JSON_TYPE);
  return { text: typeof raw === 'string' && !isJsonType(contentType) ? raw : JSON.stringify(raw, null, 2), contentType };
}

/**
 * Rows → Pact v4's `{ name: [values] }` (rows with the same name are joined in order).
 *
 * @param rows - Header or query rows.
 * @returns The map, or `null` when there are none.
 */
function toMultiMap(rows: KeyValue[]): Record<string, string[]> | null {
  const named = rows.filter((row) => row.name.trim());
  if (!named.length) return null;
  const out: Record<string, string[]> = {};
  for (const row of named) (out[row.name.trim()] = out[row.name.trim()] ?? []).push(row.value);
  return out;
}

/**
 * Pact's `{ name: value | [values] }` (or a v2 query string) → rows.
 *
 * @param raw - The map.
 * @returns The rows.
 */
function readMultiMap(raw: unknown): KeyValue[] {
  if (typeof raw === 'string') {
    return [...new URLSearchParams(raw).entries()].map(([name, value]) => ({ name, value }));
  }
  if (!isObject(raw)) return [];
  return Object.entries(raw).flatMap(([name, value]) =>
    (Array.isArray(value) ? value : [value]).map((one) => ({ name, value: typeof one === 'string' ? one : JSON.stringify(one) })),
  );
}

// --- building the pact ---------------------------------------------------------------------------

/** What stops a draft from being a pact: one sentence per problem. */
export interface DraftProblems {
  /** About the pair. */
  pair: string[];
  /** By interaction id. */
  interactions: Record<string, string[]>;
}

/**
 * Everything that stops the draft from being a pact.
 *
 * @param draft - The editor.
 * @returns The problems; empty lists when the draft builds.
 */
export function draftProblems(draft: EditorDraft): DraftProblems {
  const pair: string[] = [];
  if (!draft.consumer.trim()) pair.push('Name the consumer: the application that makes these calls.');
  if (!draft.provider.trim()) pair.push('Name the provider: the service that answers them.');
  if (!draft.interactions.length) pair.push('Add an interaction.');
  if (draft.interactions.length > MAX_INTERACTIONS) pair.push(`A written pact holds at most ${MAX_INTERACTIONS} interactions.`);
  const interactions: Record<string, string[]> = {};
  const keys = new Map<string, number>();
  draft.interactions.forEach((ix, index) => {
    const list: string[] = [];
    if (!ix.description.trim()) list.push('Describe the interaction: “get invoice 42”.');
    for (const state of ix.states) {
      if (!state.name.trim()) list.push('A provider state has no name.');
      const parsed = parseStateParams(state.params);
      if ('error' in parsed) list.push(`Parameters of “${state.name.trim() || 'a state'}”: ${parsed.error}`);
    }
    if (ix.kind === 'http' || ix.kind === 'graphql') {
      if (!/^[A-Za-z]+$/.test(ix.method.trim())) list.push('Choose the request method.');
      if (!ix.path.trim().startsWith('/')) list.push('The path starts with /.');
      else if (/[?#]/.test(ix.path)) list.push('Put query parameters under Query, not in the path.');
      if (!/^[1-5]\d\d$/.test(ix.status.trim())) list.push('The response status is a number from 100 to 599.');
    }
    if (ix.kind === 'graphql') {
      if (!ix.graphqlQuery.trim()) list.push('Write the GraphQL operation.');
      if (ix.graphqlVariables.trim()) {
        try {
          if (!isObject(JSON.parse(ix.graphqlVariables))) list.push('Variables are a JSON object.');
        } catch {
          list.push('Variables are not valid JSON.');
        }
      }
    }
    if (ix.kind === 'grpc' && !/^[A-Za-z_][\w.]*\/[A-Za-z_]\w*$/.test(ix.service.trim())) {
      list.push('Name the call as package.Service/Method.');
    }
    const bodies: Array<[string, BodyDraft]> =
      ix.kind === 'message'
        ? [['The message contents', ix.responseBody]]
        : ix.kind === 'graphql'
          ? [['The response body', ix.responseBody]]
          : [
              [ix.kind === 'grpc' ? 'The request message' : 'The request body', ix.requestBody],
              [ix.kind === 'grpc' ? 'The reply' : 'The response body', ix.responseBody],
            ];
    for (const [label, body] of bodies) {
      const built = toPactBody(body);
      if ('error' in built) list.push(`${label} ${built.error}.`);
    }
    const matchers = ix.kind === 'http' || ix.kind === 'grpc' ? [...ix.requestMatchers, ...ix.responseMatchers] : ix.responseMatchers;
    for (const matcher of matchers) {
      const problem = matcherProblem(matcher);
      if (problem) list.push(problem);
    }
    // Pact tells interactions apart by description and provider states.
    const key = `${ix.description.trim()}\u0000${ix.states.map((s) => s.name.trim()).join('\u0000')}`;
    if (ix.description.trim() && keys.has(key)) {
      list.push(`Interaction ${(keys.get(key) as number) + 1} has the same description and provider states: a verifier could not tell them apart.`);
    } else keys.set(key, index);
    if (list.length) interactions[ix.id] = list;
  });
  return { pair, interactions };
}

/** Whether a draft has no problems. */
export function draftIsReady(problems: DraftProblems): boolean {
  return !problems.pair.length && !Object.keys(problems.interactions).length;
}

/** The provider states as Pact v4 writes them. */
function pactStates(states: StateDraft[]): Array<Record<string, unknown>> {
  return states.map((state) => {
    const parsed = parseStateParams(state.params);
    const params = 'params' in parsed ? parsed.params : {};
    return Object.keys(params).length ? { name: state.name.trim(), params } : { name: state.name.trim() };
  });
}

/** A request or response part with its optional members only when set. */
function part(fields: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(fields).filter(([, value]) => value !== null && value !== undefined));
}

/** `matchingRules` holding a body block, or `null`. */
function rulesBlock(matchers: MatcherDraft[]): Record<string, unknown> | null {
  const body = bodyRules(matchers);
  return body ? { body } : null;
}

/**
 * One interaction as Pact v4 writes it.
 *
 * @param ix - The interaction (already valid).
 * @returns The interaction object.
 */
function toPactInteraction(ix: InteractionDraft): Record<string, unknown> {
  const body = (draft: BodyDraft) => {
    const built = toPactBody(draft);
    return 'body' in built ? built.body : null;
  };
  const head = part({
    description: ix.description.trim(),
    providerStates: ix.states.length ? pactStates(ix.states) : null,
  });
  if (ix.kind === 'message') {
    const metadata = ix.metadata.filter((row) => row.name.trim());
    return part({
      type: 'Asynchronous/Messages',
      ...head,
      contents: body(ix.responseBody) ?? { content: null, contentType: JSON_TYPE, encoded: false },
      metadata: metadata.length ? Object.fromEntries(metadata.map((row) => [row.name.trim(), row.value])) : null,
      matchingRules: rulesBlock(ix.responseMatchers),
    });
  }
  if (ix.kind === 'grpc') {
    const contents = (draft: BodyDraft) => body(draft) ?? { content: null, contentType: JSON_TYPE, encoded: false };
    return part({
      type: 'Synchronous/Messages',
      ...head,
      transport: 'grpc',
      pluginConfiguration: { protobuf: { service: ix.service.trim() } },
      request: part({ contents: contents(ix.requestBody), matchingRules: rulesBlock(ix.requestMatchers) }),
      response: [part({ contents: contents(ix.responseBody), matchingRules: rulesBlock(ix.responseMatchers) })],
    });
  }
  let requestBody = body(ix.requestBody);
  if (ix.kind === 'graphql') {
    const content: Record<string, unknown> = { query: ix.graphqlQuery };
    if (ix.graphqlVariables.trim()) content.variables = JSON.parse(ix.graphqlVariables);
    if (ix.operationName.trim()) content.operationName = ix.operationName.trim();
    requestBody = { content, contentType: JSON_TYPE, encoded: false };
  }
  return part({
    type: 'Synchronous/HTTP',
    ...head,
    request: part({
      method: ix.method.trim().toUpperCase(),
      path: ix.path.trim(),
      query: ix.kind === 'http' ? toMultiMap(ix.query) : null,
      headers: toMultiMap(ix.requestHeaders),
      body: requestBody,
      matchingRules: ix.kind === 'http' ? rulesBlock(ix.requestMatchers) : null,
    }),
    response: part({
      status: Number(ix.status.trim()),
      headers: toMultiMap(ix.responseHeaders),
      body: body(ix.responseBody),
      matchingRules: rulesBlock(ix.responseMatchers),
    }),
  });
}

/**
 * The Pact v4 document a draft makes.
 *
 * @param draft - The editor.
 * @returns The document, or the problems that stop it.
 */
export function buildPact(draft: EditorDraft): { pact: Record<string, unknown> } | { problems: DraftProblems } {
  const problems = draftProblems(draft);
  if (!draftIsReady(problems)) return { problems };
  return {
    pact: {
      consumer: { name: draft.consumer.trim() },
      provider: { name: draft.provider.trim() },
      interactions: draft.interactions.map(toPactInteraction),
      metadata: {
        pactSpecification: { version: '4.0' },
        apiome: { writtenWith: 'Write interactions' },
      },
    },
  };
}

/**
 * What a gRPC interaction written here lacks, said once on the editor: the editor writes the
 * messages as protobuf-JSON, without the compiled `.proto` the protobuf plugin files.
 */
export const GRPC_NOTE =
  'gRPC messages are written as JSON, without the compiled .proto: Apiome’s hosted verifier reports “descriptors missing” for them until a protobuf-plugin test publishes the same calls. Publishing and comparing still work.';

// --- reading a pact back -------------------------------------------------------------------------

/** What reading a pact gives: the draft and everything the editor could not hold. */
export interface ReadDraft {
  draft: EditorDraft;
  unsupported: string[];
}

/**
 * Read one HTTP interaction (and recognise a GraphQL one).
 *
 * @param ix - The interaction draft so far (id, description, states set).
 * @param entry - The interaction object.
 * @param where - For the sentences.
 * @param unsupported - Where what cannot be held is reported.
 * @returns The interaction.
 */
function readHttp(ix: InteractionDraft, entry: Record<string, unknown>, where: string, unsupported: string[]): InteractionDraft {
  const request = isObject(entry.request) ? entry.request : {};
  const response = isObject(entry.response) ? entry.response : {};
  const requestHeaders = readMultiMap(request.headers);
  const responseHeaders = readMultiMap(response.headers);
  const next: InteractionDraft = {
    ...ix,
    method: typeof request.method === 'string' ? request.method.toUpperCase() : 'GET',
    path: typeof request.path === 'string' ? request.path : '/',
    query: readMultiMap(request.query),
    requestHeaders,
    requestBody: readPactBody(request.body, requestHeaders, `${where}’s request`, unsupported),
    status: response.status === undefined ? '200' : String(response.status),
    responseHeaders,
    responseBody: readPactBody(response.body, responseHeaders, `${where}’s response`, unsupported),
  };
  for (const [side, block] of [
    ['request', request.matchingRules],
    ['response', response.matchingRules],
  ] as const) {
    if (!isObject(block)) continue;
    for (const key of Object.keys(block)) {
      if (key !== 'body') unsupported.push(`${where}’s ${side} has ${key} matching rules; the editor holds body rules only, so they were not read.`);
    }
    const rows = readBodyRules(block.body, `${where}’s ${side}`, unsupported);
    if (side === 'request') next.requestMatchers = rows;
    else next.responseMatchers = rows;
  }
  for (const key of ['generators']) {
    if (request[key] !== undefined || response[key] !== undefined) unsupported.push(`${where} has ${key}; the editor does not write them, so they were not read.`);
  }
  // GraphQL: a POST of { query, variables?, operationName? } as JSON to a …graphql path.
  const content = isObject(request.body) && 'content' in request.body ? request.body.content : request.body;
  const graphqlShape =
    next.method === 'POST' &&
    /graphql$/i.test(next.path) &&
    isObject(content) &&
    typeof content.query === 'string' &&
    Object.keys(content).every((key) => ['query', 'variables', 'operationName'].includes(key)) &&
    (content.variables === undefined || isObject(content.variables)) &&
    (content.operationName === undefined || typeof content.operationName === 'string') &&
    isJsonType(next.requestBody.contentType) &&
    !next.query.length &&
    !next.requestMatchers.length;
  if (!graphqlShape || !isObject(content)) return next;
  return {
    ...next,
    kind: 'graphql',
    requestBody: { text: '', contentType: JSON_TYPE },
    graphqlQuery: content.query as string,
    graphqlVariables: content.variables === undefined ? '' : JSON.stringify(content.variables, null, 2),
    operationName: typeof content.operationName === 'string' ? content.operationName : '',
  };
}

/**
 * Read a pact into the editor.
 *
 * @param text - The pact document.
 * @param nextId - Makes each interaction's id.
 * @returns The draft and what could not be held, or why the text is not a pact.
 */
export function readPactIntoEditor(text: string, nextId: () => string): ReadDraft | { error: string } {
  let document: unknown;
  try {
    document = JSON.parse(text);
  } catch {
    return { error: 'Not a pact: the text is not JSON.' };
  }
  if (!isObject(document)) return { error: 'Not a pact: the text is not a JSON object.' };
  const name = (role: string) => {
    const block = document[role];
    return isObject(block) && typeof block.name === 'string' ? block.name : '';
  };
  const unsupported: string[] = [];
  const interactions: InteractionDraft[] = [];
  const lists: Array<['interactions' | 'messages', unknown]> = [
    ['interactions', document.interactions],
    ['messages', document.messages],
  ];
  for (const [key, list] of lists) {
    if (list === undefined) continue;
    if (!Array.isArray(list)) return { error: `Not a pact: ${key} must be a list.` };
    list.forEach((entry, index) => {
      const where = `${key === 'messages' ? 'Message' : 'Interaction'} ${index + 1}`;
      if (!isObject(entry)) {
        unsupported.push(`${where} is not an object and was not read.`);
        return;
      }
      const type = typeof entry.type === 'string' ? entry.type : null;
      const base = newInteraction(nextId(), 'http');
      base.description = typeof entry.description === 'string' ? entry.description : '';
      base.states = readStates(entry, where, unsupported);
      for (const extra of ['pending', 'comments', 'interactionMarkup']) {
        if (entry[extra] !== undefined) unsupported.push(`${where} has ${extra}; the editor does not write it, so it was not read.`);
      }
      if (key === 'messages' || type === 'Asynchronous/Messages') {
        interactions.push(readMessage(base, entry, where, unsupported));
      } else if (type === 'Synchronous/Messages') {
        const grpc = readGrpc(base, entry, where, unsupported);
        if (grpc) interactions.push(grpc);
      } else if (type === null || type === 'Synchronous/HTTP') {
        interactions.push(readHttp(base, entry, where, unsupported));
      } else {
        unsupported.push(`${where} is a ${type} interaction, which the editor does not write; it was not read.`);
      }
    });
  }
  return { draft: { consumer: name('consumer'), provider: name('provider'), interactions }, unsupported };
}

/** Read an interaction's provider states (Pact v4 / v3 `providerStates`, v2 `providerState`). */
function readStates(entry: Record<string, unknown>, where: string, unsupported: string[]): StateDraft[] {
  if (typeof entry.providerState === 'string') return [{ name: entry.providerState, params: '' }];
  if (!Array.isArray(entry.providerStates)) return [];
  return entry.providerStates.flatMap((state) => {
    if (!isObject(state) || typeof state.name !== 'string') {
      unsupported.push(`${where} has a provider state without a name; it was not read.`);
      return [];
    }
    return [{ name: state.name, params: isObject(state.params) ? formatStateParams(state.params) : '' }];
  });
}

/** Read an asynchronous message (Pact v4 `contents`, or a v3 message's `contents`). */
function readMessage(ix: InteractionDraft, entry: Record<string, unknown>, where: string, unsupported: string[]): InteractionDraft {
  const metadata = isObject(entry.metadata)
    ? Object.entries(entry.metadata).map(([name, value]) => ({ name, value: typeof value === 'string' ? value : JSON.stringify(value) }))
    : [];
  const rules = isObject(entry.matchingRules) ? entry.matchingRules : {};
  for (const key of Object.keys(rules)) {
    if (key !== 'body') unsupported.push(`${where} has ${key} matching rules; the editor holds body rules only, so they were not read.`);
  }
  if (isObject(entry.metadata) && Object.values(entry.metadata).some((value) => typeof value !== 'string')) {
    unsupported.push(`${where}: metadata values that are not text are shown as JSON text and written back as text.`);
  }
  return {
    ...ix,
    kind: 'message',
    method: 'GET',
    path: '',
    responseBody: readPactBody(entry.contents, [], where, unsupported),
    metadata,
    responseMatchers: readBodyRules(rules.body, where, unsupported),
  };
}

/** Read a gRPC call (Pact v4 `Synchronous/Messages`, `transport: grpc`), or report it. */
function readGrpc(ix: InteractionDraft, entry: Record<string, unknown>, where: string, unsupported: string[]): InteractionDraft | null {
  const plugin = isObject(entry.pluginConfiguration) && isObject(entry.pluginConfiguration.protobuf) ? entry.pluginConfiguration.protobuf : null;
  if (entry.transport !== 'grpc' && !plugin) {
    unsupported.push(`${where} is a synchronous message that is not gRPC; the editor does not write those, so it was not read.`);
    return null;
  }
  if (plugin && Object.keys(plugin).some((key) => key !== 'service')) {
    unsupported.push(`${where}: the protobuf plugin’s ${Object.keys(plugin).filter((k) => k !== 'service').join(', ')} are not kept; the editor writes the service only.`);
  }
  const request = isObject(entry.request) ? entry.request : {};
  const responses = Array.isArray(entry.response) ? entry.response : [];
  if (responses.length > 1) unsupported.push(`${where} has ${responses.length} replies; the editor holds the first.`);
  const reply = isObject(responses[0]) ? responses[0] : {};
  const requestRules = isObject(request.matchingRules) ? request.matchingRules.body : undefined;
  const replyRules = isObject(reply.matchingRules) ? reply.matchingRules.body : undefined;
  return {
    ...ix,
    kind: 'grpc',
    service: plugin && typeof plugin.service === 'string' ? plugin.service : '',
    requestBody: readPactBody(request.contents, [], `${where}’s request`, unsupported),
    requestMatchers: readBodyRules(requestRules, `${where}’s request`, unsupported),
    responseBody: readPactBody(reply.contents, [], `${where}’s reply`, unsupported),
    responseMatchers: readBodyRules(replyRules, `${where}’s reply`, unsupported),
  };
}

// --- the spec ------------------------------------------------------------------------------------

/** What the spec says about an interaction's path. */
export type SpecFlag =
  | { state: 'match'; operation: SpecOperation }
  | { state: 'not-in-spec'; message: string }
  | { state: 'unchecked'; message: string };

/**
 * Whether an interaction's request is in the provider's spec. Flags only: nothing is blocked.
 *
 * @param ix - The interaction.
 * @param operations - The spec's operations, or `null` when no spec could be read.
 * @param revision - The revision's label, for the sentence.
 * @returns The match, a not-in-spec flag, or why it was not checked.
 */
export function specFlag(ix: InteractionDraft, operations: SpecOperation[] | null, revision: string | null): SpecFlag {
  if (ix.kind === 'message' || ix.kind === 'grpc') return { state: 'unchecked', message: `${KIND_LABELS[ix.kind]} interactions are not checked against the OpenAPI spec.` };
  if (operations === null) return { state: 'unchecked', message: 'No spec to check the path against.' };
  const path = ix.path.trim();
  if (!path.startsWith('/')) return { state: 'unchecked', message: 'Type a path to check it against the spec.' };
  const { operation, otherMethods } = findOperation(operations, ix.method, path);
  const where = revision ? ` in ${revision}` : '';
  if (operation) return { state: 'match', operation };
  if (otherMethods.length) {
    return { state: 'not-in-spec', message: `${path} is in the spec${where} for ${otherMethods.join(', ')}, not ${ix.method.toUpperCase()}. It can still be published; the comparison will report it.` };
  }
  return { state: 'not-in-spec', message: `${ix.method.toUpperCase()} ${path} is not in the spec${where}. It can still be published; the comparison will report it.` };
}

/**
 * The response **Fill from the spec** takes: the one with the interaction's status, else the
 * first 2xx, else the first listed.
 *
 * @param operation - The matched operation.
 * @param status - The interaction's status as typed.
 * @returns The response, or `null` when the operation documents none.
 */
export function pickSpecResponse(operation: SpecOperation, status: string): SpecResponse | null {
  const typed = status.trim();
  return (
    operation.responses.find((r) => r.status === typed) ??
    operation.responses.find((r) => /^2/.test(r.status)) ??
    operation.responses[0] ??
    null
  );
}

/**
 * The matcher a spec field suggests: `integer` for an integer, `regex` for a pattern or an enum,
 * `minType 1` for an array, `type` for the rest.
 *
 * @param field - The field.
 * @returns The matcher.
 */
export function matcherForField(field: SpecResponse['fields'][number]): MatcherDraft {
  const path = field.path;
  if (field.type === 'integer') return { path, match: 'integer', argument: '' };
  if (field.type === 'number') return { path, match: 'number', argument: '' };
  if (field.type === 'boolean') return { path, match: 'boolean', argument: '' };
  if (field.type === 'array') return { path, match: 'minType', argument: '1' };
  if (field.type === 'string' && field.pattern) return { path, match: 'regex', argument: field.pattern };
  if (field.type === 'string' && field.enum?.length) {
    return { path, match: 'regex', argument: `^(${field.enum.map((v) => String(v).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})$` };
  }
  if (field.type === 'string' && field.format === 'date') return { path, match: 'date', argument: 'yyyy-MM-dd' };
  return { path, match: 'type', argument: '' };
}

/** What **Fill from the spec** changes, and the note it leaves. */
export interface SpecFill {
  patch: Pick<InteractionDraft, 'status' | 'responseHeaders' | 'responseBody' | 'responseMatchers'>;
  note: string;
}

/**
 * Fill an interaction's response from the spec: status, content type, the example body and a
 * matcher per field. Headers already typed are kept; the Content-Type is set.
 *
 * @param ix - The interaction.
 * @param operation - The operation its path matched.
 * @returns The change and its note, or why nothing could be filled.
 */
export function fillFromSpec(ix: InteractionDraft, operation: SpecOperation): SpecFill | { error: string } {
  const response = pickSpecResponse(operation, ix.status);
  if (!response) return { error: `${operation.method} ${operation.path} documents no response to fill from.` };
  const status = /^[1-5]\d\d$/.test(response.status) ? response.status : /^[1-5]XX$/i.test(response.status) ? `${response.status[0]}00` : '200';
  const contentType = response.contentType ?? JSON_TYPE;
  const headers = ix.responseHeaders.filter((h) => h.name.toLowerCase() !== 'content-type');
  const hasBody = response.example !== undefined;
  const text = !hasBody ? '' : typeof response.example === 'string' && !isJsonType(contentType) ? response.example : JSON.stringify(response.example, null, 2);
  const note =
    response.exampleSource === 'spec'
      ? `Filled from the ${response.status} response of ${operation.method} ${operation.path}: the spec’s example.`
      : response.exampleSource === 'schema'
        ? `Filled from the ${response.status} response of ${operation.method} ${operation.path}: generated from the schema — review the values.`
        : `The ${response.status} response of ${operation.method} ${operation.path} has no body.`;
  return {
    patch: {
      status,
      responseHeaders: response.contentType ? [...headers, { name: 'Content-Type', value: contentType }] : headers,
      responseBody: { text, contentType },
      responseMatchers: isJsonType(contentType) ? response.fields.map(matcherForField) : [],
    },
    note,
  };
}

// --- adding a field the consumer needs -----------------------------------------------------------

/**
 * Put a value at a field path in a JSON body, creating objects and arrays on the way
 * (`[*]` is the first item).
 *
 * @param bodyText - The body as typed (empty is `{}`).
 * @param path - E.g. `$.items[*].id`.
 * @param value - The value.
 * @returns The new body text, or why it cannot be placed.
 */
export function placeField(bodyText: string, path: string, value: unknown): { text: string } | { error: string } {
  let root: unknown = {};
  if (bodyText.trim()) {
    try {
      root = JSON.parse(bodyText);
    } catch {
      return { error: 'The body is not valid JSON, so the field cannot be added to it.' };
    }
  }
  const tokens: Array<string | number> = [];
  const pattern = /\.([A-Za-z_][A-Za-z0-9_-]*)|\[(\*|\d+)\]|\['([^']*)'\]/gy;
  if (!path.startsWith('$')) return { error: `${path} is not a field path such as $.id.` };
  pattern.lastIndex = 1;
  while (pattern.lastIndex < path.length) {
    const match = pattern.exec(path);
    if (!match) return { error: `${path} is not a field path such as $.id or $.items[*].id.` };
    tokens.push(match[1] ?? match[3] ?? (match[2] === '*' ? 0 : Number(match[2])));
  }
  if (!tokens.length) return { text: JSON.stringify(value, null, 2) };
  if (typeof tokens[0] === 'number' ? !Array.isArray(root) : !isObject(root)) {
    root = typeof tokens[0] === 'number' ? [] : {};
  }
  let node = root as Record<string | number, unknown>;
  for (let i = 0; i < tokens.length - 1; i += 1) {
    const key = tokens[i];
    const wantArray = typeof tokens[i + 1] === 'number';
    const child = node[key];
    if (wantArray ? !Array.isArray(child) : !isObject(child)) node[key] = wantArray ? [] : {};
    node = node[key] as Record<string | number, unknown>;
  }
  node[tokens[tokens.length - 1]] = value;
  return { text: JSON.stringify(root, null, 2) };
}
