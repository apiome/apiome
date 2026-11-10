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

/** Guide metadata echoed on lint reports (GOV-1.4). */
export type LintGuideSource = 'builtin' | 'custom' | 'fallback';

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
  /** Style guide applied for this lint run (GOV-1.4). */
  guideId?: string | null;
  guideName?: string | null;
  guideSource?: LintGuideSource | null;
  /** Multi-axis scoring algorithm id (CLX-1.2). */
  algorithmId?: string | null;
  /** Per-axis scores and coverage (CLX-1.2); absent when not evaluated. */
  axes?: unknown[] | null;
  compositeScore?: number | null;
  compositeGrade?: string | null;
  requiredCoverageMet?: boolean | null;
}

/** CSS utility classes for the grade chip, keyed by letter grade. */
const GRADE_CHIP_CLASSES: Record<string, string> = {
  A: 'bg-ok-soft text-ok-fg border-ok/30',
  B: 'bg-lime-100 text-lime-800 border-lime-200 dark:bg-lime-900/40 dark:text-lime-300 dark:border-lime-800',
  C: 'bg-warn-soft text-warn-fg border-warn/30',
  D: 'bg-orange-soft text-orange-fg border-orange/30',
  F: 'bg-danger-soft text-danger-fg border-danger/30',
};

const GRADE_CHIP_FALLBACK =
  'bg-subtle text-fg-muted border-border';

/** Return the chip CSS classes for a letter grade (defensive fallback for unknown grades). */
export function gradeChipClass(grade: string): string {
  return GRADE_CHIP_CLASSES[(grade || '').trim().toUpperCase()] ?? GRADE_CHIP_FALLBACK;
}

const SEVERITY_CLASSES: Record<LintSeverity, string> = {
  error: 'bg-danger-soft text-danger-fg',
  warning: 'bg-warn-soft text-warn-fg',
  info: 'bg-accent-soft text-accent-fg',
};

const SEVERITY_FALLBACK = 'bg-subtle text-fg-muted';

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
