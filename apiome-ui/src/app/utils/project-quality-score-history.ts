/**
 * Browser-local history of OpenAPI quality scores per project (#246).
 * Snapshots are appended when an import completes successfully (Import dialog).
 */

import type { AnalysisIssue, AnalysisResult } from './openapi-analyzer';

export type QualityLetterGrade = 'A' | 'B' | 'C' | 'D' | 'F';

export type ProjectQualityReportSection = 'trend' | 'quality' | 'lint';

export interface StoredQualityCategoryScore {
  id: string;
  label: string;
  percent: number;
  points: number;
  maxPoints: number;
}

export interface StoredQualityIssue {
  category: string;
  message: string;
  suggestion: string;
  path: string;
  severity: 'high' | 'medium' | 'low';
}

export interface StoredLintFinding {
  type: 'error' | 'warning';
  message: string;
  path?: string;
  severity: string;
}

export interface ProjectQualitySnapshot {
  recordedAt: string;
  overall: number;
  grade: QualityLetterGrade;
  /** Dedupes Strict Mode / duplicate effect runs for the same import job */
  importJobId?: string;
  /** Weighted category breakdown from the import analysis */
  categories?: StoredQualityCategoryScore[];
  /** Quality score improvement suggestions */
  issues?: StoredQualityIssue[];
  /** Structural / validation lint findings (errors + warnings) */
  lintFindings?: StoredLintFinding[];
}

const MAX_STORED_ISSUES = 80;
const MAX_STORED_LINT = 80;

interface StoreShape {
  byProject: Record<string, ProjectQualitySnapshot[]>;
}

const STORAGE_KEY = 'apiome:project-quality-history:v1';
const MAX_ENTRIES_PER_PROJECT = 120;

const MAX_APPENDED_IMPORT_JOB_IDS = 500;

/**
 * Prevents duplicate snapshots when import completion runs twice
 * (e.g. React Strict Mode), while avoiding unbounded growth for long-lived tabs.
 */
const appendedImportJobIds = (() => {
  const ids = new Set<string>();
  const order: string[] = [];

  return {
    has(id: string): boolean {
      return ids.has(id);
    },
    add(id: string): void {
      if (ids.has(id)) return;

      ids.add(id);
      order.push(id);

      if (order.length > MAX_APPENDED_IMPORT_JOB_IDS) {
        const oldestId = order.shift();
        if (oldestId) {
          ids.delete(oldestId);
        }
      }
    },
  };
})();

function loadStore(): StoreShape {
  if (typeof window === 'undefined') return { byProject: {} };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { byProject: {} };
    const parsed = JSON.parse(raw) as StoreShape;
    if (!parsed || typeof parsed !== 'object' || !parsed.byProject || typeof parsed.byProject !== 'object') {
      return { byProject: {} };
    }
    return parsed;
  } catch {
    return { byProject: {} };
  }
}

function saveStore(store: StoreShape): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  } catch {
    // quota or private mode
  }
}

function clampOverall(n: number): number {
  const safeValue = Number.isFinite(n) ? n : 0;
  return Math.max(0, Math.min(100, Math.round(safeValue)));
}

function toStoredLintFinding(issue: AnalysisIssue, type: 'error' | 'warning'): StoredLintFinding {
  return {
    type,
    message: issue.message,
    ...(issue.path ? { path: issue.path } : {}),
    severity: issue.severity,
  };
}

/** Serializable quality + lint report extras from an import analysis. */
export function buildQualitySnapshotReportExtras(
  analysis: Pick<AnalysisResult, 'qualityScore' | 'errors' | 'warnings'>
): Pick<ProjectQualitySnapshot, 'categories' | 'issues' | 'lintFindings'> {
  const categories = Object.values(analysis.qualityScore.categories).map((cat) => ({
    id: cat.id,
    label: cat.label,
    percent: cat.percent,
    points: cat.points,
    maxPoints: cat.maxPoints,
  }));

  const issues = (analysis.qualityScore.issues ?? []).slice(0, MAX_STORED_ISSUES).map((issue) => ({
    category: issue.category,
    message: issue.message,
    suggestion: issue.suggestion,
    path: issue.path,
    severity: issue.severity,
  }));

  const lintFindings = [
    ...analysis.errors.map((issue) => toStoredLintFinding(issue, 'error')),
    ...analysis.warnings.map((issue) => toStoredLintFinding(issue, 'warning')),
  ].slice(0, MAX_STORED_LINT);

  return { categories, issues, lintFindings };
}

/** Latest snapshot that includes a stored report, or the latest snapshot overall. */
export function getLatestProjectQualitySnapshotWithReport(
  projectId: string
): ProjectQualitySnapshot | null {
  const history = getProjectQualityHistory(projectId);
  if (history.length === 0) return null;
  for (let i = history.length - 1; i >= 0; i -= 1) {
    const snap = history[i];
    if (
      snap.categories !== undefined ||
      snap.issues !== undefined ||
      snap.lintFindings !== undefined
    ) {
      return snap;
    }
  }
  return history[history.length - 1];
}

export function snapshotHasQualityReport(snapshot: ProjectQualitySnapshot | null | undefined): boolean {
  if (!snapshot) return false;
  return snapshot.categories !== undefined || snapshot.issues !== undefined;
}

export function snapshotHasLintReport(snapshot: ProjectQualitySnapshot | null | undefined): boolean {
  if (!snapshot) return false;
  return snapshot.lintFindings !== undefined;
}

/**
 * Append a snapshot for a project. Keeps entries ordered by `recordedAt` ascending.
 * Skips if the last entry for this project has the same `importJobId`.
 */
export function appendProjectQualitySnapshot(
  projectId: string,
  payload: {
    overall: number;
    grade: QualityLetterGrade;
    importJobId?: string;
    recordedAt?: string;
    categories?: StoredQualityCategoryScore[];
    issues?: StoredQualityIssue[];
    lintFindings?: StoredLintFinding[];
  }
): void {
  if (!projectId) return;

  if (payload.importJobId && appendedImportJobIds.has(payload.importJobId)) return;

  const store = loadStore();
  const prev = [...(store.byProject[projectId] ?? [])].sort(
    (a, b) => new Date(a.recordedAt).getTime() - new Date(b.recordedAt).getTime()
  );

  if (payload.importJobId) {
    const last = prev[prev.length - 1];
    if (last?.importJobId === payload.importJobId) return;
  }

  if (payload.importJobId) appendedImportJobIds.add(payload.importJobId);

  const snap: ProjectQualitySnapshot = {
    recordedAt: payload.recordedAt ?? new Date().toISOString(),
    overall: clampOverall(payload.overall),
    grade: payload.grade,
    ...(payload.importJobId ? { importJobId: payload.importJobId } : {}),
    ...(payload.categories !== undefined ? { categories: payload.categories } : {}),
    ...(payload.issues !== undefined ? { issues: payload.issues } : {}),
    ...(payload.lintFindings !== undefined ? { lintFindings: payload.lintFindings } : {}),
  };

  const next = [...prev, snap];
  if (next.length > MAX_ENTRIES_PER_PROJECT) {
    next.splice(0, next.length - MAX_ENTRIES_PER_PROJECT);
  }

  store.byProject[projectId] = next;
  saveStore(store);
}

export function getProjectQualityHistory(projectId: string): ProjectQualitySnapshot[] {
  if (!projectId) return [];
  const store = loadStore();
  const list = store.byProject[projectId] ?? [];
  return [...list].sort((a, b) => new Date(a.recordedAt).getTime() - new Date(b.recordedAt).getTime());
}

/** Latest overall score if any history exists */
export function getLatestProjectQualityOverall(projectId: string): number | null {
  const h = getProjectQualityHistory(projectId);
  if (h.length === 0) return null;
  return h[h.length - 1].overall;
}

export interface SparklinePoint {
  x: number;
  y: number;
  overall: number;
}

/**
 * Normalized SVG coordinates (0–100 viewBox) for a polyline / area under the curve.
 */
export function buildQualityTrendPoints(overallValues: number[]): SparklinePoint[] {
  const vals = overallValues.map((v) => clampOverall(v));
  if (vals.length === 0) return [];
  if (vals.length === 1) {
    const y = 100 - vals[0];
    return [
      { x: 0, y, overall: vals[0] },
      { x: 100, y, overall: vals[0] },
    ];
  }
  const n = vals.length;
  return vals.map((overall, i) => ({
    x: (i / (n - 1)) * 100,
    y: 100 - overall,
    overall,
  }));
}

/** One point per import snapshot event across the portfolio (running average of latest score per project). */
export interface PortfolioQualityPoint {
  recordedAt: string;
  avgOverall: number;
}

/**
 * Merges per-project snapshot timelines chronologically. After each event, `avgOverall` is the
 * mean of each project's latest known score among projects that have at least one snapshot so far.
 */
export function buildPortfolioQualitySeries(
  historiesByProjectId: Record<string, ProjectQualitySnapshot[]>
): PortfolioQualityPoint[] {
  type Ev = { at: number; projectId: string; overall: number };
  const events: Ev[] = [];
  for (const [projectId, snaps] of Object.entries(historiesByProjectId)) {
    for (const s of snaps) {
      const at = new Date(s.recordedAt).getTime();
      if (!Number.isFinite(at)) continue;
      events.push({ at, projectId, overall: clampOverall(s.overall) });
    }
  }
  events.sort((a, b) => a.at - b.at);
  const latest = new Map<string, number>();
  const out: PortfolioQualityPoint[] = [];
  for (const e of events) {
    latest.set(e.projectId, e.overall);
    let sum = 0;
    for (const v of latest.values()) sum += v;
    const avgOverall = Math.round(sum / latest.size);
    out.push({ recordedAt: new Date(e.at).toISOString(), avgOverall });
  }
  return out;
}
