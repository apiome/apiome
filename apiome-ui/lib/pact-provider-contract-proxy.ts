/**
 * The BFF side of **Publish a provider contract** (PFX-8.6, #7303): what `/api/pact/provider-contracts`
 * and `/api/pact/provider-contracts/check` accept, and the publish with **Run it now**.
 *
 * - {@link pickContractRequest} reads the browser's body — `{ provider, providerVersion, body, run? }`
 *   — and refuses, naming it, any field it does not know, a mistyped one or an oversized one, so
 *   nothing reaches REST that the page did not mean to send (and nothing is silently dropped).
 * - {@link publishWithEvidence} runs the publish. With **Run it now** it first runs the hosted
 *   provider verifier (`POST …/contracts/{versionRef}/verify-provider`); a run that does not pass
 *   **publishes nothing** and answers with the failing operations and the report. A run that passes
 *   is cited by its report id (`verificationResults.providerVerificationReportId`), so REST reads
 *   the evidence from the stored report, not from anything the browser says.
 *
 * Every call goes to REST as the signed-in user; the tenant, the `pacts` permission (and
 * `versions:view` / `verification_evidence:*` for the run and the report) are REST's. Pure apart
 * from the injected {@link RestCall}.
 */

import { MAX_FIELD_CHARS, MAX_URL_CHARS } from './pact-publish';
import { failingOperations } from './pact-provider-contract';

/** The REST body fields the page may send, and the shape each must have. */
const BODY_FIELDS: Record<string, 'string' | 'strings' | 'results'> = {
  content: 'string',
  contentType: 'string',
  contractType: 'string',
  apiomeVersion: 'string',
  branch: 'string',
  tags: 'strings',
  buildUrl: 'string',
  verificationResults: 'results',
};

/** The `verificationResults` fields, as REST names them. */
const RESULT_FIELDS: Record<string, 'string' | 'boolean'> = {
  success: 'boolean',
  content: 'string',
  contentType: 'string',
  verifier: 'string',
  verifierVersion: 'string',
  providerVerificationReportId: 'string',
};

/** The largest base64 field (a 8 MiB document is 4/3 of that). */
const MAX_CONTENT_CHARS = Math.ceil((8 * 1024 * 1024 * 4) / 3) + 8;

/** What the browser asked for, checked. */
export interface ContractRequest {
  provider: string;
  providerVersion: string;
  /** The REST body, as the page built it. */
  body: Record<string, unknown>;
  /** **Run it now**: the version reference to verify and the target to run against. */
  run: { versionRef: string; target: string } | null;
}

/** A checked request, or why it is refused. */
export type PickedContractRequest = { ok: true; request: ContractRequest } | { ok: false; error: string };

/**
 * A short string field, or the refusal.
 *
 * @param value - The value.
 * @param name - Its name, for the message.
 * @param max - Its longest length.
 * @returns The trimmed value, or an error message.
 */
function shortText(value: unknown, name: string, max = MAX_FIELD_CHARS): { value: string } | { error: string } {
  if (typeof value !== 'string' || !value.trim()) return { error: `${name} is required.` };
  if (value.trim().length > max) return { error: `${name} is longer than ${max} characters.` };
  return { value: value.trim() };
}

/**
 * Check one REST body field.
 *
 * @param name - The field.
 * @param value - Its value.
 * @returns An error message, or `null`.
 */
function bodyFieldProblem(name: string, value: unknown): string | null {
  const kind = BODY_FIELDS[name];
  if (!kind) return `body.${name} is not a field the page sends.`;
  if (kind === 'string') {
    if (typeof value !== 'string') return `body.${name} must be text.`;
    const max = name === 'content' ? MAX_CONTENT_CHARS : name === 'buildUrl' ? MAX_URL_CHARS : MAX_FIELD_CHARS;
    return value.length > max ? `body.${name} is too long.` : null;
  }
  if (kind === 'strings') {
    return Array.isArray(value) && value.every((tag) => typeof tag === 'string') && value.length <= 50
      ? null
      : `body.${name} must be at most 50 tags.`;
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) return 'body.verificationResults must be an object.';
  for (const [key, inner] of Object.entries(value)) {
    const want = RESULT_FIELDS[key];
    if (!want) return `body.verificationResults.${key} is not a field the page sends.`;
    if (typeof inner !== want) return `body.verificationResults.${key} must be ${want === 'boolean' ? 'true or false' : 'text'}.`;
    if (key === 'content' && typeof inner === 'string' && inner.length > MAX_CONTENT_CHARS) return 'The report is too large.';
  }
  return null;
}

/**
 * Read the browser's body.
 *
 * @param raw - The parsed JSON.
 * @param mode - `check` also takes `body.contentUrl` and no `run`; `publish` takes `run`.
 * @returns The request, or the first reason it is refused.
 */
export function pickContractRequest(raw: unknown, mode: 'publish' | 'check'): PickedContractRequest {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return { ok: false, error: 'The request must be a JSON object.' };
  const doc = raw as Record<string, unknown>;
  const allowed = mode === 'publish' ? ['provider', 'providerVersion', 'body', 'run'] : ['provider', 'providerVersion', 'body'];
  const unknown = Object.keys(doc).find((key) => !allowed.includes(key));
  if (unknown) return { ok: false, error: `${unknown} is not a field of this request.` };
  const provider = shortText(doc.provider, 'provider');
  if ('error' in provider) return { ok: false, error: provider.error };
  const providerVersion = shortText(doc.providerVersion, 'providerVersion');
  if ('error' in providerVersion) return { ok: false, error: providerVersion.error };
  if (providerVersion.value.includes('/')) return { ok: false, error: 'providerVersion cannot contain "/".' };
  const body = doc.body;
  if (!body || typeof body !== 'object' || Array.isArray(body)) return { ok: false, error: 'body must be an object.' };
  const fields = { ...(body as Record<string, unknown>) };
  if (mode === 'check' && 'contentUrl' in fields) {
    const url = fields.contentUrl;
    if (typeof url !== 'string' || !/^https?:\/\//i.test(url.trim()) || url.length > MAX_URL_CHARS) {
      return { ok: false, error: 'body.contentUrl must be an http(s) URL.' };
    }
    delete fields.contentUrl;
  }
  for (const [name, value] of Object.entries(fields)) {
    const problem = bodyFieldProblem(name, value);
    if (problem) return { ok: false, error: problem };
  }
  let run: ContractRequest['run'] = null;
  if (doc.run !== undefined) {
    const spec = doc.run as Record<string, unknown> | null;
    if (!spec || typeof spec !== 'object' || Array.isArray(spec)) return { ok: false, error: 'run must be an object.' };
    const extra = Object.keys(spec).find((key) => key !== 'versionRef' && key !== 'target');
    if (extra) return { ok: false, error: `run.${extra} is not a field of this request.` };
    const ref = shortText(spec.versionRef, 'run.versionRef', 600);
    if ('error' in ref) return { ok: false, error: ref.error };
    if (!/^project\/[^/]+\/[^/]+$/.test(ref.value)) return { ok: false, error: 'run.versionRef must be project/<project>/<version>.' };
    const target = shortText(spec.target, 'run.target');
    if ('error' in target) return { ok: false, error: target.error };
    const results = (body as Record<string, unknown>).verificationResults;
    if (results !== undefined) return { ok: false, error: 'Run it now brings its own evidence; send no verificationResults with it.' };
    run = { versionRef: ref.value, target: target.value };
  }
  return { ok: true, request: { provider: provider.value, providerVersion: providerVersion.value, body: body as Record<string, unknown>, run } };
}

/**
 * The REST path of a provider version's contract, below `/v1/tenants/{slug}/`.
 *
 * @param provider - The provider's name or handle.
 * @param version - The provider version.
 * @param suffix - E.g. `/check`.
 * @returns The path.
 */
export function contractPath(provider: string, version: string, suffix = ''): string {
  return `pact-broker/contracts/provider/${encodeURIComponent(provider)}/version/${encodeURIComponent(version)}${suffix}`;
}

/** One REST call as the signed-in user: the status and the parsed body, or `null` when unreachable. */
export type RestCall = (method: 'POST' | 'PUT', path: string, body: unknown) => Promise<{ status: number; body: unknown } | null>;

/** What the BFF answers: the status and the JSON body. */
export interface ProxyAnswer {
  status: number;
  body: Record<string, unknown>;
}

/** What the browser is told when apiome-rest cannot be reached. */
export const CONTRACT_UNAVAILABLE = 'The Pact Broker is unavailable (apiome-rest not reachable). Try again shortly.';

/**
 * REST's refusal as the page reads it: the message, and the code and pointer when REST sent them.
 *
 * @param status - REST's status.
 * @param body - REST's body.
 * @returns `{ success: false, error, code?, pointer? }` with the status.
 */
export function refusal(status: number, body: unknown): ProxyAnswer {
  const detail = (body as { detail?: unknown } | null)?.detail;
  const doc = detail && typeof detail === 'object' && !Array.isArray(detail) ? (detail as Record<string, unknown>) : {};
  const message =
    typeof detail === 'string'
      ? detail
      : typeof doc.message === 'string'
        ? doc.message
        : Array.isArray(detail)
          ? 'The request was refused.'
          : `The Pact Broker refused it (${status}).`;
  return {
    status: status >= 400 ? status : 502,
    body: {
      success: false,
      error: message,
      ...(typeof doc.code === 'string' ? { code: doc.code } : {}),
      ...(typeof doc.pointer === 'string' ? { pointer: doc.pointer } : {}),
    },
  };
}

/**
 * Run the hosted verifier for **Run it now**.
 *
 * @param call - The REST call.
 * @param run - The version reference and target.
 * @returns The report id when the run passed, or the answer to send back (a failed run, or REST's refusal).
 */
async function runVerifier(call: RestCall, run: NonNullable<ContractRequest['run']>): Promise<{ reportId: string } | ProxyAnswer> {
  const path = `contracts/${run.versionRef.split('/').map(encodeURIComponent).join('/')}/verify-provider`;
  const answer = await call('POST', path, { target_ref: run.target });
  if (!answer) return { status: 503, body: { success: false, error: CONTRACT_UNAVAILABLE } };
  if (answer.status >= 400) return refusal(answer.status, answer.body);
  const doc = (answer.body ?? {}) as Record<string, unknown>;
  const report = (doc.report ?? null) as Record<string, unknown> | null;
  const stored = (doc.stored ?? null) as Record<string, unknown> | null;
  const runRecord = (doc.run ?? null) as Record<string, unknown> | null;
  const reportId = typeof stored?.id === 'string' ? stored.id : null;
  const outcome = typeof report?.outcome === 'string' ? report.outcome : 'errored';
  if (doc.ok === true && outcome === 'passed' && reportId) return { reportId };
  const error = (doc.error ?? null) as Record<string, unknown> | null;
  const message =
    doc.ok !== true
      ? `The verifier could not run: ${typeof error?.message === 'string' ? error.message : 'the version yields no executable cases'}. Nothing was published.`
      : outcome === 'passed'
        ? 'The run passed but its report could not be stored, so it cannot be cited. Nothing was published.'
        : `The provider did not pass (${outcome}). Nothing was published.`;
  return {
    status: 200,
    body: {
      success: true,
      published: false,
      run: {
        outcome,
        reportId,
        runId: typeof runRecord?.id === 'string' ? runRecord.id : null,
        failing: failingOperations(report),
        message,
      },
    },
  };
}

/**
 * Publish the contract — after **Run it now**, only when the run passed.
 *
 * @param call - The REST call as the signed-in user.
 * @param request - The checked request.
 * @returns `{ success, published: true, created, contract }`, `{ success, published: false, run }`, or REST's refusal.
 */
export async function publishWithEvidence(call: RestCall, request: ContractRequest): Promise<ProxyAnswer> {
  let body = request.body;
  if (request.run) {
    const ran = await runVerifier(call, request.run);
    if (!('reportId' in ran)) return ran;
    body = { ...body, verificationResults: { providerVerificationReportId: ran.reportId } };
  }
  const answer = await call('PUT', contractPath(request.provider, request.providerVersion), body);
  if (!answer) return { status: 503, body: { success: false, error: CONTRACT_UNAVAILABLE } };
  if (answer.status >= 400) return refusal(answer.status, answer.body);
  return { status: 200, body: { success: true, published: true, created: answer.status === 201, contract: answer.body } };
}

/**
 * Check the contract (store nothing).
 *
 * @param call - The REST call as the signed-in user.
 * @param request - The checked request.
 * @returns REST's answer, or its refusal.
 */
export async function checkContract(call: RestCall, request: ContractRequest): Promise<ProxyAnswer> {
  const answer = await call('POST', contractPath(request.provider, request.providerVersion, '/check'), request.body);
  if (!answer) return { status: 503, body: { success: false, error: CONTRACT_UNAVAILABLE } };
  if (answer.status >= 400) return refusal(answer.status, answer.body);
  return { status: 200, body: { success: true, ...(answer.body as Record<string, unknown>) } };
}

/** How many runs **Reuse** offers. */
export const REPORTS_LIMIT = 20;

/**
 * The REST path of a version's provider-verification reports, from the BFF's query.
 *
 * @param search - `project` and `version`, nothing else.
 * @returns The path below `/v1/tenants/{slug}/`, or why the query is refused.
 */
export function reportsQuery(search: URLSearchParams): { ok: true; path: string } | { ok: false; error: string } {
  const extra = [...search.keys()].find((key) => key !== 'project' && key !== 'version');
  if (extra) return { ok: false, error: `${extra} is not a parameter of this list.` };
  const project = search.get('project')?.trim() ?? '';
  const version = search.get('version')?.trim() ?? '';
  if (!project || !version) return { ok: false, error: 'project and version are required.' };
  if (project.includes('/') || version.includes('/')) return { ok: false, error: 'project and version cannot contain "/".' };
  if (project.length > MAX_FIELD_CHARS || version.length > MAX_FIELD_CHARS) return { ok: false, error: 'project or version is too long.' };
  const query = new URLSearchParams({ version_ref: `project/${project}/${version}`, limit: String(REPORTS_LIMIT) });
  return { ok: true, path: `provider-verifications?${query.toString()}` };
}
