/**
 * **Upload verification results** (PFX-8.9, #7306) — the dialog for `apiome pact
 * publish-verification-results`: attach the report of a verifier that ran elsewhere to the pact
 * version it verified, as a result of the provider version.
 *
 * The report is read on the server (`POST …/pact-version/{sha}/external-verification-results`):
 * `pact_verifier_cli --json` output, JUnit XML, or a Schemathesis (NDJSON or JUnit), Newman (JSON or
 * JUnit) or Dredd (xunit) report. **Detect** lets the server tell them apart; {@link guessFormat} says
 * beforehand what it will most likely find, and refuses at once a file that is neither JSON nor XML.
 * A report the server cannot read is refused with its reason and nothing is recorded.
 *
 * Pure: the form, its checks, the command block and the BFF's picker.
 */

import { MAX_REPORT_CHARS, reportContentType } from './pact-provider-contract';
import { tenantPath, type PactAction, type PactOption } from './pact-commands';
import { isPactSha } from './pact-verification';
import { MAX_TEXT, MAX_URL } from './pact-verify-run';

/** The proxy the dialog sends the report to. */
export const UPLOAD_PROXY = '/api/pact/verification/results/upload';

/** The report formats, as `format` and the CLI's `--format` name them. */
export const REPORT_FORMATS = [
  'auto',
  'pact-verifier-json',
  'junit',
  'schemathesis',
  'newman',
  'dredd',
] as const;

/** One report format. */
export type ReportFormat = (typeof REPORT_FORMATS)[number];

/** The Report format select, as it reads. */
export const FORMAT_LABELS: Record<ReportFormat, string> = {
  auto: 'Detect',
  'pact-verifier-json': 'Pact verifier JSON',
  junit: 'JUnit XML',
  schemathesis: 'Schemathesis',
  newman: 'Newman',
  dredd: 'Dredd',
};

/** The dialog's form. */
export interface UploadForm {
  consumer: string;
  sha: string;
  providerVersion: string;
  branch: string;
  buildUrl: string;
  tags: string;
  format: ReportFormat;
  verifier: string;
  verifierVersion: string;
  /** The chosen file: its name and text. */
  file: { name: string; text: string } | null;
}

/** An empty form. */
export const EMPTY_UPLOAD: UploadForm = {
  consumer: '',
  sha: '',
  providerVersion: '',
  branch: '',
  buildUrl: '',
  tags: '',
  format: 'auto',
  verifier: '',
  verifierVersion: '',
  file: null,
};

/** What the dialog expects the server to read a file as. */
export interface FormatGuess {
  /** The format, or `null` when the file is neither JSON nor XML. */
  format: Exclude<ReportFormat, 'auto'> | null;
  /** One sentence for the dialog: `Looks like a Dredd report (xunit XML).` or why it is unreadable. */
  sentence: string;
}

/**
 * Guess what the server's **Detect** will read a file as, the way it decides.
 *
 * @param name - The file name.
 * @param text - Its text.
 * @returns The format and a sentence, or why it cannot be a report.
 */
export function guessFormat(name: string, text: string): FormatGuess {
  const body = text.replace(/^﻿/, '').trimStart();
  if (!body) return { format: null, sentence: 'The file is empty: there is nothing to read.' };
  if (body.startsWith('<')) {
    if (/<testsuite\b[^>]*\bname\s*=\s*["']schemathesis["']/i.test(body)) {
      return { format: 'schemathesis', sentence: 'Looks like a Schemathesis report (JUnit XML).' };
    }
    if (/<testsuite\b[^>]*\bname\s*=\s*["']Dredd Tests["']/i.test(body)) {
      return { format: 'dredd', sentence: 'Looks like a Dredd report (xunit XML).' };
    }
    return { format: 'junit', sentence: 'Looks like JUnit XML: each test case is an interaction.' };
  }
  if (body.startsWith('{') || body.startsWith('[')) {
    const lower = name.toLowerCase();
    let document: unknown = undefined;
    try {
      document = JSON.parse(body);
    } catch {
      if (lower.endsWith('.ndjson') || lower.endsWith('.jsonl') || body.includes('\n')) {
        return /"Initialize"\s*:\s*\{[^}]*schemathesis_version/.test(body)
          ? { format: 'schemathesis', sentence: 'Looks like a Schemathesis report (NDJSON).' }
          : {
              format: null,
              sentence:
                'This is several JSON lines but not a Schemathesis report: it has no Initialize event.',
            };
      }
      return { format: null, sentence: 'The file starts like JSON but is not valid JSON.' };
    }
    const doc =
      document && typeof document === 'object' ? (document as Record<string, unknown>) : {};
    const run =
      doc.run && typeof doc.run === 'object' ? (doc.run as Record<string, unknown>) : null;
    if (run && Array.isArray(run.executions) && 'collection' in doc) {
      return { format: 'newman', sentence: 'Looks like a Newman report (JSON).' };
    }
    return {
      format: 'pact-verifier-json',
      sentence: 'Looks like Pact verifier JSON (pact_verifier_cli --json).',
    };
  }
  return { format: null, sentence: 'This is neither JSON nor XML, so no verifier wrote it.' };
}

/** One reason the form cannot be sent, and the field it is about. */
export interface UploadProblem {
  field: keyof UploadForm;
  message: string;
}

/** The tags, split on commas and spaces. */
export function uploadTags(form: UploadForm): string[] {
  return form.tags
    .split(/[\s,]+/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

/**
 * Why the form cannot be sent yet.
 *
 * @param form - The form.
 * @returns Every problem, one per field.
 */
export function uploadProblems(form: UploadForm): UploadProblem[] {
  const problems: UploadProblem[] = [];
  const add = (field: keyof UploadForm, message: string) => problems.push({ field, message });
  if (!form.consumer.trim()) add('consumer', 'Choose the consumer whose pact the report verified.');
  if (!form.sha.trim()) add('sha', 'Choose the pact version the report verified.');
  else if (!isPactSha(form.sha.trim()))
    add('sha', 'A pact version is the 64-character SHA-256 of the pact.');
  const version = form.providerVersion.trim();
  if (!version)
    add(
      'providerVersion',
      'Enter the provider version the verifier ran against (a commit SHA is best).',
    );
  else if (version.length > MAX_TEXT) add('providerVersion', `At most ${MAX_TEXT} characters.`);
  if (form.branch.trim().length > MAX_TEXT) add('branch', `At most ${MAX_TEXT} characters.`);
  const url = form.buildUrl.trim();
  if (url && (!/^https?:\/\/\S+$/i.test(url) || url.length > MAX_URL))
    add('buildUrl', 'The build URL must be an http(s) URL.');
  if (uploadTags(form).some((tag) => tag.length > MAX_TEXT))
    add('tags', `A tag is at most ${MAX_TEXT} characters.`);
  if (form.verifier.trim().length > MAX_TEXT) add('verifier', `At most ${MAX_TEXT} characters.`);
  if (form.verifierVersion.trim().length > MAX_TEXT)
    add('verifierVersion', `At most ${MAX_TEXT} characters.`);
  if (!form.file) add('file', 'Choose the report.');
  else if (form.file.text.length > MAX_REPORT_CHARS)
    add('file', 'The report is larger than 5 MB, the most a report can be.');
  else {
    const guess = guessFormat(form.file.name, form.file.text);
    if (guess.format === null)
      add('file', `${guess.sentence} The report is refused; nothing is recorded.`);
  }
  return problems;
}

/**
 * The body the dialog sends to {@link UPLOAD_PROXY}.
 *
 * @param provider - The provider's handle.
 * @param form - The form (checked).
 * @returns The JSON body; the proxy sends `report` to REST as the request body.
 */
export function uploadBody(provider: string, form: UploadForm): Record<string, unknown> {
  const body: Record<string, unknown> = {
    provider,
    consumer: form.consumer.trim(),
    pact_version_sha: form.sha.trim(),
    provider_version: form.providerVersion.trim(),
    format: form.format,
    report: form.file?.text ?? '',
  };
  const contentType = form.file ? reportContentType(form.file.name) : null;
  if (contentType) body.content_type = contentType;
  if (form.branch.trim()) body.branch = form.branch.trim();
  if (form.buildUrl.trim()) body.build_url = form.buildUrl.trim();
  if (uploadTags(form).length) body.tags = uploadTags(form);
  if (form.verifier.trim()) body.verifier = form.verifier.trim();
  if (form.verifierVersion.trim()) body.verifier_version = form.verifierVersion.trim();
  return body;
}

/** The query of `…/external-verification-results`, as REST names it. */
function restQuery(form: UploadForm): string {
  const query = new URLSearchParams();
  query.set('providerApplicationVersion', form.providerVersion.trim() || '$GIT_COMMIT');
  if (form.buildUrl.trim()) query.set('buildUrl', form.buildUrl.trim());
  if (form.branch.trim()) query.set('branch', form.branch.trim());
  for (const tag of uploadTags(form)) query.append('tag', tag);
  if (form.format !== 'auto') query.set('format', form.format);
  if (form.verifier.trim()) query.set('verifier', form.verifier.trim());
  if (form.verifierVersion.trim()) query.set('verifierVersion', form.verifierVersion.trim());
  return query.toString();
}

/**
 * The REST path of the upload, with its query.
 *
 * @param tenant - The workspace handle (`''` for the placeholder).
 * @param provider - The provider's handle.
 * @param form - The form.
 * @returns `/v1/tenants/{t}/pact-broker/pacts/provider/{p}/consumer/{c}/pact-version/{sha}/external-verification-results?…`.
 */
export function uploadRestPath(tenant: string, provider: string, form: UploadForm): string {
  const consumer = form.consumer.trim() || '{consumer}';
  const sha = form.sha.trim() || '{sha}';
  return tenantPath(
    tenant,
    `/pact-broker/pacts/provider/${encodeURIComponent(provider || '{provider}')}/consumer/${encodeURIComponent(consumer)}/pact-version/${encodeURIComponent(sha)}/external-verification-results?${restQuery(form)}`,
  );
}

/**
 * The dialog as `apiome pact publish-verification-results` (and REST), for **The same, from anywhere**.
 *
 * @param provider - The provider's display name or handle.
 * @param form - The form.
 * @param tenant - The workspace handle (`''` for the placeholder).
 * @returns The action.
 */
export function uploadCommandAction(
  provider: string,
  form: UploadForm,
  tenant: string,
): PactAction {
  const options: PactOption[] = [
    { flag: '--provider', value: provider || '<provider>' },
    { flag: '--consumer', value: form.consumer.trim() || '<consumer>' },
    { flag: '--pact-version', value: form.sha.trim() || '<sha>' },
    { flag: '--provider-app-version', value: form.providerVersion.trim() || '$GIT_COMMIT' },
    { flag: '--branch', value: form.branch.trim() },
    { flag: '--tag', value: uploadTags(form) },
    { flag: '--build-url', value: form.buildUrl.trim() },
    { flag: '--format', value: form.format === 'auto' ? '' : form.format },
    { flag: '--verifier', value: form.verifier.trim() },
    { flag: '--verifier-version', value: form.verifierVersion.trim() },
  ];
  return {
    verb: 'publish-verification-results',
    args: [{ value: form.file?.name || 'report.json' }],
    options,
    rest: {
      method: 'POST',
      path: uploadRestPath(tenant, provider, form),
      body: '<the report file>',
    },
  };
}

// --- the BFF ---------------------------------------------------------------------------------------

/** A checked upload: the REST path below `/v1/tenants/{slug}`, the report and its media type. */
export interface PickedUpload {
  path: string;
  report: string;
  contentType: string;
}

const TEXT_FIELDS = [
  'provider',
  'consumer',
  'pact_version_sha',
  'provider_version',
  'branch',
  'build_url',
  'verifier',
  'verifier_version',
] as const;
const KNOWN = new Set<string>([...TEXT_FIELDS, 'format', 'tags', 'report', 'content_type']);
const CONTENT_TYPES = new Set([
  'application/json',
  'application/xml',
  'application/x-ndjson',
  'text/plain',
  'text/xml',
]);
const HANDLE = /^[A-Za-z0-9][A-Za-z0-9._ -]{0,254}$/;

/**
 * Read the browser's upload and refuse, naming it, anything the dialog would not send.
 *
 * @param raw - The parsed JSON.
 * @returns The REST call to make, or the first reason it is refused.
 */
export function pickUpload(
  raw: unknown,
): { ok: true; upload: PickedUpload } | { ok: false; error: string } {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw))
    return { ok: false, error: 'The request must be a JSON object.' };
  const body = raw as Record<string, unknown>;
  const unknown = Object.keys(body).find((key) => !KNOWN.has(key));
  if (unknown) return { ok: false, error: `${unknown} is not a field of an upload.` };
  for (const name of TEXT_FIELDS) {
    const value = body[name];
    if (
      value !== undefined &&
      (typeof value !== 'string' || value.length > (name === 'build_url' ? MAX_URL : MAX_TEXT))
    ) {
      return {
        ok: false,
        error: `${name} must be text of at most ${name === 'build_url' ? MAX_URL : MAX_TEXT} characters.`,
      };
    }
  }
  const text = (name: (typeof TEXT_FIELDS)[number]) =>
    typeof body[name] === 'string' ? (body[name] as string).trim() : '';
  for (const name of ['provider', 'consumer', 'pact_version_sha', 'provider_version'] as const) {
    if (!text(name)) return { ok: false, error: `${name} is required.` };
  }
  if (!HANDLE.test(text('provider')) || !HANDLE.test(text('consumer')))
    return { ok: false, error: 'provider and consumer must be pacticipant names.' };
  if (!isPactSha(text('pact_version_sha')))
    return { ok: false, error: 'pact_version_sha must be the pact version (64 hex characters).' };
  const format = body.format === undefined ? 'auto' : body.format;
  if (typeof format !== 'string' || !(REPORT_FORMATS as readonly string[]).includes(format)) {
    return { ok: false, error: `format must be one of ${REPORT_FORMATS.join(', ')}.` };
  }
  const tags = body.tags === undefined ? [] : body.tags;
  if (
    !Array.isArray(tags) ||
    tags.length > 20 ||
    tags.some((tag) => typeof tag !== 'string' || !tag.trim() || tag.length > MAX_TEXT)
  ) {
    return { ok: false, error: 'tags must be at most 20 names.' };
  }
  if (typeof body.report !== 'string' || !body.report.trim())
    return { ok: false, error: 'report is required: the report’s text.' };
  if (body.report.length > MAX_REPORT_CHARS)
    return { ok: false, error: 'The report is larger than 5 MB, the most a report can be.' };
  const contentType =
    body.content_type === undefined ? 'application/octet-stream' : body.content_type;
  if (
    typeof contentType !== 'string' ||
    (contentType !== 'application/octet-stream' && !CONTENT_TYPES.has(contentType))
  ) {
    return { ok: false, error: 'content_type must be the media type of a report.' };
  }
  const form: UploadForm = {
    ...EMPTY_UPLOAD,
    consumer: text('consumer'),
    sha: text('pact_version_sha'),
    providerVersion: text('provider_version'),
    branch: text('branch'),
    buildUrl: text('build_url'),
    tags: (tags as string[]).join(','),
    format: format as ReportFormat,
    verifier: text('verifier'),
    verifierVersion: text('verifier_version'),
  };
  const path = uploadRestPath('', text('provider'), form).replace(
    /^\/v1\/tenants\/\{tenant\}\//,
    '',
  );
  return { ok: true, upload: { path, report: body.report, contentType } };
}

/** What the server read, from the stored result's `ingestion`. */
export interface UploadAnswer {
  success: boolean;
  format: string;
  interactions: number;
  notices: { pointer: string; reason: string }[];
  resultUrl: string | null;
}

/**
 * Read REST's answer to an upload.
 *
 * @param body - The stored result, with `ingestion`.
 * @returns What the dialog reports.
 */
export function readUploadAnswer(body: Record<string, unknown>): UploadAnswer {
  const ingestion =
    body.ingestion && typeof body.ingestion === 'object'
      ? (body.ingestion as Record<string, unknown>)
      : {};
  const links =
    body._links && typeof body._links === 'object' ? (body._links as Record<string, unknown>) : {};
  const self =
    links.self && typeof links.self === 'object' ? (links.self as Record<string, unknown>) : {};
  const notices = Array.isArray(ingestion.notices) ? ingestion.notices : [];
  return {
    success: body.success === true,
    format: typeof ingestion.format === 'string' ? ingestion.format : 'auto',
    interactions: typeof ingestion.interactions === 'number' ? ingestion.interactions : 0,
    notices: notices
      .filter((n): n is Record<string, unknown> => Boolean(n) && typeof n === 'object')
      .map((n) => ({ pointer: String(n.pointer ?? ''), reason: String(n.reason ?? '') })),
    resultUrl: typeof self.href === 'string' ? self.href : null,
  };
}

/**
 * The dialog's one-line verdict on a stored upload.
 *
 * @param answer - What the server read.
 * @returns E.g. `Recorded a failed result from a Dredd report: 1 interaction, 1 note.`
 */
export function uploadHeadline(answer: UploadAnswer): string {
  const label = FORMAT_LABELS[answer.format as ReportFormat] ?? answer.format;
  const verdict = answer.success ? 'a successful' : 'a failed';
  const interactions = `${answer.interactions} ${answer.interactions === 1 ? 'interaction' : 'interactions'}`;
  const notes = answer.notices.length
    ? `, ${answer.notices.length} ${answer.notices.length === 1 ? 'note' : 'notes'}`
    : '';
  return `Recorded ${verdict} result from a ${label} report: ${interactions}${notes}.`;
}
