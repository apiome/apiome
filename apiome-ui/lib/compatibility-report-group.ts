/**
 * Groups compatibility findings for display: severity (category) → entity path (#2590).
 */

export type CompatibilityFindingRow = {
  id?: string;
  category?: string;
  rule: string;
  path: string;
  message: string;
  /** Optional 1-based source line (oasdiff evidence / CLX-2.3). */
  startLine?: number | null;
};

const SEVERITY_ORDER = ['breaking', 'unknown', 'safe'] as const;

export type SeverityGroup = (typeof SEVERITY_ORDER)[number];

export type GroupedCompatibilitySection = {
  severity: SeverityGroup;
  label: string;
  paths: Array<{
    path: string;
    findings: CompatibilityFindingRow[];
  }>;
};

const SEVERITY_LABEL: Record<SeverityGroup, string> = {
  breaking: 'Breaking',
  unknown: 'Unknown',
  safe: 'Safe',
};

function normalizeSeverity(raw: string | undefined): SeverityGroup {
  const c = (raw || '').toLowerCase();
  if (c === 'breaking' || c === 'unknown' || c === 'safe') {
    return c;
  }
  return 'unknown';
}

export function groupCompatibilityFindings(
  findings: CompatibilityFindingRow[]
): GroupedCompatibilitySection[] {
  const bySev = new Map<SeverityGroup, Map<string, CompatibilityFindingRow[]>>();
  for (const f of findings) {
    const sev = normalizeSeverity(f.category);
    if (!bySev.has(sev)) {
      bySev.set(sev, new Map());
    }
    const pathMap = bySev.get(sev)!;
    const p = f.path || '/';
    if (!pathMap.has(p)) {
      pathMap.set(p, []);
    }
    pathMap.get(p)!.push(f);
  }
  const out: GroupedCompatibilitySection[] = [];
  for (const sev of SEVERITY_ORDER) {
    const pathMap = bySev.get(sev);
    if (!pathMap || pathMap.size === 0) {
      continue;
    }
    const paths = [...pathMap.keys()].sort((a, b) => a.localeCompare(b));
    out.push({
      severity: sev,
      label: SEVERITY_LABEL[sev],
      paths: paths.map((path) => ({
        path,
        findings: pathMap.get(path)!,
      })),
    });
  }
  return out;
}
