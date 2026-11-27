/**
 * **Run a verification** — the model of `/ade/dashboard/pacts/verification/new` (PFX-8.8, #7305).
 *
 * The screen for `apiome pact verify`, built to `docs/mockups/contracts/verify.html`. Pure: no
 * fetch, no React. It holds
 *
 * - the form ({@link VerifyForm}) and its problems ({@link formProblems}) — including the one rule
 *   the page states before anything is sent: requests that change data are never sent to a target
 *   marked production ({@link MUTATING_PRODUCTION});
 * - the selector builder: each rule ({@link SelectorRule}) as a consumer-version selector
 *   ({@link ruleSelector}) and as a sentence ({@link ruleSentence}); the presets Recommended,
 *   Everything and Custom ({@link presetRules});
 * - the REST bodies of `…/verify` and `…/verify/preview` ({@link verifyBody}, {@link previewBody}),
 *   the same selection either way, so the preview lists exactly what the run verifies;
 * - **The same, from anywhere**: `apiome pact verify` with every option the form sets
 *   ({@link verifyCommandAction}), and for a self-run the native Pact verifier
 *   ({@link pactVerifierSurface}) — pointed at the broker, with the same selectors, publishing its
 *   results back;
 * - readers of the preview and run answers ({@link readPreview}, {@link readRun}).
 */

import { scrubSecrets, shellLines, shellQuote, type CommandSurface } from './command-block';
import { pactCommandSurfaces, tenantPath, type PactAction, type PactOption } from './pact-commands';
import type { ConsoleRunResponse, RunPact, SkippedPact } from './pact-verification';

// --- routes ----------------------------------------------------------------------------------------

/** The page. */
export const VERIFY_RUN_ROUTE = '/ade/dashboard/pacts/verification/new';

/** The preview proxy. */
export const VERIFY_PREVIEW_PROXY = '/api/pact/verification/preview';

/** The run proxy: a live run (PFX-8.9) the drawer follows — see `lib/pact-verify-live.ts`. */
export const VERIFY_RUN_PROXY = '/api/pact/verification/runs';

/**
 * The page for one provider.
 *
 * @param provider - The provider's handle.
 * @returns `/ade/dashboard/pacts/verification/new?provider=…`.
 */
export function verifyRunRoute(provider?: string | null): string {
  return provider ? `${VERIFY_RUN_ROUTE}?${new URLSearchParams({ provider }).toString()}` : VERIFY_RUN_ROUTE;
}

// --- limits and sentences --------------------------------------------------------------------------

/** The longest handle, version, branch or rule value the form sends (REST's own limit). */
export const MAX_TEXT = 255;

/** The longest URL the form sends. */
export const MAX_URL = 2000;

/** The most selector rules a run carries. */
export const MAX_RULES = 20;

/** The rule the page and REST both state; REST refuses with `pact-verify-mutating-production`. */
export const MUTATING_PRODUCTION = 'Requests that change data are never sent to a production target.';

/** Why the hosted commands cannot do a self-run. */
export const SELF_RUN_NO_HOSTED =
  'apiome pact verify runs Apiome’s hosted verifier, which needs a target Apiome can reach. For a provider only your pipeline can reach, run the Pact verifier there.';

// --- the form --------------------------------------------------------------------------------------

/** Who runs the verification. */
export type RunMode = 'hosted' | 'self';

/** The selector presets. */
export type SelectorPreset = 'recommended' | 'everything' | 'custom';

/** How provider states are set up. */
export type StateStrategy = 'registry' | 'setup-url' | 'none';

/** What a rule selects. */
export type RuleKind =
  | 'mainBranch'
  | 'deployedOrReleased'
  | 'deployed'
  | 'released'
  | 'matchingBranch'
  | 'branch'
  | 'tag'
  | 'latest';

/** Every rule kind, in the order **Add a rule** offers them. */
export const RULE_KINDS: readonly RuleKind[] = [
  'mainBranch',
  'deployedOrReleased',
  'matchingBranch',
  'branch',
  'tag',
  'deployed',
  'released',
  'latest',
];

/** What **Add a rule** calls each kind. */
export const RULE_KIND_LABELS: Record<RuleKind, string> = {
  mainBranch: 'Main branch',
  deployedOrReleased: 'Deployed or released',
  matchingBranch: 'Matching branch',
  branch: 'By branch',
  tag: 'By tag',
  deployed: 'Deployed',
  released: 'Released',
  latest: 'Latest',
};

/** The kinds that take an environment. */
const ENVIRONMENT_KINDS: readonly RuleKind[] = ['deployedOrReleased', 'deployed', 'released'];

/** One selector rule as the builder holds it. */
export interface SelectorRule {
  /** A stable key for the list. */
  id: string;
  kind: RuleKind;
  /** The branch or tag (`branch`, `tag`), or the environment (deployed / released kinds). */
  value: string;
  /** Narrow the rule to one consumer. */
  consumer: string;
}

/** The form. */
export interface VerifyForm {
  provider: string;
  providerVersion: string;
  branch: string;
  buildUrl: string;
  mode: RunMode;
  target: string;
  preset: SelectorPreset;
  rules: SelectorRule[];
  pending: boolean;
  wip: boolean;
  wipSince: string;
  states: StateStrategy;
  setupUrl: string;
  allowMutating: boolean;
  /** Skip pacts already verified for this provider version (**Run anyway** turns it off). */
  skipVerified: boolean;
  publish: boolean;
  /** Non-secret CI context, one `KEY=VALUE` per line. */
  context: string;
}

/**
 * A rule.
 *
 * @param kind - What it selects.
 * @param value - Its branch, tag or environment.
 * @param id - Its key (defaults to the kind and value).
 * @returns The rule.
 */
export function rule(kind: RuleKind, value = '', id?: string): SelectorRule {
  return { id: id ?? `${kind}:${value}`, kind, value, consumer: '' };
}

/**
 * The rules of a preset. Custom starts from the rules already there.
 *
 * - **Recommended** — the PactFlow advice: each consumer's main branch, everything deployed or
 *   released, and the consumer branch named like the provider's (feature branches built together).
 * - **Everything** — Recommended plus each consumer's latest pact, wherever it was published.
 *
 * @param preset - The preset.
 * @param current - The rules now (kept for Custom).
 * @returns The rules.
 */
export function presetRules(preset: SelectorPreset, current: SelectorRule[] = []): SelectorRule[] {
  const recommended = [rule('mainBranch'), rule('deployedOrReleased'), rule('matchingBranch')];
  if (preset === 'recommended') return recommended;
  if (preset === 'everything') return [...recommended, rule('latest')];
  return current.length ? current : recommended;
}

/** The form a fresh page starts with: Recommended, pending pacts on, the registry for states. */
export const EMPTY_FORM: VerifyForm = {
  provider: '',
  providerVersion: '',
  branch: '',
  buildUrl: '',
  mode: 'hosted',
  target: '',
  preset: 'recommended',
  rules: presetRules('recommended'),
  pending: true,
  wip: false,
  wipSince: '',
  states: 'registry',
  setupUrl: '',
  allowMutating: false,
  skipVerified: true,
  publish: true,
  context: '',
};

/**
 * The consumer-version selector a rule stands for.
 *
 * @param r - The rule.
 * @returns E.g. `{ mainBranch: true }`, `{ branch: 'feat', consumer: 'web' }`.
 */
export function ruleSelector(r: SelectorRule): Record<string, unknown> {
  const value = r.value.trim();
  const selector: Record<string, unknown> = {};
  if (r.kind === 'branch') selector.branch = value;
  else if (r.kind === 'tag') {
    selector.tag = value;
    selector.latest = true;
  } else selector[r.kind] = true;
  if (ENVIRONMENT_KINDS.includes(r.kind) && value) selector.environment = value;
  if (r.consumer.trim()) selector.consumer = r.consumer.trim();
  return selector;
}

/**
 * A rule as the page writes it.
 *
 * @param r - The rule.
 * @param branch - The provider branch being verified (named by **Matching branch**).
 * @returns E.g. `Each consumer’s latest pact on its main branch`.
 */
export function ruleSentence(r: SelectorRule, branch = ''): string {
  const value = r.value.trim();
  const where = value ? ` to ${value}` : ' anywhere';
  const base: Record<RuleKind, string> = {
    mainBranch: 'Each consumer’s latest pact on its main branch',
    deployedOrReleased: `Pacts of every consumer version deployed or released${where}`,
    deployed: `Pacts of every consumer version currently deployed${where}`,
    released: `Pacts of every consumer version released and supported${value ? ` in ${value}` : ''}`,
    matchingBranch: `Pacts on a consumer branch named like this one${branch.trim() ? ` — ${branch.trim()}` : ''}`,
    branch: `The latest pact on branch ${value || '…'}`,
    tag: `The latest pact tagged ${value || '…'}`,
    latest: 'Each consumer’s latest pact, wherever it was published',
  };
  return r.consumer.trim() ? `${base[r.kind]}, from ${r.consumer.trim()} only` : base[r.kind];
}

/**
 * Whether a rule takes a value, and what it is called.
 *
 * @param kind - The rule's kind.
 * @returns `{ label, required }`, or `null` when it takes none.
 */
export function ruleValueField(kind: RuleKind): { label: string; required: boolean } | null {
  if (kind === 'branch') return { label: 'Branch', required: true };
  if (kind === 'tag') return { label: 'Tag', required: true };
  if (ENVIRONMENT_KINDS.includes(kind)) return { label: 'Environment (optional)', required: false };
  return null;
}

/**
 * The selectors the form's rules stand for, duplicates verified once.
 *
 * @param form - The form.
 * @returns The selectors, in order, each once.
 */
export function formSelectors(form: Pick<VerifyForm, 'rules'>): Record<string, unknown>[] {
  const seen = new Set<string>();
  const out: Record<string, unknown>[] = [];
  for (const r of form.rules) {
    const selector = ruleSelector(r);
    const key = JSON.stringify(selector, Object.keys(selector).sort());
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(selector);
  }
  return out;
}

// --- problems --------------------------------------------------------------------------------------

/** The field a problem belongs to. */
export type FormField = keyof VerifyForm | `rule:${string}`;

/** One problem with the form. */
export interface FormProblem {
  field: FormField;
  message: string;
}

/** A context line: `KEY=VALUE`. */
const CONTEXT_LINE = /^([A-Za-z_][A-Za-z0-9_.-]*)=(.*)$/;

/**
 * The CI context lines as an object.
 *
 * @param text - One `KEY=VALUE` per line; blank lines are ignored.
 * @returns The context, or the first line that is not `KEY=VALUE`.
 */
export function parseContext(text: string): { ok: true; context: Record<string, string> } | { ok: false; line: string } {
  const context: Record<string, string> = {};
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    const match = CONTEXT_LINE.exec(line);
    if (!match) return { ok: false, line };
    context[match[1]] = match[2];
  }
  return { ok: true, context };
}

/**
 * Whether a setup URL is one REST accepts: a path on the target or an absolute http(s) URL.
 *
 * @param url - The URL.
 * @returns `true` when it is.
 */
export function isSetupUrl(url: string): boolean {
  const value = url.trim();
  if (value.startsWith('/')) return !value.startsWith('//');
  return /^https?:\/\/[^/\s]+/i.test(value);
}

/**
 * What is wrong with the form, in the order the page shows it.
 *
 * @param form - The form.
 * @param target - The chosen target's environment, when known (`production` blocks mutating).
 * @returns The problems; empty when the run can be sent.
 */
export function formProblems(form: VerifyForm, target?: { environment: string } | null): FormProblem[] {
  const problems: FormProblem[] = [];
  const need = (field: keyof VerifyForm, message: string) => problems.push({ field, message });
  if (!form.provider.trim()) need('provider', 'Choose the provider under test.');
  if (form.mode === 'hosted' && !form.providerVersion.trim()) need('providerVersion', 'Say which provider version is verified.');
  for (const [field, value] of [
    ['provider', form.provider],
    ['providerVersion', form.providerVersion],
    ['branch', form.branch],
  ] as const) {
    if (value.trim().length > MAX_TEXT) need(field, `At most ${MAX_TEXT} characters.`);
  }
  if (form.mode === 'hosted' && !form.target.trim()) need('target', 'Choose the target Apiome calls, or add one.');
  if (form.buildUrl.trim() && !/^https?:\/\/\S+$/i.test(form.buildUrl.trim())) need('buildUrl', 'An http(s) URL.');
  if (form.buildUrl.trim().length > MAX_URL) need('buildUrl', `At most ${MAX_URL} characters.`);
  if (form.rules.length > MAX_RULES) need('rules', `At most ${MAX_RULES} rules.`);
  for (const r of form.rules) {
    const field = ruleValueField(r.kind);
    if (field?.required && !r.value.trim()) problems.push({ field: `rule:${r.id}`, message: `Name the ${field.label.toLowerCase()}.` });
    if (r.value.trim().length > MAX_TEXT || r.consumer.trim().length > MAX_TEXT) {
      problems.push({ field: `rule:${r.id}`, message: `At most ${MAX_TEXT} characters.` });
    }
  }
  if (form.rules.some((r) => r.kind === 'matchingBranch') && !form.branch.trim()) {
    need('branch', 'Matching branch needs the provider’s branch.');
  }
  if (form.wip && !/^\d{4}-\d{2}-\d{2}$/.test(form.wipSince.trim())) need('wipSince', 'A date, YYYY-MM-DD.');
  if (form.states === 'setup-url') {
    if (!form.setupUrl.trim()) need('setupUrl', 'The provider’s setup endpoint.');
    else if (!isSetupUrl(form.setupUrl)) need('setupUrl', 'A path on the target (/_pact/provider-states) or an http(s) URL.');
    else if (form.setupUrl.trim().length > 2048) need('setupUrl', 'At most 2048 characters.');
  }
  if (form.mode === 'hosted' && form.allowMutating && target?.environment === 'production') {
    need('allowMutating', MUTATING_PRODUCTION);
  }
  const context = parseContext(form.context);
  if (!context.ok) need('context', `“${context.line}” is not KEY=VALUE.`);
  return problems;
}

// --- REST bodies -----------------------------------------------------------------------------------

/** The `selection` of the run — the body of `…/for-verification`. */
export function formSelection(form: VerifyForm): Record<string, unknown> {
  const selection: Record<string, unknown> = {};
  const selectors = formSelectors(form);
  if (selectors.length) selection.consumerVersionSelectors = selectors;
  if (form.pending) selection.includePendingStatus = true;
  if (form.wip && form.wipSince.trim()) selection.includeWipPactsSince = form.wipSince.trim();
  return selection;
}

/** The run's `verification` options. */
function formVerification(form: VerifyForm): Record<string, unknown> {
  const verification: Record<string, unknown> = {};
  if (form.allowMutating) verification.allow_mutating = true;
  if (form.states === 'none') verification.replay_without_state_setup = true;
  if (form.states === 'setup-url' && form.setupUrl.trim()) verification.provider_states_setup_url = form.setupUrl.trim();
  return verification;
}

/**
 * The body of `POST …/pact-verifier/pacts/provider/{provider}/verify`, with only what was set.
 *
 * @param form - The form (already free of problems).
 * @param options - `runAnyway` verifies pacts already verified for this version too.
 * @returns The body.
 */
export function verifyBody(form: VerifyForm, options: { runAnyway?: boolean } = {}): Record<string, unknown> {
  const body: Record<string, unknown> = {
    target_ref: form.target.trim(),
    provider_version: form.providerVersion.trim(),
    publish: form.publish,
  };
  if (form.branch.trim()) body.provider_branch = form.branch.trim();
  if (form.buildUrl.trim()) body.build_url = form.buildUrl.trim();
  const selection = formSelection(form);
  if (Object.keys(selection).length) body.selection = selection;
  const verification = formVerification(form);
  if (Object.keys(verification).length) body.verification = verification;
  if (form.skipVerified && !options.runAnyway) body.skip_already_verified = true;
  const context = parseContext(form.context);
  if (context.ok && Object.keys(context.context).length) body.context = context.context;
  return body;
}

/**
 * The body of `POST …/verify/preview`: the run's selection and options, target and version optional.
 *
 * @param form - The form.
 * @returns The body.
 */
export function previewBody(form: VerifyForm): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  if (form.mode === 'hosted' && form.target.trim()) body.target_ref = form.target.trim();
  if (form.providerVersion.trim()) body.provider_version = form.providerVersion.trim();
  if (form.branch.trim()) body.provider_branch = form.branch.trim();
  const selection = formSelection(form);
  if (Object.keys(selection).length) body.selection = selection;
  const verification = formVerification(form);
  if (Object.keys(verification).length) body.verification = verification;
  if (form.skipVerified) body.skip_already_verified = true;
  return body;
}

/**
 * The REST path of the run.
 *
 * @param tenant - The workspace handle (empty prints `{tenant}`).
 * @param provider - The provider's handle.
 * @returns E.g. `/v1/tenants/acme/pact-verifier/pacts/provider/billing/verify`.
 */
export function verifyPath(tenant: string, provider: string): string {
  return tenantPath(tenant, `/pact-verifier/pacts/provider/${encodeURIComponent(provider.trim() || '{provider}')}/verify`);
}

// --- the same, from anywhere -------------------------------------------------------------------------

/** A selector as one shell word of JSON. */
function selectorWord(selector: Record<string, unknown>): string {
  return JSON.stringify(selector);
}

/**
 * The form as `apiome pact verify` — every flag the form sets, the hosted run's REST request.
 *
 * @param form - The form.
 * @param tenant - The workspace handle.
 * @returns The action for `pactCommandSurfaces`.
 */
export function verifyCommandAction(form: VerifyForm, tenant: string): PactAction {
  const context = parseContext(form.context);
  const options: PactOption[] = [
    { flag: '--provider', value: form.provider.trim() || '<provider>' },
    { flag: '--provider-app-version', value: form.providerVersion.trim() || '$GIT_COMMIT' },
    { flag: '--target', value: form.target.trim() || '<target>' },
    { flag: '--branch', value: form.branch.trim() },
    { flag: '--build-url', value: form.buildUrl.trim() },
    { flag: '--consumer-version-selector', value: formSelectors(form).map(selectorWord) },
    { flag: '--enable-pending', value: form.pending },
    { flag: '--include-wip-pacts-since', value: form.wip ? form.wipSince.trim() : '' },
    { flag: '--allow-mutating', value: form.allowMutating },
    { flag: '--replay-without-state-setup', value: form.states === 'none' },
    { flag: '--provider-states-setup-url', value: form.states === 'setup-url' ? form.setupUrl.trim() : '' },
    { flag: '--skip-already-verified', value: form.skipVerified },
    { flag: '--no-publish-verification-results', value: !form.publish },
    { flag: '--context', value: context.ok ? Object.entries(context.context).map(([k, v]) => `${k}=${v}`) : [] },
  ];
  return {
    verb: 'verify',
    options,
    rest: { method: 'POST', path: verifyPath(tenant, form.provider), body: verifyBody(form) },
  };
}

/**
 * The self-run: the native Pact verifier (`pact-provider-verifier`) in the provider's pipeline,
 * fetching the same pacts from Apiome's broker and publishing its results back.
 *
 * @param form - The form.
 * @returns The surface, with what the native verifier does differently in its notes.
 */
export function pactVerifierSurface(form: VerifyForm): CommandSurface {
  const args = [
    `--provider ${shellQuote(form.provider.trim() || '<provider>')}`,
    '--provider-base-url http://localhost:8080',
    '--pact-broker-base-url "$PACT_BROKER_BASE_URL"',
    '--broker-token "$PACT_BROKER_TOKEN"',
    ...formSelectors(form).map((selector) => `--consumer-version-selector ${shellQuote(selectorWord(selector))}`),
    ...(form.pending ? ['--enable-pending'] : []),
    ...(form.wip && form.wipSince.trim() ? [`--include-wip-pacts-since ${shellQuote(form.wipSince.trim())}`] : []),
    ...(form.states === 'setup-url' && form.setupUrl.trim()
      ? [`--provider-states-setup-url ${shellQuote(form.setupUrl.trim())}`]
      : []),
    ...(form.publish ? ['--publish-verification-results'] : []),
    `--provider-app-version ${form.providerVersion.trim() ? shellQuote(form.providerVersion.trim()) : '"$GIT_COMMIT"'}`,
    ...(form.branch.trim() ? [`--provider-version-branch ${shellQuote(form.branch.trim())}`] : []),
    ...(form.buildUrl.trim() ? [`--build-url ${shellQuote(form.buildUrl.trim())}`] : []),
  ];
  const notes = ['Point --provider-base-url at the provider your pipeline starts. Reads the token from PACT_BROKER_TOKEN.'];
  if (!form.allowMutating) {
    notes.push('The Pact verifier sends every interaction, including POST, PUT, PATCH and DELETE; it has no switch to hold them back.');
  }
  if (form.skipVerified) notes.push('It verifies every selected pact, including those already verified for this version.');
  if (form.states === 'registry') notes.push('Apiome’s state handlers run only in the hosted verifier; give the Pact verifier your own --provider-states-setup-url.');
  if (form.states === 'none') notes.push('Without --provider-states-setup-url it replays as-is, like Replay without setup here.');
  if (parseContext(form.context).ok && form.context.trim()) notes.push('CI context is stored only by the hosted verifier.');
  return { id: 'pact-verifier', label: 'Pact verifier', text: scrubSecrets(shellLines('pact-provider-verifier', args)), notes };
}

/**
 * Every pill of the block, in order: apiome, Pact verifier, the pipeline step, REST. A self-run has
 * only the Pact verifier; the others say why.
 *
 * @param form - The form.
 * @param tenant - The workspace handle.
 * @returns The surfaces.
 */
export function verifySurfaces(form: VerifyForm, tenant: string): CommandSurface[] {
  const hosted = pactCommandSurfaces(verifyCommandAction(form, tenant));
  const verifier = pactVerifierSurface(form);
  const rest = hosted.filter((surface) => surface.id !== 'pact-cli');
  if (form.mode === 'self') {
    return [
      verifier,
      ...rest.map((surface) => ({ ...surface, text: null, unavailable: SELF_RUN_NO_HOSTED, notes: [] })),
    ];
  }
  return [rest[0], verifier, ...rest.slice(1)];
}

// --- answers ---------------------------------------------------------------------------------------

/** A pact's newest result, as the preview lists it. */
export interface PreviewResult {
  number: number;
  success: boolean;
  provider_version: string;
  verified_at: string | null;
}

/** One pact the run would choose. */
export interface PreviewPact {
  consumer: string;
  consumer_name: string;
  consumer_version: string;
  pact_version_sha: string;
  short_description: string;
  branches: string[];
  deployed_to: string[];
  released_in: string[];
  pending: boolean;
  wip: boolean;
  interactions: number;
  mutating_interactions: number;
  state_interactions: number;
  held_back: number;
  last_result: PreviewResult | null;
  already_verified: boolean;
  will_run: boolean;
}

/** What `…/verify/preview` answered. */
export interface VerifyPreview {
  provider: string;
  provider_name: string;
  provider_version: string | null;
  target: {
    slug: string;
    name: string;
    environment: string;
    production: boolean;
    allow_mutating_methods: boolean;
    enabled: boolean;
  } | null;
  rules: { index: number; selector: Record<string, unknown>; pacts: number }[];
  selected: number;
  will_run: number;
  skipped: number;
  interactions: number;
  pacts: PreviewPact[];
  truncated: boolean;
  states: { strategy: StateStrategy; used: number; handled: number; missing: string[]; registered: number };
  max_pacts_per_run: number;
  refusals: { code: string; message: string }[];
}

/** What `…/verify` answered: the console's answer shape, plus why the target was not reached. */
export interface VerifyRunAnswer extends ConsoleRunResponse {
  connection_error: string | null;
}

/** Read a list of records. */
function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object') : [];
}

/** Read text. */
function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

/** Read a count. */
function count(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/** Read a list of text. */
function texts(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

/**
 * Read the preview, tolerating missing fields.
 *
 * @param body - REST's JSON.
 * @returns The preview.
 */
export function readPreview(body: Record<string, unknown>): VerifyPreview {
  const target = body.target && typeof body.target === 'object' ? (body.target as Record<string, unknown>) : null;
  const states = body.states && typeof body.states === 'object' ? (body.states as Record<string, unknown>) : {};
  const strategy = text(states.strategy, 'registry');
  return {
    provider: text(body.provider),
    provider_name: text(body.provider_name, text(body.provider)),
    provider_version: typeof body.provider_version === 'string' ? body.provider_version : null,
    target: target
      ? {
          slug: text(target.slug),
          name: text(target.name, text(target.slug)),
          environment: text(target.environment),
          production: target.production === true,
          allow_mutating_methods: target.allow_mutating_methods === true,
          enabled: target.enabled !== false,
        }
      : null,
    rules: records(body.rules).map((r) => ({
      index: count(r.index),
      selector: r.selector && typeof r.selector === 'object' ? (r.selector as Record<string, unknown>) : {},
      pacts: count(r.pacts),
    })),
    selected: count(body.selected),
    will_run: count(body.will_run),
    skipped: count(body.skipped),
    interactions: count(body.interactions),
    pacts: records(body.pacts).map((p) => {
      const last = p.last_result && typeof p.last_result === 'object' ? (p.last_result as Record<string, unknown>) : null;
      return {
        consumer: text(p.consumer),
        consumer_name: text(p.consumer_name, text(p.consumer)),
        consumer_version: text(p.consumer_version),
        pact_version_sha: text(p.pact_version_sha),
        short_description: text(p.short_description),
        branches: texts(p.branches),
        deployed_to: texts(p.deployed_to),
        released_in: texts(p.released_in),
        pending: p.pending === true,
        wip: p.wip === true,
        interactions: count(p.interactions),
        mutating_interactions: count(p.mutating_interactions),
        state_interactions: count(p.state_interactions),
        held_back: count(p.held_back),
        last_result: last
          ? {
              number: count(last.number),
              success: last.success === true,
              provider_version: text(last.provider_version),
              verified_at: typeof last.verified_at === 'string' ? last.verified_at : null,
            }
          : null,
        already_verified: p.already_verified === true,
        will_run: p.will_run !== false,
      };
    }),
    truncated: body.truncated === true,
    states: {
      strategy: strategy === 'setup-url' || strategy === 'none' ? strategy : 'registry',
      used: count(states.used),
      handled: count(states.handled),
      missing: texts(states.missing),
      registered: count(states.registered),
    },
    max_pacts_per_run: count(body.max_pacts_per_run) || 25,
    refusals: records(body.refusals).map((r) => ({ code: text(r.code), message: text(r.message) })),
  };
}

/**
 * Read the run's answer.
 *
 * @param body - REST's JSON.
 * @returns The answer, in the console's shape so its outcome panel can show it.
 */
export function readRun(body: Record<string, unknown>): VerifyRunAnswer {
  const target = body.target && typeof body.target === 'object' ? (body.target as Record<string, unknown>) : {};
  return {
    provider: text(body.provider),
    provider_version: text(body.provider_version),
    provider_branch: typeof body.provider_branch === 'string' ? body.provider_branch : null,
    target: { slug: text(target.slug), base_url: text(target.base_url), environment: text(target.environment) },
    success: body.success === true,
    outcome: text(body.outcome),
    pacts: records(body.pacts) as unknown as RunPact[],
    trigger: 'hosted',
    skipped: records(body.skipped) as unknown as SkippedPact[],
    connection_error: typeof body.connection_error === 'string' ? body.connection_error : null,
  };
}

// --- what the page says ----------------------------------------------------------------------------

/**
 * The aside's headline.
 *
 * @param preview - The preview.
 * @returns E.g. `This run will verify 8 pacts · 61 interactions`.
 */
export function previewHeadline(preview: VerifyPreview): string {
  const pacts = `${preview.will_run} ${preview.will_run === 1 ? 'pact' : 'pacts'}`;
  const interactions = `${preview.interactions} ${preview.interactions === 1 ? 'interaction' : 'interactions'}`;
  return `This run will verify ${pacts} · ${interactions}`;
}

/**
 * The provider-state line under **Apiome’s state handlers**.
 *
 * @param preview - The preview (`null` before one came back).
 * @returns E.g. `9 of the 11 states these pacts use have a handler. 2 are missing — those interactions will be skipped and reported.`
 */
export function statesSentence(preview: VerifyPreview | null): string {
  if (!preview) return 'Each state a pact names is set up by the handler registered for it.';
  const { used, handled, missing } = preview.states;
  if (used === 0) return 'These pacts name no provider state.';
  if (missing.length === 0) return `All ${used} ${used === 1 ? 'state' : 'states'} these pacts use have a handler.`;
  return `${handled} of the ${used} states these pacts use have a handler. ${missing.length} ${
    missing.length === 1 ? 'is' : 'are'
  } missing — those interactions will be skipped and reported.`;
}

/**
 * Whether every selected pact is already verified for this version (the *Nothing to verify* state).
 *
 * @param preview - The preview.
 * @returns `true` when the run would verify nothing because of it.
 */
export function everythingVerified(preview: VerifyPreview | null): boolean {
  return Boolean(preview && preview.selected > 0 && preview.will_run === 0 && preview.skipped > 0);
}

/**
 * The run's outcome as one sentence.
 *
 * @param run - The answer.
 * @returns E.g. `Could not connect to billing.staging.acme.dev (timeout) — not a failed verification; nothing was published.`
 */
export function runHeadline(run: VerifyRunAnswer): string {
  if (run.connection_error) return `${run.connection_error} — not a failed verification; nothing was published.`;
  if (run.outcome === 'already-verified') return `Every selected pact is already verified for ${run.provider_version}.`;
  if (run.outcome === 'no-pacts') return 'The rules chose no pact: nothing was verified.';
  if (run.outcome === 'stopped') {
    return `Stopped: pacts finished before the stop kept their results; the pact cut short and those not reached published nothing.`;
  }
  if (run.outcome === 'passed') return `Verified ${run.provider} ${run.provider_version}: every pact passed.`;
  if (run.outcome === 'failed') return `Verified ${run.provider} ${run.provider_version}: a pact failed.`;
  return `Verified ${run.provider} ${run.provider_version}: incomplete — something could not be replayed, nothing failed.`;
}

// --- targets ---------------------------------------------------------------------------------------

/** A verification target, as the Target select lists it. */
export interface VerifyTarget {
  slug: string;
  name: string;
  baseUrl: string;
  environment: string;
  enabled: boolean;
  /** How the run signs in: `none`, or the reference kind and name (`secret`, `billing-staging-token`). */
  authKind: string;
  authRef: string | null;
}

/**
 * Read `GET /api/verification-targets`.
 *
 * @param body - REST's JSON (`{ targets }`).
 * @returns The targets, enabled ones first.
 */
export function readTargets(body: unknown): VerifyTarget[] {
  const rows = body && typeof body === 'object' ? (body as Record<string, unknown>).targets : null;
  return records(rows)
    .map((row) => {
      const auth = row.auth && typeof row.auth === 'object' ? (row.auth as Record<string, unknown>) : {};
      return {
        slug: text(row.slug),
        name: text(row.name, text(row.slug)),
        baseUrl: text(row.base_url),
        environment: text(row.environment),
        enabled: row.enabled !== false,
        authKind: text(auth.kind, 'none'),
        authRef: typeof auth.ref === 'string' && auth.ref ? auth.ref : null,
      };
    })
    .filter((target) => target.slug)
    .sort((a, b) => Number(b.enabled) - Number(a.enabled));
}

/** What each credential kind is called on the page. */
const AUTH_KIND_LABELS: Record<string, string> = {
  secret: 'Secret',
  env: 'Environment variable',
  stored: 'Stored credential',
};

/**
 * How a target signs in, as **Sign in with** reads it.
 *
 * @param target - The target.
 * @returns E.g. `Secret · billing-staging-token`, or `None`.
 */
export function targetSignIn(target: Pick<VerifyTarget, 'authKind' | 'authRef'>): string {
  if (target.authKind === 'none' || !target.authKind) return 'None';
  const label = AUTH_KIND_LABELS[target.authKind] ?? target.authKind;
  return target.authKind === 'stored' || !target.authRef ? label : `${label} · ${target.authRef}`;
}

/**
 * How a target is listed: `staging — https://billing.staging.acme.dev`, marked when production.
 *
 * @param target - The target.
 * @returns The option text.
 */
export function targetLabel(target: VerifyTarget): string {
  const production = target.environment === 'production' ? ' (production)' : '';
  const off = target.enabled ? '' : ' — turned off';
  return `${target.name}${production} — ${target.baseUrl || target.slug}${off}`;
}

/** The **Add a target** dialog. */
export interface NewTargetForm {
  name: string;
  baseUrl: string;
  production: boolean;
  /** A workspace secret's name sent as a bearer token; empty signs in with nothing. */
  secret: string;
}

/** An empty **Add a target** dialog. */
export const EMPTY_TARGET: NewTargetForm = { name: '', baseUrl: '', production: false, secret: '' };

/**
 * A handle for a new target, from its name.
 *
 * @param name - The name.
 * @returns E.g. `billing-staging`.
 */
export function targetSlug(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 63);
}

/**
 * What is wrong with the **Add a target** dialog.
 *
 * @param form - The dialog.
 * @returns One message per problem.
 */
export function newTargetProblems(form: NewTargetForm): string[] {
  const problems: string[] = [];
  if (!targetSlug(form.name)) problems.push('Name the target.');
  if (!/^https?:\/\/[^/\s]+/i.test(form.baseUrl.trim())) problems.push('The base URL is an http(s) URL.');
  if (form.secret.trim() && !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(form.secret.trim())) {
    problems.push('A secret is named with letters, digits, dots, dashes and underscores.');
  }
  return problems;
}

/**
 * The body of `POST /api/verification-targets` (ECA-1.2) for the dialog.
 *
 * A production target is created read-only (its policy allows no mutating method), and the run
 * refuses mutating requests to it whatever its policy says.
 *
 * @param form - The dialog (already free of problems).
 * @returns The body.
 */
export function newTargetBody(form: NewTargetForm): Record<string, unknown> {
  const secret = form.secret.trim();
  return {
    slug: targetSlug(form.name),
    name: form.name.trim(),
    environment: form.production ? 'production' : 'staging',
    base_url: form.baseUrl.trim(),
    auth: secret ? { kind: 'secret', scheme: 'bearer', ref: secret } : { kind: 'none' },
    policy: { allow_mutating_methods: !form.production },
  };
}
