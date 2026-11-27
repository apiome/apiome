/**
 * **Check it before it counts** on the Publish page — PFX-8.4 (#7301).
 *
 * The page compares each pact it holds with several provider versions at once —
 * the provider's main branch, what is deployed to an environment, a named version, a draft revision —
 * through `POST /v1/tenants/{t}/pact-broker/pacts/check`, which stores nothing. This module holds the
 * parts with no React:
 *
 * - **the proxy's body** ({@link pickCompareBody}): exactly `{ pact, against }`, anything else a 400;
 * - **the choices** ({@link compareChoices}, {@link parseSelector}): one chip per selector;
 * - **the answer** ({@link readCompareAnswer}, {@link pillLabel}, {@link orderedInteractions},
 *   {@link interactionNote}, {@link nothingToCompare}): what the aside shows per provider version
 *   and per interaction;
 * - **the drawer** ({@link differenceView}): what the pact needs beside what the spec declares,
 *   and where the spec change is;
 * - **the command** ({@link checkCommandAction}): the same check as `apiome pact check`.
 */

import { tenantPath, type PactAction } from './pact-commands';
import { MAX_PACT_CHARS } from './pact-publish';

/** The REST path below `/v1/tenants/{slug}/` (no leading slash, as `tenantUrl` joins it). */
export const CHECK_PROXY_PATH = 'pact-broker/pacts/check';

/** The most selectors one check sends (REST's limit). */
export const MAX_SELECTORS = 10;

/** The longest selector REST accepts. */
export const MAX_SELECTOR_CHARS = 300;

/** How many interactions a pill shows before **Show all**. */
export const VISIBLE_INTERACTIONS = 4;

/** What a selector is. */
export type SelectorKind = 'main' | 'deployed' | 'version' | 'draft';

/** One choice of **Compare with**. */
export interface CompareChoice {
  /** The selector REST reads, e.g. `deployed:production`. */
  selector: string;
  /** What the chip reads. */
  label: string;
  kind: SelectorKind;
}

/** Whether a value is a plain JSON object. */
function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

// --- the proxy's body ----------------------------------------------------------------------------

/** A checked body, or why it was refused. */
export type PickedCompare = { ok: true; body: { pact: Record<string, unknown>; against: string[] } } | { ok: false; error: string };

/**
 * Check the body the browser sent to `/api/pact/publish/compare`.
 *
 * @param raw - The parsed JSON body.
 * @returns `{ pact, against }` unchanged, or the first problem — an unknown field, a missing pact,
 *   no or too many selectors, a selector that is not text or is too long, a pact too large.
 */
export function pickCompareBody(raw: unknown): PickedCompare {
  if (!isObject(raw)) return { ok: false, error: 'The body must be a JSON object with pact and against.' };
  const unknown = Object.keys(raw).find((key) => key !== 'pact' && key !== 'against');
  if (unknown !== undefined) return { ok: false, error: `Unsupported field ${unknown}: send only pact and against.` };
  if (!isObject(raw.pact)) return { ok: false, error: 'pact must be the Pact document, as a JSON object.' };
  if (JSON.stringify(raw.pact).length > MAX_PACT_CHARS) return { ok: false, error: 'pact is too large to check.' };
  const against = raw.against;
  if (!Array.isArray(against) || against.length < 1 || against.length > MAX_SELECTORS) {
    return { ok: false, error: `against takes 1 to ${MAX_SELECTORS} provider versions.` };
  }
  if (against.some((item) => typeof item !== 'string' || !item.trim() || item.length > MAX_SELECTOR_CHARS)) {
    return { ok: false, error: `Each provider version in against is text of at most ${MAX_SELECTOR_CHARS} characters.` };
  }
  return { ok: true, body: { pact: raw.pact, against: against as string[] } };
}

// --- the choices ---------------------------------------------------------------------------------

/**
 * Read a selector typed into **+ Another version**.
 *
 * `2.7.0` alone means `version:2.7.0`; `main`, `deployed:<environment>`, `version:<number>` and
 * `draft:<revision>` are taken as typed.
 *
 * @param text - What was typed.
 * @returns The choice, or why it is not one.
 */
export function parseSelector(text: string): CompareChoice | { error: string } {
  const value = text.trim();
  if (!value) return { error: 'Type a version, or main, deployed:<environment> or draft:<revision>.' };
  if (value.length > MAX_SELECTOR_CHARS) return { error: `A provider version is at most ${MAX_SELECTOR_CHARS} characters.` };
  const colon = value.indexOf(':');
  const head = (colon === -1 ? value : value.slice(0, colon)).trim().toLowerCase();
  const rest = colon === -1 ? '' : value.slice(colon + 1).trim();
  if (head === 'main' && colon === -1) return { selector: 'main', label: 'Provider’s main', kind: 'main' };
  if (colon !== -1 && (head === 'deployed' || head === 'version' || head === 'draft')) {
    if (!rest) return { error: `${head}: needs a value after the colon.` };
    return choiceFor(head, rest);
  }
  if (colon !== -1) return { error: `${value} is not a provider version: use main, deployed:, version: or draft:.` };
  return choiceFor('version', value);
}

/** The chip of one selector kind and value. */
function choiceFor(kind: SelectorKind, value: string): CompareChoice {
  if (kind === 'deployed') return { selector: `deployed:${value}`, label: `Deployed to ${value}`, kind };
  if (kind === 'draft') return { selector: `draft:${value}`, label: `Draft · ${value}`, kind };
  if (kind === 'main') return { selector: 'main', label: 'Provider’s main', kind };
  return { selector: `version:${value}`, label: `Version ${value}`, kind };
}

/**
 * The chips **Compare with** offers before anything is typed.
 *
 * @param environments - The workspace's environment names.
 * @returns The provider's main branch, one chip per environment, and the provider project's latest
 *   draft.
 */
export function compareChoices(environments: string[]): CompareChoice[] {
  return [
    choiceFor('main', ''),
    ...environments.map((name) => choiceFor('deployed', name)),
    { selector: 'draft:latest', label: 'Draft · latest', kind: 'draft' },
  ];
}

/**
 * The chips switched on when the page opens: the provider's main branch, and the first production
 * environment (else the first environment).
 *
 * @param environments - The workspace's environments, each with whether it is production.
 * @returns The selectors.
 */
export function defaultSelectors(environments: Array<{ name: string; production: boolean }>): string[] {
  const deployed = environments.find((env) => env.production) ?? environments[0];
  return ['main', ...(deployed ? [`deployed:${deployed.name}`] : [])];
}

// --- the answer ----------------------------------------------------------------------------------

/** What an interaction is, against one provider version. */
export type Outcome = 'match' | 'differs' | 'not-in-spec';

/** A bounded excerpt REST sends for the drawer. */
export interface Excerpt {
  value?: unknown;
  truncated?: boolean;
  bytes?: number;
  pointer?: string;
}

/** One finding of an interaction. */
export interface CheckFinding {
  code: string;
  message: string;
  pactPointer?: string | null;
  oasPointer?: string | null;
}

/** One interaction, against one provider version. */
export interface CheckInteraction {
  index: number;
  description: string | null;
  method: string | null;
  path: string | null;
  status: number | null;
  providerStates: string[];
  outcome: Outcome;
  verdict: string | null;
  failures: CheckFinding[];
  expected?: Excerpt;
  declared?: Excerpt;
}

/** Where a provider contract came from, when it was rendered from Apiome. */
export interface CheckSource {
  projectId: string | null;
  projectSlug: string | null;
  versionLabel: string | null;
}

/** The check against one provider version. */
export interface CheckResult {
  selectors: string[];
  reasons: string[];
  providerVersion: string;
  draft: boolean;
  verdict: string | null;
  comparisonVerdict: string | null;
  success: boolean | null;
  selfVerification: string | null;
  source: CheckSource | null;
  counts: { match: number; differs: number; notInSpec: number };
  interactions: CheckInteraction[];
  error?: string;
}

/** A selector that named nothing, or a version over the limit. */
export interface CheckNote {
  selector: string;
  reason: string;
  providerVersion?: string;
}

/** The answer for one pact. */
export interface CompareAnswer {
  consumer: string | null;
  provider: string;
  registered: boolean;
  success: boolean;
  results: CheckResult[];
  unresolved: CheckNote[];
  skipped: CheckNote[];
}

/** Text, or `null`. */
function text(value: unknown): string | null {
  return typeof value === 'string' && value ? value : null;
}

/** An array of `value`, or `[]`. */
function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/** An excerpt, or `undefined`. */
function excerpt(value: unknown): Excerpt | undefined {
  if (!isObject(value)) return undefined;
  return {
    ...('value' in value ? { value: value.value } : {}),
    ...(value.truncated === true ? { truncated: true, bytes: typeof value.bytes === 'number' ? value.bytes : undefined } : {}),
    ...(text(value.pointer) ? { pointer: text(value.pointer) as string } : {}),
  };
}

/** One interaction row, read defensively. */
function readInteraction(raw: unknown): CheckInteraction | null {
  if (!isObject(raw)) return null;
  const outcome = raw.outcome === 'differs' || raw.outcome === 'not-in-spec' ? raw.outcome : 'match';
  return {
    index: typeof raw.index === 'number' ? raw.index : 0,
    description: text(raw.description),
    method: text(raw.method),
    path: text(raw.path),
    status: typeof raw.status === 'number' ? raw.status : null,
    providerStates: list(raw.providerStates).filter((state): state is string => typeof state === 'string'),
    outcome,
    verdict: text(raw.verdict),
    failures: list(raw.failures).flatMap((item) =>
      isObject(item) && text(item.code)
        ? [{ code: item.code as string, message: text(item.message) ?? '', pactPointer: text(item.pactPointer), oasPointer: text(item.oasPointer) }]
        : [],
    ),
    expected: excerpt(raw.expected),
    declared: excerpt(raw.declared),
  };
}

/** One provider version's result, read defensively. */
function readResult(raw: unknown): CheckResult | null {
  if (!isObject(raw) || !text(raw.providerVersion)) return null;
  const counts = isObject(raw.counts) ? raw.counts : {};
  const source = isObject(raw.source)
    ? { projectId: text(raw.source.projectId), projectSlug: text(raw.source.projectSlug), versionLabel: text(raw.source.versionLabel) }
    : null;
  const number = (value: unknown) => (typeof value === 'number' ? value : 0);
  return {
    selectors: list(raw.selectors).filter((item): item is string => typeof item === 'string'),
    reasons: list(raw.reasons).filter((item): item is string => typeof item === 'string'),
    providerVersion: raw.providerVersion as string,
    draft: raw.draft === true,
    verdict: text(raw.verdict),
    comparisonVerdict: text(raw.comparisonVerdict),
    success: typeof raw.success === 'boolean' ? raw.success : null,
    selfVerification: text(raw.selfVerification),
    source,
    counts: { match: number(counts.match), differs: number(counts.differs), notInSpec: number(counts.notInSpec) },
    interactions: list(raw.interactions).flatMap((item) => readInteraction(item) ?? []),
    ...(text(raw.error) ? { error: text(raw.error) as string } : {}),
  };
}

/** One note, read defensively. */
function readNote(raw: unknown): CheckNote | null {
  if (!isObject(raw) || !text(raw.selector)) return null;
  return {
    selector: raw.selector as string,
    reason: text(raw.reason) ?? 'nothing to compare with',
    ...(text(raw.providerVersion) ? { providerVersion: raw.providerVersion as string } : {}),
  };
}

/**
 * Read REST's answer for one pact.
 *
 * @param body - The `POST …/pacts/check` answer.
 * @returns The answer, or `null` when it is not one.
 */
export function readCompareAnswer(body: unknown): CompareAnswer | null {
  if (!isObject(body) || !isObject(body.provider)) return null;
  const summary = isObject(body.summary) ? body.summary : {};
  return {
    consumer: isObject(body.consumer) ? text(body.consumer.name) : null,
    provider: text(body.provider.name) ?? 'The provider',
    registered: body.provider.registered === true,
    success: summary.success === true,
    results: list(body.results).flatMap((item) => readResult(item) ?? []),
    unresolved: list(body.unresolved).flatMap((item) => readNote(item) ?? []),
    skipped: list(body.skipped).flatMap((item) => readNote(item) ?? []),
  };
}

/**
 * The pill of one provider version: `main · 2.7.0`, `production · 2.6.1`, `draft · 2.8.0-rc1`.
 *
 * @param result - The result.
 * @returns The label.
 */
export function pillLabel(result: CheckResult): string {
  const first = result.selectors[0] ?? '';
  const [kind, ...rest] = first.split(':');
  const value = rest.join(':');
  if (result.draft || kind === 'draft') return `draft · ${result.providerVersion}`;
  if (kind === 'main') return `main · ${result.providerVersion}`;
  if (kind === 'deployed' && value) return `${value} · ${result.providerVersion}`;
  return result.providerVersion;
}

/**
 * The count a pill shows: interactions that match, of all of them.
 *
 * @param result - The result.
 * @returns E.g. `4/6`.
 */
export function pillCount(result: CheckResult): string {
  return `${result.counts.match}/${result.interactions.length}`;
}

/** The order outcomes are listed in: what needs attention first. */
const OUTCOME_ORDER: Record<Outcome, number> = { differs: 0, 'not-in-spec': 1, match: 2 };

/**
 * The interactions, what does not match first, each group in pact order.
 *
 * @param rows - The interactions.
 * @returns A new, sorted list.
 */
export function orderedInteractions(rows: CheckInteraction[]): CheckInteraction[] {
  return [...rows].sort((a, b) => OUTCOME_ORDER[a.outcome] - OUTCOME_ORDER[b.outcome] || a.index - b.index);
}

/** What the badge of an outcome reads. */
export const OUTCOME_LABELS: Record<Outcome, string> = { match: 'Match', differs: 'Differs', 'not-in-spec': 'Not in spec' };

/**
 * The line under an interaction.
 *
 * @param row - The interaction.
 * @param providerVersion - The version it was compared with.
 * @returns For a match its provider states and status; for a difference the first failure; for an
 *   operation the spec does not declare, that it may be served undocumented.
 */
export function interactionNote(row: CheckInteraction, providerVersion: string): string {
  if (row.outcome === 'not-in-spec') return `Not in the spec of ${providerVersion}. The provider may serve it undocumented.`;
  if (row.outcome === 'differs') {
    const first = row.failures[0];
    const more = row.failures.length > 1 ? ` (+${row.failures.length - 1} more)` : '';
    return first ? `${first.message}${more}` : `${providerVersion} contradicts what the pact expects.`;
  }
  const states = row.providerStates.map((state) => `“${state}”`);
  return [...states, row.status !== null ? String(row.status) : null].filter(Boolean).join(' · ') || 'Matches the spec';
}

/**
 * The interaction's name: `POST /invoices`, or its description for a message.
 *
 * @param row - The interaction.
 * @returns The name.
 */
export function interactionName(row: CheckInteraction): string {
  return row.method && row.path ? `${row.method.toUpperCase()} ${row.path}` : row.description ?? `Interaction ${row.index + 1}`;
}

/**
 * What the aside reads when nothing could be compared.
 *
 * @param answer - The answer.
 * @returns The sentence, or `null` when at least one version was compared.
 */
export function nothingToCompare(answer: CompareAnswer): string | null {
  if (answer.results.length) return null;
  return `${answer.provider} has no contract or deployed version yet. Publish anyway — the verdict appears when the provider shows up.`;
}

// --- the drawer ----------------------------------------------------------------------------------

/** What the difference drawer shows. */
export interface DifferenceView {
  title: string;
  subtitle: string;
  expected: string;
  declared: string;
  declaredPointer: string | null;
  findings: CheckFinding[];
  /** The project's version history, where the spec change is, or `null` when unknown. */
  specChangeHref: string | null;
  specChangeLabel: string | null;
}

/** An excerpt as text: pretty JSON, or why it is not shown. */
function excerptText(part: Excerpt | undefined, what: string): string {
  if (!part) return `No ${what} was sent.`;
  if (part.truncated) return `Too large to show here (${part.bytes ?? 0} bytes).`;
  if (part.value === undefined || part.value === null) return `Nothing declared.`;
  return JSON.stringify(part.value, null, 2);
}

/**
 * The drawer for one interaction against one provider version.
 *
 * @param row - The interaction (not a match).
 * @param result - The provider version.
 * @param provider - The provider's name.
 * @returns The view.
 */
export function differenceView(row: CheckInteraction, result: CheckResult, provider: string): DifferenceView {
  const status = row.status !== null ? ` — ${row.status}` : '';
  const source = result.source;
  const href = source?.projectId ? `/ade/dashboard/versions?projectId=${encodeURIComponent(source.projectId)}` : null;
  return {
    title: `${interactionName(row)}${status}`,
    subtitle: `What the pact needs, beside what ${provider} ${result.draft ? 'draft ' : ''}${result.providerVersion} declares`,
    expected: excerptText(row.expected, 'expectation'),
    declared: row.outcome === 'not-in-spec' ? 'The spec declares no such operation.' : excerptText(row.declared, 'declaration'),
    declaredPointer: row.declared?.pointer ?? null,
    findings: row.failures,
    specChangeHref: href,
    specChangeLabel: href ? `Open ${source?.projectSlug ?? 'the project'} ${source?.versionLabel ?? ''}`.trim() : null,
  };
}

// --- the command ---------------------------------------------------------------------------------

/**
 * The check as `apiome pact check`, for **The same, from anywhere**.
 *
 * @param input - The chosen selectors and the tenant.
 * @returns The action. The REST body names the pact by placeholder: the page sends one request per
 *   pact, each with the whole document.
 */
export function checkCommandAction(input: { selectors: string[]; tenant: string }): PactAction {
  const against = input.selectors.length ? input.selectors : ['main'];
  return {
    verb: 'check',
    args: [{ value: 'pacts/' }],
    options: [{ flag: '--against', value: against }],
    rest: { method: 'POST', path: tenantPath(input.tenant, `/${CHECK_PROXY_PATH}`), body: { pact: '<the Pact document, as JSON>', against } },
  };
}
