/**
 * **Publish a provider contract** — the page's model (PFX-8.6, #7303).
 *
 * The page (`/ade/dashboard/pacts/provider-contracts/new`) is the screen for
 * `apiome pact publish-provider-contract`: a contract from a project version, an uploaded file, a
 * URL or — as a standing source (PFX-8.7, #7304) — a file of a repository published on every push;
 * whose version it is; and the evidence that the provider behaves as the contract says, as five
 * explicit choices labelled by strength. Every sentence the page shows is decided here, and so is
 * every request body, so the page, the BFF and the command block agree.
 *
 * - {@link detectContract} reads an uploaded document: its format pill (`OpenAPI 3.1`), its media
 *   type, or why it cannot be published (“Could not read this file: line 42, …”).
 * - {@link formProblems} lists what stops a publish, per field.
 * - {@link publishRequest} / {@link checkRequest} build the BFF bodies (the REST body plus the
 *   provider, the version and — for **Run it now** — the run).
 * - {@link providerContractCommandAction} is the form as `apiome pact publish-provider-contract`,
 *   and lists what the command cannot carry, with the reason.
 * - {@link readCheckAnswer}, {@link readPublishAnswer} and the sentence helpers read REST's answers.
 *
 * Pure: no React, no fetch.
 */

import { parse as parseYaml } from 'yaml';
import { isHttpUrl, MAX_FIELD_CHARS, MAX_TAGS, MAX_URL_CHARS, parseTags } from './pact-publish';
import { tenantPath, type PactAction, type PactOption, type PactUnsupported } from './pact-commands';
import { pathProblem, SOURCES_HAVE_NO_FLAG } from './pact-contract-sources';

/** The page. */
export const PROVIDER_CONTRACT_ROUTE = '/ade/dashboard/pacts/provider-contracts/new';

/** The largest document the page reads (REST's `APIOME_PACT_MAX_BYTES` default is 8 MiB). */
export const MAX_CONTRACT_CHARS = 8 * 1024 * 1024;

/** The largest evidence report the page reads (REST's `APIOME_PACT_EVIDENCE_MAX_BYTES` default). */
export const MAX_REPORT_CHARS = 5 * 1024 * 1024;

/** Where the contract comes from. `repository` is a standing source: nothing is published now. */
export type ContractSource = 'project' | 'upload' | 'url' | 'repository';

/** The five kinds of evidence, strongest first. */
export type EvidenceKind = 'run' | 'report' | 'reuse' | 'exit' | 'none';

/** How well a kind of evidence backs the contract. */
export type EvidenceStrength = 'Strong' | 'Weak' | 'None';

/** One evidence choice, as its option card reads. */
export interface EvidenceChoice {
  kind: EvidenceKind;
  title: string;
  description: string;
  strength: EvidenceStrength;
}

/** The evidence choices, in the order the page lists them. */
export const EVIDENCE_CHOICES: readonly EvidenceChoice[] = [
  {
    kind: 'run',
    title: 'Run it now against a provider',
    description: 'Apiome’s hosted verifier calls a running instance and checks every operation against the spec.',
    strength: 'Strong',
  },
  {
    kind: 'report',
    title: 'Attach a verifier’s report',
    description: 'JUnit XML (Schemathesis, Dredd, Newman or any JUnit writer), Newman JSON or Schemathesis NDJSON. Read per test, not just stored.',
    strength: 'Strong',
  },
  {
    kind: 'reuse',
    title: 'Reuse an Apiome contract-test run',
    description: 'A provider-verification report already recorded for this version.',
    strength: 'Strong',
  },
  {
    kind: 'exit',
    title: 'My pipeline vouches for it',
    description: 'Only the tool’s name, version and exit code are recorded.',
    strength: 'Weak',
  },
  {
    kind: 'none',
    title: 'None yet',
    description: 'Publish now, add evidence later. Verdicts read “unverified” and never unblock a deploy.',
    strength: 'None',
  },
];

/** The sentence under **None yet**: the existing rule, said where it applies. */
export const UNVERIFIED_RULE = 'Nothing is blocked by publishing unverified — and nothing is unblocked either.';

/** A file the page read. */
export interface PickedText {
  name: string;
  text: string;
}

/** The form. */
export interface ProviderContractForm {
  source: ContractSource;
  /** A project version: the project's handle and the version label. */
  project: string;
  version: string;
  /** **Do this on every publish**: each published version of the project becomes the contract (PFX-8.7). */
  followProject: boolean;
  /** Upload: the file. */
  file: PickedText | null;
  /** URL: the document's address. */
  url: string;
  /** Repository (a standing source): the registered repository, the file's path and the branch whose pushes publish it. */
  repositoryId: string;
  repositoryPath: string;
  repositoryBranch: string;
  /** Whose version this is. */
  provider: string;
  providerVersion: string;
  branch: string;
  /** Comma separated. */
  tags: string;
  buildUrl: string;
  /** Evidence. */
  evidence: EvidenceKind;
  /** Run it now: the verification target's handle. */
  target: string;
  /** Attach a report: the file. */
  report: PickedText | null;
  /** Reuse: the provider-verification report id. */
  reportId: string;
  /** Pipeline (and, optionally, an attached report): the tool, its version and its exit code. */
  verifier: string;
  verifierVersion: string;
  exitCode: string;
}

/** A form with nothing in it. */
export const EMPTY_FORM: ProviderContractForm = {
  source: 'project',
  project: '',
  version: '',
  followProject: false,
  file: null,
  url: '',
  repositoryId: '',
  repositoryPath: '',
  repositoryBranch: '',
  provider: '',
  providerVersion: '',
  branch: '',
  tags: '',
  buildUrl: '',
  evidence: 'none',
  target: '',
  report: null,
  reportId: '',
  verifier: '',
  verifierVersion: '',
  exitCode: '',
};

// --- reading a document --------------------------------------------------------------------------

/** What an uploaded document is. */
export interface DetectedContract {
  /** The format pill, e.g. `OpenAPI 3.1` or `AsyncAPI 3.0`; `null` when unreadable. */
  format: string | null;
  /** `oas` or `asyncapi`; `null` when unreadable. */
  contractType: 'oas' | 'asyncapi' | null;
  /** How it is sent: `application/json` or `application/yaml`. */
  contentType: 'application/json' | 'application/yaml';
  /** Why it cannot be published, or `null`. */
  problem: string | null;
}

/**
 * The `major.minor` of a version string, e.g. `3.1` for `3.1.0`.
 *
 * @param version - The declared version.
 * @returns The short form.
 */
function shortVersion(version: string): string {
  const [major, minor] = version.split('.');
  return minor === undefined ? major : `${major}.${minor}`;
}

/**
 * The sentence for a YAML parse error, e.g. `line 42, mapping values are not allowed here`.
 *
 * @param error - What `yaml` threw.
 * @returns The sentence.
 */
function yamlProblem(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  const first = raw.split('\n')[0].replace(/\s+at line \d+, column \d+:?$/, '').trim();
  const line = (error as { linePos?: { line: number }[] } | null)?.linePos?.[0]?.line;
  const text = first.charAt(0).toLowerCase() + first.slice(1);
  return line ? `line ${line}, ${text}` : text;
}

/**
 * Read an uploaded document the way REST will: JSON, else YAML; then OpenAPI 3 or AsyncAPI.
 *
 * @param text - The file's text.
 * @param name - Its name (`.json` is sent as JSON).
 * @returns The format pill, the media type, and the problem when it cannot be published.
 */
export function detectContract(text: string, name = ''): DetectedContract {
  const json = /\.json$/i.test(name) || /^\s*[{[]/.test(text);
  const contentType = json ? 'application/json' : 'application/yaml';
  const unreadable = (problem: string): DetectedContract => ({ format: null, contractType: null, contentType, problem });
  if (!text.trim()) return unreadable('The file is empty.');
  if (text.length > MAX_CONTRACT_CHARS) return unreadable('The file is larger than 8 MB, the most a provider contract can be.');
  let document: unknown;
  try {
    document = json ? JSON.parse(text) : parseYaml(text);
  } catch (error) {
    const reason = json ? (error instanceof Error ? error.message : 'it is not valid JSON') : yamlProblem(error);
    return unreadable(`Could not read this file: ${reason}.`);
  }
  if (!document || typeof document !== 'object' || Array.isArray(document)) {
    return unreadable('Could not read this file: it is not an OpenAPI or AsyncAPI document (no top-level object).');
  }
  const doc = document as Record<string, unknown>;
  if (typeof doc.openapi === 'string' && doc.openapi.startsWith('3')) {
    return { format: `OpenAPI ${shortVersion(doc.openapi)}`, contractType: 'oas', contentType, problem: null };
  }
  if (typeof doc.asyncapi === 'string' && /^[23]\./.test(doc.asyncapi)) {
    return { format: `AsyncAPI ${shortVersion(doc.asyncapi)}`, contractType: 'asyncapi', contentType, problem: null };
  }
  if (doc.swagger !== undefined) {
    return unreadable('This is Swagger 2.0. A provider contract is OpenAPI 3.x or AsyncAPI 2.x / 3.x — convert it first.');
  }
  if (typeof doc.openapi === 'string') {
    return unreadable(`OpenAPI ${doc.openapi} is not supported; a provider contract is OpenAPI 3.0, 3.1 or 3.2.`);
  }
  return unreadable('Could not read this file: it has neither an `openapi` nor an `asyncapi` field.');
}

/**
 * The media type of an evidence report, from its name — as `apiome pact` infers it.
 *
 * @param name - The file name.
 * @returns `application/xml`, `application/json`, `application/x-ndjson`, `text/plain`, or `null` (REST sniffs it).
 */
export function reportContentType(name: string): string | null {
  const lower = name.toLowerCase();
  if (lower.endsWith('.xml')) return 'application/xml';
  if (lower.endsWith('.ndjson') || lower.endsWith('.jsonl')) return 'application/x-ndjson';
  if (lower.endsWith('.json')) return 'application/json';
  if (lower.endsWith('.txt')) return 'text/plain';
  return null;
}

/**
 * UTF-8 text as base64.
 *
 * @param text - The text.
 * @returns Its base64.
 */
export function toBase64(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}

// --- checking the form ---------------------------------------------------------------------------

/** One reason the form cannot be sent, and the field it is about. */
export interface FormProblem {
  field: keyof ProviderContractForm;
  message: string;
}

/** The exit code, or `null` when it is empty; `NaN` when it is not a whole number. */
export function parsedExitCode(text: string): number | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  return /^-?\d{1,3}$/.test(trimmed) ? Number(trimmed) : Number.NaN;
}

/**
 * Every reason the form cannot be published (or compared), in the order of the page.
 *
 * @param form - The form.
 * @returns The problems; empty when it can be sent.
 */
export function formProblems(form: ProviderContractForm): FormProblem[] {
  const problems: FormProblem[] = [];
  const add = (field: keyof ProviderContractForm, message: string) => problems.push({ field, message });
  if (form.source === 'project') {
    if (!form.project.trim()) add('project', 'Choose the project whose version is the contract.');
    else if (!form.version.trim()) add('version', 'Choose the version to publish.');
  } else if (form.source === 'upload') {
    if (!form.file) add('file', 'Drop or browse for an OpenAPI or AsyncAPI document.');
    else {
      const detected = detectContract(form.file.text, form.file.name);
      if (detected.problem) add('file', detected.problem);
    }
  } else if (form.source === 'url') {
    const url = form.url.trim();
    if (!url) add('url', 'Give the URL of the specification.');
    else if (url.length > MAX_URL_CHARS || !isHttpUrl(url)) add('url', 'The specification URL must be an http(s) URL.');
  } else {
    if (!form.repositoryId) add('repositoryId', 'Choose the repository the file is in.');
    const path = pathProblem(form.repositoryPath);
    if (path) add('repositoryPath', path);
    const branch = form.repositoryBranch.trim();
    if (!branch) add('repositoryBranch', 'Give the branch whose pushes publish the file.');
    else if (branch.length > MAX_FIELD_CHARS) add('repositoryBranch', `Branch is longer than ${MAX_FIELD_CHARS} characters.`);
  }
  if (!form.provider.trim()) add('provider', 'Give the provider’s name.');
  else if (form.provider.trim().length > MAX_FIELD_CHARS) add('provider', `The provider’s name is longer than ${MAX_FIELD_CHARS} characters.`);
  // A repository source publishes nothing now: each push is a version (its commit), with no evidence.
  if (form.source === 'repository') return problems;
  const version = form.providerVersion.trim();
  if (!version) add('providerVersion', 'Give the provider version (a commit SHA is ideal).');
  else if (version.length > MAX_FIELD_CHARS) add('providerVersion', `The provider version is longer than ${MAX_FIELD_CHARS} characters.`);
  else if (version.includes('/')) add('providerVersion', 'A provider version cannot contain “/”.');
  if (form.branch.trim().length > MAX_FIELD_CHARS) add('branch', `Branch is longer than ${MAX_FIELD_CHARS} characters.`);
  const tags = parseTags(form.tags);
  if (tags.length > MAX_TAGS) add('tags', `At most ${MAX_TAGS} tags.`);
  else if (tags.some((tag) => tag.length > MAX_FIELD_CHARS)) add('tags', `A tag is longer than ${MAX_FIELD_CHARS} characters.`);
  const buildUrl = form.buildUrl.trim();
  if (buildUrl && (buildUrl.length > MAX_URL_CHARS || !isHttpUrl(buildUrl))) add('buildUrl', 'The build URL must be an http(s) URL.');

  const exitCode = parsedExitCode(form.exitCode);
  if (Number.isNaN(exitCode)) add('exitCode', 'The exit code is a whole number, 0 for success.');
  switch (form.evidence) {
    case 'run':
      if (form.source !== 'project') add('target', 'Run it now verifies a project version; choose A project version, or attach a report instead.');
      else if (!form.target.trim()) add('target', 'Choose the verification target to run against.');
      break;
    case 'report':
      if (!form.report) add('report', 'Drop or browse for the verifier’s report.');
      else if (!form.report.text.trim()) add('report', 'The report is empty.');
      else if (form.report.text.length > MAX_REPORT_CHARS) add('report', 'The report is larger than 5 MB, the most a report can be.');
      break;
    case 'reuse':
      if (!form.reportId.trim()) add('reportId', 'Choose the contract-test run to reuse.');
      break;
    case 'exit':
      if (!form.verifier.trim()) add('verifier', 'Name the tool that verified the provider (schemathesis, dredd, newman…).');
      if (exitCode === null) add('exitCode', 'Give the verifier’s exit code, 0 for success.');
      break;
    case 'none':
      break;
  }
  return problems;
}

// --- requests -------------------------------------------------------------------------------------

/** `<project>@<version>`, as `apiomeVersion` and `--apiome-version` take it. */
export function apiomeVersion(form: ProviderContractForm): string {
  return `${form.project.trim()}@${form.version.trim()}`;
}

/** The ECA version reference **Run it now** verifies, e.g. `project/billing-api/2.7.0`. */
export function versionRef(form: ProviderContractForm): string {
  return `project/${form.project.trim()}/${form.version.trim()}`;
}

/**
 * The `verificationResults` the form sends, or `undefined` for none (and for **Run it now**,
 * whose report id the BFF adds once the run has passed).
 *
 * @param form - The form (already valid).
 * @returns The object, as `apiome pact` builds it.
 */
export function verificationResults(form: ProviderContractForm): Record<string, unknown> | undefined {
  const exitCode = parsedExitCode(form.exitCode);
  const tool = {
    ...(form.verifier.trim() ? { verifier: form.verifier.trim() } : {}),
    ...(form.verifierVersion.trim() ? { verifierVersion: form.verifierVersion.trim() } : {}),
  };
  switch (form.evidence) {
    case 'report': {
      if (!form.report) return undefined;
      const type = reportContentType(form.report.name);
      return {
        // As the CLI: a report counts as success unless an exit code says otherwise; failures in it win.
        success: exitCode === null || Number.isNaN(exitCode) ? true : exitCode === 0,
        content: toBase64(form.report.text),
        ...(type ? { contentType: type } : {}),
        ...tool,
      };
    }
    case 'reuse':
      return { providerVerificationReportId: form.reportId.trim() };
    case 'exit':
      return { success: exitCode === 0, ...tool };
    default:
      return undefined;
  }
}

/**
 * The REST body of the publish (`PUT …/contracts/provider/{p}/version/{v}`), or of the check with
 * `contentUrl` in place of `content` for a URL.
 *
 * @param form - The form (already valid).
 * @param mode - `publish` sends the fetched content; `check` sends the URL for REST to read.
 * @param fetched - For a URL source: the base64 content a check read from it.
 * @returns The body.
 */
export function restBody(
  form: ProviderContractForm,
  mode: 'publish' | 'check',
  fetched: string | null = null,
): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (form.source === 'project') {
    body.apiomeVersion = apiomeVersion(form);
  } else if (form.source === 'upload' && form.file) {
    const detected = detectContract(form.file.text, form.file.name);
    body.content = toBase64(form.file.text);
    body.contentType = detected.contentType;
    if (detected.contractType) body.contractType = detected.contractType;
  } else if (form.source === 'url') {
    if (mode === 'check' || fetched === null) body.contentUrl = form.url.trim();
    else body.content = fetched;
  }
  if (form.branch.trim()) body.branch = form.branch.trim();
  if (mode === 'publish') {
    const tags = parseTags(form.tags);
    if (tags.length) body.tags = tags;
    if (form.buildUrl.trim()) body.buildUrl = form.buildUrl.trim();
  }
  const results = verificationResults(form);
  if (results) body.verificationResults = results;
  return body;
}

/** A BFF body: the provider, its version, the REST body, and for **Run it now** the run. */
export interface ContractRequestBody {
  provider: string;
  providerVersion: string;
  body: Record<string, unknown>;
  run?: { versionRef: string; target: string };
}

/** The BFF body of `/api/pact/provider-contracts/check`. */
export function checkRequest(form: ProviderContractForm): ContractRequestBody {
  return { provider: form.provider.trim(), providerVersion: form.providerVersion.trim(), body: restBody(form, 'check') };
}

/**
 * The BFF body of `/api/pact/provider-contracts`: the REST body, and for **Run it now** the run.
 *
 * @param form - The form (already valid).
 * @param fetched - For a URL source: the content the last check read from it (published as-is).
 * @returns The body.
 */
export function publishRequest(form: ProviderContractForm, fetched: string | null = null): ContractRequestBody {
  return {
    provider: form.provider.trim(),
    providerVersion: form.providerVersion.trim(),
    body: restBody(form, 'publish', fetched),
    ...(form.evidence === 'run' ? { run: { versionRef: versionRef(form), target: form.target.trim() } } : {}),
  };
}

// --- the command ---------------------------------------------------------------------------------

/** Why a URL source has no flag. */
export const URL_HAS_NO_FLAG =
  'apiome pact publish-provider-contract reads a local file; download it first (curl -fsSL -o openapi.yaml <url>) and pass the file.';

/** Why **Run it now** has no flag. */
export const RUN_HAS_NO_FLAG =
  'The command cites a finished run with --evidence-report <report id>; run the hosted verifier first, then publish.';

/**
 * The form as `apiome pact publish-provider-contract`, with what the command cannot carry.
 *
 * @param form - The form, as it stands (empty fields are left out of the command).
 * @param tenant - The workspace's handle, for the REST path.
 * @returns The action for `pactCommandSurfaces`.
 */
export function providerContractCommandAction(form: ProviderContractForm, tenant: string): PactAction {
  const unsupported: PactUnsupported[] = [];
  const args =
    form.source === 'upload' && form.file
      ? [{ value: form.file.name }]
      : form.source === 'url'
        ? [{ value: 'openapi.yaml' }]
        : form.source === 'repository'
          ? [{ value: form.repositoryPath.trim() || 'openapi.yaml' }]
          : [];
  // A repository source is what a pipeline would run on every push: the commit is the version.
  const pushed = form.source === 'repository';
  if (form.source === 'url' && form.url.trim()) {
    unsupported.push({ what: `The URL ${form.url.trim()}`, reason: URL_HAS_NO_FLAG, inRest: false });
  }
  if (form.source === 'repository') {
    unsupported.push({ what: 'Publishing a repository file on every push', reason: SOURCES_HAVE_NO_FLAG, inRest: false });
  } else if (form.source === 'project' && form.followProject) {
    unsupported.push({ what: 'Do this on every publish', reason: SOURCES_HAVE_NO_FLAG, inRest: false });
  }
  const exitCode = parsedExitCode(form.exitCode);
  const tool: PactOption[] = [
    { flag: '--verifier', value: form.verifier.trim() },
    { flag: '--verifier-version', value: form.verifierVersion.trim() },
  ];
  const evidence: PactOption[] = [];
  if (pushed) {
    // A push publishes without evidence (PUSH_EVIDENCE_NOTE).
  } else if (form.evidence === 'report') {
    evidence.push({ flag: '--evidence', value: form.report?.name ?? '<report>' });
    if (exitCode !== null && !Number.isNaN(exitCode)) evidence.push({ flag: '--verification-exit-code', value: String(exitCode) });
    evidence.push(...tool);
  } else if (form.evidence === 'reuse') {
    evidence.push({ flag: '--evidence-report', value: form.reportId.trim() || '<report id>' });
  } else if (form.evidence === 'exit') {
    evidence.push(...tool, { flag: '--verification-exit-code', value: exitCode === null || Number.isNaN(exitCode) ? '<exit code>' : String(exitCode) });
  } else if (form.evidence === 'run') {
    evidence.push({ flag: '--evidence-report', value: '<report id>' });
    unsupported.push({ what: 'Run it now', reason: RUN_HAS_NO_FLAG, inRest: false });
  }
  const options: PactOption[] = [
    { flag: '--provider', value: form.provider.trim() || '<provider>' },
    { flag: '--provider-app-version', value: pushed ? '<commit sha>' : form.providerVersion.trim() || '<version>' },
    ...(form.source === 'project' ? [{ flag: '--apiome-version', value: form.project.trim() ? apiomeVersion(form) : '<project>@<version>' }] : []),
    { flag: '--branch', value: pushed ? form.repositoryBranch.trim() : form.branch.trim() },
    { flag: '--tag', value: pushed ? [] : parseTags(form.tags) },
    { flag: '--build-url', value: pushed ? '' : form.buildUrl.trim() },
    ...evidence,
  ];
  const body = restBody(form, 'publish', form.source === 'url' ? '<base64 of the downloaded file>' : null);
  if ((form.source === 'upload' && form.file) || pushed) body.content = '<base64 of the file>';
  if (pushed) {
    delete body.verificationResults;
    if (form.repositoryBranch.trim()) body.branch = form.repositoryBranch.trim();
  }
  const results = body.verificationResults as Record<string, unknown> | undefined;
  if (results && typeof results.content === 'string') results.content = '<base64 of the report>';
  if (form.evidence === 'run' && !pushed) body.verificationResults = { providerVerificationReportId: '<report id>' };
  const path = `/pact-broker/contracts/provider/${encodeURIComponent(form.provider.trim() || '{provider}')}/version/${encodeURIComponent(form.providerVersion.trim() || '{version}')}`;
  return {
    verb: 'publish-provider-contract',
    args,
    options,
    rest: { method: 'PUT', path: tenantPath(tenant, path), body },
    unsupported,
  };
}

// --- answers ---------------------------------------------------------------------------------------

/** One failure of a consumer pact against the contract. */
export interface CheckFailure {
  interaction: string | null;
  operation: string | null;
  message: string;
}

/** One consumer pact, as the check (or a publish) compares it. */
export interface ConsumerVerdict {
  consumer: string;
  consumerVersion: string | null;
  sha: string;
  environments: string[];
  /** `true` compatible, `false` breaks, `null` not compared (`reason` says why). */
  success: boolean | null;
  verdict: string | null;
  interactions: number;
  failures: CheckFailure[];
  moreFailures: number;
  reason: string | null;
}

/** What the check says. */
export interface CheckAnswer {
  provider: { name: string; exists: boolean };
  providerVersion: string;
  format: string | null;
  operationCount: number | null;
  evidence: EvidenceSummary;
  existingSha: string | null;
  /** `false` when the version already published a different contract (a publish would be `409`). */
  publishable: boolean;
  results: ConsumerVerdict[];
  coverage: { operations: number; used: number; unused: string[]; unusedMore: number } | null;
  coverageReason: string | null;
  /** The base64 content read from a URL, published as-is. */
  fetched: { url: string; bytes: number; content: string } | null;
  /** Fields the check accepted and did not use, with the reason. */
  ignored: string[];
}

/** The evidence as REST read it. */
export interface EvidenceSummary {
  /** `verified`, `failed`, `inconclusive` or `missing`. */
  status: string;
  verified: boolean;
  tool: string | null;
  reasons: string[];
  summary: { tests: number; passed: number; failed: number } | null;
}

const str = (value: unknown): string | null => (typeof value === 'string' && value ? value : null);
const num = (value: unknown): number => (typeof value === 'number' && Number.isFinite(value) ? value : 0);
const obj = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

/**
 * Read REST's `selfVerification`.
 *
 * @param raw - The document.
 * @returns The summary.
 */
export function readEvidence(raw: unknown): EvidenceSummary {
  const doc = obj(raw);
  const summary = obj(doc.summary);
  return {
    status: str(doc.status) ?? 'missing',
    verified: doc.providerContractVerified === true || doc.status === 'verified',
    tool: str(doc.tool),
    reasons: list(doc.reasons).filter((r): r is string => typeof r === 'string'),
    summary: doc.summary ? { tests: num(summary.tests), passed: num(summary.passed), failed: num(summary.failed) } : null,
  };
}

/**
 * Read one consumer result of the check.
 *
 * @param raw - One entry of `results`.
 * @returns The verdict.
 */
function readVerdict(raw: unknown): ConsumerVerdict {
  const row = obj(raw);
  return {
    consumer: str(row.consumer) ?? 'A consumer',
    consumerVersion: str(row.consumerVersion),
    sha: str(row.sha) ?? '',
    environments: list(row.environments).filter((e): e is string => typeof e === 'string'),
    success: typeof row.success === 'boolean' ? row.success : null,
    verdict: str(row.verdict),
    interactions: num(row.interactions),
    failures: list(row.failures).map((f) => {
      const failure = obj(f);
      return {
        interaction: str(failure.interaction),
        operation: str(failure.operation),
        message: str(failure.message) ?? str(failure.code) ?? 'differs from the contract',
      };
    }),
    moreFailures: num(row.moreFailures),
    reason: str(row.reason),
  };
}

/**
 * Read the check's answer.
 *
 * @param raw - REST's document.
 * @returns The answer.
 */
export function readCheckAnswer(raw: unknown): CheckAnswer {
  const doc = obj(raw);
  const contract = obj(doc.contract);
  const coverage = doc.coverage ? obj(doc.coverage) : null;
  const fetched = doc.fetched ? obj(doc.fetched) : null;
  const summary = obj(doc.summary);
  const format =
    contract.contractType === 'asyncapi'
      ? str(contract.asyncapiVersion) && `AsyncAPI ${shortVersion(String(contract.asyncapiVersion))}`
      : str(contract.oasVersion) && `OpenAPI ${shortVersion(String(contract.oasVersion))}`;
  return {
    provider: { name: str(obj(doc.provider).name) ?? '', exists: obj(doc.provider).exists === true },
    providerVersion: str(doc.providerVersion) ?? '',
    format: format || null,
    operationCount: typeof contract.operationCount === 'number' ? contract.operationCount : null,
    evidence: readEvidence(doc.selfVerification),
    existingSha: str(obj(doc.existing).contentSha),
    publishable: summary.publishable !== false,
    results: list(doc.results).map(readVerdict),
    coverage: coverage
      ? {
          operations: num(coverage.operations),
          used: num(coverage.used),
          unused: list(coverage.unused).map((u) => `${str(obj(u).method) ?? ''} ${str(obj(u).path) ?? ''}`.trim()),
          unusedMore: num(coverage.unusedMore),
        }
      : null,
    coverageReason: str(doc.coverageReason),
    fetched: fetched && str(fetched.content) ? { url: str(fetched.url) ?? '', bytes: num(fetched.bytes), content: String(fetched.content) } : null,
    ignored: list(doc.ignored).map((i) => str(obj(i).field) ?? '').filter(Boolean),
  };
}

/** The aside's headline. */
export interface AsideHeadline {
  /** E.g. `2/3`; `null` when there is nothing to compare with. */
  ring: string | null;
  /** 0–100, for the ring. */
  percent: number;
  tone: 'ok' | 'warn' | 'danger' | 'neutral';
  title: string;
  detail: string;
}

/** The aside's sentence when no consumer has a pact yet (the mockup's *No consumers yet* state). */
export const NO_CONSUMERS = 'No pacts to compare with. The verdicts appear the moment a consumer publishes.';

/**
 * The aside's headline: how many consumers stay compatible.
 *
 * @param answer - The check.
 * @returns The ring and its sentences.
 */
export function asideHeadline(answer: CheckAnswer): AsideHeadline {
  const compared = answer.results.filter((r) => r.success !== null);
  if (!answer.results.length) {
    return { ring: null, percent: 0, tone: 'neutral', title: 'No consumers yet', detail: NO_CONSUMERS };
  }
  const consumers = new Set(compared.map((r) => r.consumer));
  const breaking = new Set(compared.filter((r) => r.success === false).map((r) => r.consumer));
  const fine = consumers.size - breaking.size;
  const percent = consumers.size ? Math.round((fine / consumers.size) * 100) : 0;
  const tone = breaking.size === 0 ? 'ok' : fine === 0 ? 'danger' : 'warn';
  const notCompared = answer.results.length - compared.length;
  return {
    ring: `${fine}/${consumers.size}`,
    percent,
    tone,
    title: `${fine} of ${consumers.size} consumer${consumers.size === 1 ? '' : 's'} stay${consumers.size === 1 && fine === 1 ? 's' : ''} compatible`,
    detail:
      'Compared with each consumer’s newest pact on its main branch, the latest on this branch and everything deployed.' +
      (notCompared ? ` ${notCompared} pact${notCompared === 1 ? ' was' : 's were'} not compared; each says why.` : ''),
  };
}

/**
 * The line under one consumer in the aside.
 *
 * @param row - The verdict.
 * @returns E.g. `GET /invoices/{id}: … Orders UI 3.3.2 is in production.` or `4 interactions covered.`
 */
export function verdictSentence(row: ConsumerVerdict): string {
  if (row.success === null) return row.reason ?? 'Not compared.';
  const where = row.environments.length
    ? ` ${row.consumer}${row.consumerVersion ? ` ${row.consumerVersion}` : ''} is in ${row.environments.join(', ')}.`
    : '';
  if (row.success) {
    const unverified = row.verdict === 'unverified' ? ' Unverified: the contract has no passing evidence.' : '';
    return `${row.interactions} interaction${row.interactions === 1 ? '' : 's'} covered.${unverified}${where}`;
  }
  const first = row.failures[0];
  const what = first ? `${first.operation ? `${first.operation}: ` : ''}${first.message}` : 'Differs from the contract';
  const more = row.failures.length - 1 + row.moreFailures;
  return `${what}${/[.!?]$/.test(what) ? '' : '.'}${more > 0 ? ` And ${more} more.` : ''}${where}`;
}

/** What **Nobody uses** says, or `null` when there is nothing to say. */
export function nobodyUsesSentence(answer: CheckAnswer): string | null {
  const coverage = answer.coverage;
  if (!coverage) return answer.coverageReason ? `Not worked out: ${answer.coverageReason}.` : null;
  const unused = coverage.operations - coverage.used;
  if (coverage.operations === 0) return 'The contract declares no operations.';
  if (unused === 0) return `Every one of the ${coverage.operations} operations appears in a pact.`;
  const examples = coverage.unused.slice(0, 2).join(' and ');
  return `${unused} of ${coverage.operations} operations appear in no pact — including ${examples}. Safe to change, as far as contracts know.`;
}

/**
 * The sentence for a version that already published a different contract.
 *
 * @param version - The provider version.
 * @returns The sentence the page and the dialog show.
 */
export function conflictSentence(version: string): string {
  return `${version} already has a different contract — use the new commit’s version.`;
}

/** The headline of the evidence, e.g. `Verified · schemathesis · 412 tests, 0 failed`. */
export function evidenceSentence(evidence: EvidenceSummary): string {
  const label: Record<string, string> = {
    verified: 'Verified',
    failed: 'Failed',
    inconclusive: 'Inconclusive',
    missing: 'Unverified — no evidence',
  };
  const parts = [label[evidence.status] ?? evidence.status];
  if (evidence.tool) parts.push(evidence.tool);
  if (evidence.summary) parts.push(`${evidence.summary.tests} tests, ${evidence.summary.failed} failed`);
  const sentence = parts.join(' · ');
  return evidence.verified || !evidence.reasons.length ? sentence : `${sentence}. ${evidence.reasons[0]}`;
}

// --- the publish -----------------------------------------------------------------------------------

/** One operation a failed **Run it now** found the provider does not honour. */
export interface FailingOperation {
  operation: string;
  outcome: string;
  detail: string | null;
}

/** What a publish (or a failed **Run it now**) came to. */
export type PublishAnswer =
  | {
      published: true;
      created: boolean;
      providerVersion: string;
      provider: string;
      evidence: EvidenceSummary;
      counts: { compatible: number; incompatible: number; unverified: number; notCompared: number };
      results: { consumer: string; consumerVersion: string | null; verdict: string | null; status: string; reason: string | null }[];
    }
  | {
      published: false;
      reportId: string | null;
      runId: string | null;
      outcome: string;
      failing: FailingOperation[];
      message: string;
    };

/**
 * Read the BFF's answer to a publish.
 *
 * @param raw - `{ published: true, created, contract }` or `{ published: false, run }`.
 * @returns The answer.
 */
export function readPublishAnswer(raw: unknown): PublishAnswer {
  const doc = obj(raw);
  if (doc.published === false) {
    const run = obj(doc.run);
    return {
      published: false,
      reportId: str(run.reportId),
      runId: str(run.runId),
      outcome: str(run.outcome) ?? 'errored',
      failing: list(run.failing).map((f) => ({
        operation: str(obj(f).operation) ?? '',
        outcome: str(obj(f).outcome) ?? 'failed',
        detail: str(obj(f).detail),
      })),
      message: str(run.message) ?? 'The provider did not pass the verification, so nothing was published.',
    };
  }
  const contract = obj(doc.contract);
  const comparisons = obj(contract.comparisons);
  const results = list(comparisons.results).map((r) => {
    const row = obj(r);
    return {
      consumer: str(row.consumer) ?? 'A consumer',
      consumerVersion: str(row.consumerVersion),
      verdict: str(row.verdict),
      status: str(row.status) ?? 'compared',
      reason: str(row.reason),
    };
  });
  const settled = results.filter((r) => r.status === 'compared' || r.status === 'already-compared');
  return {
    published: true,
    created: doc.created === true,
    providerVersion: str(contract.providerVersion) ?? '',
    provider: str(obj(contract.provider).name) ?? '',
    evidence: readEvidence(contract.selfVerification),
    counts: {
      compatible: settled.filter((r) => r.verdict === 'pass' || r.verdict === 'partial').length,
      incompatible: settled.filter((r) => r.verdict === 'fail').length,
      unverified: settled.filter((r) => r.verdict === 'unverified').length,
      notCompared: results.length - settled.length,
    },
    results,
  };
}

/**
 * The operations of a conformance report that the provider did not honour.
 *
 * @param report - REST's `ConformanceReport` (`operations[]` with `outcome` and `drift[]`).
 * @returns One entry per failed or errored operation, with its first drift.
 */
export function failingOperations(report: unknown): FailingOperation[] {
  return list(obj(report).operations)
    .map(obj)
    .filter((op) => op.outcome === 'failed' || op.outcome === 'errored')
    .map((op) => {
      const drift = obj(list(op.drift)[0]);
      return {
        operation: `${String(op.http_method ?? '').toUpperCase()} ${String(op.http_path ?? '')}`.trim(),
        outcome: String(op.outcome),
        detail: str(drift.message),
      };
    });
}

/** The dialog's notification line: bi-directional verdicts send nothing yet (PFX-2.3, #6941). */
export const NOTIFICATIONS_LINE =
  'No webhooks or commit statuses are sent for bi-directional verdicts yet; consumers see them in the matrix and can-i-deploy.';

/**
 * The dialog's verdict lines.
 *
 * @param answer - A published answer.
 * @returns The lines, each with its tone.
 */
export function publishedLines(answer: Extract<PublishAnswer, { published: true }>): { tone: 'ok' | 'danger' | 'warn' | 'neutral'; text: string }[] {
  const { compatible, incompatible, unverified, notCompared } = answer.counts;
  const lines: { tone: 'ok' | 'danger' | 'warn' | 'neutral'; text: string }[] = [];
  if (!answer.results.length) lines.push({ tone: 'neutral', text: NO_CONSUMERS });
  const plural = (n: number) => (n === 1 ? 'verdict' : 'verdicts');
  if (compatible) lines.push({ tone: 'ok', text: `${compatible} ${plural(compatible)} recorded as compatible` });
  if (incompatible) {
    const who = [...new Set(answer.results.filter((r) => r.verdict === 'fail').map((r) => r.consumer))].join(', ');
    lines.push({ tone: 'danger', text: `${incompatible} recorded as incompatible — ${who}` });
  }
  if (unverified) {
    lines.push({ tone: 'warn', text: `${unverified} recorded as unverified: they never unblock a deploy until the contract has passing evidence` });
  }
  if (notCompared) lines.push({ tone: 'warn', text: `${notCompared} not compared; see the provider’s comparisons for why` });
  return lines;
}

/** The can-i-deploy link for the published version. */
export function canIDeployHref(provider: string, version: string): string {
  return `/ade/dashboard/pacts/can-i-deploy?${new URLSearchParams({ pacticipant: provider, version }).toString()}`;
}
