'use client';

/**
 * Export studio's **SDK compatibility** tab — SGD-2.1 (#4735).
 *
 * Pick a project and a version (the latest by default) and see the generator compatibility manifest:
 * **Findings** first — every construct a generated artifact leaves out or cannot represent, each with
 * what to do about it — then **Artifacts** (coverage, runtime, auth, pagination per artifact), then
 * **Semver** and **Provenance** (the source, options and per-artifact digests).
 *
 * The data is `GET /api/projects/{id}/sdk-compatibility`, a proxy of the REST route
 * `apiome sdk compatibility` reads; the formatting helpers live in `lib/sdk-compat-manifest.ts`.
 */

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { ShieldCheck } from 'lucide-react';

import { Badge } from '@/app/components/ui/Badge';
import { Card, CardContent, CardHeader } from '@/app/components/ui/Card';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { Label } from '@/app/components/ui/Label';
import { Skeleton } from '@/app/components/ui/Skeleton';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import {
  fetchProjectOptions,
  fetchVersionOptions,
  type ProjectOption,
  type VersionOption,
} from '@/app/ade/dashboard/style-guides/api';
import {
  artifactLabel,
  coverageLabel,
  isComplete,
  semverSummary,
  severityCounts,
  sortedFindings,
  type SdkCompatManifest,
  type SdkCompatSeverity,
} from '@lib/sdk-compat-manifest';

/** The latest-revision choice in the version picker. */
const LATEST = '';

/** Badge tone per severity. */
const SEVERITY_TONE: Record<SdkCompatSeverity, 'error' | 'warning' | 'secondary'> = {
  error: 'error',
  warning: 'warning',
  info: 'secondary',
};

/**
 * Load a manifest from the BFF.
 *
 * @param projectId - The project.
 * @param version - A version label or revision id, or `''` for the latest.
 * @returns The manifest.
 */
async function fetchManifest(projectId: string, version: string): Promise<SdkCompatManifest> {
  const query = version ? `?${new URLSearchParams({ version }).toString()}` : '';
  const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/sdk-compatibility${query}`);
  const json = (await response.json().catch(() => ({}))) as { success?: boolean; data?: SdkCompatManifest; error?: string };
  if (!json.success || !json.data) throw new Error(json.error || 'The compatibility manifest could not be loaded.');
  return json.data;
}

interface SdkCompatClientProps {
  /** Export studio's tab strip, rendered in the page header. */
  tabs: ReactNode;
}

export default function SdkCompatClient({ tabs }: SdkCompatClientProps) {
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [projectId, setProjectId] = useState('');
  const [versions, setVersions] = useState<VersionOption[]>([]);
  const [version, setVersion] = useState(LATEST);
  const [manifest, setManifest] = useState<SdkCompatManifest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    void fetchProjectOptions().then((options) => {
      if (cancelled) return;
      setProjects(options);
      setProjectId((current) => current || options[0]?.id || '');
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    void fetchVersionOptions(projectId).then((options) => {
      if (!cancelled) setVersions(options);
    });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    Promise.resolve()
      .then(() => {
        if (cancelled) return null;
        setLoading(true);
        setError(null);
        return fetchManifest(projectId, version);
      })
      .then((loaded) => {
        if (!cancelled && loaded) setManifest(loaded);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setManifest(null);
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, version, attempt]);

  const findings = useMemo(() => (manifest ? sortedFindings(manifest) : []), [manifest]);
  const counts = useMemo(() => (manifest ? severityCounts(manifest) : null), [manifest]);

  return (
    <Page data-testid="sdk-compat">
      <PageHeader
        breadcrumb={[{ label: 'Home', href: '/ade/dashboard' }, { label: 'Ship' }, { label: 'Export studio' }]}
        title="Export studio"
        description="Whether each generated SDK artifact matches its version, and what to change if not."
        tabs={tabs}
      />
      <PageBody>
        <div className="sdkc-pickers">
          <div className="sdkc-picker">
            <Label htmlFor="sdk-compat-project">Project</Label>
            <select
              id="sdk-compat-project"
              className="hive-control sdkc-picker__select"
              value={projectId}
              onChange={(event) => {
                setProjectId(event.target.value);
                setVersion(LATEST);
              }}
            >
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </div>
          <div className="sdkc-picker">
            <Label htmlFor="sdk-compat-version">Version</Label>
            <select
              id="sdk-compat-version"
              className="hive-control sdkc-picker__select"
              value={version}
              onChange={(event) => setVersion(event.target.value)}
            >
              <option value={LATEST}>Latest</option>
              {versions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        {loading && !manifest ? (
          <div className="sdkc-loading" data-testid="sdk-compat-loading">
            <Skeleton className="sdkc-skeleton" />
            <Skeleton className="sdkc-skeleton" />
          </div>
        ) : null}

        {error ? (
          <ErrorState
            variant="compact"
            title="The compatibility manifest could not be loaded"
            description={error}
            onRetry={() => setAttempt((n) => n + 1)}
            data-testid="sdk-compat-error"
          />
        ) : null}

        {!projectId && !loading ? (
          <EmptyState
            variant="compact"
            icon={<ShieldCheck aria-hidden />}
            title="No projects yet"
            description="Import or create a project to see what its generated SDKs cover."
          />
        ) : null}

        {manifest && !error ? (
          <div className="sdkc-body" data-testid="sdk-compat-manifest">
            <p className="sdkc-summary">
              <strong>{manifest.api.title ?? 'This API'}</strong> {manifest.source.version_label ?? manifest.api.version} ·{' '}
              {manifest.constructs.operations} operations ({manifest.constructs.http_operations} over HTTP) ·{' '}
              {manifest.artifacts.length} artifacts
            </p>

            <Card className="sdkc-card" data-testid="sdk-compat-findings">
              <CardHeader className="sdkc-card__header">
                <h2 className="sdkc-card__title">Findings</h2>
                {counts ? (
                  <div className="sdkc-counts">
                    {(['error', 'warning', 'info'] as const).map((severity) =>
                      counts[severity] ? (
                        <Badge key={severity} variant={SEVERITY_TONE[severity]}>
                          {counts[severity]} {severity}
                        </Badge>
                      ) : null,
                    )}
                  </div>
                ) : null}
              </CardHeader>
              <CardContent>
                {findings.length === 0 ? (
                  <p className="sdkc-clean" data-testid="sdk-compat-clean">
                    Every artifact represents every construct of this version.
                  </p>
                ) : (
                  <ul className="sdkc-findings">
                    {findings.map((finding, index) => (
                      <li
                        key={`${finding.artifact}-${finding.code}-${finding.subject}-${index}`}
                        className="sdkc-finding"
                        data-testid="sdk-compat-finding"
                      >
                        <div className="sdkc-finding__head">
                          <Badge variant={SEVERITY_TONE[finding.severity]}>{finding.severity}</Badge>
                          <span className="sdkc-finding__artifact">{artifactLabel(finding.artifact)}</span>
                          <code className="mono sdkc-finding__subject">{finding.subject}</code>
                          <code className="mono sdkc-finding__code">{finding.code}</code>
                        </div>
                        <p className="sdkc-finding__reason">{finding.reason}</p>
                        <p className="sdkc-finding__action">
                          <strong>What to do:</strong> {finding.action}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            <Card className="sdkc-card" data-testid="sdk-compat-artifacts">
              <CardHeader className="sdkc-card__header">
                <h2 className="sdkc-card__title">Artifacts</h2>
              </CardHeader>
              <CardContent>
                <table className="sdkc-table">
                  <thead>
                    <tr>
                      <th scope="col">Artifact</th>
                      <th scope="col">Coverage</th>
                      <th scope="col">Runtime</th>
                      <th scope="col">Auth</th>
                      <th scope="col">Pagination</th>
                      <th scope="col">Findings</th>
                    </tr>
                  </thead>
                  <tbody>
                    {manifest.artifacts.map((artifact) => (
                      <tr key={artifact.id} data-testid={`sdk-compat-artifact-${artifact.id}`}>
                        <th scope="row">
                          <span className="sdkc-table__name">{artifactLabel(artifact.id)}</span>
                          <span className="sdkc-table__sub mono">{artifact.directory}/</span>
                        </th>
                        <td>
                          <Badge variant={isComplete(artifact) ? 'success' : artifact.included ? 'warning' : 'error'}>
                            {coverageLabel(artifact)}
                          </Badge>
                        </td>
                        <td className="sdkc-table__sub">
                          {artifact.runtime?.language_version ?? '—'}
                          {artifact.runtime?.dependencies.length ? (
                            <span className="sdkc-table__deps mono"> · {artifact.runtime.dependencies.join(', ')}</span>
                          ) : null}
                        </td>
                        <td className="sdkc-table__sub">
                          {artifact.auth == null
                            ? 'n/a'
                            : artifact.auth.unsupported.length
                              ? `Unsupported: ${artifact.auth.unsupported.join(', ')}`
                              : artifact.auth.supported.length
                                ? artifact.auth.supported.join(', ')
                                : 'None declared'}
                        </td>
                        <td className="sdkc-table__sub">
                          {artifact.pagination == null
                            ? 'n/a'
                            : artifact.pagination.mode === 'manual'
                              ? `Manual (${artifact.pagination.parameters.join(', ')})`
                              : 'None'}
                        </td>
                        <td>{artifact.findings.length}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>

            <Card className="sdkc-card" data-testid="sdk-compat-semver">
              <CardHeader className="sdkc-card__header">
                <h2 className="sdkc-card__title">Semver and provenance</h2>
              </CardHeader>
              <CardContent className="sdkc-provenance">
                <p>{semverSummary(manifest.semver)}</p>
                <dl className="sdkc-digests">
                  <dt>Source</dt>
                  <dd className="mono">{manifest.source.digest}</dd>
                  <dt>Options</dt>
                  <dd className="mono">{manifest.options.digest}</dd>
                  <dt>Schema</dt>
                  <dd className="mono">{manifest.schema_version}</dd>
                </dl>
              </CardContent>
            </Card>
          </div>
        ) : null}
      </PageBody>
    </Page>
  );
}
