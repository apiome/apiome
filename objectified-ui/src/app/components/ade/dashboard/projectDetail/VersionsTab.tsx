'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Activity, GitBranch, Info, Tag } from 'lucide-react';
import {
  projectPanelClass,
  projectPanelHeaderClass,
} from '../dashboardScreenClasses';
import { ProjectStatusChip, type ProjectStatusKind } from '../ProjectStatusChip';
import { LoadingState } from '../../../ui/LoadingState';
import { EmptyState } from '../../../ui/EmptyState';
import { Alert } from '../../../ui/Alert';

export interface VersionsTabProps {
  projectId: string;
  /** Notifies the parent so it can refresh the tab's count badge. */
  onCountChange?: (count: number | null) => void;
}

interface VersionRow {
  id: string;
  version_id: string;
  enabled: boolean;
  published: boolean;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  published_at: string | null;
  creator_name?: string;
  creator_email?: string;
  shortMessage?: string | null;
  changelog?: string | null;
  parent_version_id?: string | null;
  lifecycle?: string;
}

interface VersionBranchRow {
  id: string;
  name: string;
  tip_version_id: string;
  tip_version_string?: string;
  is_default?: boolean;
  protected?: boolean;
  updated_at?: string;
}

interface VersionTagRow {
  id: string;
  name: string;
  version_id: string;
  target_version_string?: string;
  channel?: string | null;
  message?: string | null;
  immutable?: boolean;
  protected?: boolean;
}

function lifecycleToKind(version: VersionRow): ProjectStatusKind {
  if (version.deleted_at) return 'deleted';
  if (version.published) return 'published';
  const lc = (version.lifecycle ?? '').toLowerCase();
  if (lc === 'deprecated') return 'deprecated';
  if (lc === 'archived') return 'disabled';
  if (lc === 'beta') return 'inReview';
  return 'draft';
}

function relativeTime(iso?: string | null): string {
  if (!iso) return '—';
  const ts = Date.parse(iso);
  if (!Number.isFinite(ts)) return '—';
  const diff = Date.now() - ts;
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} d ago`;
  const months = Math.round(days / 30);
  if (months < 12) return `${months} mo ago`;
  return `${Math.round(months / 12)} y ago`;
}

export function VersionsTab({ projectId, onCountChange }: VersionsTabProps) {
  const [versions, setVersions] = useState<VersionRow[]>([]);
  const [branches, setBranches] = useState<VersionBranchRow[]>([]);
  const [tags, setTags] = useState<VersionTagRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [versionsRes, branchesRes, tagsRes] = await Promise.all([
        fetch(`/api/versions?projectId=${encodeURIComponent(projectId)}`),
        fetch(`/api/projects/${projectId}/version-branches`),
        fetch(`/api/projects/${projectId}/version-tags`),
      ]);

      const versionsJson = (await versionsRes.json()) as {
        success?: boolean;
        versions?: VersionRow[];
        error?: string;
      };
      if (!versionsRes.ok || !versionsJson.success) {
        throw new Error(versionsJson.error || 'Failed to load versions');
      }
      const list = versionsJson.versions ?? [];
      setVersions(list);
      if (list.length > 0 && !selectedVersionId) {
        setSelectedVersionId(list[0].id);
      }
      onCountChange?.(list.length);

      const branchesJson = (await branchesRes.json()) as {
        success?: boolean;
        branches?: VersionBranchRow[];
      };
      if (branchesRes.ok && branchesJson.success) setBranches(branchesJson.branches ?? []);

      const tagsJson = (await tagsRes.json()) as {
        success?: boolean;
        tags?: VersionTagRow[];
      };
      if (tagsRes.ok && tagsJson.success) setTags(tagsJson.tags ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load versions');
      onCountChange?.(null);
    } finally {
      setIsLoading(false);
    }
  }, [projectId, selectedVersionId, onCountChange]);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = useMemo(
    () => versions.find((v) => v.id === selectedVersionId) ?? null,
    [versions, selectedVersionId]
  );

  const counts = useMemo(() => {
    const c = { total: versions.length, published: 0, draft: 0, deprecated: 0 };
    for (const v of versions) {
      if (v.published) c.published += 1;
      else if ((v.lifecycle ?? '').toLowerCase() === 'deprecated') c.deprecated += 1;
      else c.draft += 1;
    }
    return c;
  }, [versions]);

  if (isLoading) return <LoadingState message="Loading versions…" />;
  if (error) return <Alert variant="error">{error}</Alert>;
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
      <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiTile label="Versions" value={counts.total} />
        <KpiTile label="Published" value={counts.published} tone="positive" />
        <KpiTile label="Drafts" value={counts.draft} />
        <KpiTile label="Deprecated" value={counts.deprecated} tone="warning" />
      </section>

      <section className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className={`${projectPanelClass} xl:col-span-2`}>
          <div className={projectPanelHeaderClass}>
            <div className="flex items-center gap-3">
              <GitBranch className="w-5 h-5 text-indigo-500" />
              <div>
                <h3 className="text-base font-semibold">Revisions</h3>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  All committed schema revisions, newest first
                </p>
              </div>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-[10px] uppercase tracking-wider text-gray-500 bg-gray-50 dark:bg-gray-900">
                <tr>
                  <th className="text-left px-4 py-2 font-semibold">Version</th>
                  <th className="text-left px-4 py-2 font-semibold">Status</th>
                  <th className="text-left px-4 py-2 font-semibold">Author</th>
                  <th className="text-left px-4 py-2 font-semibold">Message</th>
                  <th className="text-right px-4 py-2 font-semibold">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700/60">
                {versions.map((version) => {
                  const kind = lifecycleToKind(version);
                  const isSelected = version.id === selectedVersionId;
                  return (
                    <tr
                      key={version.id}
                      onClick={() => setSelectedVersionId(version.id)}
                      className={`cursor-pointer ${
                        isSelected
                          ? 'bg-indigo-500/5'
                          : 'hover:bg-gray-50/60 dark:hover:bg-gray-900/30'
                      }`}
                    >
                      <td className="px-4 py-2.5 font-mono text-xs">
                        v{version.version_id}
                      </td>
                      <td className="px-4 py-2.5">
                        <ProjectStatusChip kind={kind} />
                      </td>
                      <td className="px-4 py-2.5 text-xs text-gray-500">
                        {version.creator_name || '—'}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-gray-600 dark:text-gray-300 max-w-xs truncate">
                        {version.shortMessage || (
                          <span className="italic text-gray-400">no message</span>
                        )}
                      </td>
                      <td className="px-4 py-2.5 text-right text-[11px] text-gray-500 font-mono">
                        {relativeTime(version.updated_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        <div className="space-y-6">
          <div className={projectPanelClass}>
            <div className={projectPanelHeaderClass}>
              <div className="flex items-center gap-3">
                <Info className="w-5 h-5 text-indigo-500" />
                <div>
                  <h3 className="text-base font-semibold">Selected revision</h3>
                  <p className="text-xs text-gray-500 dark:text-gray-400">
                    {selected ? `v${selected.version_id}` : 'Pick a row on the left'}
                  </p>
                </div>
              </div>
            </div>
            <div className="p-5 space-y-3 text-xs">
              {selected ? (
                <>
                  <DetailRow label="Status">
                    <ProjectStatusChip kind={lifecycleToKind(selected)} />
                  </DetailRow>
                  <DetailRow label="Author">{selected.creator_name || '—'}</DetailRow>
                  <DetailRow label="Created">
                    {relativeTime(selected.created_at)}
                  </DetailRow>
                  <DetailRow label="Updated">
                    {relativeTime(selected.updated_at)}
                  </DetailRow>
                  <DetailRow label="Published">
                    {selected.published_at ? relativeTime(selected.published_at) : '—'}
                  </DetailRow>
                  <DetailRow label="Lifecycle">
                    <span className="font-mono">{selected.lifecycle ?? '—'}</span>
                  </DetailRow>
                  {selected.changelog ? (
                    <div>
                      <p className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1">
                        Changelog
                      </p>
                      <p className="text-xs text-gray-600 dark:text-gray-300 whitespace-pre-line">
                        {selected.changelog}
                      </p>
                    </div>
                  ) : null}
                </>
              ) : (
                <p className="text-gray-500 italic">Select a revision to inspect.</p>
              )}
            </div>
          </div>

          <div className={projectPanelClass}>
            <div className={projectPanelHeaderClass}>
              <div className="flex items-center gap-3">
                <GitBranch className="w-5 h-5 text-indigo-500" />
                <h3 className="text-base font-semibold">Branches</h3>
                <span className="text-[10px] font-mono text-gray-500">{branches.length}</span>
              </div>
            </div>
            <ul className="divide-y divide-gray-100 dark:divide-gray-700/60 text-xs">
              {branches.length === 0 ? (
                <li className="px-5 py-4 text-gray-500 italic">No branches.</li>
              ) : (
                branches.map((branch) => (
                  <li key={branch.id} className="px-5 py-3 flex items-center gap-3">
                    <GitBranch className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                    <span className="font-mono text-sm flex-1 min-w-0 truncate">
                      {branch.name}
                    </span>
                    {branch.is_default ? (
                      <span className="text-[9px] uppercase font-semibold text-indigo-500">
                        default
                      </span>
                    ) : null}
                    {branch.protected ? (
                      <span className="text-[9px] uppercase font-semibold text-amber-500">
                        protected
                      </span>
                    ) : null}
                    <span className="font-mono text-[11px] text-gray-500 truncate">
                      v{branch.tip_version_string ?? branch.tip_version_id}
                    </span>
                  </li>
                ))
              )}
            </ul>
          </div>

          <div className={projectPanelClass}>
            <div className={projectPanelHeaderClass}>
              <div className="flex items-center gap-3">
                <Tag className="w-5 h-5 text-indigo-500" />
                <h3 className="text-base font-semibold">Tags</h3>
                <span className="text-[10px] font-mono text-gray-500">{tags.length}</span>
              </div>
            </div>
            <ul className="divide-y divide-gray-100 dark:divide-gray-700/60 text-xs">
              {tags.length === 0 ? (
                <li className="px-5 py-4 text-gray-500 italic">No tags.</li>
              ) : (
                tags.map((tag) => (
                  <li key={tag.id} className="px-5 py-3 flex items-center gap-3">
                    <Tag className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                    <span className="font-mono text-sm flex-1 min-w-0 truncate">
                      {tag.name}
                    </span>
                    {tag.channel ? (
                      <span className="text-[10px] font-mono text-gray-500">
                        {tag.channel}
                      </span>
                    ) : null}
                    {tag.immutable ? (
                      <Activity className="w-3 h-3 text-amber-500" />
                    ) : null}
                    <span className="font-mono text-[11px] text-gray-500">
                      v{tag.target_version_string ?? tag.version_id}
                    </span>
                  </li>
                ))
              )}
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}

function KpiTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: 'positive' | 'warning';
}) {
  const valueClass =
    tone === 'positive'
      ? 'text-emerald-500'
      : tone === 'warning'
        ? 'text-amber-500'
        : '';
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
      <p className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
        {label}
      </p>
      <p className={`text-2xl font-bold font-mono mt-1.5 ${valueClass}`}>{value}</p>
    </div>
  );
}

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold shrink-0">
        {label}
      </dt>
      <dd className="text-right text-xs">{children}</dd>
    </div>
  );
}
