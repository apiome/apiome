/**
 * The **Publish a consumer pact** page — PFX-8.3 (#7300), `/ade/dashboard/pacts/publish`.
 *
 * Everything the page decides without the network lives here, so the page, the proxies and the
 * tests share one model:
 *
 * * **Reading files** ({@link readPactFile}): each uploaded or pasted document becomes a row with
 *   its pair, Pact specification, interaction count and kinds — or the reason it will not be
 *   published. The checks are REST's (`pact_publication.validate_pact_document`), so a row the page
 *   accepts is one REST accepts; a bad row never blocks the others ({@link annotateRows}).
 * * **Whose version** ({@link validateWhose}): every flag of `apiome pact publish` has a field.
 *   *Merge* is refused with the CLI's reason, because Apiome stores a version's pact as published.
 * * **Publishing** ({@link publishBatches}): one request per consumer, at most 100 pacts each — what
 *   the CLI sends — and {@link readPublishOutcome} turns REST's notices into new / unchanged /
 *   changed per pact.
 * * **Check only** ({@link classifyCheck}): reads the pact already published for the version and
 *   says, before anything is written, whether the publish would be new, unchanged, or refused.
 * * **The same, from anywhere** ({@link publishCommandAction}).
 */

import { parseTags, MAX_FIELD_CHARS, MAX_PACT_CHARS, MAX_PACTS_PER_REQUEST, MAX_TAGS, MAX_URL_CHARS, isHttpUrl } from './pact-publish';
import { versionProblem } from './pact-detail';
import { tenantPath, type PactAction, type PactOption, type PactUnsupported } from './pact-commands';

/** The page's route. */
export const PUBLISH_ROUTE = '/ade/dashboard/pacts/publish';

/** Where the import dialog leaves the pact it hands to the page (sessionStorage, read once). */
export const PUBLISH_HANDOFF_KEY = 'apiome.pactPublish.handoff';

/** Most files one page holds (one request per consumer carries at most 100 anyway). */
export const MAX_FILES = 200;

/** The page's ways to bring a pact in (`write` is the interaction editor, PFX-8.5). */
export const PUBLISH_SOURCES = ['upload', 'paste', 'derive', 'write'] as const;

/** One way in. */
export type PublishSource = (typeof PUBLISH_SOURCES)[number];

/** Why Merge cannot be turned on — the CLI's `--merge` refusal, word for word in meaning. */
export const MERGE_REFUSED =
  'Apiome stores a consumer version’s pact as published and does not merge interactions. Turn Merge off and publish the complete pact; apiome pact publish --merge is refused for the same reason.';

/** What a version conflict says (same version, different content). */
export function conflictMessage(version: string): string {
  return `${version} already has a different pact. Use a new version: Apiome does not merge pacts, and a published pact is never changed.`;
}

// --- reading files -------------------------------------------------------------------------------

/** One pact the page holds, uploaded or pasted. */
export interface PactFileRow {
  /** Unique within the page. */
  id: string;
  /** The file's name, or `Pasted pact`. */
  fileName: string;
  /** The document as text. */
  text: string;
  /** `consumer.name`, when the document has one. */
  consumer: string | null;
  /** `provider.name`, when the document has one. */
  provider: string | null;
  /** The declared specification, e.g. `3.0.0`. */
  specVersion: string | null;
  /** How many interactions and messages it carries. */
  interactions: number;
  /** The kinds of interaction it carries, e.g. `['HTTP', 'Message']`. */
  kinds: string[];
  /** Why it will not be published, or `null` when it will. */
  problem: string | null;
}

/** HTTP interaction `type`s REST checks as HTTP (lower case). */
const HTTP_TYPES = ['synchronous/http', 'http'];

/** Whether a value is a plain JSON object. */
function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * The Pact specification a document declares (REST's `pact_specification_version`).
 *
 * @param document - The parsed document.
 * @returns E.g. `3.0.0`, or `null`.
 */
export function pactSpecVersion(document: Record<string, unknown>): string | null {
  const metadata = isObject(document.metadata) ? document.metadata : {};
  for (const key of ['pactSpecification', 'pact-specification']) {
    const block = metadata[key];
    const version = isObject(block) ? block.version : undefined;
    if (typeof version === 'string' && version.trim()) return version.trim();
  }
  const flat = metadata.pactSpecificationVersion;
  return typeof flat === 'string' && flat.trim() ? flat.trim() : null;
}

/**
 * How a specification reads in the table.
 *
 * @param version - E.g. `3.0.0`.
 * @returns `Pact v3`, or `Unstated` without one.
 */
export function specLabel(version: string | null): string {
  if (!version) return 'Unstated';
  const major = /^v?(\d+)/i.exec(version)?.[1];
  return major ? `Pact v${major}` : `Pact ${version}`;
}

/**
 * The kind of one interaction or message.
 *
 * @param entry - The interaction.
 * @param key - `interactions` or `messages`.
 * @param plugins - The plugin names the document's metadata lists (lower case).
 * @returns `HTTP`, `Message`, `GraphQL` or `gRPC`.
 */
function interactionKind(entry: Record<string, unknown>, key: string, plugins: string[]): string {
  if (key === 'messages') return 'Message';
  const type = typeof entry.type === 'string' ? entry.type.toLowerCase() : '';
  if (type.includes('message')) {
    // `transport: grpc` names a gRPC call outright (the editor writes it, PFX-8.5); older protobuf
    // plugins only list themselves in the metadata.
    if (typeof entry.transport === 'string' && entry.transport.toLowerCase() === 'grpc') return 'gRPC';
    return plugins.includes('protobuf') || plugins.includes('grpc') ? 'gRPC' : 'Message';
  }
  const request = isObject(entry.request) ? entry.request : {};
  const path = typeof request.path === 'string' ? request.path : '';
  // A v4 body is `{ content, contentType }`; earlier specifications carry the body itself.
  const raw = request.body;
  const body = isObject(raw) ? (isObject(raw.content) ? raw.content : raw) : {};
  if (/graphql/i.test(path) && typeof body.query === 'string') return 'GraphQL';
  return 'HTTP';
}

/**
 * Check one HTTP interaction as REST does.
 *
 * @param entry - The interaction.
 * @param where - E.g. `interaction 3`, for the sentence.
 * @returns The problem, or `null`.
 */
function httpProblem(entry: Record<string, unknown>, where: string): string | null {
  if (!isObject(entry.request)) return `${where} has no request object.`;
  const method = entry.request.method;
  if (typeof method !== 'string' || !method.trim()) return `${where} has no request method.`;
  if ('path' in entry.request && typeof entry.request.path !== 'string') return `${where} has a request path that is not text.`;
  if (!isObject(entry.response)) return `${where} has no response object.`;
  const status = entry.response.status;
  if (status !== undefined && status !== null && !Number.isInteger(status)) return `${where} has a response status that is not a whole number.`;
  return null;
}

/**
 * Read one document into a row.
 *
 * @param id - The row's id.
 * @param fileName - The file's name (or `Pasted pact`).
 * @param text - The document.
 * @returns The row; `problem` says why it will not be published, starting with “Not a pact”.
 */
export function readPactFile(id: string, fileName: string, text: string): PactFileRow {
  const row: PactFileRow = { id, fileName, text, consumer: null, provider: null, specVersion: null, interactions: 0, kinds: [], problem: null };
  const fail = (problem: string): PactFileRow => ({ ...row, problem });
  if (text.length > MAX_PACT_CHARS) return fail('Too large to publish (over 8 MB).');
  let document: unknown;
  try {
    document = JSON.parse(text);
  } catch {
    return fail('Not a pact: the file is not JSON.');
  }
  if (!isObject(document)) return fail('Not a pact: the file is not a JSON object.');
  const names: Record<'consumer' | 'provider', string | null> = { consumer: null, provider: null };
  for (const role of ['consumer', 'provider'] as const) {
    const block = document[role];
    const name = isObject(block) ? block.name : undefined;
    if (block !== undefined && (!isObject(block) || typeof name !== 'string' || !name.trim())) {
      return fail(`Not a pact: the ${role} name is missing or empty.`);
    }
    names[role] = typeof name === 'string' ? name.trim() : null;
  }
  Object.assign(row, names, { specVersion: pactSpecVersion(document) });
  if (!names.consumer) return { ...row, problem: 'Not a pact: missing consumer.' };
  if (!names.provider) return { ...row, problem: 'Not a pact: missing provider.' };
  if (names.consumer.length > MAX_FIELD_CHARS || names.provider.length > MAX_FIELD_CHARS) {
    return { ...row, problem: `A pacticipant name is longer than ${MAX_FIELD_CHARS} characters.` };
  }
  if ('metadata' in document && !isObject(document.metadata)) return { ...row, problem: 'Not a pact: metadata must be an object.' };
  if (!('interactions' in document) && !('messages' in document)) {
    return { ...row, problem: 'Not a pact: there is no interactions or messages list.' };
  }
  const metadata = isObject(document.metadata) ? document.metadata : {};
  const plugins = Array.isArray(metadata.plugins)
    ? metadata.plugins.flatMap((plugin) => (isObject(plugin) && typeof plugin.name === 'string' ? [plugin.name.toLowerCase()] : []))
    : [];
  const kinds = new Set<string>();
  let count = 0;
  for (const key of ['interactions', 'messages']) {
    if (!(key in document)) continue;
    const entries = document[key];
    if (!Array.isArray(entries)) return { ...row, problem: `Not a pact: ${key} must be a list.` };
    for (const [index, entry] of entries.entries()) {
      const where = `${key === 'messages' ? 'Message' : 'Interaction'} ${index + 1}`;
      if (!isObject(entry)) return { ...row, problem: `${where} is not an object.` };
      const type = typeof entry.type === 'string' ? entry.type.trim().toLowerCase() : null;
      if (key === 'interactions' && (type === null || HTTP_TYPES.includes(type))) {
        const problem = httpProblem(entry, where);
        if (problem) return { ...row, problem };
      }
      kinds.add(interactionKind(entry, key, plugins));
    }
    count += entries.length;
  }
  return { ...row, interactions: count, kinds: [...kinds] };
}

/**
 * The handle REST derives from a name (`slugify_consumer_name`), for telling pairs apart.
 *
 * @param name - E.g. `Billing Service`.
 * @returns E.g. `billing-service`.
 */
export function pacticipantKey(name: string): string {
  return name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 128).replace(/-+$/, '');
}

/**
 * Mark the rows that cannot go with the others: a second file for the same pair.
 *
 * @param rows - The rows, in the order they were added.
 * @returns The same rows; a repeated pair carries a problem naming the file it repeats.
 */
export function annotateRows(rows: PactFileRow[]): PactFileRow[] {
  const seen = new Map<string, string>();
  return rows.map((row) => {
    if (row.problem || !row.consumer || !row.provider) return row;
    const pair = `${pacticipantKey(row.consumer)}→${pacticipantKey(row.provider)}`;
    const first = seen.get(pair);
    if (first) {
      return { ...row, problem: `${first} is also ${row.consumer} → ${row.provider}: a consumer version publishes one pact per provider.` };
    }
    seen.set(pair, row.fileName);
    return row;
  });
}

/** The rows that will be published. */
export function publishableRows(rows: PactFileRow[]): PactFileRow[] {
  return rows.filter((row) => !row.problem && row.consumer && row.provider);
}

// --- whose version -------------------------------------------------------------------------------

/** The **Whose version this is** section. */
export interface WhoseVersion {
  version: string;
  branch: string;
  /** Comma- or space-separated, as typed. */
  tags: string;
  buildUrl: string;
  /** `--merge`: refused (see {@link MERGE_REFUSED}). */
  merge: boolean;
  /** `--tag-with-git-branch`: the branch is also put on the version as a tag. */
  tagWithBranch: boolean;
}

/** An empty section. */
export const EMPTY_WHOSE: WhoseVersion = { version: '', branch: '', tags: '', buildUrl: '', merge: false, tagWithBranch: false };

/**
 * The tags the version gets: the typed ones, plus the branch with *Also tag with the branch name*.
 *
 * @param whose - The section.
 * @returns The tags, without repeats.
 */
export function effectiveTags(whose: WhoseVersion): string[] {
  const tags = parseTags(whose.tags);
  const branch = whose.branch.trim();
  return whose.tagWithBranch && branch && !tags.includes(branch) ? [...tags, branch] : tags;
}

/**
 * Check the section before anything is sent (and before a check).
 *
 * @param whose - The section.
 * @returns A sentence naming the first problem, or `null`.
 */
export function validateWhose(whose: WhoseVersion): string | null {
  if (whose.merge) return MERGE_REFUSED;
  const version = whose.version.trim();
  if (!version) return 'Give the consumer version being published (a commit SHA, for instance).';
  if (version.length > MAX_FIELD_CHARS) return `Consumer version is longer than ${MAX_FIELD_CHARS} characters.`;
  if (whose.branch.trim().length > MAX_FIELD_CHARS) return `Branch is longer than ${MAX_FIELD_CHARS} characters.`;
  if (whose.tagWithBranch && !whose.branch.trim()) return 'Also tag with the branch name needs a branch.';
  const tags = effectiveTags(whose);
  if (tags.length > MAX_TAGS) return `At most ${MAX_TAGS} tags.`;
  if (tags.some((tag) => tag.length > MAX_FIELD_CHARS)) return `A tag is longer than ${MAX_FIELD_CHARS} characters.`;
  const url = whose.buildUrl.trim();
  if (url && (url.length > MAX_URL_CHARS || !isHttpUrl(url))) return 'The build URL must be an http(s) URL.';
  return null;
}

// --- publishing ----------------------------------------------------------------------------------

/** One request to `/api/pact/publish`: one consumer, at most 100 pacts. */
export interface PublishBatch {
  consumer: string;
  rows: PactFileRow[];
  body: Record<string, unknown>;
}

/**
 * The requests a publish sends — one per consumer (and per 100 pacts), as the CLI sends them.
 *
 * @param rows - Every row; only {@link publishableRows} are sent.
 * @param whose - The section (already valid).
 * @returns The requests, in the order the consumers first appear.
 */
export function publishBatches(rows: PactFileRow[], whose: WhoseVersion): PublishBatch[] {
  const byConsumer = new Map<string, PactFileRow[]>();
  for (const row of publishableRows(rows)) {
    const key = pacticipantKey(row.consumer as string);
    byConsumer.set(key, [...(byConsumer.get(key) ?? []), row]);
  }
  const tags = effectiveTags(whose);
  const batches: PublishBatch[] = [];
  for (const group of byConsumer.values()) {
    for (let start = 0; start < group.length; start += MAX_PACTS_PER_REQUEST) {
      const chunk = group.slice(start, start + MAX_PACTS_PER_REQUEST);
      const consumer = chunk[0].consumer as string;
      batches.push({
        consumer,
        rows: chunk,
        body: {
          consumerName: consumer,
          version: whose.version.trim(),
          ...(whose.branch.trim() ? { branch: whose.branch.trim() } : {}),
          ...(tags.length ? { tags } : {}),
          ...(whose.buildUrl.trim() ? { buildUrl: whose.buildUrl.trim() } : {}),
          pacts: chunk.map((row) => ({ providerName: row.provider as string, pact: row.text })),
        },
      });
    }
  }
  return batches;
}

/** What publishing did to one pact. */
export type PublishedState = 'new' | 'unchanged' | 'changed';

/** One pact of a publish result. */
export interface PublishedPact {
  provider: string;
  state: PublishedState;
  /** The content address, when REST returned it. */
  sha: string | null;
}

/** What one request answered. */
export interface PublishOutcome {
  consumer: string;
  pacts: PublishedPact[];
  /** Every notice, as the CLI prints them. */
  notices: string[];
  /** How many bi-directional comparisons the publish stored. */
  compared: number;
}

/**
 * Read REST's publish answer.
 *
 * @param consumer - The consumer the request was for.
 * @param data - REST's body (`notices`, `_links['pb:contracts']`, `comparisons`).
 * @returns One entry per pact, with its state from the notice that names its provider.
 */
export function readPublishOutcome(consumer: string, data: unknown): PublishOutcome {
  const body = isObject(data) ? data : {};
  const notices = Array.isArray(body.notices)
    ? body.notices.flatMap((n) => (isObject(n) && typeof n.text === 'string' ? [n.text] : []))
    : [];
  const links = isObject(body._links) && Array.isArray(body._links['pb:contracts']) ? body._links['pb:contracts'] : [];
  const shas = links.flatMap((link) => (isObject(link) && typeof link.pactVersionSha === 'string' ? [link.pactVersionSha] : [null]));
  const pacts: PublishedPact[] = [];
  for (const text of notices) {
    const match = /^(Pact successfully published|Pact successfully republished|Pact with changed content published) for .+ and provider (.+?)( with no content changes)?\.$/.exec(text);
    if (!match) continue;
    const state: PublishedState = match[1].includes('changed content') ? 'changed' : match[1].includes('republished') ? 'unchanged' : 'new';
    pacts.push({ provider: match[2], state, sha: shas[pacts.length] ?? null });
  }
  const comparisons = isObject(body.comparisons) ? body.comparisons : {};
  return { consumer, pacts, notices, compared: typeof comparisons.compared === 'number' ? comparisons.compared : 0 };
}

/**
 * The provider a REST refusal of a bulk publish names (`contract 2 (Billing Service): …`).
 *
 * @param message - REST's message.
 * @returns The 0-based contract index, or `null` when the refusal is about the whole request.
 */
export function refusedContractIndex(message: string): number | null {
  const match = /\bcontract (\d+) \(/.exec(message);
  return match ? Number(match[1]) : null;
}

/**
 * The sentence for one published pact.
 *
 * @param pact - The pact.
 * @returns E.g. `new content — pending for Billing Service until they pass it once.`
 */
export function publishedSentence(pact: PublishedPact): string {
  const sha = pact.sha ? pact.sha.slice(0, 7) : null;
  if (pact.state === 'new') return `new content, pending for ${pact.provider} until they pass it once: it cannot fail their build before then.`;
  if (pact.state === 'unchanged') return `unchanged${sha ? ` since ${sha}` : ''}: its verification results still apply, nothing to do.`;
  return `changed content replaced the pact for this version: ${pact.provider} verifies it again.`;
}

// --- check only ----------------------------------------------------------------------------------

/** What a publish would do to one row, read before anything is written. */
export type CheckVerdict =
  | { kind: 'new' }
  | { kind: 'unchanged'; sha: string | null }
  | { kind: 'conflict'; sha: string | null }
  | { kind: 'error'; message: string };

/** The proxy URL that reads the pact a version already has for a pair. */
export function checkUrl(consumer: string, provider: string, version: string): string {
  const query = new URLSearchParams({ consumer, provider, version });
  return `/api/pact/publish/check?${query.toString()}`;
}

/** The check proxy's parameters, or why the request is refused. */
export type PickedCheck = { ok: true; consumer: string; provider: string; version: string } | { ok: false; error: string };

/**
 * Read the check proxy's query: exactly `consumer`, `provider` and `version`, once each.
 *
 * @param params - The browser's query string.
 * @returns The three values, or a sentence naming the problem (a 400).
 */
export function pickCheckQuery(params: URLSearchParams): PickedCheck {
  const values: Record<string, string> = {};
  for (const [key, value] of params.entries()) {
    if (!['consumer', 'provider', 'version'].includes(key)) {
      return { ok: false, error: `Unsupported parameter ${key}: a check takes consumer, provider and version.` };
    }
    if (key in values) return { ok: false, error: `The ${key} parameter is given more than once.` };
    values[key] = value;
  }
  for (const key of ['consumer', 'provider']) {
    const value = (values[key] ?? '').trim();
    if (!value) return { ok: false, error: `${key} is required.` };
    if (value.length > MAX_FIELD_CHARS) return { ok: false, error: `${key} is longer than ${MAX_FIELD_CHARS} characters.` };
    if (/[\u0000-\u001f\u007f]/.test(value)) return { ok: false, error: `${key} contains a control character.` };
  }
  const problem = versionProblem(values.version ?? '');
  if (problem) return { ok: false, error: problem };
  return { ok: true, consumer: values.consumer.trim(), provider: values.provider.trim(), version: values.version };
}

/**
 * A JSON value with object keys sorted, for comparing two documents whatever their key order.
 *
 * @param value - Any JSON value.
 * @returns Its canonical text.
 */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (isObject(value)) {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`)
      .join(',')}}`;
  }
  return JSON.stringify(value);
}

/**
 * Whether two pacts are the same content as REST counts it (`pact_content_sha`): the same
 * interactions, messages and specification, whatever the metadata or key order.
 *
 * @param left - One document.
 * @param right - The other.
 * @returns `true` when REST would store them as one pact version.
 */
export function samePactContent(left: Record<string, unknown>, right: Record<string, unknown>): boolean {
  const content = (document: Record<string, unknown>) =>
    canonical({
      ...(document.interactions !== undefined ? { interactions: document.interactions } : {}),
      ...(document.messages !== undefined ? { messages: document.messages } : {}),
      spec: pactSpecVersion(document),
    });
  return content(left) === content(right);
}

/**
 * The content address of a pact REST returned (`_links['pb:pact-version'].href` ends with it).
 *
 * @param body - The read pact.
 * @returns The SHA, or `null`.
 */
export function pactVersionSha(body: unknown): string | null {
  const href = isObject(body) && isObject(body._links) && isObject(body._links['pb:pact-version']) ? body._links['pb:pact-version'].href : null;
  return typeof href === 'string' ? (/\/pact-version\/([0-9a-f]{6,64})$/.exec(href)?.[1] ?? null) : null;
}

/**
 * What publishing a row would do, from the read of the pact its version already has.
 *
 * @param row - The row (publishable).
 * @param status - The read's HTTP status.
 * @param body - The read's body.
 * @returns New (nothing published for the version), unchanged, a conflict, or the read's failure.
 */
export function classifyCheck(row: PactFileRow, status: number, body: unknown): CheckVerdict {
  if (status === 404) return { kind: 'new' };
  if (status >= 400 || !isObject(body)) {
    const error = isObject(body) && typeof body.error === 'string' ? body.error : `The check failed (${status}).`;
    return { kind: 'error', message: error };
  }
  const mine = JSON.parse(row.text) as Record<string, unknown>;
  const sha = pactVersionSha(body);
  return samePactContent(mine, body) ? { kind: 'unchanged', sha } : { kind: 'conflict', sha };
}

/**
 * The sentence for a check verdict.
 *
 * @param verdict - The verdict.
 * @param version - The consumer version checked.
 * @returns E.g. `Unchanged since 8d2f1c0 — its verification results still apply.`
 */
export function checkSentence(verdict: CheckVerdict, version: string): string {
  switch (verdict.kind) {
    case 'new':
      return `Nothing is published for ${version} yet: this pact will be new.`;
    case 'unchanged':
      return `Unchanged${verdict.sha ? ` since ${verdict.sha.slice(0, 7)}` : ''}: its verification results still apply.`;
    case 'conflict':
      return conflictMessage(version);
    default:
      return verdict.message;
  }
}

// --- derive from a project -----------------------------------------------------------------------

/** The **Derive from a project** tab: `apiome pact publish-consumer-contract`'s own fields. */
export interface DeriveDraft {
  /** Project handle or id. */
  project: string;
  /** Consumer handle or id within the project. */
  consumer: string;
  /** A contract revision number; empty is the current one. */
  revision: string;
  /** The provider pacticipant's name; empty lets REST resolve it. */
  provider: string;
}

/** An empty tab. */
export const EMPTY_DERIVE: DeriveDraft = { project: '', consumer: '', revision: '', provider: '' };

/** The REST path below the tenant for a derived publish. */
export function derivePath(project: string, consumer: string): string {
  return `projects/${encodeURIComponent(project)}/consumers/${encodeURIComponent(consumer)}/pact/publish`;
}

/**
 * Check the tab before anything is sent.
 *
 * @param draft - The tab.
 * @returns A sentence naming the first problem, or `null`.
 */
export function validateDerive(draft: DeriveDraft): string | null {
  if (!draft.project.trim()) return 'Pick the project whose consumer surface becomes the pact.';
  if (!draft.consumer.trim()) return 'Pick the consumer the pact is for.';
  if (draft.revision.trim() && !/^[1-9]\d{0,8}$/.test(draft.revision.trim())) return 'Revision is a whole number (1 or more), or empty for the current one.';
  if (draft.provider.trim().length > 200) return 'Provider is longer than 200 characters.';
  return null;
}

/**
 * The body for `/api/pact/publish/consumer-contract`.
 *
 * @param draft - The tab.
 * @param whose - The version section.
 * @returns The JSON body; empty optional fields are left out.
 */
export function deriveRequest(draft: DeriveDraft, whose: WhoseVersion): Record<string, unknown> {
  const tags = effectiveTags(whose);
  return {
    project: draft.project.trim(),
    consumer: draft.consumer.trim(),
    version: whose.version.trim(),
    ...(whose.branch.trim() ? { branch: whose.branch.trim() } : {}),
    ...(tags.length ? { tags } : {}),
    ...(whose.buildUrl.trim() ? { buildUrl: whose.buildUrl.trim() } : {}),
    ...(draft.revision.trim() ? { revision: Number(draft.revision.trim()) } : {}),
    ...(draft.provider.trim() ? { provider: draft.provider.trim() } : {}),
  };
}

/** The fields `/api/pact/publish/consumer-contract` takes. */
export const DERIVE_FIELDS = ['project', 'consumer', 'version', 'branch', 'tags', 'buildUrl', 'revision', 'provider'] as const;

/** A derived publish the proxy accepted, or why not. */
export type PickedDerive = { ok: true; path: string; body: Record<string, unknown> } | { ok: false; error: string };

/**
 * Check what the browser sent the derive proxy and build REST's path and body.
 *
 * @param raw - The parsed request body.
 * @returns REST's path below the tenant and its body (`consumer_version`, …), or a 400 sentence.
 */
export function pickDeriveBody(raw: unknown): PickedDerive {
  if (!isObject(raw)) return { ok: false, error: 'The body must be a JSON object describing the publication.' };
  for (const key of Object.keys(raw)) {
    if (!(DERIVE_FIELDS as readonly string[]).includes(key)) {
      return { ok: false, error: `Unsupported field ${key}: a derived publication takes ${DERIVE_FIELDS.join(', ')}.` };
    }
  }
  for (const key of ['project', 'consumer', 'version', 'branch', 'buildUrl', 'provider']) {
    if (raw[key] !== undefined && typeof raw[key] !== 'string') return { ok: false, error: `${key} must be a string.` };
  }
  const text = (key: string) => ((raw[key] as string | undefined) ?? '').trim();
  for (const key of ['project', 'consumer', 'version']) if (!text(key)) return { ok: false, error: `${key} is required.` };
  for (const key of ['project', 'consumer', 'version', 'branch']) {
    if (text(key).length > MAX_FIELD_CHARS) return { ok: false, error: `${key} is longer than ${MAX_FIELD_CHARS} characters.` };
  }
  if (text('provider').length > 200) return { ok: false, error: 'provider is longer than 200 characters.' };
  if (text('buildUrl') && (text('buildUrl').length > MAX_URL_CHARS || !isHttpUrl(text('buildUrl')))) {
    return { ok: false, error: 'buildUrl must be an http(s) URL.' };
  }
  if (raw.revision !== undefined && (!Number.isInteger(raw.revision) || (raw.revision as number) < 1)) {
    return { ok: false, error: 'revision must be a whole number, 1 or more.' };
  }
  let tags: string[] = [];
  if (raw.tags !== undefined) {
    if (!Array.isArray(raw.tags) || raw.tags.some((tag) => typeof tag !== 'string' || !tag.trim())) {
      return { ok: false, error: 'tags must be a list of non-empty strings.' };
    }
    tags = raw.tags as string[];
    if (tags.length > MAX_TAGS) return { ok: false, error: `tags takes at most ${MAX_TAGS}.` };
    if (tags.some((tag) => tag.length > MAX_FIELD_CHARS)) return { ok: false, error: `A tag is longer than ${MAX_FIELD_CHARS} characters.` };
  }
  return {
    ok: true,
    path: derivePath(text('project'), text('consumer')),
    body: {
      consumer_version: text('version'),
      ...(text('branch') ? { branch: text('branch') } : {}),
      ...(tags.length ? { tags } : {}),
      ...(text('buildUrl') ? { build_url: text('buildUrl') } : {}),
      ...(raw.revision !== undefined ? { revision: raw.revision } : {}),
      ...(text('provider') ? { provider: text('provider') } : {}),
    },
  };
}

/** One finding of a derived pact (a value invented, or something left out). */
export interface DeriveFinding {
  outcome: string;
  message: string;
  method?: string | null;
  path?: string | null;
}

/** What a derived publish answered: the generated pact's findings and the broker's result. */
export interface DeriveOutcome extends PublishOutcome {
  revision: number | null;
  findings: DeriveFinding[];
  /** The generated Pact document, for **Download the published pact** (`--output`). */
  pact: Record<string, unknown> | null;
}

/**
 * Read REST's derived publish answer.
 *
 * @param data - REST's body (`consumer_name`, `findings`, `pact`, `publish`).
 * @returns The outcome.
 */
export function readDeriveOutcome(data: unknown): DeriveOutcome {
  const body = isObject(data) ? data : {};
  const consumer = typeof body.consumer_name === 'string' ? body.consumer_name : '';
  const findings = Array.isArray(body.findings)
    ? body.findings.flatMap((f) => (isObject(f) && typeof f.message === 'string' ? [f as unknown as DeriveFinding] : []))
    : [];
  return {
    ...readPublishOutcome(consumer, body.publish),
    revision: typeof body.revision === 'number' ? body.revision : null,
    findings,
    pact: isObject(body.pact) ? body.pact : null,
  };
}

// --- arriving pre-filled -------------------------------------------------------------------------

/** What the page can be opened with (the import dialog's shortcut, a pacticipant's link). */
export interface PublishPrefill {
  whose: WhoseVersion;
  source: PublishSource;
  derive: DeriveDraft;
  /** Query parameters the page cannot use, each reported. */
  problems: string[];
}

/** The query parameters the page reads. */
export const PREFILL_PARAMS = ['version', 'branch', 'tag', 'buildUrl', 'source', 'project', 'consumer', 'provider'] as const;

/**
 * Read the address the page was opened with.
 *
 * @param query - Next's search params.
 * @returns The prefill; anything that cannot be used is named in `problems`, never dropped.
 */
export function readPublishPrefill(query: Record<string, string | string[] | undefined>): PublishPrefill {
  const problems: string[] = [];
  const one = (key: string): string => {
    const value = query[key];
    if (Array.isArray(value)) {
      problems.push(`?${key}= was given more than once; the first is used.`);
      return value[0] ?? '';
    }
    return value ?? '';
  };
  for (const key of Object.keys(query)) {
    if (!(PREFILL_PARAMS as readonly string[]).includes(key)) problems.push(`?${key}= is not something this page reads.`);
  }
  const tags = query.tag === undefined ? [] : Array.isArray(query.tag) ? query.tag : [query.tag];
  const sourceText = one('source');
  let source: PublishSource = 'upload';
  if (sourceText) {
    if ((PUBLISH_SOURCES as readonly string[]).includes(sourceText)) source = sourceText as PublishSource;
    else problems.push(`?source=${sourceText} is not a way in (upload, paste, derive or write).`);
  }
  const clip = (key: string, max = MAX_FIELD_CHARS): string => {
    const value = one(key).trim();
    if (value.length > max) {
      problems.push(`?${key}= is longer than ${max} characters and was left out.`);
      return '';
    }
    return value;
  };
  return {
    whose: { ...EMPTY_WHOSE, version: clip('version'), branch: clip('branch'), tags: tags.join(', '), buildUrl: clip('buildUrl', MAX_URL_CHARS) },
    source,
    derive: { ...EMPTY_DERIVE, project: clip('project'), consumer: clip('consumer'), provider: clip('provider', 200) },
    problems,
  };
}

/**
 * The page's address, pre-filled — what the import dialog's **Open the Publish page** links to.
 *
 * @param fields - What to fill in.
 * @returns E.g. `/ade/dashboard/pacts/publish?source=paste&version=9f3c2a1`.
 */
export function publishRoute(fields: Partial<Record<'version' | 'branch' | 'buildUrl' | 'source' | 'project' | 'consumer' | 'provider', string>> & { tags?: string[] } = {}): string {
  const query = new URLSearchParams();
  for (const key of ['source', 'version', 'branch', 'buildUrl', 'project', 'consumer', 'provider'] as const) {
    const value = fields[key]?.trim();
    if (value) query.set(key, value);
  }
  for (const tag of fields.tags ?? []) query.append('tag', tag);
  const text = query.toString();
  return text ? `${PUBLISH_ROUTE}?${text}` : PUBLISH_ROUTE;
}

// --- the same, from anywhere ---------------------------------------------------------------------

/**
 * Every flag of the two commands this page does, and the field that sets it — the ledger's
 * `fields` for `publish` and `publish-consumer-contract` (`docs/pact-parity-ledger.json`); the
 * parity test holds the three together.
 */
export const PUBLISH_FLAG_FIELDS: Readonly<Record<'publish' | 'publish-consumer-contract', Readonly<Record<string, string>>>> = {
  publish: {
    pacts: 'Upload (files or a folder), Paste and Write interactions',
    '--consumer-app-version': 'Consumer version',
    '--branch': 'Branch',
    '--auto-detect-version-properties': 'Fill from the linked repository',
    '--tag': 'Tags',
    '--tag-with-git-branch': 'Also tag with the branch name',
    '--build-url': 'Build URL',
    '--merge': 'Merge with the pact already published for this version (refused, with the reason)',
    '--output': 'The result dialog (the CLI’s text or JSON output)',
    '--broker-base-url': 'The workspace you are signed in to',
    '--broker-token': 'Your session',
  },
  'publish-consumer-contract': {
    '--project': 'Derive from a project → Project',
    '--consumer': 'Derive from a project → Consumer',
    '--consumer-app-version': 'Consumer version',
    '--branch': 'Branch',
    '--tag': 'Tags',
    '--build-url': 'Build URL',
    '--revision': 'Derive from a project → Revision',
    '--provider': 'Derive from a project → Provider',
    '--output': 'Download the published pact, in the result dialog',
    '--fail-on-findings': 'The findings, listed in the result dialog',
    '--broker-base-url': 'The workspace you are signed in to',
    '--broker-token': 'Your session',
  },
};

/**
 * What the page's form would do, for **The same, from anywhere**.
 *
 * Uploaded files become the `pacts` argument (`pacts/`, the folder a test run writes); a derive
 * becomes `publish-consumer-contract`. Merge is listed as not carried, with its reason.
 *
 * @param input - The tab, the rows, both sections, and the workspace slug (empty writes `{tenant}`).
 * @returns The action for `pactCommandSurfaces`.
 */
export function publishCommandAction(input: {
  source: PublishSource;
  rows: PactFileRow[];
  whose: WhoseVersion;
  derive: DeriveDraft;
  tenant: string;
}): PactAction {
  const { source, whose, derive, tenant } = input;
  const version = whose.version.trim() || '<version>';
  const tags = parseTags(whose.tags);
  const unsupported: PactUnsupported[] = whose.merge
    ? [{ what: 'Merge', reason: 'apiome pact publish --merge is refused: Apiome does not merge interactions.', inRest: false }]
    : [];
  if (source === 'derive') {
    const options: PactOption[] = [
      { flag: '--project', value: derive.project.trim() || '<project>' },
      { flag: '--consumer', value: derive.consumer.trim() || '<consumer>' },
      { flag: '--consumer-app-version', value: version },
      { flag: '--branch', value: whose.branch.trim() },
      { flag: '--tag', value: effectiveTags(whose) },
      { flag: '--build-url', value: whose.buildUrl.trim() },
      { flag: '--revision', value: derive.revision.trim() },
      { flag: '--provider', value: derive.provider.trim() },
    ];
    return {
      verb: 'publish-consumer-contract',
      options,
      rest: {
        method: 'POST',
        path: tenantPath(tenant, `/projects/${derive.project.trim() || '{project}'}/consumers/${derive.consumer.trim() || '{consumer}'}/pact/publish`),
        body: deriveRequest(derive, { ...whose, version }),
      },
      unsupported,
    };
  }
  const files = publishableRows(input.rows);
  const options: PactOption[] = [
    { flag: '--consumer-app-version', value: version, actionInput: 'version' },
    { flag: '--branch', value: whose.branch.trim(), actionInput: 'branch' },
    { flag: '--tag', value: tags, actionInput: 'tags' },
    { flag: '--tag-with-git-branch', value: whose.tagWithBranch },
    { flag: '--build-url', value: whose.buildUrl.trim() },
  ];
  const consumers = [...new Set(files.map((row) => row.consumer as string))];
  return {
    verb: 'publish',
    args: [{ value: 'pacts/', actionInput: 'pacts' }],
    options,
    rest: {
      method: 'POST',
      path: tenantPath(tenant, '/pact-broker/contracts/publish'),
      body: {
        pacticipantName: consumers[0] ?? '<consumer>',
        pacticipantVersionNumber: version,
        ...(whose.branch.trim() ? { branch: whose.branch.trim() } : {}),
        ...(effectiveTags(whose).length ? { tags: effectiveTags(whose) } : {}),
        ...(whose.buildUrl.trim() ? { buildUrl: whose.buildUrl.trim() } : {}),
        contracts: (files.length ? files : [null]).map((row) => ({
          consumerName: row?.consumer ?? '<consumer>',
          providerName: row?.provider ?? '<provider>',
          specification: 'pact',
          contentType: 'application/json',
          content: '<the pact, base64-encoded>',
        })),
      },
    },
    unsupported: [
      ...unsupported,
      ...(consumers.length > 1
        ? [{ what: `${consumers.length} consumers`, reason: 'REST takes one consumer per request; apiome pact publish sends one request per consumer, as this page does.', inRest: false }]
        : []),
    ],
  };
}
