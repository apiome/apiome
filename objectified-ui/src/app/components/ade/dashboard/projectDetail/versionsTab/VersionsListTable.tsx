'use client';

/**
 * Versions table with status filter chips + free-text search.
 *
 * Rendering this as a plain HTML table (not a virtualized list) is fine —
 * version counts are bounded by what humans publish, and even the busiest
 * projects rarely cross the low hundreds. If we ever do, swap to a windowed
 * row renderer; nothing here leaks state that would prevent that.
 *
 * Columns intentionally exclude per-row Quality / Lint / Schema-scope. Those
 * require either a bulk endpoint or N+1 fetches per row; we land them with
 * the bulk APIs in Phase 10. The right rail surfaces the selected row's
 * detail without the bulk-fetch hazard.
 */

import Link from 'next/link';
import { Eye, Search, User } from 'lucide-react';
import {
  type VersionLifecycle,
  type VersionRow,
  LIFECYCLE_ORDER,
  authorGradient,
  authorInitials,
  deriveLifecycle,
  lifecycleStyle,
  relativeTime,
  searchHaystack,
  VersionStatusChip,
} from './versionLifecycle';

export type VersionStatusFilter = 'all' | VersionLifecycle | 'mine';

interface VersionsListTableProps {
  projectId: string;
  versions: VersionRow[];
  selectedVersionId: string | null;
  onSelect: (versionId: string) => void;

  filter: VersionStatusFilter;
  onFilterChange: (next: VersionStatusFilter) => void;
  search: string;
  onSearchChange: (next: string) => void;

  /** Used to power the "Mine" chip. */
  currentUserId?: string | null;
}

export function VersionsListTable({
  projectId,
  versions,
  selectedVersionId,
  onSelect,
  filter,
  onFilterChange,
  search,
  onSearchChange,
  currentUserId,
}: VersionsListTableProps) {
  const counts = countByLifecycle(versions);
  const mineCount = currentUserId
    ? versions.filter((v) => v.creator_id === currentUserId).length
    : 0;

  const filtered = filterAndSearch(versions, filter, search, currentUserId);

  return (
    <div className="space-y-3 min-w-0">
      <Toolbar
        filter={filter}
        onFilterChange={onFilterChange}
        search={search}
        onSearchChange={onSearchChange}
        counts={counts}
        mineCount={mineCount}
        totalCount={versions.length}
        showMineChip={Boolean(currentUserId)}
      />

      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-[10px] uppercase tracking-wider text-gray-500 bg-gray-50 dark:bg-gray-900/60">
              <tr>
                <th className="text-left px-4 py-2.5 font-semibold w-44">Version</th>
                <th className="text-left px-4 py-2.5 font-semibold w-28">Status</th>
                <th className="text-left px-4 py-2.5 font-semibold">Message</th>
                <th className="text-left px-4 py-2.5 font-semibold w-44">Author</th>
                <th className="text-right px-4 py-2.5 font-semibold w-24">Updated</th>
                <th className="px-2 py-2.5 w-12"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700/60">
              {filtered.length === 0 ? (
                <tr>
                  <td
                    colSpan={6}
                    className="px-4 py-8 text-center text-sm text-gray-500 dark:text-gray-400"
                  >
                    {versions.length === 0
                      ? 'No versions yet for this project.'
                      : 'No versions match this filter — adjust the chips or clear the search.'}
                  </td>
                </tr>
              ) : (
                filtered.map((version) => (
                  <VersionRowEl
                    key={version.id}
                    projectId={projectId}
                    version={version}
                    selected={selectedVersionId === version.id}
                    onSelect={() => onSelect(version.id)}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-2.5 border-t border-gray-100 dark:border-gray-700/60 bg-gray-50/60 dark:bg-gray-900/30 flex items-center justify-between text-[11px] text-gray-500 gap-3 flex-wrap">
          <span className="font-mono">
            Showing {filtered.length} of {versions.length}{' '}
            {versions.length === 1 ? 'version' : 'versions'}
          </span>
          <span>Click a row to inspect · the right rail follows your selection</span>
        </div>
      </div>
    </div>
  );
}

interface ToolbarProps {
  filter: VersionStatusFilter;
  onFilterChange: (next: VersionStatusFilter) => void;
  search: string;
  onSearchChange: (next: string) => void;
  counts: Record<VersionLifecycle, number>;
  mineCount: number;
  totalCount: number;
  showMineChip: boolean;
}

function Toolbar({
  filter,
  onFilterChange,
  search,
  onSearchChange,
  counts,
  mineCount,
  totalCount,
  showMineChip,
}: ToolbarProps) {
  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-3 flex items-center gap-3 flex-wrap">
      <div className="flex items-center gap-1.5 flex-wrap">
        <FilterChip
          active={filter === 'all'}
          onClick={() => onFilterChange('all')}
          label="All"
          count={totalCount}
          tone="primary"
        />
        {LIFECYCLE_ORDER.map((kind) => (
          <FilterChip
            key={kind}
            active={filter === kind}
            onClick={() => onFilterChange(kind)}
            label={lifecycleStyle(kind).label}
            count={counts[kind]}
            dotClass={lifecycleStyle(kind).dotClass}
          />
        ))}
        {showMineChip ? (
          <>
            <span className="w-px h-5 bg-gray-200 dark:bg-gray-700 mx-1" aria-hidden="true" />
            <FilterChip
              active={filter === 'mine'}
              onClick={() => onFilterChange('mine')}
              label="Mine"
              count={mineCount}
              icon={<User className="w-3 h-3" aria-hidden="true" />}
            />
          </>
        ) : null}
      </div>

      <div className="flex-1" />

      <div className="relative">
        <Search
          className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-1/2 -translate-y-1/2"
          aria-hidden="true"
        />
        <input
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-7 pr-3 h-7 w-56 text-xs rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 focus:outline-none focus:border-indigo-500"
          placeholder="Search version, message, author…"
          aria-label="Search versions"
        />
      </div>
    </div>
  );
}

interface FilterChipProps {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
  tone?: 'primary';
  dotClass?: string;
  icon?: React.ReactNode;
}

function FilterChip({ active, onClick, label, count, tone, dotClass, icon }: FilterChipProps) {
  const base =
    'px-2.5 py-1 text-xs rounded-md inline-flex items-center gap-1.5 transition-colors';
  const inactive =
    'border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-300';
  const activePrimary =
    'font-semibold bg-indigo-600 text-white border border-indigo-600';
  const activeNeutral =
    'font-semibold border border-indigo-300 dark:border-indigo-700/60 bg-indigo-500/10 text-indigo-600 dark:text-indigo-400';
  const cls = active ? (tone === 'primary' ? activePrimary : activeNeutral) : inactive;

  return (
    <button
      type="button"
      onClick={onClick}
      className={`${base} ${cls}`}
      aria-pressed={active}
    >
      {icon}
      {dotClass ? (
        <span className={`w-1.5 h-1.5 rounded-full ${dotClass}`} aria-hidden="true" />
      ) : null}
      <span>{label}</span>
      <span
        className={`font-mono text-[10px] ${
          active && tone === 'primary'
            ? 'text-white/80 px-1 rounded bg-white/20'
            : 'text-gray-400'
        }`}
      >
        {count}
      </span>
    </button>
  );
}

interface VersionRowProps {
  projectId: string;
  version: VersionRow;
  selected: boolean;
  onSelect: () => void;
}

function VersionRowEl({ projectId, version, selected, onSelect }: VersionRowProps) {
  const kind = deriveLifecycle(version);
  const initials = authorInitials(version.creator_name, version.creator_email);
  const gradient = authorGradient(version.creator_id ?? version.creator_name);
  const message =
    version.shortMessage?.trim() ||
    version.changelog?.split(/\n+/)[0]?.trim() ||
    null;
  const detailHref = `/ade/dashboard/projects/${projectId}/versions/${version.id}`;

  const baseRowClass = 'cursor-pointer transition-colors';
  const stateRowClass = selected
    ? 'bg-indigo-500/5 dark:bg-indigo-500/10'
    : kind === 'sunset'
      ? 'hover:bg-rose-50/40 dark:hover:bg-rose-900/10'
      : 'hover:bg-gray-50/60 dark:hover:bg-gray-900/30';
  const rowAccentClass = kind === 'sunset' ? 'shadow-[inset_3px_0_0_0_#f43f5e]' : '';

  const handleRowClick = () => {
    onSelect();
  };

  return (
    <tr className={`${baseRowClass} ${stateRowClass} ${rowAccentClass}`} onClick={handleRowClick}>
      <td className="px-4 py-3 font-mono text-xs">
        <Link
          href={detailHref}
          onClick={(e) => e.stopPropagation()}
          className="font-semibold hover:text-indigo-500"
        >
          {version.version_id}
        </Link>
      </td>
      <td className="px-4 py-3">
        <VersionStatusChip kind={kind} />
      </td>
      <td className="px-4 py-3 text-xs text-gray-600 dark:text-gray-300 max-w-md">
        <p className="truncate" title={message ?? undefined}>
          {message ?? <span className="italic text-gray-400">no message</span>}
        </p>
      </td>
      <td className="px-4 py-3 text-xs text-gray-500">
        <span className="inline-flex items-center gap-1.5">
          <span
            className={`w-5 h-5 rounded-full bg-gradient-to-br ${gradient} text-white text-[9px] font-semibold inline-flex items-center justify-center shrink-0`}
          >
            {initials}
          </span>
          <span className="truncate">{version.creator_name || version.creator_email || '—'}</span>
        </span>
      </td>
      <td className="px-4 py-3 text-right text-[11px] text-gray-500 font-mono">
        {relativeTime(version.updated_at)}
      </td>
      <td className="px-2 py-3 text-right">
        <Link
          href={detailHref}
          onClick={(e) => e.stopPropagation()}
          title="Open version detail"
          className="inline-flex p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
        >
          <Eye className="w-3.5 h-3.5 text-gray-400" aria-hidden="true" />
          <span className="sr-only">Open version {version.version_id}</span>
        </Link>
      </td>
    </tr>
  );
}

function countByLifecycle(versions: VersionRow[]): Record<VersionLifecycle, number> {
  const counts: Record<VersionLifecycle, number> = {
    draft: 0,
    published: 0,
    deprecated: 0,
    sunset: 0,
  };
  for (const v of versions) counts[deriveLifecycle(v)] += 1;
  return counts;
}

function filterAndSearch(
  versions: VersionRow[],
  filter: VersionStatusFilter,
  search: string,
  currentUserId?: string | null,
): VersionRow[] {
  const q = search.trim().toLowerCase();
  const filtered = versions.filter((v) => {
    if (filter === 'mine') {
      if (!currentUserId || v.creator_id !== currentUserId) return false;
    } else if (filter !== 'all' && deriveLifecycle(v) !== filter) {
      return false;
    }
    if (q && !searchHaystack(v).includes(q)) return false;
    return true;
  });
  filtered.sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
  return filtered;
}
