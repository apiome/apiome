/**
 * Model for the per-branch refresh rules panel (RAR-6.4, #3541).
 *
 * A repository can carry branch rules. Each names a branch exactly (`main`) or with a glob
 * (`release/*`; `*` stays within one path segment, `**` crosses segments) and sets, for the
 * branches it matches, whether they refresh, how often, and the version line a refresh lands in:
 * the refreshed version is labelled `<line>-<UTC timestamp>`. The most specific rule wins, and a
 * branch no rule matches follows the repository-wide settings.
 *
 * Pure helpers only — parsing the proxy's flat projection, the cadence choices, the sentence
 * that describes how a branch refreshes, draft editing and validation — so they are unit-tested
 * without rendering.
 */

/** One stored branch rule as the server returns it. */
export interface BranchRefreshRule {
  branchPattern: string;
  refreshEnabled: boolean;
  /** Seconds; `null` inherits the repository's cadence. */
  refreshIntervalSeconds: number | null;
  /** `null` keeps the default naming. */
  targetVersionLine: string | null;
}

/** How one tracked branch refreshes once the rules are applied. */
export interface TrackedBranchRefresh {
  branch: string;
  enabled: boolean;
  intervalSeconds: number;
  targetVersionLine: string | null;
  /** The governing rule's pattern; `null` when the branch follows the repository settings. */
  rulePattern: string | null;
  lastRefreshedAt: string | null;
}

/** The panel's data: the rules, the repository-wide fallback, and every tracked branch. */
export interface BranchRefreshData {
  repositoryId: string;
  autoRefreshEnabled: boolean;
  repositoryIntervalSeconds: number;
  minIntervalSeconds: number;
  rules: BranchRefreshRule[];
  branches: TrackedBranchRefresh[];
}

/** One rule while it is being edited: every field a string or boolean the form controls hold. */
export interface BranchRuleDraft {
  /** Stable key for React lists; not sent to the server. */
  key: string;
  branchPattern: string;
  refreshEnabled: boolean;
  /** `'inherit'` or a number of seconds, as a string (the select's value). */
  interval: string;
  targetVersionLine: string;
}

/** The select value that means "inherit the repository's cadence". */
export const INHERIT_INTERVAL = 'inherit';

/** The cadences the panel offers, in seconds. */
export const CADENCE_CHOICES: readonly number[] = [60, 300, 900, 3600, 21600, 86400];

/** A version line: letters, digits, `.`, `_` and `-`, starting with a letter or digit (mirrors REST). */
const VERSION_LINE_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

function asNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function asOptionalString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

/**
 * Parse the proxy's flat branch-refresh projection.
 *
 * @param body The JSON the `/api/repositories/{id}/branch-refresh-rules` route returned.
 * @returns The panel data, with safe defaults for anything missing.
 */
export function parseBranchRefreshResponse(body: unknown): BranchRefreshData {
  const raw = (body && typeof body === 'object' ? body : {}) as Record<string, unknown>;
  const rules = Array.isArray(raw.rules) ? raw.rules : [];
  const branches = Array.isArray(raw.branches) ? raw.branches : [];
  return {
    repositoryId: typeof raw.repositoryId === 'string' ? raw.repositoryId : '',
    autoRefreshEnabled: raw.autoRefreshEnabled !== false,
    repositoryIntervalSeconds: asNumber(raw.repositoryIntervalSeconds, 300),
    minIntervalSeconds: asNumber(raw.minIntervalSeconds, 60),
    rules: rules.map((r) => {
      const rule = (r ?? {}) as Record<string, unknown>;
      return {
        branchPattern: typeof rule.branchPattern === 'string' ? rule.branchPattern : '',
        refreshEnabled: rule.refreshEnabled !== false,
        refreshIntervalSeconds:
          typeof rule.refreshIntervalSeconds === 'number' ? rule.refreshIntervalSeconds : null,
        targetVersionLine: asOptionalString(rule.targetVersionLine),
      };
    }),
    branches: branches.map((b) => {
      const branch = (b ?? {}) as Record<string, unknown>;
      return {
        branch: typeof branch.branch === 'string' ? branch.branch : '',
        enabled: branch.enabled !== false,
        intervalSeconds: asNumber(branch.intervalSeconds, 300),
        targetVersionLine: asOptionalString(branch.targetVersionLine),
        rulePattern: asOptionalString(branch.rulePattern),
        lastRefreshedAt: asOptionalString(branch.lastRefreshedAt),
      };
    }),
  };
}

/**
 * A cadence in words: `300` → `5 min`, `3600` → `1 hour`, `86400` → `1 day`.
 *
 * @param seconds The cadence.
 * @returns The human form.
 */
export function formatCadence(seconds: number): string {
  if (seconds % 86400 === 0) return seconds === 86400 ? '1 day' : `${seconds / 86400} days`;
  if (seconds % 3600 === 0) return seconds === 3600 ? '1 hour' : `${seconds / 3600} hours`;
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds} s`;
}

/**
 * The cadences a rule may choose: the standard choices at or above the minimum, plus the rule's
 * current value when it is not one of them.
 *
 * @param minIntervalSeconds The deployment's minimum cadence.
 * @param current The rule's current value, if any.
 * @returns Seconds, ascending.
 */
export function cadenceChoices(minIntervalSeconds: number, current?: number | null): number[] {
  const choices = CADENCE_CHOICES.filter((s) => s >= minIntervalSeconds);
  if (typeof current === 'number' && !choices.includes(current)) choices.push(current);
  return choices.sort((a, b) => a - b);
}

/**
 * The sentence that says how a tracked branch refreshes.
 *
 * @param branch The branch's effective settings.
 * @param autoRefreshEnabled The repository-wide switch.
 * @returns For example "Every 5 min into latest · rule main".
 */
export function describeBranchRefresh(branch: TrackedBranchRefresh, autoRefreshEnabled: boolean): string {
  const source = branch.rulePattern ? `rule ${branch.rulePattern}` : 'repository settings';
  if (!autoRefreshEnabled) return `Off — auto-refresh is off for the repository`;
  if (!branch.enabled) return `Refresh off · ${source}`;
  const into = branch.targetVersionLine ? ` into ${branch.targetVersionLine}` : '';
  return `Every ${formatCadence(branch.intervalSeconds)}${into} · ${source}`;
}

let draftCounter = 0;

/**
 * Turn stored rules into editable drafts.
 *
 * @param rules The stored rules.
 * @returns One draft per rule, in order.
 */
export function draftsFromRules(rules: BranchRefreshRule[]): BranchRuleDraft[] {
  return rules.map((rule) => ({
    key: `rule-${(draftCounter += 1)}`,
    branchPattern: rule.branchPattern,
    refreshEnabled: rule.refreshEnabled,
    interval: rule.refreshIntervalSeconds === null ? INHERIT_INTERVAL : String(rule.refreshIntervalSeconds),
    targetVersionLine: rule.targetVersionLine ?? '',
  }));
}

/**
 * A new, empty draft rule.
 *
 * @returns A rule that refreshes, inherits the cadence and has no line.
 */
export function newDraft(): BranchRuleDraft {
  return {
    key: `rule-${(draftCounter += 1)}`,
    branchPattern: '',
    refreshEnabled: true,
    interval: INHERIT_INTERVAL,
    targetVersionLine: '',
  };
}

/**
 * Check drafts before saving; the server checks again.
 *
 * @param drafts The rules being edited.
 * @returns The first problem in words, or `null` when the drafts can be saved.
 */
export function validateDrafts(drafts: BranchRuleDraft[]): string | null {
  const seen = new Set<string>();
  for (const draft of drafts) {
    const pattern = draft.branchPattern.trim();
    if (!pattern) return 'Every rule needs a branch name or pattern.';
    if (/\s/.test(pattern)) return `Branch pattern “${pattern}” must not contain spaces.`;
    if (seen.has(pattern)) return `Branch pattern “${pattern}” appears more than once.`;
    seen.add(pattern);
    const line = draft.targetVersionLine.trim();
    if (line && (line.length > 64 || !VERSION_LINE_RE.test(line))) {
      return `Version line “${line}” may use letters, digits, “.”, “_” and “-”.`;
    }
  }
  return null;
}

/**
 * The `PUT` body for the drafts.
 *
 * @param drafts The rules being edited (already validated).
 * @returns `{ rules }` in the REST shape.
 */
export function draftsToRequest(drafts: BranchRuleDraft[]): { rules: BranchRefreshRule[] } {
  return {
    rules: drafts.map((draft) => ({
      branchPattern: draft.branchPattern.trim(),
      refreshEnabled: draft.refreshEnabled,
      refreshIntervalSeconds: draft.interval === INHERIT_INTERVAL ? null : Number(draft.interval),
      targetVersionLine: draft.targetVersionLine.trim() || null,
    })),
  };
}

/**
 * Whether the drafts differ from the stored rules (so Save is worth pressing).
 *
 * @param drafts The rules being edited.
 * @param rules The stored rules.
 * @returns True when saving would change something.
 */
export function draftsChanged(drafts: BranchRuleDraft[], rules: BranchRefreshRule[]): boolean {
  return JSON.stringify(draftsToRequest(drafts).rules) !== JSON.stringify(rules);
}
