'use client';

/**
 * Version detail header — the sub-page banner that sits between the shared
 * project header/tabs and the detail body.
 *
 * Two visual sections:
 *
 *   1. Title strip — back-link, record id with copy button, large
 *      mono version label, status chip, lineage badge, schema-shape badge,
 *      message/description, and a row of right-aligned action buttons.
 *   2. Hero metadata strip — six bordered tiles (Author, Created, Published,
 *      Lineage, Sunset, Quality) so the most-asked questions answer
 *      themselves above the fold.
 *
 * Action buttons are intentionally disabled for now: deprecation, sunset
 * scheduling, edit-notes, and bundle export each need their own server
 * surfaces and live in later phases. We render them so the layout matches
 * the mockup but mark them with `aria-disabled` + tooltip so a click in
 * production tells the user where the work is going.
 */

import Link from 'next/link';
import { useState } from 'react';
import {
  Archive,
  ArrowLeft,
  Copy,
  Download,
  GitFork,
  MoreHorizontal,
  Moon,
  Pencil,
  Ruler,
} from 'lucide-react';
import {
  type VersionRow,
  authorGradient,
  authorInitials,
  deriveLifecycle,
  lifecycleStyle,
  relativeTime,
  VersionStatusChip,
} from '../projectDetail/versionsTab/versionLifecycle';

export interface VersionDetailHeaderQuality {
  /** Latest overall score (0-100), or null if a snapshot doesn't yet exist. */
  overall: number | null;
  /** Latest lint grade letter, or null if it's never been linted. */
  lintGrade: 'A' | 'B' | 'C' | 'D' | 'F' | null;
  /** ISO timestamp of the latest quality snapshot, used to age-out the tile. */
  computedAt?: string | null;
}

export interface VersionDetailHeaderProps {
  projectId: string;
  version: VersionRow;
  /**
   * Optional quality summary so the hero strip's "Quality" tile shows the
   * latest score without re-fetching from the parent. The version detail
   * page wires this through after `/api/version-quality` resolves.
   */
  quality?: VersionDetailHeaderQuality | null;
}

function shortId(id: string, max = 12): string {
  return id.length > max ? `${id.slice(0, max - 1)}…` : id;
}

function formatDateLong(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
  });
}

function readSunsetAt(metadata: Record<string, unknown> | null | undefined): string | null {
  if (!metadata) return null;
  const v = metadata.sunset_at ?? metadata.sunsetAt;
  return typeof v === 'string' ? v : null;
}

export function VersionDetailHeader({
  projectId,
  version,
  quality,
}: VersionDetailHeaderProps) {
  const [copied, setCopied] = useState(false);
  const lifecycle = deriveLifecycle(version);
  const style = lifecycleStyle(lifecycle);
  const initials = authorInitials(version.creator_name, version.creator_email);
  const gradient = authorGradient(version.creator_id ?? version.creator_name);
  const message = version.shortMessage?.trim() || version.message?.trim() || null;
  const sunsetAt = readSunsetAt(version.metadata ?? null);
  const versionsHref = `/ade/dashboard/projects/${projectId}?tab=versions`;

  async function copyId() {
    try {
      await navigator.clipboard.writeText(version.id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard unavailable — silent failure is fine */
    }
  }

  return (
    <section className="border-b border-gray-200 dark:border-gray-700 bg-gradient-to-br from-emerald-500/5 via-transparent to-transparent dark:from-emerald-500/10">
      <div className="px-6 py-5 flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400 mb-2 flex-wrap">
            <Link
              href={versionsHref}
              className="inline-flex items-center gap-1 hover:text-indigo-500"
            >
              <ArrowLeft className="w-3 h-3" aria-hidden="true" /> All versions
            </Link>
            <span className="text-gray-300 dark:text-gray-600">·</span>
            <span className="font-mono truncate max-w-[24rem]" title={version.id}>
              {version.id}
            </span>
            <button
              type="button"
              onClick={copyId}
              className="text-gray-400 hover:text-indigo-500"
              title={copied ? 'Copied!' : 'Copy version id'}
              aria-label="Copy version id"
            >
              <Copy className="w-3 h-3" />
            </button>
            {copied ? (
              <span className="text-[10px] text-emerald-600 dark:text-emerald-400">copied</span>
            ) : null}
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            <h1 className="text-2xl font-bold font-mono leading-tight">{version.version_id}</h1>
            <VersionStatusChip kind={lifecycle} />
            {version.parent_version_id ? (
              <span className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-1 rounded bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300">
                <GitFork className="w-3 h-3" aria-hidden="true" /> from{' '}
                <span className="font-semibold" title={version.parent_version_id}>
                  {shortId(version.parent_version_id)}
                </span>
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-1 rounded bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
                <GitFork className="w-3 h-3" aria-hidden="true" /> root revision
              </span>
            )}
            {quality && (typeof quality.overall === 'number') && (
              <span className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-1 rounded bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300">
                <Ruler className="w-3 h-3" aria-hidden="true" />{' '}
                quality {quality.overall}
              </span>
            )}
          </div>

          {message ? (
            <p className="text-sm text-gray-600 dark:text-gray-300 mt-2 max-w-2xl">{message}</p>
          ) : (
            <p className="text-sm italic text-gray-400 mt-2">no commit message</p>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0 flex-wrap">
          <DisabledAction
            icon={<Download className="w-4 h-4" />}
            label="Export"
            tooltip="Bundle export ships in a later phase"
          />
          <DisabledAction
            icon={<Pencil className="w-4 h-4" />}
            label="Edit notes"
            tooltip="Inline release-note editor ships in a later phase"
          />
          <DisabledAction
            icon={<Archive className="w-4 h-4" />}
            label="Deprecate"
            tooltip="Lifecycle transitions land with the workflow phase"
            tone="warn"
            disabled={lifecycle === 'deprecated' || lifecycle === 'sunset'}
          />
          <DisabledAction
            icon={<Moon className="w-4 h-4" />}
            label="Schedule sunset"
            tooltip="Sunset scheduling lands with the workflow phase"
            tone="danger"
            disabled={lifecycle === 'sunset'}
          />
          <button
            type="button"
            disabled
            aria-disabled="true"
            title="More actions coming soon"
            className="p-2 rounded-md border border-gray-200 dark:border-gray-700 text-gray-400 cursor-not-allowed"
          >
            <MoreHorizontal className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </div>

      {/* Hero metadata strip */}
      <div className="px-6 pb-5">
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-px bg-gray-200 dark:bg-gray-700 rounded-md overflow-hidden border border-gray-200 dark:border-gray-700">
          <Tile label="Author">
            <div className="flex items-center gap-1.5 mt-1 min-w-0">
              <span
                className={`w-5 h-5 rounded-full bg-gradient-to-br ${gradient} text-white text-[10px] flex items-center justify-center font-semibold shrink-0`}
                aria-hidden="true"
              >
                {initials}
              </span>
              <p
                className="text-xs font-medium truncate"
                title={version.creator_email ?? version.creator_name ?? ''}
              >
                {version.creator_name || version.creator_email || 'unknown'}
              </p>
            </div>
          </Tile>

          <Tile label="Created">
            <p className="text-xs font-mono mt-1">
              {formatDateLong(version.created_at)} · {relativeTime(version.created_at)}
            </p>
          </Tile>

          <Tile label="Published">
            {version.published_at ? (
              <p className="text-xs font-mono mt-1">
                {formatDateLong(version.published_at)} · {relativeTime(version.published_at)}
              </p>
            ) : (
              <p className="text-xs font-mono mt-1 text-gray-400">— not published</p>
            )}
          </Tile>

          <Tile label="Lineage">
            {version.parent_version_id ? (
              <p className="text-xs font-mono mt-1 truncate" title={version.parent_version_id}>
                <span className="text-indigo-500">{shortId(version.parent_version_id, 14)}</span>{' '}
                <span className="text-gray-400">→</span>{' '}
                <span className="font-semibold">{version.version_id}</span>
              </p>
            ) : (
              <p className="text-xs font-mono mt-1 text-gray-400">— root revision</p>
            )}
          </Tile>

          <Tile label="Sunset">
            {sunsetAt ? (
              <p className="text-xs font-mono mt-1 text-rose-600 dark:text-rose-300">
                {formatDateLong(sunsetAt)} · {relativeTime(sunsetAt)}
              </p>
            ) : (
              <p className="text-xs font-mono mt-1 text-gray-400">— not scheduled</p>
            )}
          </Tile>

          <Tile label="Quality">
            {quality && typeof quality.overall === 'number' ? (
              <p className="text-xs font-mono mt-1">
                <span className={qualityToneClass(quality.overall)}>
                  <span className="font-bold">{quality.overall}</span>
                </span>{' '}
                <span className="text-gray-400">/ 100</span>
                {quality.lintGrade ? (
                  <>
                    {' '}
                    <span className="text-gray-400">·</span>{' '}
                    <span className={lintToneClass(quality.lintGrade)}>
                      lint {quality.lintGrade}
                    </span>
                  </>
                ) : (
                  <>
                    {' '}
                    <span className="text-gray-400">· lint —</span>
                  </>
                )}
              </p>
            ) : (
              <p className="text-xs font-mono mt-1 text-gray-400">— not yet computed</p>
            )}
          </Tile>
        </div>
      </div>

      {/* Lane-tone accent stripe at the bottom — keeps the lifecycle colour
          from the mockup while staying subtle enough to read against the
          tile grid above. */}
      <div className={`h-0.5 ${style.dotClass.replace('bg-', 'bg-')} opacity-70`} aria-hidden="true" />
    </section>
  );
}

interface TileProps {
  label: string;
  children: React.ReactNode;
}

function Tile({ label, children }: TileProps) {
  return (
    <div className="bg-white dark:bg-gray-800 px-3 py-2.5 min-w-0">
      <p className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400 font-semibold">
        {label}
      </p>
      {children}
    </div>
  );
}

interface DisabledActionProps {
  icon: React.ReactNode;
  label: string;
  tooltip: string;
  tone?: 'default' | 'warn' | 'danger';
  disabled?: boolean;
}

function DisabledAction({
  icon,
  label,
  tooltip,
  tone = 'default',
  disabled = true,
}: DisabledActionProps) {
  const toneClass =
    tone === 'warn'
      ? 'border-orange-200 dark:border-orange-700/40 text-orange-500/70 dark:text-orange-400/60'
      : tone === 'danger'
        ? 'border-rose-200 dark:border-rose-700/40 text-rose-500/70 dark:text-rose-400/60'
        : 'border-gray-200 dark:border-gray-700 text-gray-400';
  return (
    <button
      type="button"
      disabled={disabled}
      aria-disabled={disabled}
      title={tooltip}
      className={`px-3 py-1.5 text-sm rounded-md border ${toneClass} cursor-not-allowed inline-flex items-center gap-2`}
    >
      {icon}
      {label}
    </button>
  );
}

function qualityToneClass(score: number): string {
  if (score >= 85) return 'text-emerald-600 dark:text-emerald-400';
  if (score >= 70) return 'text-indigo-600 dark:text-indigo-400';
  if (score >= 50) return 'text-amber-600 dark:text-amber-400';
  return 'text-rose-600 dark:text-rose-400';
}

function lintToneClass(grade: 'A' | 'B' | 'C' | 'D' | 'F'): string {
  switch (grade) {
    case 'A':
      return 'text-emerald-600 dark:text-emerald-400';
    case 'B':
      return 'text-indigo-600 dark:text-indigo-400';
    case 'C':
      return 'text-amber-600 dark:text-amber-400';
    case 'D':
    case 'F':
      return 'text-rose-600 dark:text-rose-400';
  }
}
