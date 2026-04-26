'use client';

/**
 * Lifecycle pipeline kanban — the headline differentiator of the Versions tab.
 *
 * Versions are grouped into four lanes (Draft, Published, Deprecated, Sunset)
 * via `deriveLifecycle`. Each card is a click target that opens the version
 * detail page. The kanban is read-only for now: drag-and-drop transitions
 * (publish, deprecate, schedule sunset) live behind real-action endpoints
 * that aren't part of the Phase 4 surface — those buttons live on the version
 * detail page in Phase 5 and would simply mutate state and reload here.
 *
 * Trajectory toggle and per-card quality/lint badges from the mockup are
 * intentionally deferred until the bulk quality + lint endpoints land
 * (Phase 10). We don't fake numbers we can't back.
 */

import Link from 'next/link';
import { Kanban, Plus } from 'lucide-react';
import {
  type VersionRow,
  type VersionLifecycle,
  LIFECYCLE_ORDER,
  authorGradient,
  authorInitials,
  deriveLifecycle,
  lifecycleStyle,
  relativeTime,
} from './versionLifecycle';

interface VersionsLifecyclePipelineProps {
  projectId: string;
  versions: VersionRow[];
  selectedVersionId: string | null;
}

const MAX_CARDS_PER_LANE = 5;

const LANE_DESCRIPTIONS: Record<VersionLifecycle, string> = {
  draft: 'In-progress revisions not yet published.',
  published: 'Live revisions consumers can resolve to.',
  deprecated: 'Still resolvable, but flagged for migration.',
  sunset: 'Scheduled for removal — notify pinned consumers.',
};

export function VersionsLifecyclePipeline({
  projectId,
  versions,
  selectedVersionId,
}: VersionsLifecyclePipelineProps) {
  const lanes: Record<VersionLifecycle, VersionRow[]> = {
    draft: [],
    published: [],
    deprecated: [],
    sunset: [],
  };
  for (const v of versions) lanes[deriveLifecycle(v)].push(v);

  for (const k of LIFECYCLE_ORDER) {
    lanes[k].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
  }

  return (
    <section className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 min-w-0">
          <Kanban className="w-5 h-5 text-indigo-500 shrink-0" aria-hidden="true" />
          <div className="min-w-0">
            <h3 className="text-base font-semibold">Lifecycle pipeline</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Versions grouped by lifecycle stage. Click a card to inspect the revision.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-3 p-4">
        {LIFECYCLE_ORDER.map((kind) => {
          const style = lifecycleStyle(kind);
          const items = lanes[kind];
          const visible = items.slice(0, MAX_CARDS_PER_LANE);
          const overflow = items.length - visible.length;
          return (
            <div
              key={kind}
              className={`rounded-md border p-3 min-h-[260px] flex flex-col gap-2 ${style.laneHeaderClass}`}
              aria-label={`${style.label} lane`}
            >
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2 min-w-0">
                  <span className={`w-2 h-2 rounded-full ${style.dotClass}`} aria-hidden="true" />
                  <h4
                    className={`text-xs font-semibold uppercase tracking-wider ${style.laneTitleClass}`}
                  >
                    {style.label}
                  </h4>
                  <span className="text-[10px] font-mono text-gray-400">{items.length}</span>
                </div>
              </div>
              <p className="text-[10px] text-gray-500 dark:text-gray-400 -mt-1">
                {LANE_DESCRIPTIONS[kind]}
              </p>

              {visible.length === 0 ? (
                <p className="text-[11px] italic text-gray-400 dark:text-gray-500 my-3">
                  No {style.label.toLowerCase()} revisions.
                </p>
              ) : (
                visible.map((version) => (
                  <PipelineCard
                    key={version.id}
                    projectId={projectId}
                    version={version}
                    selected={selectedVersionId === version.id}
                  />
                ))
              )}

              {overflow > 0 ? (
                <p className="mt-auto text-[11px] text-gray-400 inline-flex items-center gap-1.5">
                  <Plus className="w-3 h-3" aria-hidden="true" />
                  {overflow} more · use the table below
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

interface PipelineCardProps {
  projectId: string;
  version: VersionRow;
  selected: boolean;
}

function PipelineCard({ projectId, version, selected }: PipelineCardProps) {
  const kind = deriveLifecycle(version);
  const style = lifecycleStyle(kind);
  const initials = authorInitials(version.creator_name, version.creator_email);
  const gradient = authorGradient(version.creator_id ?? version.creator_name);
  const message =
    version.shortMessage?.trim() ||
    version.changelog?.split(/\n+/)[0]?.trim() ||
    null;
  const detailHref = `/ade/dashboard/projects/${projectId}/versions/${version.id}`;
  const ringClass = selected
    ? 'ring-2 ring-indigo-500/60 ring-offset-1 ring-offset-white dark:ring-offset-gray-800'
    : '';

  return (
    <Link
      href={detailHref}
      className={`block w-full bg-white dark:bg-gray-800 rounded-md border p-3 transition-shadow transition-colors transition-transform duration-100 hover:-translate-y-px hover:shadow-md hover:border-indigo-300 dark:hover:border-indigo-600 ${style.cardBorderClass} ${ringClass}`}
    >
      <div className="flex items-center justify-between mb-1.5 gap-2">
        <span className="font-mono text-xs font-semibold truncate" title={version.version_id}>
          {version.version_id}
        </span>
        <span className="text-[9px] font-mono text-gray-400 shrink-0">
          {relativeTime(version.updated_at)}
        </span>
      </div>
      <p
        className="text-[11px] text-gray-500 dark:text-gray-400 truncate"
        title={message ?? undefined}
      >
        {message ?? <span className="italic text-gray-400">no message</span>}
      </p>
      <div className="mt-2.5 flex items-center justify-between text-[10px]">
        <span className="font-mono text-gray-400 truncate">
          {version.creator_name || version.creator_email || '—'}
        </span>
        <span
          className={`w-5 h-5 rounded-full bg-gradient-to-br ${gradient} text-white text-[9px] font-semibold inline-flex items-center justify-center shrink-0`}
          title={version.creator_name || version.creator_email || ''}
        >
          {initials}
        </span>
      </div>
    </Link>
  );
}
