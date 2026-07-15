/**
 * Helpers for the MCP trust-drift and shadowing panels (CLX-3.4, #4858).
 *
 * Parses the `GET …/endpoints/{id}/trust-drift` and `GET …/data-quality/shadowing` reports and shapes
 * them for rendering. The honesty guarantee that lives here rather than in the component: a drift
 * change is always shown with its *classification* — normal change / quality regression / security
 * regression / coverage loss — never a bare "changed" line that would let a regression read as a
 * routine update, and every change keeps its old→new evidence reference so the panel can link both
 * sides.
 */

export type DriftCategory =
  | 'normal_change'
  | 'quality_regression'
  | 'security_regression'
  | 'coverage_loss'
  | string;

export type DriftGateStatus = 'pass' | 'warn' | 'blocked' | string;

export interface DriftEvidenceRef {
  [key: string]: unknown;
}

export interface DriftChange {
  category: DriftCategory;
  component: string;
  path: string;
  summary: string;
  before: unknown;
  after: unknown;
  evidence: { baseline: DriftEvidenceRef; current: DriftEvidenceRef };
}

export interface DriftGate {
  status: DriftGateStatus;
  blockingCategories: string[];
  reason: string;
  enforced: boolean;
}

export interface DriftReport {
  baselineFingerprint: string | null;
  currentFingerprint: string | null;
  unchanged: boolean;
  alertSeverity: DriftCategory;
  hasRegression: boolean;
  categoryCounts: Record<string, number>;
  gate: DriftGate;
  changes: DriftChange[];
}

export interface ShadowEndpoint {
  id: string;
  name: string | null;
  slug: string | null;
  host: string | null;
}

export interface ShadowGroup {
  itemType: string;
  name: string;
  hostScope: 'same_host' | 'cross_host' | string;
  endpointCount: number;
  endpoints: ShadowEndpoint[];
}

export interface ShadowReport {
  advisory: boolean;
  groupCount: number;
  sameHostCount: number;
  crossHostCount: number;
  groups: ShadowGroup[];
}

/** Human label for a drift category. */
export function driftCategoryLabel(category: DriftCategory): string {
  switch (category) {
    case 'security_regression':
      return 'Security regression';
    case 'coverage_loss':
      return 'Coverage loss';
    case 'quality_regression':
      return 'Quality regression';
    case 'normal_change':
      return 'Normal change';
    default:
      return String(category);
  }
}

/** CSS classes for a drift-category chip (token utilities only — no hard-coded colors). */
export function driftCategoryClass(category: DriftCategory): string {
  switch (category) {
    case 'security_regression':
      return 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300';
    case 'coverage_loss':
      return 'bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300';
    case 'quality_regression':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
    case 'normal_change':
    default:
      return 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300';
  }
}

/** CSS classes for the gate-status chip. */
export function driftGateClass(status: DriftGateStatus): string {
  switch (status) {
    case 'blocked':
      return 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300';
    case 'warn':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
    case 'pass':
    default:
      return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300';
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** Normalize the REST / proxy trust-drift payload into a typed report (or null when malformed). */
export function parseDriftReport(payload: unknown): DriftReport | null {
  const root = asRecord(payload);
  if (!root) return null;
  const drift = asRecord(root.drift) ?? root;
  if (!drift) return null;

  const gateRaw = asRecord(drift.gate) ?? {};
  const gate: DriftGate = {
    status: typeof gateRaw.status === 'string' ? gateRaw.status : 'pass',
    blockingCategories: Array.isArray(gateRaw.blocking_categories)
      ? (gateRaw.blocking_categories as unknown[]).map(String)
      : [],
    reason: typeof gateRaw.reason === 'string' ? gateRaw.reason : '',
    enforced: gateRaw.enforced === true,
  };

  const changesRaw = Array.isArray(drift.changes) ? drift.changes : [];
  const changes: DriftChange[] = changesRaw.map((entry) => {
    const record = asRecord(entry) ?? {};
    const evidence = asRecord(record.evidence) ?? {};
    return {
      category: typeof record.category === 'string' ? record.category : 'normal_change',
      component: typeof record.component === 'string' ? record.component : '',
      path: typeof record.path === 'string' ? record.path : '',
      summary: typeof record.summary === 'string' ? record.summary : '',
      before: record.before ?? null,
      after: record.after ?? null,
      evidence: {
        baseline: asRecord(evidence.baseline) ?? {},
        current: asRecord(evidence.current) ?? {},
      },
    };
  });

  const counts = asRecord(drift.category_counts) ?? {};
  const categoryCounts: Record<string, number> = {};
  for (const [key, value] of Object.entries(counts)) {
    categoryCounts[key] = typeof value === 'number' ? value : Number(value) || 0;
  }

  return {
    baselineFingerprint:
      typeof drift.baseline_fingerprint === 'string' ? drift.baseline_fingerprint : null,
    currentFingerprint:
      typeof drift.current_fingerprint === 'string' ? drift.current_fingerprint : null,
    unchanged: drift.unchanged === true,
    alertSeverity: typeof drift.alert_severity === 'string' ? drift.alert_severity : 'normal_change',
    hasRegression: drift.has_regression === true,
    categoryCounts,
    gate,
    changes,
  };
}

/** Normalize the REST / proxy shadowing payload into a typed report (or null when malformed). */
export function parseShadowReport(payload: unknown): ShadowReport | null {
  const root = asRecord(payload);
  if (!root) return null;
  const groupsRaw = Array.isArray(root.groups) ? root.groups : [];
  const groups: ShadowGroup[] = groupsRaw.map((entry) => {
    const record = asRecord(entry) ?? {};
    const endpointsRaw = Array.isArray(record.endpoints) ? record.endpoints : [];
    const endpoints: ShadowEndpoint[] = endpointsRaw.map((e) => {
      const ep = asRecord(e) ?? {};
      return {
        id: typeof ep.id === 'string' ? ep.id : '',
        name: typeof ep.name === 'string' ? ep.name : null,
        slug: typeof ep.slug === 'string' ? ep.slug : null,
        host: typeof ep.host === 'string' ? ep.host : null,
      };
    });
    return {
      itemType: typeof record.item_type === 'string' ? record.item_type : '',
      name: typeof record.name === 'string' ? record.name : '',
      hostScope: typeof record.host_scope === 'string' ? record.host_scope : 'cross_host',
      endpointCount:
        typeof record.endpoint_count === 'number' ? record.endpoint_count : endpoints.length,
      endpoints,
    };
  });

  return {
    advisory: root.advisory === true,
    groupCount: typeof root.group_count === 'number' ? root.group_count : groups.length,
    sameHostCount: typeof root.same_host_count === 'number' ? root.same_host_count : 0,
    crossHostCount: typeof root.cross_host_count === 'number' ? root.cross_host_count : 0,
    groups,
  };
}
