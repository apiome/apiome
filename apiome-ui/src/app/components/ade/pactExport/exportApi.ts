/**
 * The Export page's calls (PFX-8.18, #7315). Each goes through an `/api/pact/export/*` proxy as the
 * signed-in user; tenant scoping and the `pacts` permission are REST's. None of them throws: the
 * page shows every answer — and every refusal, with what it left out — beside the kind it belongs to.
 */

import {
  consumerPactUrl,
  pactFileUrl,
  readDerivedPact,
  readFindings,
  readNotices,
  readPostmanOutcome,
  type DerivedPact,
  type DeriveExportDraft,
  type ExportFinding,
  type PactFileDraft,
  type PostmanNotice,
  type PostmanOutcome,
} from '@lib/pact-export';

/** A refusal: the proxy's message, REST's code and status, and what REST said was left out. */
export interface ExportFailure {
  error: string;
  status: number;
  code: string | null;
  findings: ExportFinding[];
  notices: PostmanNotice[];
}

/** What the network said when it could not be reached. */
const UNREACHABLE = 'The Pact Broker could not be reached. Try again shortly.';

/**
 * A refusal from a proxy's JSON body.
 *
 * @param body - `{ error, code?, findings?, notices? }`, or anything.
 * @param status - The status.
 * @param fallback - What to say when the body has no message.
 * @returns The failure.
 */
function failureOf(body: unknown, status: number, fallback: string): ExportFailure {
  const data = (body ?? {}) as Record<string, unknown>;
  return {
    error: typeof data.error === 'string' && data.error ? data.error : `${fallback} (${status}).`,
    status,
    code: typeof data.code === 'string' ? data.code : null,
    findings: readFindings(data.findings),
    notices: readNotices(data.notices),
  };
}

/**
 * Send one request and read its JSON.
 *
 * @param url - The proxy URL.
 * @param init - Fetch options.
 * @returns The status and the parsed body (`null` when it was not JSON), or `null` offline.
 */
async function send(url: string, init?: RequestInit): Promise<{ status: number; body: unknown } | null> {
  try {
    const response = await fetch(url, init);
    return { status: response.status, body: await response.json().catch(() => null) };
  } catch {
    return null;
  }
}

/** Whether an answer is a failure. */
export function isFailure(value: unknown): value is ExportFailure {
  return typeof value === 'object' && value !== null && 'error' in value && 'status' in value && 'findings' in value;
}

/**
 * Derive a consumer's pact (`export-consumer-contract`).
 *
 * @param draft - The checked form.
 * @returns The pact, its findings and its checklist, or the refusal.
 */
export async function derivePact(draft: DeriveExportDraft): Promise<DerivedPact | ExportFailure> {
  const answer = await send(consumerPactUrl(draft));
  if (!answer) return failureOf({ error: UNREACHABLE }, 503, UNREACHABLE);
  if (answer.status >= 400) return failureOf(answer.body, answer.status, 'Could not derive the pact');
  return readDerivedPact(answer.body) ?? failureOf(null, 502, 'The answer was not a pact');
}

/**
 * Export a Postman collection (`export-postman`).
 *
 * @param body - The REST body.
 * @returns The collection, its counts and notices, or the refusal.
 */
export async function exportPostman(body: Record<string, unknown>): Promise<PostmanOutcome | ExportFailure> {
  const answer = await send('/api/pact/export/postman', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!answer) return failureOf({ error: UNREACHABLE }, 503, UNREACHABLE);
  if (answer.status >= 400) return failureOf(answer.body, answer.status, 'Could not export the collection');
  return readPostmanOutcome(answer.body) ?? failureOf(null, 502, 'The answer was not a collection');
}

/** One stored pact, ready to save. */
export interface PactFileAnswer {
  pact: Record<string, unknown>;
  fileName: string;
}

/**
 * Read one stored pact.
 *
 * @param draft - The checked form.
 * @returns The pact and its file name, or the refusal (a 404 when the pair has no such pact).
 */
export async function fetchPactFile(draft: PactFileDraft): Promise<PactFileAnswer | ExportFailure> {
  const answer = await send(pactFileUrl(draft));
  if (!answer) return failureOf({ error: UNREACHABLE }, 503, UNREACHABLE);
  const body = answer.body as Record<string, unknown> | null;
  if (answer.status >= 400 || !body || typeof body.pact !== 'object' || body.pact === null) {
    return failureOf(body, answer.status >= 400 ? answer.status : 502, 'Could not read the pact');
  }
  return { pact: body.pact as Record<string, unknown>, fileName: typeof body.fileName === 'string' ? body.fileName : 'pact.json' };
}

/**
 * Read every pact for the provider as a zip.
 *
 * @param draft - The checked form.
 * @returns The archive and its name, or the refusal.
 */
export async function fetchProviderPacts(draft: PactFileDraft): Promise<{ blob: Blob; fileName: string } | ExportFailure> {
  try {
    const response = await fetch(pactFileUrl(draft, true));
    if (!response.ok) return failureOf(await response.json().catch(() => null), response.status, 'Could not read the pacts');
    const disposition = response.headers.get('Content-Disposition') ?? '';
    const named = /filename="([^"]+)"/.exec(disposition);
    return { blob: await response.blob(), fileName: named ? named[1] : 'pacts.zip' };
  } catch {
    return failureOf({ error: UNREACHABLE }, 503, UNREACHABLE);
  }
}

/**
 * Save a file in the browser.
 *
 * @param fileName - The name to save as.
 * @param content - The text, or a blob.
 * @param type - The media type of a text.
 */
export function saveFile(fileName: string, content: string | Blob, type = 'application/json'): void {
  const blob = typeof content === 'string' ? new Blob([content], { type }) : content;
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
