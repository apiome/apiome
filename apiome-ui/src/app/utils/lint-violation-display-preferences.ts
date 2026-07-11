/**
 * Per-surface "group by rule" preference for lint violation lists (GOV-2.4, #4436).
 *
 * Studio lint, import report, and catalog lint each persist their own toggle in localStorage so
 * revisiting a surface restores the last grouping mode.
 */

export const LINT_VIOLATION_DISPLAY_VIEWS = ['studio-lint', 'import-report', 'catalog-lint'] as const;
export type LintViolationDisplayView = (typeof LINT_VIOLATION_DISPLAY_VIEWS)[number];

export interface LintViolationDisplayPreferences {
  groupByRule: boolean;
}

export const DEFAULT_LINT_VIOLATION_DISPLAY_PREFERENCES: LintViolationDisplayPreferences = {
  groupByRule: false,
};

const STORAGE_KEY = 'apiome.lint-violation-display.v1';

type StoredBlob = Partial<Record<LintViolationDisplayView, Partial<LintViolationDisplayPreferences>>>;

function readBlob(): StoredBlob {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    return parsed && typeof parsed === 'object' ? (parsed as StoredBlob) : {};
  } catch {
    return {};
  }
}

function writeBlob(blob: StoredBlob): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(blob));
  } catch {
    /* quota / private mode — no-op */
  }
}

/** Read the persisted group-by-rule flag for one violation surface. */
export function readLintViolationDisplayPreferences(
  view: LintViolationDisplayView,
): LintViolationDisplayPreferences {
  const stored = readBlob()[view];
  return {
    groupByRule:
      typeof stored?.groupByRule === 'boolean'
        ? stored.groupByRule
        : DEFAULT_LINT_VIOLATION_DISPLAY_PREFERENCES.groupByRule,
  };
}

/** Persist the group-by-rule flag for one violation surface. */
export function persistLintViolationDisplayPreferences(
  view: LintViolationDisplayView,
  patch: Partial<LintViolationDisplayPreferences>,
): void {
  const blob = readBlob();
  const current = readLintViolationDisplayPreferences(view);
  blob[view] = { ...current, ...patch };
  writeBlob(blob);
}
