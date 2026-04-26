'use client';

/**
 * Versions tab — per-project surface.
 *
 * Phase 4 rebuilds this against `mockups/versions/detail.html`:
 *
 *   sub-page header  →  KPI band (4)  →  lifecycle pipeline kanban
 *   ────────────────────────────────────────────────────────────
 *   versions table (filter chips + search)   |   selected-rail
 *
 * Data is `/api/versions?projectId=…` only. Per-row quality/lint badges,
 * the trajectory chart, lifecycle alerts, and the activity timeline from
 * the mockup are deferred until the bulk quality + lint endpoints land
 * (Phase 10) — we don't fake numbers we can't back. The right rail and
 * version detail page (Phase 5) compute quality + lint on demand.
 *
 * Branches and tags from the legacy implementation were git-like surface
 * area; with `FEATURE_GITLIKE` off the proxy returns 404 anyway, so the
 * fetches are gone entirely.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSession } from 'next-auth/react';
import {
  Activity,
  Download,
  FileEdit,
  GitBranch,
  GitBranchPlus,
  Rocket,
} from 'lucide-react';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { Alert } from '@/app/components/ui/Alert';
import { ProjectKpiCard } from '@/app/components/ade/dashboard/ProjectKpiCard';
import {
  VersionsLifecyclePipeline,
} from './versionsTab/VersionsLifecyclePipeline';
import {
  VersionsListTable,
  type VersionStatusFilter,
} from './versionsTab/VersionsListTable';
import { VersionDetailRail } from './versionsTab/VersionDetailRail';
import {
  type VersionRow,
  deriveLifecycle,
  relativeTime,
} from './versionsTab/versionLifecycle';

export interface VersionsTabProps {
  projectId: string;
  /** Notifies the parent so it can refresh the tab's count badge. */
  onCountChange?: (count: number | null) => void;
}

interface SessionUserExtensions {
  user_id?: string;
}

const RECENT_WINDOW_MS = 24 * 60 * 60 * 1000;

export function VersionsTab({ projectId, onCountChange }: VersionsTabProps) {
  const { data: session } = useSession();
  const currentUserId = (session?.user as SessionUserExtensions | undefined)?.user_id;

  const [versions, setVersions] = useState<VersionRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [filter, setFilter] = useState<VersionStatusFilter>('all');
  const [search, setSearch] = useState('');

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/versions?projectId=${encodeURIComponent(projectId)}`
      );
      const payload = (await response.json()) as {
        success?: boolean;
        versions?: VersionRow[];
        error?: string;
      };
      if (!response.ok || !payload.success) {
        throw new Error(payload.error || 'Failed to load versions');
      }
      const list = payload.versions ?? [];
      setVersions(list);
      onCountChange?.(list.length);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load versions');
      onCountChange?.(null);
    } finally {
      setIsLoading(false);
    }
  }, [projectId, onCountChange]);

  useEffect(() => {
    void load();
  }, [load]);

  /* Auto-select the most recently updated version once data lands. */
  useEffect(() => {
    if (versions.length === 0) {
      setSelectedVersionId(null);
      return;
    }
    setSelectedVersionId((prev) => {
      if (prev && versions.some((v) => v.id === prev)) return prev;
      const sorted = [...versions].sort(
        (a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)
      );
      return sorted[0].id;
    });
  }, [versions]);

  const selected = useMemo(
    () => versions.find((v) => v.id === selectedVersionId) ?? null,
    [versions, selectedVersionId]
  );

  const kpis = useMemo(() => deriveKpis(versions), [versions]);

  const eyebrow = useMemo(() => {
    if (versions.length === 0) return 'No revisions yet';
    const counts = countByLifecycle(versions);
    const parts: string[] = [
      `${versions.length} ${versions.length === 1 ? 'total' : 'total'}`,
    ];
    if (counts.draft) parts.push(`${counts.draft} ${counts.draft === 1 ? 'draft' : 'drafts'}`);
    if (counts.published) parts.push(`${counts.published} published`);
    if (counts.deprecated) parts.push(`${counts.deprecated} deprecated`);
    if (counts.sunset) parts.push(`${counts.sunset} sunsetting`);
    return parts.join(' · ');
  }, [versions]);

  if (isLoading) {
    return <LoadingState message="Loading versions…" />;
  }

  if (error) {
    return <Alert variant="error">{error}</Alert>;
  }

  if (versions.length === 0) {
    return (
      <EmptyState
        icon={<GitBranch className="w-8 h-8" />}
        title="No versions yet"
        description="Open the Studio editor to commit the first revision of this project's schema."
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Sub-page header — sits inside the dashboard <main>, below the project tabs. */}
      <section className="flex items-end justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold inline-flex items-center gap-2">
            <GitBranch className="w-5 h-5 text-indigo-500" aria-hidden="true" />
            Versions
          </h2>
          <p className="text-xs text-gray-500 font-mono truncate">{eyebrow}</p>
        </div>
        {/* Action buttons are placeholders — the real wiring is on the version
            detail page (Phase 5). Disabled here so we don't paint dead clicks. */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled
            title="Bundle export lands with the version detail page"
            className="px-3 py-1.5 text-sm rounded-md border border-gray-200 dark:border-gray-700 text-gray-400 cursor-not-allowed inline-flex items-center gap-2"
          >
            <Download className="w-4 h-4" aria-hidden="true" /> Export bundle
          </button>
          <button
            type="button"
            disabled
            title="New-version workflow is wired in the version detail page"
            className="px-3 py-1.5 text-sm rounded-md bg-indigo-600/50 text-white cursor-not-allowed inline-flex items-center gap-2"
          >
            <GitBranchPlus className="w-4 h-4" aria-hidden="true" /> New version
          </button>
        </div>
      </section>

      {/* KPI band */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <ProjectKpiCard
          label="Latest published"
          value={kpis.latestPublished?.version_id ?? '—'}
          subtitle={
            kpis.latestPublished
              ? `${relativeTime(kpis.latestPublished.published_at ?? kpis.latestPublished.updated_at)} · ${
                  kpis.latestPublished.creator_name || kpis.latestPublished.creator_email || 'unknown author'
                }`
              : 'Nothing published yet'
          }
          tone={kpis.latestPublished ? 'emerald' : 'slate'}
          icon={<Rocket className="w-4 h-4" />}
        />
        <ProjectKpiCard
          label="Drafts in flight"
          value={kpis.draftCount}
          subtitle={
            kpis.draftCount === 0
              ? 'No drafts open'
              : kpis.draftSamples.map((v) => v.version_id).join(' · ')
          }
          tone={kpis.draftCount > 0 ? 'sky' : 'slate'}
          icon={<FileEdit className="w-4 h-4" />}
        />
        <ProjectKpiCard
          label="Revisions"
          value={versions.length}
          subtitle={
            kpis.deprecatedCount + kpis.sunsetCount > 0
              ? `${kpis.publishedCount} published · ${kpis.deprecatedCount} deprecated`
              : `${kpis.publishedCount} published · ${kpis.draftCount} draft`
          }
          tone="indigo"
          icon={<GitBranch className="w-4 h-4" />}
        />
        <ProjectKpiCard
          label="Updated · 24h"
          value={kpis.recentlyUpdated}
          subtitle={
            kpis.recentlyUpdated === 0
              ? 'No edits in the last day'
              : `${kpis.recentlyUpdated} active`
          }
          tone={kpis.recentlyUpdated > 0 ? 'sky' : 'slate'}
          icon={<Activity className="w-4 h-4" />}
        />
      </section>

      {/* Lifecycle pipeline kanban */}
      <VersionsLifecyclePipeline
        projectId={projectId}
        versions={versions}
        selectedVersionId={selectedVersionId}
      />

      {/* Body grid: table  |  rail */}
      <section className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2 min-w-0">
          <VersionsListTable
            projectId={projectId}
            versions={versions}
            selectedVersionId={selectedVersionId}
            onSelect={setSelectedVersionId}
            filter={filter}
            onFilterChange={setFilter}
            search={search}
            onSearchChange={setSearch}
            currentUserId={currentUserId}
          />
        </div>
        <div className="min-w-0">
          <VersionDetailRail projectId={projectId} version={selected} />
        </div>
      </section>
    </div>
  );
}

interface VersionsKpis {
  latestPublished: VersionRow | null;
  draftCount: number;
  publishedCount: number;
  deprecatedCount: number;
  sunsetCount: number;
  recentlyUpdated: number;
  draftSamples: VersionRow[];
}

function deriveKpis(versions: VersionRow[]): VersionsKpis {
  let latestPublished: VersionRow | null = null;
  let latestPublishedTs = -Infinity;
  const drafts: VersionRow[] = [];
  let recentlyUpdated = 0;
  const counts = countByLifecycle(versions);
  const now = Date.now();

  for (const v of versions) {
    if (v.published) {
      const when = Date.parse(v.published_at ?? v.updated_at);
      if (Number.isFinite(when) && when > latestPublishedTs) {
        latestPublishedTs = when;
        latestPublished = v;
      }
    }
    if (deriveLifecycle(v) === 'draft') drafts.push(v);
    if (now - Date.parse(v.updated_at) <= RECENT_WINDOW_MS) recentlyUpdated += 1;
  }

  drafts.sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));

  return {
    latestPublished,
    draftCount: counts.draft,
    publishedCount: counts.published,
    deprecatedCount: counts.deprecated,
    sunsetCount: counts.sunset,
    recentlyUpdated,
    draftSamples: drafts.slice(0, 2),
  };
}

function countByLifecycle(versions: VersionRow[]) {
  const counts = { draft: 0, published: 0, deprecated: 0, sunset: 0 };
  for (const v of versions) counts[deriveLifecycle(v)] += 1;
  return counts;
}
