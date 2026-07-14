/**
 * Helpers for the catalog "source-format checks" strip (CLX-2.4 / #4854).
 *
 * Surfaces per-scanner coverage from `GET …/lint/evidence` so an absent scan reads as
 * not_run / unavailable — never as a silent clean score.
 */

export type LintEvidenceOutcome =
  | 'passed'
  | 'findings'
  | 'not_run'
  | 'unavailable'
  | 'failed'
  | 'blocked_by_policy'
  | string;

export interface LintEvidenceCoverageEntry {
  scannerId: string;
  outcome: LintEvidenceOutcome;
  coverage: { state?: string; diagnostics?: string; [key: string]: unknown };
  runId?: string | null;
  recordedAt?: string | null;
}

export interface LintEvidencePayload {
  subjectType?: string;
  subjectId?: string;
  coverage: LintEvidenceCoverageEntry[];
  count?: number;
}

export type FormatLintMode = 'native' | 'adapted' | 'unsupported' | string;

export interface FormatLintCapability {
  format: string;
  mode: FormatLintMode;
  importable?: boolean;
  nativePack?: string | null;
  adaptedScanners?: string[];
  commonPackOnly?: boolean;
  relatedIssues?: string[];
  notes?: string;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined;
}

/** Normalize a REST / proxy evidence payload into camelCase coverage entries. */
export function parseLintEvidenceCoverage(payload: unknown): LintEvidenceCoverageEntry[] {
  const root = asRecord(payload);
  if (!root) return [];
  const raw = root.coverage;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((row): LintEvidenceCoverageEntry | null => {
      const r = asRecord(row);
      if (!r) return null;
      const scannerId = asString(r.scannerId) ?? asString(r.scanner_id);
      const outcome = asString(r.outcome);
      if (!scannerId || !outcome) return null;
      const coverageRaw = asRecord(r.coverage) ?? {};
      return {
        scannerId,
        outcome,
        coverage: coverageRaw,
        runId: asString(r.runId) ?? asString(r.run_id) ?? null,
        recordedAt: asString(r.recordedAt) ?? asString(r.recorded_at) ?? null,
      };
    })
    .filter((e): e is LintEvidenceCoverageEntry => e != null);
}

/** Pick the capability row matching a source format (handles a few aliases). */
export function capabilityForSourceFormat(
  formats: FormatLintCapability[] | undefined,
  sourceFormat: string | null | undefined
): FormatLintCapability | null {
  if (!formats?.length || !sourceFormat) return null;
  const key = sourceFormat.trim().toLowerCase();
  const aliases = new Set([key]);
  if (key === 'api-blueprint' || key === 'apib') aliases.add('apiblueprint');
  if (key === 'grpc') aliases.add('protobuf');
  if (key === 'tsp' || key === 'cadl') aliases.add('typespec');
  return formats.find((f) => aliases.has(f.format.toLowerCase())) ?? null;
}

/** Human label for a scanner id. */
export function scannerLabel(scannerId: string): string {
  const map: Record<string, string> = {
    'apiome.native-lint': 'Native lint',
    'buf.lint': 'Buf lint',
    'graphql.eslint': 'GraphQL ESLint',
    'spectral.oas': 'Spectral',
    'vacuum.oas': 'Vacuum',
    'redocly.oas': 'Redocly',
    'oasdiff.breaking': 'oasdiff',
  };
  return map[scannerId] ?? scannerId;
}

/** CSS classes for outcome chips (token utilities only). */
export function outcomeChipClass(outcome: string): string {
  switch (outcome) {
    case 'passed':
      return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300';
    case 'findings':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
    case 'not_run':
      return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300';
    case 'unavailable':
    case 'failed':
    case 'blocked_by_policy':
      return 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300';
    default:
      return 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300';
  }
}

export async function fetchLintEvidence(
  projectId: string,
  versionRecordId: string,
  options?: { signal?: AbortSignal }
): Promise<LintEvidenceCoverageEntry[]> {
  const response = await fetch(
    `/api/projects/${encodeURIComponent(projectId)}/versions/${encodeURIComponent(versionRecordId)}/lint/evidence`,
    { method: 'GET', signal: options?.signal }
  );
  const data = await response.json().catch(() => null);
  if (!response.ok || !data || data.success === false) {
    const message =
      (data && (data.error || data.detail)) ||
      `Failed to load lint evidence (HTTP ${response.status})`;
    throw new Error(typeof message === 'string' ? message : 'Failed to load lint evidence');
  }
  return parseLintEvidenceCoverage(data);
}

export async function fetchFormatLintCapabilities(options?: {
  signal?: AbortSignal;
}): Promise<FormatLintCapability[]> {
  const response = await fetch('/api/lint/format-capabilities', {
    method: 'GET',
    signal: options?.signal,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok || !data || data.success === false) {
    return [];
  }
  const formats = Array.isArray(data.formats) ? data.formats : [];
  return formats
    .map((row: unknown): FormatLintCapability | null => {
      const r = asRecord(row);
      if (!r) return null;
      const format = asString(r.format);
      const mode = asString(r.mode);
      if (!format || !mode) return null;
      return {
        format,
        mode,
        importable: Boolean(r.importable),
        nativePack: asString(r.nativePack) ?? asString(r.native_pack) ?? null,
        adaptedScanners: Array.isArray(r.adaptedScanners)
          ? (r.adaptedScanners as string[])
          : Array.isArray(r.adapted_scanners)
            ? (r.adapted_scanners as string[])
            : [],
        commonPackOnly: Boolean(r.commonPackOnly ?? r.common_pack_only),
        relatedIssues: Array.isArray(r.relatedIssues)
          ? (r.relatedIssues as string[])
          : Array.isArray(r.related_issues)
            ? (r.related_issues as string[])
            : [],
        notes: asString(r.notes) ?? '',
      };
    })
    .filter((e): e is FormatLintCapability => e != null);
}
