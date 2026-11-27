/**
 * The provider's spec, as the **Write interactions** editor reads it — PFX-8.5 (#7302).
 *
 * The editor checks each interaction's path against the provider's spec, fills a response from
 * it (**Fill from the spec**), and suggests provider states. Everything it needs comes from one
 * BFF read, `GET /api/pact/publish/provider-spec?provider=<name>`, which this module serves:
 *
 * * {@link pickSpecQuery} — the proxy's query: exactly `provider`, once.
 * * {@link loadProviderSpec} — the provider's pacticipant → its linked project → the project's
 *   latest revision → that revision's OpenAPI document and mock scenarios, plus the provider's
 *   registered states (PFX-3.3). Each read is the signed-in user's, so tenancy and RBAC are REST's;
 *   a part that cannot be read is named in `problems`, never left out quietly. Only a refusal of
 *   the pacticipant read itself (401 / 403 / 5xx) fails the whole answer.
 * * {@link outlineOpenApi} — the document cut down to what the editor uses: each operation's
 *   method and path template, and per response its status, media type, example (from the spec, or
 *   generated from the schema and marked so) and the typed body fields matchers are drawn from.
 *
 * Pure apart from the injected `fetchJson`.
 */

/** One typed field of a response body, e.g. `$.amount` integer. */
export interface SpecField {
  /** A Pact matching-rule path: `$.id`, `$.items[*].id`. */
  path: string;
  /** The JSON Schema type: `string`, `integer`, `number`, `boolean`, `array`, `object`. */
  type: string;
  /** The schema's `format`, when it has one. */
  format?: string;
  /** The schema's `pattern`, when it has one. */
  pattern?: string;
  /** The schema's `enum`, when it has one (scalars only). */
  enum?: Array<string | number | boolean>;
}

/** Where a response's example came from. */
export type ExampleSource = 'spec' | 'schema' | 'none';

/** One documented response of an operation. */
export interface SpecResponse {
  /** `200`, `404`, `default`, `2XX`. */
  status: string;
  /** The media type the example is for, e.g. `application/json`; `null` without a body. */
  contentType: string | null;
  /** The example body; `undefined` when there is none. */
  example?: unknown;
  /** `spec` (an example in the document), `schema` (generated — review it) or `none`. */
  exampleSource: ExampleSource;
  /** The body's typed fields. */
  fields: SpecField[];
}

/** One operation of the spec. */
export interface SpecOperation {
  /** Upper case, e.g. `GET`. */
  method: string;
  /** The path template, e.g. `/invoices/{id}`. */
  path: string;
  summary: string | null;
  responses: SpecResponse[];
}

/** Where a suggested provider state comes from. */
export type StateSource = 'catalogue' | 'mock';

/** One provider-state suggestion. */
export interface StateSuggestion {
  name: string;
  source: StateSource;
  /** The parameters the state declares (catalogue states only). */
  parameters: Array<{ name: string; required: boolean }>;
  description: string | null;
}

/** What the BFF answers. */
export interface ProviderSpec {
  provider: string;
  /** The revision the operations come from; `null` when none could be read. */
  revision: { projectId: string; versionId: string; label: string } | null;
  operations: SpecOperation[];
  /** Provider states from the catalogue and the mock's scenarios. */
  states: StateSuggestion[];
  /** Every part that could not be read, as a sentence. */
  problems: string[];
}

/** Most operations an outline keeps (the rest are named in `problems`). */
export const MAX_OPERATIONS = 500;

/** Most fields one response body contributes. */
export const MAX_FIELDS = 200;

/** How deep a schema is walked. */
const MAX_DEPTH = 8;

/** The HTTP methods an OpenAPI path item carries. */
const METHODS = ['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'] as const;

/** Most characters a provider name may have (REST's pacticipant name limit). */
const MAX_PROVIDER_CHARS = 255;

/** Whether a value is a plain JSON object. */
function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

// --- the proxy's query ---------------------------------------------------------------------------

/** The query, or why it is refused. */
export type PickedSpecQuery = { ok: true; provider: string } | { ok: false; error: string };

/**
 * Read the proxy's query: exactly `provider`, once.
 *
 * @param params - The browser's query string.
 * @returns The provider's name, or a sentence naming the problem (a 400).
 */
export function pickSpecQuery(params: URLSearchParams): PickedSpecQuery {
  let provider: string | null = null;
  for (const [key, value] of params.entries()) {
    if (key !== 'provider') return { ok: false, error: `Unsupported parameter ${key}: the spec read takes provider only.` };
    if (provider !== null) return { ok: false, error: 'The provider parameter is given more than once.' };
    provider = value;
  }
  const name = (provider ?? '').trim();
  if (!name) return { ok: false, error: 'provider is required.' };
  if (name.length > MAX_PROVIDER_CHARS) return { ok: false, error: `provider is longer than ${MAX_PROVIDER_CHARS} characters.` };
  if (/[\u0000-\u001f\u007f]/.test(name)) return { ok: false, error: 'provider contains a control character.' };
  return { ok: true, provider: name };
}

// --- the OpenAPI outline -------------------------------------------------------------------------

/**
 * Follow a local `$ref` (`#/components/schemas/Invoice`).
 *
 * @param root - The whole document.
 * @param node - A schema or a reference.
 * @param seen - References already followed on this branch (cycle guard).
 * @returns The schema it points at (or `node` itself), and the references followed.
 */
function deref(root: Record<string, unknown>, node: unknown, seen: Set<string>): { node: unknown; seen: Set<string> } {
  let current = node;
  const followed = new Set(seen);
  while (isObject(current) && typeof current.$ref === 'string') {
    const ref = current.$ref;
    if (!ref.startsWith('#/') || followed.has(ref)) return { node: {}, seen: followed };
    followed.add(ref);
    let target: unknown = root;
    for (const raw of ref.slice(2).split('/')) {
      const key = raw.replace(/~1/g, '/').replace(/~0/g, '~');
      target = isObject(target) ? target[key] : undefined;
    }
    current = target;
  }
  return { node: current, seen: followed };
}

/**
 * A schema's single type: `type` (the first non-null of a list), or what its shape implies.
 *
 * @param schema - The schema.
 * @returns The type, or `null` when it cannot be told.
 */
function schemaType(schema: Record<string, unknown>): string | null {
  const type = Array.isArray(schema.type) ? schema.type.find((t) => t !== 'null') : schema.type;
  if (typeof type === 'string') return type;
  if (isObject(schema.properties)) return 'object';
  if (schema.items !== undefined) return 'array';
  return null;
}

/**
 * Merge `allOf` parts into one schema (properties and required lists joined); the first of
 * `oneOf` / `anyOf` stands for the choice.
 *
 * @param root - The document.
 * @param schema - The schema.
 * @param seen - References followed on this branch.
 * @returns A schema without composition keywords at its top.
 */
function flatten(root: Record<string, unknown>, schema: Record<string, unknown>, seen: Set<string>): Record<string, unknown> {
  let merged: Record<string, unknown> = { ...schema };
  if (Array.isArray(schema.allOf)) {
    const properties: Record<string, unknown> = isObject(schema.properties) ? { ...schema.properties } : {};
    for (const part of schema.allOf) {
      const resolved = deref(root, part, seen).node;
      if (!isObject(resolved)) continue;
      const flat = flatten(root, resolved, seen);
      if (isObject(flat.properties)) Object.assign(properties, flat.properties);
      merged = { ...flat, ...merged };
    }
    merged.properties = properties;
    if (!merged.type && Object.keys(properties).length) merged.type = 'object';
    delete merged.allOf;
  }
  for (const key of ['oneOf', 'anyOf']) {
    const choices = merged[key];
    if (Array.isArray(choices) && choices.length && !merged.type && !merged.properties) {
      const first = deref(root, choices[0], seen).node;
      if (isObject(first)) merged = { ...flatten(root, first, seen), ...merged };
      delete merged[key];
    }
  }
  return merged;
}

/** A Pact path for a property: `$.id`, or `$['odd key']` when the name is not an identifier. */
function childPath(parent: string, name: string): string {
  return /^[A-Za-z_][A-Za-z0-9_-]*$/.test(name) ? `${parent}.${name}` : `${parent}['${name.replace(/'/g, "\\'")}']`;
}

/**
 * The typed fields of a schema, walked depth first: every scalar leaf, and every array.
 *
 * @param root - The document.
 * @param node - The schema (or reference).
 * @param path - Its Pact path.
 * @param seen - References followed on this branch.
 * @param out - Where fields are collected.
 * @param depth - How deep the walk is.
 */
function collectFields(root: Record<string, unknown>, node: unknown, path: string, seen: Set<string>, out: SpecField[], depth: number): void {
  if (out.length >= MAX_FIELDS || depth > MAX_DEPTH) return;
  const resolved = deref(root, node, seen);
  if (!isObject(resolved.node)) return;
  const schema = flatten(root, resolved.node, resolved.seen);
  const type = schemaType(schema);
  if (type === 'object') {
    const properties = isObject(schema.properties) ? schema.properties : {};
    for (const [name, child] of Object.entries(properties)) collectFields(root, child, childPath(path, name), resolved.seen, out, depth + 1);
    return;
  }
  if (type === 'array') {
    if (path !== '$') out.push({ path, type });
    collectFields(root, schema.items, `${path}[*]`, resolved.seen, out, depth + 1);
    return;
  }
  if (!type || path === '$') return;
  const field: SpecField = { path, type };
  if (typeof schema.format === 'string') field.format = schema.format;
  if (typeof schema.pattern === 'string') field.pattern = schema.pattern;
  if (Array.isArray(schema.enum)) {
    const values = schema.enum.filter((v): v is string | number | boolean => ['string', 'number', 'boolean'].includes(typeof v));
    if (values.length) field.enum = values;
  }
  out.push(field);
}

/**
 * A value generated from a schema, for a response with no example (marked `schema`).
 *
 * @param root - The document.
 * @param node - The schema.
 * @param seen - References followed on this branch.
 * @param depth - How deep the walk is.
 * @returns A value that satisfies the schema's shape.
 */
function generateExample(root: Record<string, unknown>, node: unknown, seen: Set<string>, depth = 0): unknown {
  if (depth > MAX_DEPTH) return null;
  const resolved = deref(root, node, seen);
  if (!isObject(resolved.node)) return null;
  const schema = flatten(root, resolved.node, resolved.seen);
  if (schema.example !== undefined) return schema.example;
  if (Array.isArray(schema.examples) && schema.examples.length) return schema.examples[0];
  if (schema.default !== undefined) return schema.default;
  if (Array.isArray(schema.enum) && schema.enum.length) return schema.enum[0];
  switch (schemaType(schema)) {
    case 'object': {
      const out: Record<string, unknown> = {};
      const properties = isObject(schema.properties) ? schema.properties : {};
      for (const [name, child] of Object.entries(properties)) out[name] = generateExample(root, child, resolved.seen, depth + 1);
      return out;
    }
    case 'array':
      return [generateExample(root, schema.items, resolved.seen, depth + 1)];
    case 'integer':
      return 1;
    case 'number':
      return 1.5;
    case 'boolean':
      return true;
    case 'string':
      if (schema.format === 'date') return '2026-01-31';
      if (schema.format === 'date-time') return '2026-01-31T09:30:00Z';
      if (schema.format === 'uuid') return '3fa85f64-5717-4562-b3fc-2c963f66afa6';
      if (schema.format === 'email') return 'someone@example.com';
      return 'string';
    default:
      return null;
  }
}

/**
 * The media type an example is drawn from: JSON first, then the first one listed.
 *
 * @param content - A response's `content` map.
 * @returns The media type and its object, or `null`.
 */
function pickMedia(content: unknown): [string, Record<string, unknown>] | null {
  if (!isObject(content)) return null;
  const entries = Object.entries(content).filter((entry): entry is [string, Record<string, unknown>] => isObject(entry[1]));
  return entries.find(([type]) => /json/i.test(type)) ?? entries[0] ?? null;
}

/**
 * One response of an operation.
 *
 * @param root - The document.
 * @param status - Its status key.
 * @param node - The response (or reference).
 * @returns The outline of the response.
 */
function outlineResponse(root: Record<string, unknown>, status: string, node: unknown): SpecResponse {
  const response = deref(root, node, new Set()).node;
  const media = isObject(response) ? pickMedia(response.content) : null;
  if (!media) return { status, contentType: null, exampleSource: 'none', fields: [] };
  const [contentType, body] = media;
  const fields: SpecField[] = [];
  if (body.schema !== undefined) collectFields(root, body.schema, '$', new Set(), fields, 0);
  if (body.example !== undefined) return { status, contentType, example: body.example, exampleSource: 'spec', fields };
  if (isObject(body.examples)) {
    const first = Object.values(body.examples).map((entry) => deref(root, entry, new Set()).node).find(isObject);
    if (first && first.value !== undefined) return { status, contentType, example: first.value, exampleSource: 'spec', fields };
  }
  if (body.schema !== undefined) {
    const resolved = deref(root, body.schema, new Set()).node;
    if (isObject(resolved) && resolved.example !== undefined) return { status, contentType, example: resolved.example, exampleSource: 'spec', fields };
    return { status, contentType, example: generateExample(root, body.schema, new Set()), exampleSource: 'schema', fields };
  }
  return { status, contentType, exampleSource: 'none', fields };
}

/**
 * Cut an OpenAPI document down to what the editor uses.
 *
 * @param document - The parsed OpenAPI 3.x document.
 * @returns The operations (at most {@link MAX_OPERATIONS}), and how many were left out.
 */
export function outlineOpenApi(document: unknown): { operations: SpecOperation[]; leftOut: number } {
  if (!isObject(document) || !isObject(document.paths)) return { operations: [], leftOut: 0 };
  const operations: SpecOperation[] = [];
  let leftOut = 0;
  for (const [path, rawItem] of Object.entries(document.paths)) {
    const item = deref(document, rawItem, new Set()).node;
    if (!isObject(item)) continue;
    for (const method of METHODS) {
      const operation = item[method];
      if (!isObject(operation)) continue;
      if (operations.length >= MAX_OPERATIONS) {
        leftOut += 1;
        continue;
      }
      const responses = isObject(operation.responses) ? operation.responses : {};
      operations.push({
        method: method.toUpperCase(),
        path,
        summary: typeof operation.summary === 'string' ? operation.summary : typeof operation.operationId === 'string' ? operation.operationId : null,
        responses: Object.entries(responses).map(([status, response]) => outlineResponse(document, status, response)),
      });
    }
  }
  return { operations, leftOut };
}

// --- matching a path -----------------------------------------------------------------------------

/**
 * Whether a concrete path fits a template: `/invoices/42` fits `/invoices/{id}`.
 *
 * @param template - The spec's path, e.g. `/invoices/{id}`.
 * @param path - The interaction's path.
 * @returns `true` when every segment matches.
 */
export function pathFits(template: string, path: string): boolean {
  const split = (value: string) => value.replace(/\/+$/, '').split('/');
  const want = split(template);
  const have = split(path);
  if (want.length !== have.length) return false;
  return want.every((segment, i) => {
    if (!segment.includes('{')) return segment === have[i];
    // A segment can mix text and parameters: `{name}.json`, `v{major}`.
    const pattern = segment
      .split(/(\{[^}]+\})/)
      .map((part) => (part.startsWith('{') ? '[^/]+' : part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
      .join('');
    return new RegExp(`^${pattern}$`).test(have[i]);
  });
}

/**
 * The operations a request reaches: the literal template before a templated one, as servers route.
 *
 * @param operations - The spec's operations.
 * @param method - The request's method.
 * @param path - The request's path.
 * @returns The matching operation, or `null`; and whether the path exists for another method.
 */
export function findOperation(operations: SpecOperation[], method: string, path: string): { operation: SpecOperation | null; otherMethods: string[] } {
  const fitting = operations.filter((op) => pathFits(op.path, path));
  const byLiteral = (a: SpecOperation, b: SpecOperation) => (a.path.match(/\{/g)?.length ?? 0) - (b.path.match(/\{/g)?.length ?? 0);
  const same = fitting.filter((op) => op.method === method.toUpperCase()).sort(byLiteral);
  return { operation: same[0] ?? null, otherMethods: [...new Set(fitting.map((op) => op.method))].filter((m) => m !== method.toUpperCase()) };
}

// --- the BFF read --------------------------------------------------------------------------------

/** What one REST read answered: its status and parsed body (`null` when unreachable). */
export interface JsonAnswer {
  status: number;
  body: unknown;
}

/** A REST read, as the signed-in user (injected so the orchestration is testable). */
export type FetchJson = (url: string) => Promise<JsonAnswer | null>;

/** The REST base paths the read uses. */
export interface SpecUrls {
  /** `…/v1/tenants/{slug}/` + path. */
  tenant: (path: string) => string;
  /** `…/v1/versions/{slug}/` + path. */
  versions: (path: string) => string;
}

/** A failure of the read as a whole: the status and the sentence. */
export interface SpecFailure {
  status: number;
  error: string;
}

/** The sentence a REST error body carries. */
function errorText(body: unknown, fallback: string): string {
  if (isObject(body)) {
    if (typeof body.error === 'string') return body.error;
    if (typeof body.detail === 'string') return body.detail;
    if (isObject(body.detail) && typeof body.detail.message === 'string') return body.detail.message;
  }
  return fallback;
}

/**
 * The handle REST derives from a pacticipant name (`slugify_consumer_name`).
 *
 * @param name - E.g. `Billing Service`.
 * @returns E.g. `billing-service`.
 */
export function providerHandle(name: string): string {
  return name.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 128).replace(/-+$/, '');
}

/**
 * The revision the outline is read from: the most recently created one.
 *
 * @param versions - REST's version list.
 * @returns The revision's id and label, or `null`.
 */
export function latestRevision(versions: unknown): { id: string; label: string } | null {
  if (!Array.isArray(versions)) return null;
  const rows = versions.filter((row): row is Record<string, unknown> => isObject(row) && typeof row.id === 'string');
  if (!rows.length) return null;
  const time = (row: Record<string, unknown>) => (typeof row.created_at === 'string' ? Date.parse(row.created_at) || 0 : 0);
  const latest = [...rows].sort((a, b) => time(b) - time(a))[0];
  const label = typeof latest.version_id === 'string' && latest.version_id ? latest.version_id : (latest.id as string);
  return { id: latest.id as string, label };
}

/**
 * The provider-state suggestions: the catalogue's states, then each mock scenario not already one.
 *
 * @param catalogue - REST's state list (PFX-3.3), or `null` when it could not be read.
 * @param scenarios - The revision's `{ scenarios }` answer, or `null`.
 * @returns The suggestions, catalogue first.
 */
export function stateSuggestions(catalogue: unknown, scenarios: unknown): StateSuggestion[] {
  const out: StateSuggestion[] = [];
  for (const state of Array.isArray(catalogue) ? catalogue : []) {
    if (!isObject(state) || typeof state.name !== 'string') continue;
    const parameters = Array.isArray(state.parameters)
      ? state.parameters.flatMap((p) => (isObject(p) && typeof p.name === 'string' ? [{ name: p.name, required: p.required === true }] : []))
      : [];
    out.push({ name: state.name, source: 'catalogue', parameters, description: typeof state.description === 'string' ? state.description : null });
  }
  const map = isObject(scenarios) && isObject(scenarios.scenarios) ? scenarios.scenarios : {};
  for (const [name, spec] of Object.entries(map)) {
    if (out.some((s) => s.name === name)) continue;
    const description = isObject(spec) && typeof spec.description === 'string' && spec.description ? spec.description : null;
    out.push({ name, source: 'mock', parameters: [], description });
  }
  return out;
}

/**
 * Read everything the editor needs about one provider.
 *
 * @param provider - The provider's name, as the pact names it.
 * @param urls - The REST URL builders for the caller's workspace.
 * @param fetchJson - A REST read as the signed-in user.
 * @returns The spec, or the failure of the pacticipant read (its status kept: 401, 403, 5xx).
 */
export async function loadProviderSpec(provider: string, urls: SpecUrls, fetchJson: FetchJson): Promise<ProviderSpec | SpecFailure> {
  const handle = providerHandle(provider);
  const spec: ProviderSpec = { provider, revision: null, operations: [], states: [], problems: [] };
  if (!handle) return { ...spec, problems: [`${provider} has no usable handle, so no spec can be found for it.`] };

  const [pacticipant, catalogue] = await Promise.all([
    fetchJson(urls.tenant(`pacticipants/${handle}`)),
    fetchJson(urls.tenant(`pact-verifier/providers/${handle}/provider-states`)),
  ]);
  if (!pacticipant) return { status: 503, error: 'The provider’s spec is unavailable (apiome-rest not reachable). Try again shortly.' };
  if (pacticipant.status === 404) {
    spec.problems.push(`${provider} is not a pacticipant yet, so there is no spec to check paths against. Interactions are written and published all the same.`);
  } else if (pacticipant.status >= 400) {
    return { status: pacticipant.status, error: errorText(pacticipant.body, `The provider could not be read (${pacticipant.status}).`) };
  }

  let scenarios: unknown = null;
  const projectId = isObject(pacticipant.body) && typeof pacticipant.body.project_id === 'string' ? pacticipant.body.project_id : null;
  if (pacticipant.status < 400 && !projectId) {
    spec.problems.push(`${provider} is not linked to a project, so paths are not checked against a spec. Link it on its pacticipant page.`);
  }
  if (projectId) {
    const versions = await fetchJson(urls.versions(encodeURIComponent(projectId)));
    const revision = versions && versions.status < 400 ? latestRevision(versions.body) : null;
    if (!versions || versions.status >= 400) {
      spec.problems.push(`The revisions of ${provider}’s project could not be read: ${errorText(versions?.body, 'apiome-rest not reachable')}.`);
    } else if (!revision) {
      spec.problems.push(`${provider}’s project has no revision yet, so there is no spec to check paths against.`);
    } else {
      spec.revision = { projectId, versionId: revision.id, label: revision.label };
      const base = `${encodeURIComponent(projectId)}/${encodeURIComponent(revision.id)}`;
      const [document, mock] = await Promise.all([fetchJson(urls.versions(`${base}/document`)), fetchJson(urls.versions(`${base}/mock/scenarios`))]);
      if (!document || document.status >= 400) {
        spec.problems.push(`The spec of revision ${revision.label} could not be read: ${errorText(document?.body, 'apiome-rest not reachable')}.`);
      } else {
        const outline = outlineOpenApi(document.body);
        spec.operations = outline.operations;
        if (outline.leftOut) spec.problems.push(`${outline.leftOut} operations past the first ${MAX_OPERATIONS} are not checked.`);
      }
      if (!mock || mock.status >= 400) {
        spec.problems.push(`The mock’s scenarios could not be read, so none are suggested as provider states: ${errorText(mock?.body, 'apiome-rest not reachable')}.`);
      } else {
        scenarios = mock.body;
      }
    }
  }
  if (!catalogue || catalogue.status >= 400) {
    if (catalogue?.status !== 404) {
      spec.problems.push(`The provider-state catalogue could not be read: ${errorText(catalogue?.body, 'apiome-rest not reachable')}.`);
    }
  }
  spec.states = stateSuggestions(catalogue && catalogue.status < 400 ? catalogue.body : null, scenarios);
  return spec;
}
