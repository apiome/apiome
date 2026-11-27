/**
 * Publish pacts from the Pact import dialog — PFX-5.8 (#6952) — and from the Publish page (PFX-8.3,
 * #7300), which sends several pacts of one consumer version in one request (`pacts`).
 *
 * The Import-a-Pact-file dialog on a project's **Consumers** screen stores the pact as a consumer
 * contract in the registry. This model lets the same dialog also publish it to the Pact Broker, so
 * the provider's verification, can-i-deploy and webhooks see it: the checks the
 * `/api/pact/publish` proxy runs on what the browser sends, the body it forwards to
 * `POST /v1/tenants/{t}/pact-broker/contracts/publish`, and the browser-side form checks.
 *
 * Everything here is pure, so the proxy, the dialog and the tests share it.
 */

/** The REST path below `/v1/tenants/{slug}` a publish is forwarded to. */
export const PUBLISH_PROXY_PATH = 'pact-broker/contracts/publish';

/** Largest Pact document the browser may send, in characters (REST enforces its own limit too). */
export const MAX_PACT_CHARS = 8 * 1024 * 1024;

/** Most tags one publish may carry (REST's limit). */
export const MAX_TAGS = 50;

/** Longest name, version, branch or tag accepted. */
export const MAX_FIELD_CHARS = 255;

/** Longest build URL accepted. */
export const MAX_URL_CHARS = 2048;

/** Most pacts one publish request may carry (REST's `MAX_CONTRACTS_PER_REQUEST`). */
export const MAX_PACTS_PER_REQUEST = 100;

/**
 * The fields a publish request carries. One pact is `providerName` + `pact` (the import dialog);
 * several are `pacts`, a list of `{ providerName, pact }` (the Publish page, PFX-8.3).
 */
export const PUBLISH_FIELDS = ['consumerName', 'providerName', 'version', 'branch', 'tags', 'buildUrl', 'pact', 'pacts'] as const;

/** The fields of one entry of `pacts`. */
const PACT_ENTRY_FIELDS = ['providerName', 'pact'] as const;

/** What the dialog's broker section holds. */
export interface PublishDraft {
  providerName: string;
  version: string;
  branch: string;
  /** Comma- or space-separated tags, as typed. */
  tags: string;
  buildUrl: string;
}

/** A request the proxy accepted, or why it did not. */
export type PickedPublish =
  | { ok: true; body: Record<string, unknown> }
  | { ok: false; error: string };

/**
 * Split a typed tag list into tags.
 *
 * @param text - Tags separated by commas or whitespace.
 * @returns The tags, in order, without blanks or repeats.
 */
export function parseTags(text: string): string[] {
  return Array.from(new Set(text.split(/[\s,]+/).filter(Boolean)));
}

/**
 * The consumer name a Pact document declares.
 *
 * @param pact - The Pact document as text.
 * @returns `consumer.name` (Pact 1.x–4.x all carry it), or `''` when the text is not a Pact JSON object.
 */
export function pactConsumerName(pact: string): string {
  try {
    const name = (JSON.parse(pact) as { consumer?: { name?: unknown } })?.consumer?.name;
    return typeof name === 'string' ? name.trim() : '';
  } catch {
    return '';
  }
}

/** Whether `text` is an http(s) URL. */
export function isHttpUrl(text: string): boolean {
  try {
    return ['http:', 'https:'].includes(new URL(text).protocol);
  } catch {
    return false;
  }
}

/**
 * Check the broker section before anything is sent.
 *
 * @param draft - The section as typed.
 * @param consumerName - The consumer the pact is for (empty when unknown).
 * @returns A sentence naming the first problem, or `null` when it can be sent.
 */
export function validatePublishDraft(draft: PublishDraft, consumerName: string): string | null {
  if (!consumerName) {
    return 'The Pact document names no consumer, and no consumer handle was given: the broker needs one.';
  }
  if (!draft.providerName.trim()) return 'Name the provider the pact is with.';
  if (!draft.version.trim()) return 'Give the consumer version being published (a commit SHA, for instance).';
  for (const [label, value] of [
    ['Provider', draft.providerName],
    ['Consumer version', draft.version],
    ['Branch', draft.branch],
  ] as const) {
    if (value.trim().length > MAX_FIELD_CHARS) return `${label} is longer than ${MAX_FIELD_CHARS} characters.`;
  }
  const tags = parseTags(draft.tags);
  if (tags.length > MAX_TAGS) return `At most ${MAX_TAGS} tags.`;
  if (tags.some((tag) => tag.length > MAX_FIELD_CHARS)) return `A tag is longer than ${MAX_FIELD_CHARS} characters.`;
  const url = draft.buildUrl.trim();
  if (url && (url.length > MAX_URL_CHARS || !isHttpUrl(url))) return 'The build URL must be an http(s) URL.';
  return null;
}

/**
 * Turn the dialog's section into the proxy's request body.
 *
 * @param pact - The Pact document as text.
 * @param consumerName - The consumer publishing.
 * @param draft - The broker section.
 * @returns The JSON body for `/api/pact/publish`; empty optional fields are left out.
 */
export function buildPublishRequest(pact: string, consumerName: string, draft: PublishDraft): Record<string, unknown> {
  const tags = parseTags(draft.tags);
  return {
    consumerName,
    providerName: draft.providerName.trim(),
    version: draft.version.trim(),
    ...(draft.branch.trim() ? { branch: draft.branch.trim() } : {}),
    ...(tags.length ? { tags } : {}),
    ...(draft.buildUrl.trim() ? { buildUrl: draft.buildUrl.trim() } : {}),
    pact,
  };
}

/** A string field of `body`, or `undefined` when absent. */
function textField(body: Record<string, unknown>, key: string): string | undefined | Error {
  const value = body[key];
  if (value === undefined) return undefined;
  if (typeof value !== 'string') return new Error(`${key} must be a string.`);
  return value;
}

/**
 * The pacts of a request: `pacts`, or the single `providerName` + `pact`.
 *
 * @param body - The request body.
 * @returns The `{ providerName, pact }` entries, or a sentence naming the problem.
 */
function pickPactEntries(body: Record<string, unknown>): Array<{ providerName: string; pact: string }> | string {
  if (body.pacts === undefined) {
    for (const key of ['providerName', 'pact']) {
      const value = body[key];
      if (value !== undefined && typeof value !== 'string') return `${key} must be a string.`;
      if (typeof value !== 'string' || !value.trim()) return `${key} is required.`;
    }
    return [{ providerName: body.providerName as string, pact: body.pact as string }];
  }
  if (body.providerName !== undefined || body.pact !== undefined) {
    return 'Send either pacts or providerName and pact, not both.';
  }
  if (!Array.isArray(body.pacts) || body.pacts.length === 0) return 'pacts must be a non-empty list.';
  if (body.pacts.length > MAX_PACTS_PER_REQUEST) return `pacts takes at most ${MAX_PACTS_PER_REQUEST}.`;
  const entries: Array<{ providerName: string; pact: string }> = [];
  for (const [index, entry] of body.pacts.entries()) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return `pacts[${index}] must be an object.`;
    for (const key of Object.keys(entry)) {
      if (!(PACT_ENTRY_FIELDS as readonly string[]).includes(key)) {
        return `Unsupported field pacts[${index}].${key}: an entry takes ${PACT_ENTRY_FIELDS.join(', ')}.`;
      }
    }
    const { providerName, pact } = entry as Record<string, unknown>;
    if (typeof providerName !== 'string' || !providerName.trim()) return `pacts[${index}].providerName is required.`;
    if (typeof pact !== 'string' || !pact.trim()) return `pacts[${index}].pact is required.`;
    entries.push({ providerName, pact });
  }
  return entries;
}

/**
 * Check what the browser sent the proxy and build REST's publish body.
 *
 * Unknown, missing, mistyped or oversized fields are a refusal naming the field; each Pact
 * document is base64-encoded as REST's bulk publish expects.
 *
 * @param raw - The parsed request body.
 * @returns The REST body, or a sentence naming the problem (a 400).
 */
export function pickPublishBody(raw: unknown): PickedPublish {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return { ok: false, error: 'The body must be a JSON object describing the publication.' };
  }
  const body = raw as Record<string, unknown>;
  for (const key of Object.keys(body)) {
    if (!(PUBLISH_FIELDS as readonly string[]).includes(key)) {
      return { ok: false, error: `Unsupported field ${key}: a publication takes ${PUBLISH_FIELDS.join(', ')}.` };
    }
  }
  const text: Record<string, string | undefined> = {};
  for (const key of ['consumerName', 'version', 'branch', 'buildUrl']) {
    const value = textField(body, key);
    if (value instanceof Error) return { ok: false, error: value.message };
    text[key] = value;
  }
  for (const key of ['consumerName', 'version']) {
    if (!text[key]?.trim()) return { ok: false, error: `${key} is required.` };
  }
  const entries = pickPactEntries(body);
  if (typeof entries === 'string') return { ok: false, error: entries };
  if (entries.some((entry) => entry.pact.length > MAX_PACT_CHARS)) return { ok: false, error: 'pact is too large to publish.' };
  for (const key of ['consumerName', 'version', 'branch']) {
    if ((text[key] ?? '').length > MAX_FIELD_CHARS) return { ok: false, error: `${key} is longer than ${MAX_FIELD_CHARS} characters.` };
  }
  if (entries.some((entry) => entry.providerName.length > MAX_FIELD_CHARS)) {
    return { ok: false, error: `providerName is longer than ${MAX_FIELD_CHARS} characters.` };
  }
  if (text.buildUrl && (text.buildUrl.length > MAX_URL_CHARS || !isHttpUrl(text.buildUrl))) {
    return { ok: false, error: 'buildUrl must be an http(s) URL.' };
  }
  const tags = pickTags(body.tags);
  if (typeof tags === 'string') return { ok: false, error: tags };
  return {
    ok: true,
    body: {
      pacticipantName: text.consumerName!.trim(),
      pacticipantVersionNumber: text.version!.trim(),
      ...(text.branch?.trim() ? { branch: text.branch.trim() } : {}),
      ...(tags.length ? { tags } : {}),
      ...(text.buildUrl ? { buildUrl: text.buildUrl } : {}),
      contracts: entries.map((entry) => ({
        consumerName: text.consumerName!.trim(),
        providerName: entry.providerName.trim(),
        specification: 'pact',
        contentType: 'application/json',
        content: Buffer.from(entry.pact, 'utf8').toString('base64'),
      })),
    },
  };
}

/**
 * Check a request's `tags`.
 *
 * @param value - The `tags` field (absent is no tags).
 * @returns The tags, or a sentence naming the problem.
 */
export function pickTags(value: unknown): string[] | string {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.some((tag) => typeof tag !== 'string' || !tag.trim())) {
    return 'tags must be a list of non-empty strings.';
  }
  const tags = value as string[];
  if (tags.length > MAX_TAGS) return `tags takes at most ${MAX_TAGS}.`;
  if (tags.some((tag) => tag.length > MAX_FIELD_CHARS)) return `A tag is longer than ${MAX_FIELD_CHARS} characters.`;
  return tags;
}

/** What the dialog shows after a publish. */
export interface PublishOutcome {
  /** The lines the CLI would print, as REST answered them. */
  notices: string[];
}

/**
 * Read REST's publish answer into the lines the dialog shows.
 *
 * @param data - The proxy's `data` (REST's HAL body).
 * @returns The notices' text, in order.
 */
export function readPublishNotices(data: unknown): string[] {
  const notices = (data as { notices?: unknown } | null)?.notices;
  if (!Array.isArray(notices)) return [];
  return notices.flatMap((n) => (n && typeof (n as { text?: unknown }).text === 'string' ? [(n as { text: string }).text] : []));
}
