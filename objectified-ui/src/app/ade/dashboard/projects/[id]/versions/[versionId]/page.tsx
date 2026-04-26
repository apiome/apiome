'use client';

/**
 * Version detail page — `/ade/dashboard/projects/[id]/versions/[versionId]`.
 *
 * Layout mirrors `mockups/versions/version.html`:
 *
 *   project header + tabs (versions active)
 *   ──────────────────────────────────────
 *   version sub-page header + hero metadata strip
 *   ──────────────────────────────────────
 *   ┌──────── 2/3 ────────┐ ┌─── 1/3 ───┐
 *   │ Quality + Lint      │ │ Lineage    │
 *   │ Release notes       │ │ Lifecycle  │
 *   │                     │ │ Activity   │
 *   └─────────────────────┘ └────────────┘
 *
 * Phase 5 wires the live `/api/version-quality/[versionId]` and
 * `/api/version-lint/[versionId]` proxies so users can compute quality and
 * run lint on demand. Schema-scope (per-class change tags), real lineage
 * with children, scoped activity, and lifecycle history each need their
 * own server surfaces and ship in later phases — they render here as
 * deferred placeholders so the layout matches the mockup but no fake data
 * leaks into the UI.
 */

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  FileText,
  GitFork,
  Loader2,
  Route,
} from 'lucide-react';
import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import {
  dashboardContentStackClass,
  dashboardMainClass,
} from '@/app/components/ade/dashboard/dashboardScreenClasses';
import { DetailHeader } from '@/app/components/ade/dashboard/projectDetail/DetailHeader';
import { DetailTabs } from '@/app/components/ade/dashboard/projectDetail/DetailTabs';
import {
  VersionDetailHeader,
  type VersionDetailHeaderQuality,
} from '@/app/components/ade/dashboard/versionDetail/VersionDetailHeader';
import {
  QualityLintPanels,
  type LintFinding,
  type LintResult,
  type PanelState,
  type QualitySnapshot,
} from '@/app/components/ade/dashboard/versionDetail/QualityLintPanels';
import {
  type VersionRow,
  relativeTime,
} from '@/app/components/ade/dashboard/projectDetail/versionsTab/versionLifecycle';
import type { Project } from '@/app/components/ade/dashboard/projectTypes';

interface VersionApiResponse {
  success: boolean;
  version?: VersionRow;
  error?: string;
}

interface ProjectApiResponse {
  success: boolean;
  project?: Project;
  error?: string;
}

interface QualityApiResponse {
  success: boolean;
  snapshot?: QualitySnapshot | null;
  previous?: QualitySnapshot | null;
  error?: string;
}

interface LintApiResponse {
  success: boolean;
  result?: LintResult | null;
  findings?: LintFinding[];
  previous?: LintResult | null;
  error?: string;
}

export default function VersionDetailPage() {
  const params = useParams<{ id: string; versionId: string }>();
  const router = useRouter();
  const projectId = params?.id;
  const versionId = params?.versionId;

  const [project, setProject] = useState<Project | null>(null);
  const [version, setVersion] = useState<VersionRow | null>(null);
  const [shellLoading, setShellLoading] = useState(true);
  const [shellError, setShellError] = useState<string | null>(null);

  const [quality, setQuality] = useState<QualitySnapshot | null>(null);
  const [qualityPrevious, setQualityPrevious] = useState<QualitySnapshot | null>(null);
  const [qualityState, setQualityState] = useState<PanelState>('loading');
  const [qualityError, setQualityError] = useState<string | null>(null);

  const [lintResult, setLintResult] = useState<LintResult | null>(null);
  const [lintFindings, setLintFindings] = useState<LintFinding[]>([]);
  const [lintPrevious, setLintPrevious] = useState<LintResult | null>(null);
  const [lintState, setLintState] = useState<PanelState>('loading');
  const [lintError, setLintError] = useState<string | null>(null);

  const loadShell = useCallback(async () => {
    if (!projectId || !versionId) return;
    setShellLoading(true);
    setShellError(null);
    try {
      const [projectResp, versionResp] = await Promise.all([
        fetch(`/api/projects/${projectId}`),
        fetch(`/api/versions/${encodeURIComponent(versionId)}?projectId=${encodeURIComponent(projectId)}`),
      ]);

      if (projectResp.status === 404) {
        setShellError('Project not found');
        return;
      }
      if (!projectResp.ok) {
        throw new Error(`Failed to load project (${projectResp.status})`);
      }
      const projectPayload = (await projectResp.json()) as ProjectApiResponse;
      if (!projectPayload.success || !projectPayload.project) {
        throw new Error(projectPayload.error || 'Failed to load project');
      }
      setProject(projectPayload.project);

      if (versionResp.status === 404) {
        setShellError('Version not found in this project');
        return;
      }
      if (!versionResp.ok) {
        throw new Error(`Failed to load version (${versionResp.status})`);
      }
      const versionPayload = (await versionResp.json()) as VersionApiResponse;
      if (!versionPayload.success || !versionPayload.version) {
        throw new Error(versionPayload.error || 'Failed to load version');
      }
      setVersion(versionPayload.version);
    } catch (e) {
      setShellError(e instanceof Error ? e.message : 'Failed to load version');
    } finally {
      setShellLoading(false);
    }
  }, [projectId, versionId]);

  useEffect(() => {
    void loadShell();
  }, [loadShell]);

  /* Quality + lint are split from the shell: they render placeholders
     while loading instead of blocking the whole page, and a failure to
     reach one doesn't prevent the rest of the page from rendering. */
  const loadQuality = useCallback(async () => {
    if (!projectId || !versionId) return;
    setQualityState('loading');
    setQualityError(null);
    try {
      const resp = await fetch(
        `/api/version-quality/${encodeURIComponent(versionId)}?projectId=${encodeURIComponent(projectId)}`,
      );
      const payload = (await resp.json()) as QualityApiResponse;
      if (!resp.ok || !payload.success) {
        throw new Error(payload.error || 'Failed to load quality snapshot');
      }
      setQuality(payload.snapshot ?? null);
      setQualityPrevious(payload.previous ?? null);
      setQualityState('idle');
    } catch (e) {
      setQualityError(e instanceof Error ? e.message : 'Failed to load quality');
      setQualityState('error');
    }
  }, [projectId, versionId]);

  const loadLint = useCallback(async () => {
    if (!projectId || !versionId) return;
    setLintState('loading');
    setLintError(null);
    try {
      const resp = await fetch(
        `/api/version-lint/${encodeURIComponent(versionId)}?projectId=${encodeURIComponent(projectId)}`,
      );
      const payload = (await resp.json()) as LintApiResponse;
      if (!resp.ok || !payload.success) {
        throw new Error(payload.error || 'Failed to load lint result');
      }
      setLintResult(payload.result ?? null);
      setLintFindings(payload.findings ?? []);
      setLintPrevious(payload.previous ?? null);
      setLintState('idle');
    } catch (e) {
      setLintError(e instanceof Error ? e.message : 'Failed to load lint');
      setLintState('error');
    }
  }, [projectId, versionId]);

  useEffect(() => {
    if (!projectId || !versionId) return;
    void loadQuality();
    void loadLint();
  }, [projectId, versionId, loadQuality, loadLint]);

  const computeQuality = useCallback(async () => {
    if (!projectId || !versionId) return;
    setQualityState('busy');
    setQualityError(null);
    try {
      const resp = await fetch(
        `/api/version-quality/${encodeURIComponent(versionId)}?projectId=${encodeURIComponent(projectId)}`,
        { method: 'POST' },
      );
      const payload = (await resp.json()) as QualityApiResponse;
      if (!resp.ok || !payload.success || !payload.snapshot) {
        throw new Error(payload.error || 'Failed to compute quality');
      }
      setQuality(payload.snapshot);
      setQualityPrevious(payload.previous ?? quality ?? null);
      setQualityState('idle');
    } catch (e) {
      setQualityError(e instanceof Error ? e.message : 'Failed to compute quality');
      setQualityState('error');
    }
  }, [projectId, versionId, quality]);

  const runLint = useCallback(async () => {
    if (!projectId || !versionId) return;
    setLintState('busy');
    setLintError(null);
    try {
      const resp = await fetch(
        `/api/version-lint/${encodeURIComponent(versionId)}?projectId=${encodeURIComponent(projectId)}`,
        { method: 'POST' },
      );
      const payload = (await resp.json()) as LintApiResponse;
      if (!resp.ok || !payload.success || !payload.result) {
        throw new Error(payload.error || 'Failed to run lint');
      }
      setLintResult(payload.result);
      setLintFindings(payload.findings ?? []);
      setLintPrevious(payload.previous ?? lintResult ?? null);
      setLintState('idle');
    } catch (e) {
      setLintError(e instanceof Error ? e.message : 'Failed to run lint');
      setLintState('error');
    }
  }, [projectId, versionId, lintResult]);

  if (shellLoading) {
    return (
      <main className={dashboardMainClass}>
        <LoadingState message="Loading version…" />
      </main>
    );
  }

  if (shellError || !project || !version) {
    return (
      <main className={dashboardMainClass}>
        <div className={dashboardContentStackClass}>
          <Alert variant="error">{shellError || 'Version not available'}</Alert>
          <EmptyState
            icon={<Loader2 className="w-8 h-8" />}
            title="Version not available"
            description="This version may have been deleted, or you may not have access."
            action={
              <Button onClick={() => router.push(`/ade/dashboard/projects/${projectId ?? ''}?tab=versions`)}>
                <ArrowLeft className="w-4 h-4 mr-1.5" /> Back to versions
              </Button>
            }
          />
        </div>
      </main>
    );
  }

  const headerQuality: VersionDetailHeaderQuality | null =
    quality || lintResult
      ? {
          overall: quality?.overall ?? null,
          lintGrade: lintResult?.grade ?? null,
          computedAt: quality?.computed_at ?? null,
        }
      : null;

  return (
    <div className="flex-1 flex flex-col min-w-0">
      <DetailHeader project={project}>
        <DetailTabs projectId={project.id} active="versions" />
      </DetailHeader>

      <main className="flex-1 overflow-y-auto">
        <VersionDetailHeader
          projectId={project.id}
          version={version}
          quality={headerQuality}
        />

        <div className="p-6 grid grid-cols-1 xl:grid-cols-3 gap-6">
          <div className="xl:col-span-2 space-y-6 min-w-0">
            <QualityLintPanels
              quality={quality}
              qualityPrevious={qualityPrevious}
              qualityState={qualityState}
              qualityError={qualityError}
              onComputeQuality={computeQuality}
              lint={lintResult}
              lintFindings={lintFindings}
              lintPrevious={lintPrevious}
              lintState={lintState}
              lintError={lintError}
              onRunLint={runLint}
            />

            <ReleaseNotes version={version} />
          </div>

          <aside className="space-y-6 min-w-0">
            <LineagePanel projectId={project.id} version={version} />
            <LifecycleHistoryPlaceholder version={version} />
            <ActivityPlaceholder projectId={project.id} />
          </aside>
        </div>
      </main>
    </div>
  );
}

/* ---------- Right-rail panels ---------- */

interface LineagePanelProps {
  projectId: string;
  version: VersionRow;
}

function LineagePanel({ projectId, version }: LineagePanelProps) {
  const versionsHref = `/ade/dashboard/projects/${projectId}?tab=versions`;
  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <GitFork className="w-4 h-4 text-indigo-500" aria-hidden="true" /> Lineage
        </h3>
        <Link href={versionsHref} className="text-[10px] font-mono text-indigo-500 hover:underline">
          all versions →
        </Link>
      </header>

      <ul className="space-y-3">
        {version.parent_version_id ? (
          <li className="flex items-start gap-3">
            <span className="w-7 h-7 rounded-full border-2 border-slate-400 bg-slate-50 dark:bg-slate-900/40 text-slate-500 flex items-center justify-center shrink-0">
              <GitFork className="w-3.5 h-3.5" aria-hidden="true" />
            </span>
            <div className="flex-1 min-w-0 pt-0.5">
              <p className="font-mono text-sm font-semibold text-indigo-600 dark:text-indigo-400 truncate">
                {version.parent_version_id}
              </p>
              <p className="text-[11px] text-gray-500 font-mono">parent revision</p>
            </div>
          </li>
        ) : (
          <li className="flex items-start gap-3 text-[11px] text-gray-400 italic">
            no parent · this is a root revision
          </li>
        )}

        <li className="flex items-start gap-3">
          <span className="w-7 h-7 rounded-full border-2 border-emerald-500 bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600 flex items-center justify-center shrink-0">
            <ArrowRight className="w-3.5 h-3.5" aria-hidden="true" />
          </span>
          <div className="flex-1 min-w-0 pt-0.5">
            <p className="font-mono text-sm font-bold">{version.version_id}</p>
            <p className="text-[11px] text-emerald-600 dark:text-emerald-400 font-mono">
              this version · updated {relativeTime(version.updated_at)}
            </p>
          </div>
        </li>
      </ul>

      <p className="mt-4 text-[10px] font-mono text-gray-400">
        Child revisions list lands when the per-version successor index ships.
      </p>
    </section>
  );
}

interface LifecycleHistoryPlaceholderProps {
  version: VersionRow;
}

function LifecycleHistoryPlaceholder({ version }: LifecycleHistoryPlaceholderProps) {
  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Route className="w-4 h-4 text-indigo-500" aria-hidden="true" /> Lifecycle history
        </h3>
      </header>
      <ul className="space-y-3 text-[11px]">
        <li className="flex items-start gap-2">
          <span className="w-2 h-2 rounded-full bg-slate-400 mt-1 shrink-0" aria-hidden="true" />
          <div>
            <p className="text-gray-700 dark:text-gray-200">
              Created {relativeTime(version.created_at)}
            </p>
            <p className="text-gray-500 font-mono">draft created</p>
          </div>
        </li>
        {version.published_at ? (
          <li className="flex items-start gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500 mt-1 shrink-0" aria-hidden="true" />
            <div>
              <p className="text-gray-700 dark:text-gray-200">
                Published {relativeTime(version.published_at)}
              </p>
              <p className="text-gray-500 font-mono">draft → published</p>
            </div>
          </li>
        ) : null}
      </ul>
      <p className="mt-3 text-[10px] font-mono text-gray-400">
        Full audit timeline lands with the workflow phase.
      </p>
    </section>
  );
}

function ActivityPlaceholder({ projectId }: { projectId: string }) {
  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
      <header className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Activity className="w-4 h-4 text-indigo-500" aria-hidden="true" /> Activity
        </h3>
        <Link
          href={`/ade/dashboard/projects/${projectId}?tab=activity`}
          className="text-[10px] font-mono text-indigo-500 hover:underline"
        >
          project log →
        </Link>
      </header>
      <p className="text-[11px] text-gray-500 dark:text-gray-400">
        Version-scoped activity will surface here once the audit query supports
        per-version filters. Until then, the project-wide activity log is the
        canonical source.
      </p>
    </section>
  );
}

interface ReleaseNotesProps {
  version: VersionRow;
}

function ReleaseNotes({ version }: ReleaseNotesProps) {
  const body = version.changelog?.trim() || version.message?.trim() || null;
  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
      <header className="px-5 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <FileText className="w-5 h-5 text-indigo-500" aria-hidden="true" />
          <div>
            <h3 className="text-base font-semibold">Release notes</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Authored by the publisher. Inline editing lands in a later phase.
            </p>
          </div>
        </div>
      </header>
      <div className="px-5 py-4 text-sm">
        {body ? (
          <pre className="whitespace-pre-wrap font-sans text-sm text-gray-700 dark:text-gray-200 leading-relaxed">
            {body}
          </pre>
        ) : (
          <p className="text-xs italic text-gray-400">
            No release notes recorded for this revision.
          </p>
        )}
      </div>
    </section>
  );
}
