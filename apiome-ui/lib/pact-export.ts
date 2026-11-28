/**
 * The **Export a contract** page — PFX-8.18 (#7315), `/ade/dashboard/pacts/export`.
 *
 * Four kinds, one visible at a time (docs/mockups/contracts/export.html):
 *
 * * **A pact from a project** — `apiome pact export-consumer-contract`: a consumer's declared surface
 *   as a Pact v4 file, with an operation checklist saying where each example came from and why an
 *   operation was left out (REST's `operations` and `findings`).
 * * **A Postman collection** — `apiome pact export-postman`: a stored pact (or every consumer's, or
 *   an uploaded file) as a Postman Collection v2.1, with a variable base URL, provider-state setup
 *   scripts and a bar of how many interactions the collection keeps.
 * * **A pact file** — any published pact exactly as stored, or every pact for a provider as a zip.
 * * **Provider test scaffolding** (PFX-8.19, #7316) — `apiome pact scaffold-provider-tests`: a ready
 *   provider verification test in four languages, with a stub per provider state.
 *
 * Everything here is pure: the form drafts and their checks, the proxy queries and their pickers
 * (what each `/api/pact/export/*` proxy accepts), the readers of REST's answers and the
 * **The same, from anywhere** actions. Nothing the form holds is dropped silently: what no
 * command carries is listed with its reason, and what an export leaves out is listed with REST's.
 */

import { isHttpUrl, MAX_FIELD_CHARS, MAX_PACT_CHARS, MAX_URL_CHARS } from './pact-publish';
import { validateDerive } from './pact-publish-page';
import { tenantPath, type PactAction, type PactOption, type PactUnsupported } from './pact-commands';

// --- the page ------------------------------------------------------------------------------------

/** The page's route. */
export const EXPORT_ROUTE = '/ade/dashboard/pacts/export';

/** What can be exported. */
export const EXPORT_KINDS = ['pact', 'postman', 'file', 'tests'] as const;

/** One kind of export. */
export type ExportKind = (typeof EXPORT_KINDS)[number];

/** Each kind's option card. */
export const EXPORT_KIND_CARDS: Readonly<Record<ExportKind, { title: string; description: string }>> = {
  pact: { title: 'A pact from a project', description: 'One interaction per operation the consumer declares.' },
  postman: { title: 'A Postman collection', description: 'Replay a pact as requests with tests.' },
  file: { title: 'A pact file', description: 'Any published pact, exactly as stored.' },
  tests: { title: 'Provider test scaffolding', description: 'A starting test suite from the pacts a provider must honour.' },
};

/**
 * The biggest output (in characters of JSON) shown inline; anything larger downloads without a
 * preview, so the page never draws megabytes of text.
 */
export const PREVIEW_LIMIT_CHARS = 200_000;

/**
 * Whether a text is small enough to preview.
 *
 * @param text - The output.
 * @returns `true` when it is at most {@link PREVIEW_LIMIT_CHARS} long.
 */
export function previewable(text: string): boolean {
  return text.length <= PREVIEW_LIMIT_CHARS;
}

/**
 * A size for people: `812 B`, `14.2 KB`, `3.1 MB`.
 *
 * @param chars - The length of the text (one byte per character is close enough for JSON).
 * @returns The size.
 */
export function sizeLabel(chars: number): string {
  if (chars < 1024) return `${chars} B`;
  if (chars < 1024 * 1024) return `${(chars / 1024).toFixed(1)} KB`;
  return `${(chars / (1024 * 1024)).toFixed(1)} MB`;
}

/** What the page can be opened with (a pact's page, a pacticipant, Export studio). */
export interface ExportPrefill {
  kind: ExportKind;
  provider: string;
  consumer: string;
  /** A consumer version, for **A pact file** / **A Postman collection**. */
  version: string;
  project: string;
  /** Query parameters the page cannot use, each reported. */
  problems: string[];
}

/** The query parameters the page reads. */
export const EXPORT_PREFILL_PARAMS = ['kind', 'provider', 'consumer', 'version', 'project'] as const;

/**
 * Read the address the page was opened with.
 *
 * @param query - Next's search params.
 * @returns The prefill; anything that cannot be used is named in `problems`, never dropped.
 */
export function readExportPrefill(query: Record<string, string | string[] | undefined>): ExportPrefill {
  const problems: string[] = [];
  for (const key of Object.keys(query)) {
    if (!(EXPORT_PREFILL_PARAMS as readonly string[]).includes(key)) problems.push(`?${key}= is not something this page reads.`);
  }
  const one = (key: string): string => {
    const raw = query[key];
    if (Array.isArray(raw)) problems.push(`?${key}= was given more than once; the first is used.`);
    const value = ((Array.isArray(raw) ? raw[0] : raw) ?? '').trim();
    if (value.length > MAX_FIELD_CHARS) {
      problems.push(`?${key}= is longer than ${MAX_FIELD_CHARS} characters and was left out.`);
      return '';
    }
    return value;
  };
  const kindText = one('kind');
  let kind: ExportKind = 'pact';
  if (kindText) {
    if ((EXPORT_KINDS as readonly string[]).includes(kindText)) kind = kindText as ExportKind;
    else problems.push(`?kind=${kindText} is not something to export (pact, postman, file or tests).`);
  }
  return { kind, provider: one('provider'), consumer: one('consumer'), version: one('version'), project: one('project'), problems };
}

/**
 * The page's address, pre-filled — what a pact's page, a pacticipant and Export studio link to.
 *
 * @param fields - What to fill in.
 * @returns E.g. `/ade/dashboard/pacts/export?kind=file&provider=billing&consumer=orders-ui`.
 */
export function exportRoute(fields: Partial<Record<(typeof EXPORT_PREFILL_PARAMS)[number], string>> = {}): string {
  const query = new URLSearchParams();
  for (const key of EXPORT_PREFILL_PARAMS) {
    const value = fields[key]?.trim();
    if (value) query.set(key, value);
  }
  const text = query.toString();
  return text ? `${EXPORT_ROUTE}?${text}` : EXPORT_ROUTE;
}

/**
 * What the page says when a pair has no pact (the mockup's **No pact for the pair** state).
 *
 * @param consumer - The consumer.
 * @param provider - The provider.
 * @returns The sentence.
 */
export function noPactMessage(consumer: string, provider: string): string {
  return `${consumer || 'This consumer'} has not published a pact for ${provider || 'this provider'}. Record one from a mock, or upload a file.`;
}

/** What the page says when a revision yields no interaction (the mockup's **Nothing to derive**). */
export const NOTHING_TO_DERIVE = 'This revision has no operations a pact can describe.';

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Why a pacticipant reference (handle, id or name) cannot be sent, or `null`.
 *
 * @param label - How the form labels it.
 * @param value - The reference.
 * @returns The sentence, or `null`.
 */
export function referenceProblem(label: string, value: string): string | null {
  if (!value.trim()) return `${label} is required.`;
  if (value.length > MAX_FIELD_CHARS) return `${label} is longer than ${MAX_FIELD_CHARS} characters.`;
  if (/[\u0000-\u001f\u007f]/.test(value)) return `${label} contains a control character.`;
  return null;
}

// --- which pact ------------------------------------------------------------------------------------

/** How a stored pact is chosen — the selection flags `export-postman` has. */
export const PACT_CHOICES = ['latest', 'branch', 'tag', 'version', 'sha'] as const;

/** One way to choose a stored pact. */
export type PactChoice = (typeof PACT_CHOICES)[number];

/** Each choice's label and the field's label. */
export const PACT_CHOICE_LABELS: Readonly<Record<PactChoice, { label: string; field: string | null; flag: string | null }>> = {
  latest: { label: 'The latest pact', field: null, flag: null },
  branch: { label: 'Latest on a branch', field: 'Branch', flag: '--branch' },
  tag: { label: 'Latest with a tag', field: 'Tag', flag: '--tag' },
  version: { label: 'A consumer version', field: 'Consumer version', flag: '--consumer-version' },
  sha: { label: 'A pact version (SHA)', field: 'Pact version SHA', flag: '--pact-version' },
};

/** A pact version SHA: 64 hex characters. */
const SHA_PATTERN = /^[0-9a-f]{64}$/i;

/**
 * Why a choice's value cannot be sent, or `null`.
 *
 * @param choice - The choice.
 * @param value - Its value (ignored for `latest`).
 * @returns The sentence, or `null`.
 */
export function choiceProblem(choice: PactChoice, value: string): string | null {
  const field = PACT_CHOICE_LABELS[choice].field;
  if (field === null) return null;
  const text = value.trim();
  if (!text) return `${field} is required for “${PACT_CHOICE_LABELS[choice].label}”.`;
  if (choice === 'sha' && !SHA_PATTERN.test(text)) return 'A pact version SHA is 64 hexadecimal characters.';
  if (text.length > MAX_FIELD_CHARS) return `${field} is longer than ${MAX_FIELD_CHARS} characters.`;
  if (/[\u0000-\u001f\u007f]/.test(text)) return `${field} contains a control character.`;
  return null;
}

/** The REST body field of each choice (as `apiome pact export-postman` sends it). */
const CHOICE_BODY_FIELD: Readonly<Record<Exclude<PactChoice, 'latest'>, string>> = {
  branch: 'branch',
  tag: 'tag',
  version: 'consumerVersion',
  sha: 'pactVersionSha',
};

// --- a pact from a project -------------------------------------------------------------------------

/** The **A pact from a project** form: `export-consumer-contract`'s own fields. */
export interface DeriveExportDraft {
  /** Project handle or id. */
  project: string;
  /** Consumer handle within the project. */
  consumer: string;
  /** A contract revision; empty is the current one. */
  revision: string;
  /** The provider pacticipant's name; empty lets REST resolve it. */
  provider: string;
  /** `--fail-on-findings`: only changes the command. */
  failOnFindings: boolean;
}

/** An empty form. */
export const EMPTY_DERIVE_EXPORT: DeriveExportDraft = { project: '', consumer: '', revision: '', provider: '', failOnFindings: false };

/**
 * Check the form before anything is sent (the same rules as the Publish page's derive tab).
 *
 * @param draft - The form.
 * @returns A sentence naming the first problem, or `null`.
 */
export function validateDeriveExport(draft: DeriveExportDraft): string | null {
  return validateDerive(draft);
}

/**
 * The browser's URL of the derive proxy.
 *
 * @param draft - The checked form.
 * @returns `/api/pact/export/consumer-pact?project=…&consumer=…[&revision=…][&provider=…]`.
 */
export function consumerPactUrl(draft: DeriveExportDraft): string {
  const query = new URLSearchParams({ project: draft.project.trim(), consumer: draft.consumer.trim() });
  if (draft.revision.trim()) query.set('revision', draft.revision.trim());
  if (draft.provider.trim()) query.set('provider', draft.provider.trim());
  return `/api/pact/export/consumer-pact?${query.toString()}`;
}

/** The query parameters the derive proxy takes. */
export const CONSUMER_PACT_PARAMS = ['project', 'consumer', 'revision', 'provider'] as const;

/** A derive read the proxy accepted (REST's path below the tenant), or why not. */
export type PickedPath = { ok: true; path: string } | { ok: false; error: string };

/**
 * Check the derive proxy's query and build REST's path.
 *
 * @param params - The query.
 * @returns `projects/{p}/consumers/{c}/pact[?revision=…&provider=…]`, or a 400 sentence.
 */
export function pickConsumerPactQuery(params: URLSearchParams): PickedPath {
  const values: Record<string, string> = {};
  for (const [key, value] of params.entries()) {
    if (!(CONSUMER_PACT_PARAMS as readonly string[]).includes(key)) {
      return { ok: false, error: `Unsupported parameter ${key}: this export takes ${CONSUMER_PACT_PARAMS.join(', ')}.` };
    }
    if (key in values) return { ok: false, error: `The ${key} parameter is given more than once.` };
    values[key] = value.trim();
  }
  const problem = validateDerive({ project: values.project ?? '', consumer: values.consumer ?? '', revision: values.revision ?? '', provider: values.provider ?? '' });
  if (problem) return { ok: false, error: problem };
  for (const key of ['project', 'consumer'] as const) {
    if (values[key].length > MAX_FIELD_CHARS) return { ok: false, error: `${key} is longer than ${MAX_FIELD_CHARS} characters.` };
  }
  const query = new URLSearchParams();
  if (values.revision) query.set('revision', values.revision);
  if (values.provider) query.set('provider', values.provider);
  const path = `projects/${encodeURIComponent(values.project)}/consumers/${encodeURIComponent(values.consumer)}/pact`;
  const text = query.toString();
  return { ok: true, path: text ? `${path}?${text}` : path };
}

/** One finding of a derived pact (REST's `ExportFinding`). */
export interface ExportFinding {
  outcome: string;
  reason: string;
  message: string;
  method?: string | null;
  path?: string | null;
  status?: string | null;
  location?: string | null;
  field?: string | null;
}

/** Where an operation's examples came from — the checklist's middle column. */
export type ExampleSource = 'spec' | 'generated' | 'left-out';

/** One row of the operation checklist. */
export interface OperationRow {
  /** `METHOD path`, unique within the export. */
  key: string;
  method: string;
  path: string;
  operationId: string | null;
  /** Indexes into the pact's `interactions`. */
  interactions: number[];
  source: ExampleSource;
  /** The column's text: “The spec’s example”, “Generated from the schema — review”, or why it was left out. */
  note: string;
  /** This operation's own findings. */
  findings: ExportFinding[];
}

/** A derived pact, read. */
export interface DerivedPact {
  consumerName: string;
  providerName: string;
  revision: number | null;
  versionLabel: string | null;
  interactionCount: number;
  findings: ExportFinding[];
  /** Findings no operation owns (e.g. a contract item that could not be resolved). */
  generalFindings: ExportFinding[];
  operations: OperationRow[];
  pact: Record<string, unknown>;
}

/**
 * Read the findings of an answer (or of a refusal's `findings`).
 *
 * @param raw - The list.
 * @returns The findings that have a message.
 */
export function readFindings(raw: unknown): ExportFinding[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) =>
    isObject(item) && typeof item.message === 'string'
      ? [{ ...(item as unknown as ExportFinding), outcome: String(item.outcome ?? ''), reason: String(item.reason ?? '') }]
      : [],
  );
}

/**
 * The checklist row of one operation: where its examples came from, or why it was left out.
 *
 * @param operation - REST's operation entry.
 * @param findings - Every finding of the export.
 * @returns The row.
 */
function operationRow(operation: Record<string, unknown>, findings: ExportFinding[]): OperationRow {
  const method = String(operation.method ?? '').toUpperCase();
  const path = String(operation.path ?? '');
  const own = findings.filter((finding) => (finding.method ?? '').toUpperCase() === method && finding.path === path);
  const interactions = Array.isArray(operation.interactions) ? operation.interactions.filter((i): i is number => Number.isInteger(i)) : [];
  const placeholders = own.filter((finding) => finding.outcome === 'placeholder').length;
  let source: ExampleSource = 'spec';
  let note = 'The spec’s example';
  if (interactions.length === 0) {
    source = 'left-out';
    const omitted = own.find((finding) => finding.outcome === 'omitted');
    note = `Left out — ${omitted ? omitted.message : 'no interaction could be written'}`;
  } else if (placeholders > 0) {
    source = 'generated';
    note = `Generated from the schema — review (${placeholders} value${placeholders === 1 ? '' : 's'})`;
  }
  return {
    key: `${method} ${path}`,
    method,
    path,
    operationId: typeof operation.operation_id === 'string' ? operation.operation_id : null,
    interactions,
    source,
    note,
    findings: own,
  };
}

/**
 * Read REST's derived pact (`GET …/consumers/{c}/pact`).
 *
 * @param data - REST's body.
 * @returns The pact, its findings and the checklist, or `null` when the body is not an export.
 */
export function readDerivedPact(data: unknown): DerivedPact | null {
  if (!isObject(data) || !isObject(data.pact)) return null;
  const findings = readFindings(data.findings);
  const operations = Array.isArray(data.operations)
    ? data.operations.flatMap((raw) => (isObject(raw) ? [operationRow(raw, findings)] : []))
    : [];
  const owned = new Set(operations.flatMap((row) => row.findings));
  return {
    consumerName: typeof data.consumer_name === 'string' ? data.consumer_name : '',
    providerName: typeof data.provider_name === 'string' ? data.provider_name : '',
    revision: typeof data.revision === 'number' ? data.revision : null,
    versionLabel: typeof data.version_label === 'string' ? data.version_label : null,
    interactionCount: typeof data.interaction_count === 'number' ? data.interaction_count : 0,
    findings,
    generalFindings: findings.filter((finding) => !owned.has(finding)),
    operations,
    pact: data.pact,
  };
}

/**
 * The pact with only the chosen operations' interactions.
 *
 * @param derived - The derived pact.
 * @param excluded - The keys of the operations unticked in the checklist.
 * @returns The same document when nothing is excluded, else a copy without those interactions.
 */
export function pactWithout(derived: DerivedPact, excluded: ReadonlySet<string>): Record<string, unknown> {
  if (excluded.size === 0) return derived.pact;
  const dropped = new Set(derived.operations.filter((row) => excluded.has(row.key)).flatMap((row) => row.interactions));
  const interactions = Array.isArray(derived.pact.interactions) ? derived.pact.interactions : [];
  return { ...derived.pact, interactions: interactions.filter((_, index) => !dropped.has(index)) };
}

/**
 * How many interactions a pact carries.
 *
 * @param pact - The document.
 * @returns The length of its `interactions`.
 */
export function interactionCount(pact: Record<string, unknown>): number {
  return Array.isArray(pact.interactions) ? pact.interactions.length : 0;
}

/**
 * A file name from pacticipant names: `orders-ui-billing-service`.
 *
 * @param parts - The names.
 * @returns Lower-case words joined by `-`, or `pact` when nothing is left.
 */
export function fileStem(...parts: string[]): string {
  const stem = parts
    .map((part) => part.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, ''))
    .filter(Boolean)
    .join('-');
  return stem.slice(0, 120) || 'pact';
}

/** Why the checklist's unticked operations are not in the command. */
export const EXCLUDED_REASON =
  'export-consumer-contract writes every operation the consumer declares; to leave one out of the command, change the consumer’s declared surface.';

/**
 * The form as `apiome pact export-consumer-contract` and its REST request.
 *
 * @param draft - The form.
 * @param context - The workspace slug, and the operations unticked in the checklist.
 * @returns The action for `pactCommandSurfaces`.
 */
export function deriveExportAction(draft: DeriveExportDraft, context: { tenant: string; excluded: string[] }): PactAction {
  const project = draft.project.trim() || '{project}';
  const consumer = draft.consumer.trim() || '{consumer}';
  const query = new URLSearchParams();
  if (draft.revision.trim()) query.set('revision', draft.revision.trim());
  if (draft.provider.trim()) query.set('provider', draft.provider.trim());
  const suffix = `/projects/${encodeURIComponent(project)}/consumers/${encodeURIComponent(consumer)}/pact`;
  const unsupported: PactUnsupported[] = context.excluded.length
    ? [{ what: `Leaving out ${context.excluded.join(', ')}`, reason: EXCLUDED_REASON, inRest: false }]
    : [];
  return {
    verb: 'export-consumer-contract',
    options: [
      { flag: '--project', value: project },
      { flag: '--consumer', value: consumer },
      { flag: '--revision', value: draft.revision.trim() },
      { flag: '--provider', value: draft.provider.trim() },
      { flag: '--output', value: 'pact.json' },
      { flag: '--fail-on-findings', value: draft.failOnFindings },
    ],
    rest: { method: 'GET', path: tenantPath(context.tenant, query.toString() ? `${suffix}?${query.toString()}` : suffix) },
    unsupported,
  };
}

// --- a Postman collection --------------------------------------------------------------------------

/** Where the collection's pact comes from: a stored pact (by choice) or an uploaded file. */
export type PostmanSource = 'stored' | 'file';

/** The **A Postman collection** form: `export-postman`'s own fields. */
export interface PostmanDraft {
  source: PostmanSource;
  provider: string;
  /** Empty with `allConsumers`. */
  consumer: string;
  /** `--all-consumers`: every consumer of the provider, one folder each. */
  allConsumers: boolean;
  choice: PactChoice;
  /** The branch, tag, version or SHA of the choice. */
  choiceValue: string;
  /** The uploaded file's name and text (`--pact-file`). */
  fileName: string;
  fileText: string;
  /** `--provider-base-url`; empty keeps the `{{baseUrl}}` variable empty, to fill in. */
  baseUrl: string;
  /** `--state-setup`. */
  stateSetup: boolean;
  /** `--state-change-url`. */
  stateChangeUrl: string;
  /** `--tests/--no-tests`. */
  tests: boolean;
  /** `--fail-on-left-out`: only changes the command. */
  failOnLeftOut: boolean;
}

/** An empty form: the latest pact, tests on, state setup on (the mockup's default). */
export const EMPTY_POSTMAN: PostmanDraft = {
  source: 'stored',
  provider: '',
  consumer: '',
  allConsumers: false,
  choice: 'latest',
  choiceValue: '',
  fileName: '',
  fileText: '',
  baseUrl: '',
  stateSetup: true,
  stateChangeUrl: '',
  tests: true,
  failOnLeftOut: false,
};

/**
 * Read an uploaded pact file's text.
 *
 * @param text - The file's text.
 * @returns The document, or the sentence saying why it is not one.
 */
export function readUploadedPact(text: string): { ok: true; pact: Record<string, unknown> } | { ok: false; error: string } {
  if (text.length > MAX_PACT_CHARS) return { ok: false, error: 'The file is larger than 8 MB.' };
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { ok: false, error: 'The file is not JSON.' };
  }
  if (!isObject(parsed)) return { ok: false, error: 'A Pact file is a JSON object.' };
  return { ok: true, pact: parsed };
}

/**
 * Check the form before anything is sent.
 *
 * @param draft - The form.
 * @returns A sentence naming the first problem, or `null`.
 */
export function validatePostman(draft: PostmanDraft): string | null {
  if (draft.source === 'file') {
    if (!draft.fileText) return 'Choose the pact file to export.';
    const read = readUploadedPact(draft.fileText);
    if (!read.ok) return read.error;
  } else {
    const provider = referenceProblem('Provider', draft.provider);
    if (provider) return provider;
    if (!draft.allConsumers) {
      const consumer = referenceProblem('Consumer', draft.consumer);
      if (consumer) return consumer;
    } else if (draft.choice === 'version' || draft.choice === 'sha') {
      return 'All consumers takes the latest pact, a branch or a tag: a version or a SHA names one consumer’s pact.';
    }
    const choice = choiceProblem(draft.choice, draft.choiceValue);
    if (choice) return choice;
  }
  if (draft.baseUrl.trim() && (draft.baseUrl.trim().length > MAX_URL_CHARS || !isHttpUrl(draft.baseUrl.trim()))) {
    return 'Provider base URL is an http(s) URL, or empty to fill in the {{baseUrl}} variable later.';
  }
  if (draft.stateSetup && draft.stateChangeUrl.trim() && (draft.stateChangeUrl.trim().length > MAX_URL_CHARS || !isHttpUrl(draft.stateChangeUrl.trim()))) {
    return 'State change URL is an http(s) URL, or empty to fill in the {{stateChangeUrl}} variable later.';
  }
  return null;
}

/**
 * The REST body of the export — what `apiome pact export-postman` sends.
 *
 * @param draft - The checked form.
 * @returns The body; empty optional fields are left out.
 */
export function postmanRequestBody(draft: PostmanDraft): Record<string, unknown> {
  const body: Record<string, unknown> = { tests: draft.tests };
  if (draft.source === 'file') {
    const read = readUploadedPact(draft.fileText);
    if (read.ok) body.pact = read.pact;
  } else {
    body.provider = draft.provider.trim();
    if (draft.allConsumers) body.allConsumers = true;
    else body.consumer = draft.consumer.trim();
    if (draft.choice !== 'latest') body[CHOICE_BODY_FIELD[draft.choice]] = draft.choiceValue.trim();
  }
  if (draft.baseUrl.trim()) body.baseUrl = draft.baseUrl.trim();
  if (draft.stateSetup) {
    body.stateSetup = true;
    if (draft.stateChangeUrl.trim()) body.stateChangeUrl = draft.stateChangeUrl.trim();
  }
  return body;
}

/** The fields the Postman proxy forwards (REST's `PactPostmanRequest`). */
export const POSTMAN_FIELDS = [
  'provider',
  'consumer',
  'consumerVersion',
  'tag',
  'branch',
  'pactVersionSha',
  'pact',
  'baseUrl',
  'tests',
  'allConsumers',
  'stateSetup',
  'stateChangeUrl',
] as const;

/** A Postman export the proxy accepted, or why not. */
export type PickedBody = { ok: true; body: Record<string, unknown> } | { ok: false; error: string };

/**
 * Check what the browser sent the Postman proxy. The combination rules (one selection, an inline
 * pact without one, every consumer without a consumer) are REST's, which refuses with the reason.
 *
 * @param raw - The parsed request body.
 * @returns The body to forward unchanged, or a 400 sentence.
 */
export function pickPostmanBody(raw: unknown): PickedBody {
  if (!isObject(raw)) return { ok: false, error: 'The body must be a JSON object describing the export.' };
  for (const key of Object.keys(raw)) {
    if (!(POSTMAN_FIELDS as readonly string[]).includes(key)) {
      return { ok: false, error: `Unsupported field ${key}: a Postman export takes ${POSTMAN_FIELDS.join(', ')}.` };
    }
  }
  for (const key of ['provider', 'consumer', 'consumerVersion', 'tag', 'branch', 'pactVersionSha']) {
    if (raw[key] === undefined) continue;
    if (typeof raw[key] !== 'string') return { ok: false, error: `${key} must be a string.` };
    if ((raw[key] as string).length > MAX_FIELD_CHARS) return { ok: false, error: `${key} is longer than ${MAX_FIELD_CHARS} characters.` };
  }
  for (const key of ['baseUrl', 'stateChangeUrl']) {
    if (raw[key] === undefined) continue;
    if (typeof raw[key] !== 'string' || (raw[key] as string).length > MAX_URL_CHARS) {
      return { ok: false, error: `${key} must be a URL of at most ${MAX_URL_CHARS} characters.` };
    }
  }
  for (const key of ['tests', 'allConsumers', 'stateSetup']) {
    if (raw[key] !== undefined && typeof raw[key] !== 'boolean') return { ok: false, error: `${key} must be true or false.` };
  }
  if (raw.pact !== undefined) {
    if (!isObject(raw.pact)) return { ok: false, error: 'pact must be a Pact document (a JSON object).' };
    if (JSON.stringify(raw.pact).length > MAX_PACT_CHARS) return { ok: false, error: 'pact is larger than 8 MB.' };
  }
  return { ok: true, body: raw };
}

/** One notice of a Postman export: something the collection does not carry, and why. */
export interface PostmanNotice {
  code: string;
  outcome: string;
  pointer: string;
  message: string;
  description?: string;
  paths?: string[];
  /** With every consumer: whose pact it is about. */
  consumer?: string;
}

/** A Postman export, read. */
export interface PostmanOutcome {
  collection: Record<string, unknown>;
  provider: string;
  /** One consumer's name, or every consumer's. */
  consumers: string[];
  counts: { interactions: number; exported: number; leftOut: number };
  notices: PostmanNotice[];
}

/**
 * Read the notices of an answer (or of a refusal's `notices`).
 *
 * @param raw - The list.
 * @returns The notices that have a message.
 */
export function readNotices(raw: unknown): PostmanNotice[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((item) =>
    isObject(item) && typeof item.message === 'string'
      ? [{ ...(item as unknown as PostmanNotice), code: String(item.code ?? ''), outcome: String(item.outcome ?? '') }]
      : [],
  );
}

/**
 * Read REST's Postman export (`POST …/pact-postman-collections`).
 *
 * @param data - REST's body.
 * @returns The outcome, or `null` when the body is not an export.
 */
export function readPostmanOutcome(data: unknown): PostmanOutcome | null {
  if (!isObject(data) || !isObject(data.collection)) return null;
  const pact = isObject(data.pact) ? data.pact : {};
  const counts = isObject(data.counts) ? data.counts : {};
  const count = (key: string) => (typeof counts[key] === 'number' ? (counts[key] as number) : 0);
  const consumers = Array.isArray(pact.consumers)
    ? pact.consumers.flatMap((entry) => (isObject(entry) && typeof entry.consumer === 'string' ? [entry.consumer] : []))
    : typeof pact.consumer === 'string'
      ? [pact.consumer]
      : [];
  return {
    collection: data.collection,
    provider: typeof pact.provider === 'string' ? pact.provider : '',
    consumers,
    counts: { interactions: count('interactions'), exported: count('exported'), leftOut: count('leftOut') },
    notices: readNotices(data.notices),
  };
}

/** The fidelity bar: how much of the pact the collection keeps. */
export interface Fidelity {
  kept: number;
  leftOut: number;
  total: number;
  /** 0–100, rounded; 100 for an empty pact. */
  keptPercent: number;
}

/**
 * The fidelity bar of an export.
 *
 * @param counts - REST's counts.
 * @returns What was kept and left out, as numbers and a percentage.
 */
export function fidelity(counts: PostmanOutcome['counts']): Fidelity {
  const total = counts.exported + counts.leftOut;
  return { kept: counts.exported, leftOut: counts.leftOut, total, keptPercent: total === 0 ? 100 : Math.round((counts.exported / total) * 100) };
}

/**
 * The collection's file name: `orders-ui-billing-service.postman.json`.
 *
 * @param outcome - The export.
 * @returns The name.
 */
export function postmanFileName(outcome: PostmanOutcome): string {
  const who = outcome.consumers.length === 1 ? outcome.consumers[0] : 'every-consumer';
  return `${fileStem(who, outcome.provider)}.postman.json`;
}

/**
 * The form as `apiome pact export-postman` and its REST request.
 *
 * @param draft - The form.
 * @param tenant - The workspace slug.
 * @returns The action for `pactCommandSurfaces`.
 */
export function postmanExportAction(draft: PostmanDraft, tenant: string): PactAction {
  const options: PactOption[] = [];
  if (draft.source === 'file') {
    options.push({ flag: '--pact-file', value: draft.fileName || 'pact.json' });
  } else {
    options.push({ flag: '--provider', value: draft.provider.trim() || '{provider}' });
    if (draft.allConsumers) options.push({ flag: '--all-consumers', value: true });
    else options.push({ flag: '--consumer', value: draft.consumer.trim() || '{consumer}' });
    const flag = PACT_CHOICE_LABELS[draft.choice].flag;
    if (flag) options.push({ flag, value: draft.choiceValue.trim() });
  }
  options.push(
    { flag: '--provider-base-url', value: draft.baseUrl.trim() },
    { flag: '--state-setup', value: draft.stateSetup },
    { flag: '--state-change-url', value: draft.stateSetup ? draft.stateChangeUrl.trim() : '' },
    { flag: '--no-tests', value: !draft.tests },
    { flag: '--output', value: 'collection.json' },
    { flag: '--fail-on-left-out', value: draft.failOnLeftOut },
  );
  const body = postmanRequestBody(draft);
  if (draft.source === 'file') body.pact = `<the contents of ${draft.fileName || 'pact.json'}>`;
  return { verb: 'export-postman', options, rest: { method: 'POST', path: tenantPath(tenant, '/pact-postman-collections'), body } };
}

// --- a pact file -----------------------------------------------------------------------------------

/** The **A pact file** form. */
export interface PactFileDraft {
  provider: string;
  consumer: string;
  choice: PactChoice;
  choiceValue: string;
}

/** An empty form: the latest pact. */
export const EMPTY_PACT_FILE: PactFileDraft = { provider: '', consumer: '', choice: 'latest', choiceValue: '' };

/** The choices **Every pact for this provider** can take (a version or SHA names one consumer's pact). */
export const PROVIDER_PACT_CHOICES: readonly PactChoice[] = ['latest', 'branch', 'tag'];

/**
 * Check the form before one pact is downloaded.
 *
 * @param draft - The form.
 * @returns A sentence naming the first problem, or `null`.
 */
export function validatePactFile(draft: PactFileDraft): string | null {
  return referenceProblem('Provider', draft.provider) ?? referenceProblem('Consumer', draft.consumer) ?? choiceProblem(draft.choice, draft.choiceValue);
}

/**
 * Check the form before every pact of the provider is downloaded.
 *
 * @param draft - The form.
 * @returns A sentence naming the first problem, or `null`.
 */
export function validateProviderPacts(draft: PactFileDraft): string | null {
  if (!PROVIDER_PACT_CHOICES.includes(draft.choice)) {
    return 'Every pact for a provider takes the latest pact, a branch or a tag: a version or a SHA names one consumer’s pact.';
  }
  return referenceProblem('Provider', draft.provider) ?? choiceProblem(draft.choice, draft.choiceValue);
}

/**
 * The Pact Broker path of one pact (below `/v1/tenants/{t}`).
 *
 * @param provider - The provider (handle, id or name).
 * @param consumer - The consumer.
 * @param choice - Which pact.
 * @param value - The choice's value.
 * @returns E.g. `pact-broker/pacts/provider/billing/consumer/orders-ui/branch/main/latest`.
 */
export function pactFilePath(provider: string, consumer: string, choice: PactChoice, value: string): string {
  const pair = `pact-broker/pacts/provider/${encodeURIComponent(provider)}/consumer/${encodeURIComponent(consumer)}`;
  const v = encodeURIComponent(value);
  switch (choice) {
    case 'branch':
      return `${pair}/branch/${v}/latest`;
    case 'tag':
      return `${pair}/latest/${v}`;
    case 'version':
      return `${pair}/version/${v}`;
    case 'sha':
      return `${pair}/pact-version/${v}`;
    default:
      return `${pair}/latest`;
  }
}

/**
 * The browser's URL of a pact-file proxy.
 *
 * @param draft - The checked form.
 * @param every - Every pact for the provider (the zip) instead of one.
 * @returns `/api/pact/export/pact-file?…` or `/api/pact/export/provider-pacts?…`.
 */
export function pactFileUrl(draft: PactFileDraft, every = false): string {
  const query = new URLSearchParams({ provider: draft.provider.trim() });
  if (!every) query.set('consumer', draft.consumer.trim());
  if (draft.choice !== 'latest') query.set(draft.choice, draft.choiceValue.trim());
  return `/api/pact/export/${every ? 'provider-pacts' : 'pact-file'}?${query.toString()}`;
}

/** A pact-file read the proxy accepted, or why not. */
export type PickedPactFile =
  | { ok: true; provider: string; consumer: string; choice: PactChoice; value: string }
  | { ok: false; error: string };

/**
 * Check a pact-file proxy's query.
 *
 * @param params - The query.
 * @param every - The zip proxy (no consumer; latest, branch or tag only).
 * @returns The pair and the choice, or a 400 sentence.
 */
export function pickPactFileQuery(params: URLSearchParams, every: boolean): PickedPactFile {
  const allowed = every ? ['provider', 'branch', 'tag'] : ['provider', 'consumer', 'branch', 'tag', 'version', 'sha'];
  const values: Record<string, string> = {};
  for (const [key, value] of params.entries()) {
    if (!allowed.includes(key)) return { ok: false, error: `Unsupported parameter ${key}: this download takes ${allowed.join(', ')}.` };
    if (key in values) return { ok: false, error: `The ${key} parameter is given more than once.` };
    values[key] = value;
  }
  const chosen = (['branch', 'tag', 'version', 'sha'] as const).filter((key) => key in values);
  if (chosen.length > 1) return { ok: false, error: `Choose one of ${chosen.join(', ')}, not several.` };
  const choice: PactChoice = chosen[0] ?? 'latest';
  const value = chosen[0] ? values[chosen[0]].trim() : '';
  const problem =
    referenceProblem('provider', values.provider ?? '') ??
    (every ? null : referenceProblem('consumer', values.consumer ?? '')) ??
    choiceProblem(choice, value);
  if (problem) return { ok: false, error: problem };
  return { ok: true, provider: values.provider.trim(), consumer: every ? '' : values.consumer.trim(), choice, value };
}

/**
 * A stored pact exactly as published: the broker's `_links` and `createdAt` taken off.
 *
 * @param body - The broker's pact response.
 * @returns The document.
 */
export function storedPact(body: Record<string, unknown>): Record<string, unknown> {
  const document = { ...body };
  delete document._links;
  delete document.createdAt;
  return document;
}

/** The most pacts one zip carries; the rest are listed in its report. */
export const MAX_ZIP_PACTS = 100;

/** Why no command downloads a stored pact. */
export const PACT_FILE_HAS_NO_COMMAND =
  'No apiome pact command downloads a stored pact: the Pact Broker API serves it as published, so any HTTP client (curl, a pipeline step) fetches it with the request below.';

/**
 * The form as its REST request (no command downloads a pact).
 *
 * @param draft - The form.
 * @param tenant - The workspace slug.
 * @returns The action for `pactCommandSurfaces`.
 */
export function pactFileAction(draft: PactFileDraft, tenant: string): PactAction {
  const path = pactFilePath(draft.provider.trim() || '{provider}', draft.consumer.trim() || '{consumer}', draft.choice, draft.choiceValue.trim() || `{${draft.choice}}`);
  return { verb: null, noCommandReason: PACT_FILE_HAS_NO_COMMAND, rest: { method: 'GET', path: tenantPath(tenant, `/${path}`) } };
}

// --- provider test scaffolding (PFX-8.19, #7316) -------------------------------------------------

/** The languages a scaffold is written in — `apiome pact scaffold-provider-tests --language`. */
export const SCAFFOLD_LANGUAGES = ['typescript', 'java', 'go', 'python'] as const;

/** One scaffold language. */
export type ScaffoldLanguage = (typeof SCAFFOLD_LANGUAGES)[number];

/** How each language reads in the picker. */
export const SCAFFOLD_LANGUAGE_LABELS: Readonly<Record<ScaffoldLanguage, string>> = {
  typescript: 'TypeScript · pact-js',
  java: 'Java · pact-jvm',
  go: 'Go · pact-go',
  python: 'Python · pact-python',
};

/** What the **Pacts** field says: the selectors every scaffold uses. */
export const RECOMMENDED_SELECTORS_LABEL =
  'Recommended selectors: each consumer’s main branch, and whatever is deployed or released — pending pacts on.';

/** The **Provider test scaffolding** form. */
export interface ScaffoldDraft {
  provider: string;
  language: ScaffoldLanguage;
  /** `--fail-on-unregistered`: only changes the command. */
  failOnUnregistered: boolean;
}

/** An empty form: TypeScript, as the mockup opens. */
export const EMPTY_SCAFFOLD: ScaffoldDraft = { provider: '', language: 'typescript', failOnUnregistered: false };

/**
 * Check the form before anything is sent.
 *
 * @param draft - The form.
 * @returns A sentence naming the first problem, or `null`.
 */
export function validateScaffold(draft: ScaffoldDraft): string | null {
  if (!(SCAFFOLD_LANGUAGES as readonly string[]).includes(draft.language)) return `Language is one of ${SCAFFOLD_LANGUAGES.join(', ')}.`;
  return referenceProblem('Provider', draft.provider);
}

/**
 * The browser's URL of the scaffold proxy.
 *
 * @param draft - The checked form.
 * @returns `/api/pact/export/provider-tests?provider=…&language=…`.
 */
export function scaffoldUrl(draft: ScaffoldDraft): string {
  return `/api/pact/export/provider-tests?${new URLSearchParams({ provider: draft.provider.trim(), language: draft.language }).toString()}`;
}

/**
 * Check the scaffold proxy's query and build REST's path.
 *
 * @param params - The query.
 * @returns `pact-provider-tests/{provider}?language=…`, or a 400 sentence.
 */
export function pickScaffoldQuery(params: URLSearchParams): PickedPath {
  const values: Record<string, string> = {};
  for (const [key, value] of params.entries()) {
    if (key !== 'provider' && key !== 'language') return { ok: false, error: `Unsupported parameter ${key}: a scaffold takes provider and language.` };
    if (key in values) return { ok: false, error: `The ${key} parameter is given more than once.` };
    values[key] = value.trim();
  }
  const problem = validateScaffold({ provider: values.provider ?? '', language: (values.language ?? '') as ScaffoldLanguage, failOnUnregistered: false });
  if (problem) return { ok: false, error: problem };
  return { ok: true, path: `pact-provider-tests/${encodeURIComponent(values.provider)}?${new URLSearchParams({ language: values.language }).toString()}` };
}

/** One provider state of a scaffold. */
export interface ScaffoldStateRow {
  name: string;
  params: string[];
  registered: boolean;
  interactions: number;
  consumers: string[];
}

/** A scaffold, read. */
export interface ProviderScaffold {
  providerName: string;
  label: string;
  dependency: string;
  fileName: string;
  content: string;
  pacts: number;
  states: ScaffoldStateRow[];
  unregistered: number;
  notices: Array<{ code: string; message: string; state?: string }>;
}

/**
 * Read REST's scaffold (`GET …/pact-provider-tests/{provider}`).
 *
 * @param data - REST's body.
 * @returns The scaffold, or `null` when the body is not one.
 */
export function readScaffold(data: unknown): ProviderScaffold | null {
  if (!isObject(data) || typeof data.content !== 'string' || typeof data.file_name !== 'string') return null;
  const text = (value: unknown) => (typeof value === 'string' ? value : '');
  const states = Array.isArray(data.states)
    ? data.states.flatMap((raw) =>
        isObject(raw) && typeof raw.name === 'string'
          ? [
              {
                name: raw.name,
                params: Array.isArray(raw.params) ? raw.params.filter((p): p is string => typeof p === 'string') : [],
                registered: raw.registered === true,
                interactions: typeof raw.interactions === 'number' ? raw.interactions : 0,
                consumers: Array.isArray(raw.consumers) ? raw.consumers.filter((c): c is string => typeof c === 'string') : [],
              },
            ]
          : [],
      )
    : [];
  const notices = Array.isArray(data.notices)
    ? data.notices.flatMap((raw) =>
        isObject(raw) && typeof raw.message === 'string'
          ? [{ code: text(raw.code), message: raw.message, ...(typeof raw.state === 'string' ? { state: raw.state } : {}) }]
          : [],
      )
    : [];
  return {
    providerName: text(data.provider_name),
    label: text(data.label),
    dependency: text(data.dependency),
    fileName: data.file_name,
    content: data.content,
    pacts: typeof data.pacts === 'number' ? data.pacts : 0,
    states,
    unregistered: typeof data.unregistered === 'number' ? data.unregistered : states.filter((s) => !s.registered).length,
    notices,
  };
}

/**
 * The line under the code: `11 provider states · 2 have no handler in Apiome`.
 *
 * @param scaffold - The scaffold.
 * @returns The sentence.
 */
export function scaffoldSummary(scaffold: ProviderScaffold): string {
  const states = `${scaffold.states.length} provider state${scaffold.states.length === 1 ? '' : 's'}`;
  if (scaffold.unregistered === 0) return `${states} · all registered in Apiome`;
  return `${states} · ${scaffold.unregistered} ${scaffold.unregistered === 1 ? 'has' : 'have'} no handler in Apiome`;
}

/**
 * The form as `apiome pact scaffold-provider-tests` and its REST request.
 *
 * @param draft - The form.
 * @param tenant - The workspace slug.
 * @param fileName - The file name REST suggested, once known.
 * @returns The action for `pactCommandSurfaces`.
 */
export function scaffoldAction(draft: ScaffoldDraft, tenant: string, fileName: string | null): PactAction {
  const provider = draft.provider.trim() || '{provider}';
  return {
    verb: 'scaffold-provider-tests',
    options: [
      { flag: '--provider', value: provider },
      { flag: '--language', value: draft.language },
      { flag: '--output', value: fileName ?? '' },
      { flag: '--fail-on-unregistered', value: draft.failOnUnregistered },
    ],
    rest: { method: 'GET', path: tenantPath(tenant, `/pact-provider-tests/${encodeURIComponent(provider)}?language=${draft.language}`) },
  };
}

// --- the same, from anywhere ---------------------------------------------------------------------

/**
 * Every flag of the three commands this page does, and the control that sets it — the ledger's
 * `fields` for `export-consumer-contract`, `export-postman` and `scaffold-provider-tests` (`docs/pact-parity-ledger.json`);
 * the model test holds the two together.
 */
export const EXPORT_FLAG_FIELDS: Readonly<
  Record<'export-consumer-contract' | 'export-postman' | 'scaffold-provider-tests', Readonly<Record<string, string>>>
> = {
  'scaffold-provider-tests': {
    '--provider': 'Provider test scaffolding → Provider',
    '--language': 'Provider test scaffolding → Language',
    '--output': 'Provider test scaffolding → Download',
    '--fail-on-unregistered': 'Provider test scaffolding → Fail if a state has no handler in Apiome (the page flags each one)',
    '--broker-base-url': 'The workspace you are signed in to',
    '--broker-token': 'Your session',
  },
  'export-consumer-contract': {
    '--project': 'A pact from a project → Project',
    '--consumer': 'A pact from a project → Consumer',
    '--revision': 'A pact from a project → Revision',
    '--provider': 'A pact from a project → Provider',
    '--output': 'A pact from a project → Download pact',
    '--fail-on-findings': 'A pact from a project → Fail if anything needs review (the page lists every finding)',
    '--broker-base-url': 'The workspace you are signed in to',
    '--broker-token': 'Your session',
  },
  'export-postman': {
    '--provider': 'A Postman collection → Provider',
    '--consumer': 'A Postman collection → Consumer',
    '--consumer-version': 'A Postman collection → Which pact → A consumer version',
    '--tag': 'A Postman collection → Which pact → Latest with a tag',
    '--branch': 'A Postman collection → Which pact → Latest on a branch',
    '--pact-version': 'A Postman collection → Which pact → A pact version (SHA)',
    '--pact-file': 'A Postman collection → Which pact → Upload a pact file',
    '--provider-base-url': 'A Postman collection → Provider base URL',
    '--tests': 'A Postman collection → Give each request a test script',
    '--all-consumers': 'A Postman collection → All consumers — one folder each',
    '--state-setup': 'A Postman collection → Include provider-state setup as pre-request scripts',
    '--state-change-url': 'A Postman collection → State change URL',
    '--output': 'A Postman collection → Download collection',
    '--fail-on-left-out': 'A Postman collection → Fail if any interaction is left out (the page lists what was left out)',
    '--broker-base-url': 'The workspace you are signed in to',
    '--broker-token': 'Your session',
  },
};
