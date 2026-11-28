/**
 * Contracts **Settings → Clean-up** — PFX-8.14 (#7311): the model behind the tab, its proxies and
 * its **The same, from anywhere** block.
 *
 * The rules are apiome-rest's (`/v1/tenants/{t}/pact-retention/policy`, `app.pact_retention_policy`):
 * every version deployed or released anywhere is always kept; then, optionally, the latest N
 * versions of each main branch, the latest N of every other branch (for D days), and anything with
 * a listed tag. The nightly clean-up applies them after 02:00 UTC when it is on; deleted items stay
 * restorable for the restore window. The preview is planned exactly as the nightly run plans.
 *
 * Nothing here talks to the network: the page calls the `/api/pact/retention/*` proxies through
 * `retentionApi.ts`, and the proxies check bodies with {@link checkRulesBody}.
 */

import { tenantPath, type PactAction, type PactOption } from './pact-commands';

/** The page. */
export const SETTINGS_ROUTE = '/ade/dashboard/pacts/settings';
/** What the settings page header says, on every tab. */
export const SETTINGS_TITLE = 'Contracts settings';
export const SETTINGS_DESCRIPTION =
  'How long contract history is kept and when it is cleaned up, and when Apiome verifies pacts on its own.';
/** The page's Verification tab (PFX-6.2's verification settings). */
export const VERIFICATION_TAB_ROUTE = `${SETTINGS_ROUTE}?tab=verification`;

/** REST paths below `/v1/tenants/{slug}` the proxies forward to. */
export const POLICY_PROXY_PATH = 'pact-retention/policy';
export const PREVIEW_PROXY_PATH = 'pact-retention/policy/preview';
export const DELETED_PROXY_PATH = 'pact-retention/deleted';

/** Rows per Recently deleted page. */
export const DELETED_PAGE_SIZE = 25;

/** The restore windows the tab offers (the saved one is offered too when it is another). */
export const RESTORE_WINDOW_CHOICES = [7, 30, 90] as const;

/** The bounds REST enforces, mirrored so the form says why before saving. */
export const RULE_BOUNDS = {
  keep_main_branch_latest: [1, 1000],
  keep_other_branch_latest: [1, 1000],
  keep_other_branch_days: [1, 3650],
  restore_window_days: [1, 365],
} as const;

/** The most tags a rule set keeps by. */
export const MAX_KEEP_TAGS = 50;

/** The sentence a rule set that would remove a deployed version is refused with. */
export const KEEPS_IN_USE = 'Deployed and released versions are always kept.';

/** The rules REST stores (`PUT …/pact-retention/policy`). */
export interface RetentionRules {
  keep_main_branch_latest: number | null;
  keep_other_branch_latest: number | null;
  keep_other_branch_days: number | null;
  keep_tags: string[];
  nightly_enabled: boolean;
  restore_window_days: number;
}

/** The fields of {@link RetentionRules}, in the order REST documents them. */
export const RULE_FIELDS: ReadonlyArray<keyof RetentionRules> = [
  'keep_main_branch_latest',
  'keep_other_branch_latest',
  'keep_other_branch_days',
  'keep_tags',
  'nightly_enabled',
  'restore_window_days',
];

/** What the last nightly run did. */
export interface RetentionLastRun {
  at: string;
  deleted?: number | null;
  remaining?: number | null;
  error?: string | null;
}

/** `GET …/pact-retention/policy`. */
export interface RetentionPolicy extends RetentionRules {
  keep_deployed_or_released: boolean;
  configured: boolean;
  updated_at?: string | null;
  updated_by?: string | null;
  last_run?: RetentionLastRun | null;
  next_run_at?: string | null;
  can_edit: boolean;
}

/** One version a plan deletes. */
export interface PlannedDeletion {
  number: string;
  created_at?: string | null;
  branches: string[];
  pacts: number;
  results: number;
}

/** One pacticipant's part of a plan. */
export interface PacticipantPlan {
  slug: string;
  name: string;
  evaluated: number;
  kept: number;
  deleted: number;
  remaining: number;
  deletions: PlannedDeletion[];
}

/** The plan inside a preview. */
export interface RetentionPlan {
  evaluated: number;
  kept: number;
  deleted: number;
  remaining: number;
  pacts: number;
  results: number;
  matched_by: Record<string, number>;
  grace_days: number;
  pacticipants: PacticipantPlan[];
}

/** `POST …/pact-retention/policy/preview`. */
export interface RetentionPreview {
  draft: boolean;
  nightly_enabled: boolean;
  next_run_at?: string | null;
  plan: RetentionPlan;
}

/** One Recently deleted row. */
export interface DeletedItem {
  kind: 'pacticipant' | 'version';
  id: string;
  pacticipant_id: string;
  pacticipant_slug: string;
  pacticipant_name: string;
  number?: string | null;
  deleted_at: string;
  deleted_by?: string | null;
  cause: string;
  reason?: string | null;
  purge_after: string;
  versions: number;
  pacts: number;
  results: number;
}

/** `GET …/pact-retention/deleted`. */
export interface DeletedPage {
  items: DeletedItem[];
  count: number;
  has_more: boolean;
  next_cursor?: string | null;
  restore_window_days: number;
  can_restore: boolean;
}

/** The tab's form: each optional rule on or off, its numbers as typed. */
export interface CleanupForm {
  mainOn: boolean;
  mainLatest: string;
  otherOn: boolean;
  otherLatest: string;
  /** Empty: however old. */
  otherDays: string;
  tagsOn: boolean;
  /** Comma-separated. */
  tags: string;
  nightly: boolean;
  restoreDays: string;
}

/** The optional rules, in the order the tab lists them. */
export const OPTIONAL_RULES = ['main', 'other', 'tags'] as const;
export type OptionalRule = (typeof OPTIONAL_RULES)[number];

/** How **Add a rule** names each optional rule. */
export const RULE_LABELS: Record<OptionalRule, string> = {
  main: 'The latest versions of each main branch',
  other: 'The latest versions of every other branch',
  tags: 'Versions with a tag',
};

/** The `matched_by` key of each rule (REST's `KEEP_REASONS`). */
export const MATCH_KEYS: Record<OptionalRule | 'deployed', string> = {
  deployed: 'deployed_or_released',
  main: 'latest_per_main_branch',
  other: 'latest_per_other_branch',
  tags: 'tagged',
};

/**
 * The form for saved rules.
 *
 * @param rules - The saved rules (or the defaults).
 * @returns The form; a rule that is off keeps a sensible number to start from.
 */
export function formOf(rules: RetentionRules): CleanupForm {
  return {
    mainOn: rules.keep_main_branch_latest !== null,
    mainLatest: String(rules.keep_main_branch_latest ?? 5),
    otherOn: rules.keep_other_branch_latest !== null,
    otherLatest: String(rules.keep_other_branch_latest ?? 1),
    otherDays: rules.keep_other_branch_days === null ? '' : String(rules.keep_other_branch_days),
    tagsOn: rules.keep_tags.length > 0,
    tags: rules.keep_tags.join(', '),
    nightly: rules.nightly_enabled,
    restoreDays: String(rules.restore_window_days),
  };
}

/**
 * A whole number within bounds, or why not.
 *
 * @param text - As typed.
 * @param label - How the form names it.
 * @param bounds - `[min, max]`.
 * @returns The number, or the problem.
 */
function wholeNumber(text: string, label: string, bounds: readonly [number, number]): number | { error: string } {
  const [min, max] = bounds;
  const value = Number(text.trim());
  if (!/^\d+$/.test(text.trim()) || value < min || value > max) {
    return { error: `${label} must be a whole number from ${min} to ${max}.` };
  }
  return value;
}

/**
 * The tags of a comma-separated list, or why they cannot be kept by.
 *
 * @param text - As typed.
 * @returns The tags (in order), or the problem — a repeated tag is refused, never merged.
 */
export function parseTags(text: string): string[] | { error: string } {
  const tags = text
    .split(',')
    .map((tag) => tag.trim())
    .filter((tag) => tag !== '');
  if (tags.length === 0) return { error: 'Name at least one tag, or remove the tag rule.' };
  if (tags.length > MAX_KEEP_TAGS) return { error: `Keep by at most ${MAX_KEEP_TAGS} tags.` };
  const repeated = tags.filter((tag, index) => tags.indexOf(tag) !== index);
  if (repeated.length > 0) return { error: `The tag ${repeated[0]} is listed more than once.` };
  const long = tags.find((tag) => tag.length > 255);
  if (long) return { error: 'A tag is at most 255 characters.' };
  return tags;
}

/**
 * The rules to save (or preview), or why the form cannot be.
 *
 * @param form - The form.
 * @returns The rules, or the first problem.
 */
export function rulesOf(form: CleanupForm): { rules: RetentionRules } | { error: string } {
  const rules: RetentionRules = {
    keep_main_branch_latest: null,
    keep_other_branch_latest: null,
    keep_other_branch_days: null,
    keep_tags: [],
    nightly_enabled: form.nightly,
    restore_window_days: 30,
  };
  if (form.mainOn) {
    const value = wholeNumber(form.mainLatest, 'The main-branch count', RULE_BOUNDS.keep_main_branch_latest);
    if (typeof value !== 'number') return value;
    rules.keep_main_branch_latest = value;
  }
  if (form.otherOn) {
    const value = wholeNumber(form.otherLatest, 'The other-branch count', RULE_BOUNDS.keep_other_branch_latest);
    if (typeof value !== 'number') return value;
    rules.keep_other_branch_latest = value;
    if (form.otherDays.trim()) {
      const days = wholeNumber(form.otherDays, 'The other-branch days', RULE_BOUNDS.keep_other_branch_days);
      if (typeof days !== 'number') return days;
      rules.keep_other_branch_days = days;
    }
  }
  if (form.tagsOn) {
    const tags = parseTags(form.tags);
    if (!Array.isArray(tags)) return tags;
    rules.keep_tags = tags;
  }
  const window = wholeNumber(form.restoreDays, 'The restore window', RULE_BOUNDS.restore_window_days);
  if (typeof window !== 'number') return window;
  rules.restore_window_days = window;
  return { rules };
}

/**
 * Whether two rule sets are the same (the form is unchanged since the last save).
 *
 * @param a - One.
 * @param b - The other.
 * @returns `true` when every field agrees.
 */
export function sameRules(a: RetentionRules, b: RetentionRules): boolean {
  return RULE_FIELDS.every((field) => JSON.stringify(a[field]) === JSON.stringify(b[field]));
}

/**
 * Check a rules body the browser sent, so the proxy never forwards what REST would have to guess at.
 *
 * @param body - The parsed JSON.
 * @returns The body, or the reason it is refused (an unknown field is named, never dropped).
 */
export function checkRulesBody(body: unknown): { ok: true; body: Record<string, unknown> } | { ok: false; error: string } {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return { ok: false, error: 'Send the rules as a JSON object.' };
  const record = body as Record<string, unknown>;
  const allowed = new Set<string>([...RULE_FIELDS, 'keep_deployed_or_released']);
  const unknown = Object.keys(record).find((key) => !allowed.has(key));
  if (unknown !== undefined) return { ok: false, error: `Unsupported field ${unknown}.` };
  if (record.keep_deployed_or_released === false) return { ok: false, error: KEEPS_IN_USE };
  return { ok: true, body: record };
}

/**
 * Check a preview body: `{}` (the saved rules) or `{ rules }` (a draft).
 *
 * @param body - The parsed JSON.
 * @returns The body, or the reason it is refused.
 */
export function checkPreviewBody(body: unknown): { ok: true; body: Record<string, unknown> } | { ok: false; error: string } {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return { ok: false, error: 'Send a JSON object.' };
  const record = body as Record<string, unknown>;
  const unknown = Object.keys(record).find((key) => key !== 'rules');
  if (unknown !== undefined) return { ok: false, error: `Unsupported field ${unknown}.` };
  if (record.rules === undefined || record.rules === null) return { ok: true, body: {} };
  const rules = checkRulesBody(record.rules);
  return rules.ok ? { ok: true, body: { rules: rules.body } } : rules;
}

/**
 * `1 version` / `5 versions`, with thousands separators.
 *
 * @param count - How many.
 * @param word - The singular.
 * @returns The phrase.
 */
export function plural(count: number, word: string): string {
  return `${count.toLocaleString('en-US')} ${word}${count === 1 ? '' : 's'}`;
}

/**
 * The headline of a preview.
 *
 * @param preview - The preview.
 * @returns `412 of 1,904 versions would go` and its detail line.
 */
export function previewHeadline(preview: RetentionPreview): { title: string; detail: string } {
  const { plan } = preview;
  return {
    title: `${plan.deleted.toLocaleString('en-US')} of ${plural(plan.evaluated, 'version')} would go`,
    detail:
      `with ${plural(plan.pacts, 'pact')} and ${plural(plan.results, 'result')}. Nothing deployed or released goes.` +
      (plan.remaining > 0 ? ` ${plural(plan.remaining, 'more version')} past one run’s cap would go on a later night.` : ''),
  };
}

/**
 * The form as `apiome pact retention set` and its REST `PUT`.
 *
 * @param rules - The rules the form holds.
 * @param tenant - The workspace handle, or `''` for `{tenant}`.
 * @returns The action for `pactCommandSurfaces`.
 */
export function retentionCommandAction(rules: RetentionRules, tenant = ''): PactAction {
  const options: PactOption[] = [
    { flag: '--main-branch-latest', value: String(rules.keep_main_branch_latest ?? 0) },
    { flag: '--other-branch-latest', value: String(rules.keep_other_branch_latest ?? 0) },
    { flag: '--other-branch-days', value: String(rules.keep_other_branch_days ?? 0) },
    ...(rules.keep_tags.length > 0
      ? [{ flag: '--keep-tag', value: rules.keep_tags }]
      : [{ flag: '--no-tags', value: true }]),
    rules.nightly_enabled ? { flag: '--nightly', value: true } : { flag: '--no-nightly', value: true },
    { flag: '--restore-days', value: String(rules.restore_window_days) },
  ];
  return {
    verb: 'retention set',
    options,
    rest: { method: 'PUT', path: tenantPath(tenant, `/${POLICY_PROXY_PATH}`), body: rules },
  };
}

/**
 * A deleted row's title: the pacticipant, and the version number for a version.
 *
 * @param item - The row.
 * @returns E.g. `Orders UI 3.2.9`.
 */
export function deletedTitle(item: DeletedItem): string {
  return item.kind === 'version' ? `${item.pacticipant_name} ${item.number ?? ''}`.trim() : item.pacticipant_name;
}

/**
 * What a restore brings back with a deleted row.
 *
 * @param item - The row.
 * @returns E.g. `1 pact · 2 results`, or `41 versions · 6 pacts`.
 */
export function deletedDetail(item: DeletedItem): string {
  const parts = item.kind === 'pacticipant' ? [plural(item.versions, 'version'), plural(item.pacts, 'pact')] : [];
  if (item.kind === 'version') parts.push(plural(item.pacts, 'pact'), plural(item.results, 'result'));
  return parts.join(' · ');
}
