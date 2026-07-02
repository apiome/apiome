/**
 * Types and presentation helpers for the server-computed version lint report (#3609).
 *
 * The score and A-F grade are the authoritative quality signal computed by apiome-rest
 * (`GET .../lint`). The UI never recomputes them client-side — this module only fetches the
 * server report and maps grades/severities to CSS utility classes for rendering.
 */

export type LintSeverity = 'error' | 'warning' | 'info';

export interface VersionLintFinding {
  id: string;
  path: string;
  category: string;
  rule: string;
  severity: LintSeverity;
  message: string;
}

/**
 * A per-category 0–100 rollup score (MFI-25.6). Optional on the report: until the REST enrichment
 * lands, `/lint` omits it and the inline panel (MFI-25.5) degrades to a severity breakdown derived
 * from `findings`.
 */
export interface LintCategoryScore {
  name: string;
  score: number;
}

export interface VersionLintReport {
  projectId: string;
  versionRecordId: string;
  versionId: string;
  score: number;
  grade: string;
  findings: VersionLintFinding[];
  ruleHits: Record<string, number>;
  severityCounts: Record<string, number>;
  /** Per-category 0–100 rollup scores (MFI-25.6); absent until the REST enrichment ships. */
  categories?: LintCategoryScore[] | null;
  reportFingerprint: string;
  baseRevisionId: string | null;
  compatibilityOverall: string | null;
  /** Score persisted on the version at import time (MFI-4.2/4.4), null when never scored. */
  capturedScore?: number | null;
  /** A-F grade persisted on the version at import time, null when never scored. */
  capturedGrade?: string | null;
  /** Fingerprint persisted on the version at import time, null when never scored. */
  capturedReportFingerprint?: string | null;
  /** True when the persisted score is out of date relative to this live report (MFI-4.4). */
  scoreIsStale?: boolean;
}

/** CSS utility classes for the grade chip, keyed by letter grade. */
const GRADE_CHIP_CLASSES: Record<string, string> = {
  A: 'bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-900/40 dark:text-emerald-300 dark:border-emerald-800',
  B: 'bg-lime-100 text-lime-800 border-lime-200 dark:bg-lime-900/40 dark:text-lime-300 dark:border-lime-800',
  C: 'bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-900/40 dark:text-amber-300 dark:border-amber-800',
  D: 'bg-orange-100 text-orange-800 border-orange-200 dark:bg-orange-900/40 dark:text-orange-300 dark:border-orange-800',
  F: 'bg-rose-100 text-rose-800 border-rose-200 dark:bg-rose-900/40 dark:text-rose-300 dark:border-rose-800',
};

const GRADE_CHIP_FALLBACK =
  'bg-gray-100 text-gray-700 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700';

/** Return the chip CSS classes for a letter grade (defensive fallback for unknown grades). */
export function gradeChipClass(grade: string): string {
  return GRADE_CHIP_CLASSES[(grade || '').trim().toUpperCase()] ?? GRADE_CHIP_FALLBACK;
}

const SEVERITY_CLASSES: Record<LintSeverity, string> = {
  error: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300',
  warning: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  info: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300',
};

const SEVERITY_FALLBACK = 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300';

/** Return the badge CSS classes for a finding severity. */
export function severityBadgeClass(severity: string): string {
  return SEVERITY_CLASSES[severity as LintSeverity] ?? SEVERITY_FALLBACK;
}

const SEVERITY_RANK: Record<string, number> = { error: 0, warning: 1, info: 2 };

/** Stable ordering: most severe first, then by path and rule (matches the CLI/report ordering). */
export function sortLintFindings(findings: VersionLintFinding[]): VersionLintFinding[] {
  return [...findings].sort((a, b) => {
    const sev = (SEVERITY_RANK[a.severity] ?? 3) - (SEVERITY_RANK[b.severity] ?? 3);
    if (sev !== 0) return sev;
    if (a.path !== b.path) return a.path.localeCompare(b.path);
    return a.rule.localeCompare(b.rule);
  });
}

/**
 * Fetch the server lint report for a version via the Next.js proxy. Returns the parsed report.
 * @throws Error with the server message when the request fails.
 */
export async function fetchVersionLintReport(
  projectId: string,
  versionId: string,
  options?: { baseRevisionId?: string; signal?: AbortSignal }
): Promise<VersionLintReport> {
  const query = options?.baseRevisionId
    ? `?baseRevisionId=${encodeURIComponent(options.baseRevisionId)}`
    : '';
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/versions/${encodeURIComponent(versionId)}/lint${query}`,
    { method: 'GET', signal: options?.signal }
  );
  const data = await response.json().catch(() => null);
  if (!response.ok || !data || data.success === false) {
    const message =
      (data && (data.error || data.detail)) || `Failed to load lint report (HTTP ${response.status})`;
    throw new Error(typeof message === 'string' ? message : 'Failed to load lint report');
  }
  return data as VersionLintReport;
}

/**
 * Fetch the server lint report for a catalog item's latest revision (MFI-23.10).
 *
 * The catalog analog of {@link fetchVersionLintReport}: a catalog item's id is a project id, and
 * the REST endpoint resolves its latest revision server-side, so the catalog lint orbs can open the
 * same authoritative report the Projects screens use. Returns the identical {@link VersionLintReport}
 * shape.
 * @throws Error with the server message when the request fails.
 */
export async function fetchCatalogLintReport(
  itemId: string,
  options?: { signal?: AbortSignal }
): Promise<VersionLintReport> {
  const response = await fetch(`/api/catalog/${encodeURIComponent(itemId)}/lint`, {
    method: 'GET',
    signal: options?.signal,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok || !data || data.success === false) {
    const message =
      (data && (data.error || data.detail)) || `Failed to load lint report (HTTP ${response.status})`;
    throw new Error(typeof message === 'string' ? message : 'Failed to load lint report');
  }
  return data as VersionLintReport;
}
