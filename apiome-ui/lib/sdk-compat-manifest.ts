/**
 * The generator compatibility manifest — SGD-2.1 (#4735) — types and view model.
 *
 * Export studio's **SDK compatibility** tab renders `apiome.sdk.compat-manifest/v1`, served by
 * apiome-rest's `GET /v1/tenants/{t}/projects/{p}/sdk-compatibility` — the same document
 * `apiome sdk compatibility` prints. The types mirror `apiome-rest/src/app/sdk_compat_manifest.py`
 * (snake_case, as served). The helpers here are pure, so the tab and its tests share them, and the
 * tests run against apiome-rest's golden manifest so the dashboard and the CLI provably read one
 * document.
 */

/** A finding's severity. */
export type SdkCompatSeverity = 'error' | 'warning' | 'info';

/** One construct an artifact leaves out or cannot represent. */
export interface SdkCompatFinding {
  code: string;
  severity: SdkCompatSeverity;
  artifact: string;
  element: 'operation' | 'auth-scheme' | 'artifact';
  subject: string;
  key?: string | null;
  reason: string;
  action: string;
}

/** One generated artifact. */
export interface SdkCompatArtifact {
  id: string;
  kind: 'snippets' | 'client' | 'server-stub' | 'terraform-provider' | 'mcp-server';
  language: string;
  directory: string;
  included: boolean;
  generator: { name: string; schema_version: string; digest: string };
  digest?: string | null;
  coverage: { operations: number; of: number };
  runtime?: { language_version?: string | null; dependencies: string[] } | null;
  auth?: { supported: string[]; unsupported: string[] } | null;
  pagination?: { mode: 'manual' | 'none'; parameters: string[] } | null;
  findings: SdkCompatFinding[];
}

/** The semver block. */
export interface SdkCompatSemver {
  classification: 'breaking' | 'non-breaking' | 'docs-only' | 'unknown';
  baseline_version?: string | null;
  required_bump?: 'major' | 'minor' | 'patch' | null;
  declared_bump?: 'major' | 'minor' | 'patch' | 'none' | 'unknown' | null;
  consistent?: boolean | null;
}

/** The manifest as served. */
export interface SdkCompatManifest {
  schema_version: 'apiome.sdk.compat-manifest/v1';
  api: { title?: string | null; version?: string | null; paradigm: string; format: string };
  source: { version_record_id: string; version_label?: string | null; source_format?: string | null; digest: string };
  options: { digest: string; package_names: Record<string, string>; user_agent_set: boolean; license_header_set: boolean };
  constructs: {
    operations: number;
    http_operations: number;
    streaming_operations: number;
    types: Record<string, number>;
    security_schemes: string[];
    servers: number;
    pagination_parameters: string[];
  };
  artifacts: SdkCompatArtifact[];
  findings_count: number;
  semver: SdkCompatSemver;
}

/** Severities, most severe first. */
export const SDK_COMPAT_SEVERITIES: readonly SdkCompatSeverity[] = ['error', 'warning', 'info'];

/** How each artifact is named on screen. */
export const ARTIFACT_LABELS: Readonly<Record<string, string>> = {
  'snippets-ts': 'TypeScript snippets',
  'snippets-python': 'Python snippets',
  'snippets-curl': 'curl snippets',
  'go-client': 'Go client',
  'server-fastapi': 'FastAPI server stub',
  'server-express': 'Express server stub',
  'terraform-provider': 'Terraform provider',
  'mcp-server': 'MCP server',
};

/**
 * An artifact's display name.
 *
 * @param id - The artifact id.
 * @returns Its label, or the id for an artifact this build does not know.
 */
export function artifactLabel(id: string): string {
  return ARTIFACT_LABELS[id] ?? id;
}

/**
 * Every finding of every artifact, most severe first, then by artifact and subject — the order the
 * CLI prints them in.
 *
 * @param manifest - The manifest.
 * @returns The findings.
 */
export function sortedFindings(manifest: Pick<SdkCompatManifest, 'artifacts'>): SdkCompatFinding[] {
  const rank = (severity: string) => {
    const index = SDK_COMPAT_SEVERITIES.indexOf(severity as SdkCompatSeverity);
    return index === -1 ? SDK_COMPAT_SEVERITIES.length : index;
  };
  return manifest.artifacts
    .flatMap((artifact) => artifact.findings)
    .slice()
    .sort(
      (a, b) =>
        rank(a.severity) - rank(b.severity) ||
        a.artifact.localeCompare(b.artifact) ||
        a.subject.localeCompare(b.subject),
    );
}

/**
 * How many findings there are of each severity.
 *
 * @param manifest - The manifest.
 * @returns Counts keyed by severity (every severity present, zero when none).
 */
export function severityCounts(manifest: Pick<SdkCompatManifest, 'artifacts'>): Record<SdkCompatSeverity, number> {
  const counts: Record<SdkCompatSeverity, number> = { error: 0, warning: 0, info: 0 };
  for (const finding of sortedFindings(manifest)) {
    if (finding.severity in counts) counts[finding.severity] += 1;
  }
  return counts;
}

/**
 * An artifact's coverage, as a sentence fragment.
 *
 * @param artifact - The artifact.
 * @returns `2 of 3 operations`, or `Not generated`.
 */
export function coverageLabel(artifact: Pick<SdkCompatArtifact, 'included' | 'coverage'>): string {
  if (!artifact.included) return 'Not generated';
  const { operations, of } = artifact.coverage;
  return `${operations} of ${of} operation${of === 1 ? '' : 's'}`;
}

/**
 * Whether an artifact covers every operation the version declares.
 *
 * @param artifact - The artifact.
 * @returns True when included and complete.
 */
export function isComplete(artifact: Pick<SdkCompatArtifact, 'included' | 'coverage'>): boolean {
  return artifact.included && artifact.coverage.operations >= artifact.coverage.of;
}

/**
 * The semver block as one sentence.
 *
 * @param semver - The semver block.
 * @returns For example `Non-breaking since 0.9.0: needs a minor bump; the labels declare major —
 *   consistent.`
 */
export function semverSummary(semver: SdkCompatSemver): string {
  if (semver.classification === 'unknown') {
    return 'Unknown: this revision has no classified changelog (a draft, a first release, or not classified yet).';
  }
  const label = semver.classification === 'non-breaking' ? 'Non-breaking' : semver.classification === 'breaking' ? 'Breaking' : 'Docs-only';
  const verdict =
    semver.consistent === true ? 'consistent' : semver.consistent === false ? 'inconsistent' : 'not comparable';
  return `${label} since ${semver.baseline_version ?? 'the previous release'}: needs a ${semver.required_bump} bump; the labels declare ${semver.declared_bump} — ${verdict}.`;
}
