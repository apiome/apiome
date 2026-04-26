'use client';

/**
 * Right-rail summary for the version selected in the kanban or table.
 *
 * Surfaces only what the version row already gives us — author, lifecycle,
 * timestamps, message, lineage parent — plus a deep link to the full
 * version detail page (Phase 5). Quality / lint badges from the mockup are
 * deferred until the per-version detail page wires the on-demand quality
 * job (Phase 5) and lint runner (Phase 6); we don't fetch them here to
 * avoid an N+1 hop every time the user clicks a row.
 */

import Link from 'next/link';
import { ArrowRight, FileEdit, GitBranch, Info, Mail } from 'lucide-react';
import {
  type VersionRow,
  authorGradient,
  authorInitials,
  deriveLifecycle,
  relativeTime,
  VersionStatusChip,
} from './versionLifecycle';

interface VersionDetailRailProps {
  projectId: string;
  version: VersionRow | null;
}

export function VersionDetailRail({ projectId, version }: VersionDetailRailProps) {
  if (!version) {
    return (
      <aside className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 flex items-center gap-3">
          <Info className="w-5 h-5 text-indigo-500" aria-hidden="true" />
          <h3 className="text-base font-semibold">Selected version</h3>
        </div>
        <div className="p-5 text-sm text-gray-500 dark:text-gray-400 italic">
          Pick a card or row to inspect a revision here.
        </div>
      </aside>
    );
  }

  const kind = deriveLifecycle(version);
  const initials = authorInitials(version.creator_name, version.creator_email);
  const gradient = authorGradient(version.creator_id ?? version.creator_name);
  const message =
    version.shortMessage?.trim() || version.message?.trim() || null;
  const detailHref = `/ade/dashboard/projects/${projectId}/versions/${version.id}`;

  return (
    <aside className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden flex flex-col">
      <div className="px-5 py-4 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold">
            Selected version
          </p>
          <VersionStatusChip kind={kind} />
        </div>
        <h3 className="text-base font-bold font-mono mt-1 truncate" title={version.version_id}>
          {version.version_id}
        </h3>
        {message ? (
          <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5 line-clamp-2">
            {message}
          </p>
        ) : (
          <p className="text-[11px] italic text-gray-400 mt-0.5">no commit message</p>
        )}
      </div>

      <div className="p-5 space-y-4 text-xs">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-[11px]">
          <Term>Author</Term>
          <dd className="text-right inline-flex items-center justify-end gap-1.5 min-w-0">
            <span
              className={`w-4 h-4 rounded-full bg-gradient-to-br ${gradient} text-white text-[9px] font-semibold inline-flex items-center justify-center shrink-0`}
              aria-hidden="true"
            >
              {initials}
            </span>
            <span className="truncate" title={version.creator_email ?? ''}>
              {version.creator_name || version.creator_email || '—'}
            </span>
          </dd>

          <Term>Created</Term>
          <dd className="text-right font-mono">{relativeTime(version.created_at)}</dd>

          <Term>Updated</Term>
          <dd className="text-right font-mono">{relativeTime(version.updated_at)}</dd>

          <Term>Published</Term>
          <dd className="text-right font-mono">
            {version.published_at ? relativeTime(version.published_at) : '—'}
          </dd>

          <Term>Lifecycle</Term>
          <dd className="text-right font-mono">{(version.lifecycle ?? '—').toLowerCase()}</dd>

          <Term>Lineage</Term>
          <dd className="text-right font-mono truncate" title={version.parent_version_id ?? ''}>
            {version.parent_version_id ? `← ${shortId(version.parent_version_id)}` : 'root revision'}
          </dd>
        </dl>

        {version.changelog ? (
          <div>
            <p className="text-[10px] uppercase tracking-wider text-gray-500 font-semibold mb-1.5">
              Changelog
            </p>
            <p className="text-[11px] text-gray-600 dark:text-gray-300 whitespace-pre-line line-clamp-6">
              {version.changelog}
            </p>
          </div>
        ) : null}

        <div className="grid grid-cols-2 gap-2 text-[11px]">
          <PlaceholderTile
            icon={<FileEdit className="w-3.5 h-3.5" />}
            label="Quality"
            note="Run from version detail"
          />
          <PlaceholderTile
            icon={<GitBranch className="w-3.5 h-3.5" />}
            label="Lint"
            note="Run from version detail"
          />
        </div>
      </div>

      <div className="mt-auto px-5 py-3 border-t border-gray-100 dark:border-gray-700 bg-gray-50/60 dark:bg-gray-900/30 flex items-center justify-between gap-2">
        {version.creator_email ? (
          <a
            href={`mailto:${version.creator_email}`}
            className="text-[11px] text-gray-500 hover:text-indigo-500 inline-flex items-center gap-1.5 truncate"
            title={version.creator_email}
          >
            <Mail className="w-3 h-3" aria-hidden="true" />
            <span className="truncate">{version.creator_email}</span>
          </a>
        ) : (
          <span className="text-[11px] text-gray-400 italic">no contact</span>
        )}
        <Link
          href={detailHref}
          className="px-3 py-1.5 text-xs rounded-md bg-indigo-600 hover:bg-indigo-700 text-white inline-flex items-center gap-1.5 shrink-0"
        >
          View detail <ArrowRight className="w-3 h-3" aria-hidden="true" />
        </Link>
      </div>
    </aside>
  );
}

function Term({ children }: { children: React.ReactNode }) {
  return (
    <dt className="text-gray-500 uppercase tracking-wider text-[9px] font-semibold self-center">
      {children}
    </dt>
  );
}

interface PlaceholderTileProps {
  icon: React.ReactNode;
  label: string;
  note: string;
}

function PlaceholderTile({ icon, label, note }: PlaceholderTileProps) {
  return (
    <div className="rounded-md border border-dashed border-gray-200 dark:border-gray-700 p-2.5 text-gray-500 dark:text-gray-400">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-semibold">
        {icon}
        {label}
      </div>
      <p className="text-[10px] text-gray-400 dark:text-gray-500 mt-1">{note}</p>
    </div>
  );
}

function shortId(id: string): string {
  return id.length > 10 ? `${id.slice(0, 8)}…` : id;
}
