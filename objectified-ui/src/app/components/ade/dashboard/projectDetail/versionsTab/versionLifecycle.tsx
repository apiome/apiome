'use client';

/**
 * Shared types and helpers for the per-project Versions tab.
 *
 * The REST API exposes two pieces of lifecycle state on each version row:
 *
 *   - `published` (boolean) — has it been published at least once?
 *   - `lifecycle`  ('stable' | 'beta' | 'deprecated' | 'archived')
 *
 * Plus a free-form `metadata` blob that may carry deprecation/sunset hints
 * (`metadata.sunset_at`, `metadata.deprecated_at`). The mockup wants four
 * UI-facing buckets — Draft, Published, Deprecated, Sunset — so we project
 * the API state into those buckets centrally and reuse the result everywhere
 * (kanban lanes, table chip, KPI counters, right rail). One source of truth
 * keeps the chip colour, lane colour, and counts in lockstep.
 */

import type { ReactNode } from 'react';

export type VersionLifecycle = 'draft' | 'published' | 'deprecated' | 'sunset';

/**
 * Subset of fields used by the Versions tab. Mirrors the FastAPI
 * `VersionSchema` payload (camelCase via Pydantic aliases) so we don't have
 * to rebuild it row-by-row in components.
 */
export interface VersionRow {
  id: string;
  project_id?: string;
  version_id: string;
  enabled?: boolean;
  published?: boolean;
  published_at?: string | null;
  deleted_at?: string | null;
  created_at: string;
  updated_at: string;
  creator_id?: string | null;
  creator_name?: string | null;
  creator_email?: string | null;
  shortMessage?: string | null;
  changelog?: string | null;
  message?: string | null;
  parent_version_id?: string | null;
  lifecycle?: string | null;
  metadata?: Record<string, unknown> | null;
}

const ATTENTION_DRAFT_LABELS = new Set(['draft', 'wip', 'in-review']);

/**
 * Map a version row to its lifecycle bucket.
 *
 * Precedence is intentional: deletion is always terminal, sunset wins over
 * deprecated (a deprecated version still listed for sunset is a sunset row,
 * not a deprecated row), and otherwise the published flag decides between
 * Published and Draft.
 */
export function deriveLifecycle(version: VersionRow): VersionLifecycle {
  const meta = version.metadata ?? {};
  const lifecycle = (version.lifecycle ?? '').toLowerCase();

  if (meta && (typeof meta.sunset_at === 'string' || typeof meta.sunsetAt === 'string')) {
    return 'sunset';
  }
  if (lifecycle === 'archived') return 'sunset';
  if (lifecycle === 'deprecated') return 'deprecated';
  if (
    meta &&
    (typeof meta.deprecated_at === 'string' || typeof meta.deprecatedAt === 'string')
  ) {
    return 'deprecated';
  }
  if (version.published) return 'published';
  return 'draft';
}

/**
 * Free-form revision label used for fuzzy matching (search box).
 * Combines the canonical version_id with the various human-supplied notes
 * so users can find a row by message text or author.
 */
export function searchHaystack(version: VersionRow): string {
  return [
    version.version_id ?? '',
    version.shortMessage ?? '',
    version.changelog ?? '',
    version.message ?? '',
    version.creator_name ?? '',
    version.creator_email ?? '',
  ]
    .join(' ')
    .toLowerCase();
}

export interface LifecycleStyle {
  /** Short uppercase chip label (Draft / Published / Deprecated / Sunset). */
  label: string;
  /** Tailwind classes for a small pill (background + text). */
  chipClass: string;
  /** Tailwind classes for a coloured dot — used in toolbars and lane headers. */
  dotClass: string;
  /** Tailwind classes for an outlined card border in the lane. */
  cardBorderClass: string;
  /** Tailwind classes for a kanban lane header strip. */
  laneHeaderClass: string;
  /** Tailwind classes for the "draft"-style draft attention prefix on chips. */
  laneTitleClass: string;
}

const STYLES: Record<VersionLifecycle, LifecycleStyle> = {
  draft: {
    label: 'Draft',
    chipClass:
      'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
    dotClass: 'bg-slate-400',
    cardBorderClass: 'border-gray-200 dark:border-gray-700',
    laneHeaderClass:
      'bg-gradient-to-b from-slate-200/40 dark:from-slate-700/30 to-transparent border-slate-300/60 dark:border-slate-600/40',
    laneTitleClass: 'text-slate-600 dark:text-slate-300',
  },
  published: {
    label: 'Published',
    chipClass:
      'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
    dotClass: 'bg-emerald-500',
    cardBorderClass: 'border-emerald-300 dark:border-emerald-700/50',
    laneHeaderClass:
      'bg-gradient-to-b from-emerald-200/40 dark:from-emerald-700/20 to-transparent border-emerald-300/70 dark:border-emerald-700/40',
    laneTitleClass: 'text-emerald-700 dark:text-emerald-300',
  },
  deprecated: {
    label: 'Deprecated',
    chipClass:
      'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
    dotClass: 'bg-orange-500',
    cardBorderClass: 'border-orange-200 dark:border-orange-800/50',
    laneHeaderClass:
      'bg-gradient-to-b from-orange-200/40 dark:from-orange-700/20 to-transparent border-orange-300/70 dark:border-orange-700/40',
    laneTitleClass: 'text-orange-700 dark:text-orange-300',
  },
  sunset: {
    label: 'Sunset',
    chipClass:
      'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
    dotClass: 'bg-rose-500',
    cardBorderClass: 'border-rose-200 dark:border-rose-700/40',
    laneHeaderClass:
      'bg-gradient-to-b from-rose-200/40 dark:from-rose-700/20 to-transparent border-rose-300/70 dark:border-rose-700/40',
    laneTitleClass: 'text-rose-700 dark:text-rose-300',
  },
};

export function lifecycleStyle(kind: VersionLifecycle): LifecycleStyle {
  return STYLES[kind];
}

/**
 * Order lanes appear in the kanban and chip toolbar. Locked here rather than
 * leaving it to dictionary iteration so we don't get accidental reorderings.
 */
export const LIFECYCLE_ORDER: VersionLifecycle[] = [
  'draft',
  'published',
  'deprecated',
  'sunset',
];

interface VersionStatusChipProps {
  kind: VersionLifecycle;
  /** Optional extra text to the right (e.g. "latest"). */
  badge?: ReactNode;
  className?: string;
}

/**
 * Compact uppercase chip used in the table and right rail. Kept local to
 * the Versions tab because the shared `ProjectStatusChip` doesn't carry a
 * 'sunset' tone yet — extending it can land in a later cleanup pass.
 */
export function VersionStatusChip({ kind, badge, className }: VersionStatusChipProps) {
  const style = lifecycleStyle(kind);
  return (
    <span
      className={`inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded ${style.chipClass}${
        className ? ` ${className}` : ''
      }`}
    >
      {style.label}
      {badge != null ? <span className="opacity-80 normal-case">{badge}</span> : null}
    </span>
  );
}

/**
 * Human-friendly relative time, capped at year granularity. Returns an
 * em-dash for missing/unparseable input so callers can render it directly.
 */
export function relativeTime(iso?: string | null): string {
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

/**
 * Two-character author monogram for the pill avatars. Falls back to "··"
 * so we never render an empty bubble.
 */
export function authorInitials(name?: string | null, email?: string | null): string {
  const source = (name ?? email ?? '').trim();
  if (!source) return '··';
  const words = source.split(/[\s_\-/@.]+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  const compact = source.replace(/[^a-zA-Z0-9]/g, '');
  return (compact.slice(0, 2) || '··').toUpperCase();
}

/**
 * Deterministic Tailwind gradient picker for an author bubble — same
 * convention as the project avatars so a given author is visually stable
 * across the dashboard.
 */
const AUTHOR_GRADIENTS = [
  'from-indigo-500 to-purple-500',
  'from-emerald-500 to-teal-500',
  'from-amber-500 to-orange-500',
  'from-rose-500 to-pink-500',
  'from-sky-500 to-cyan-500',
  'from-violet-500 to-fuchsia-500',
];

export function authorGradient(seed?: string | null): string {
  const key = (seed ?? '').toString();
  let hash = 0;
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  return AUTHOR_GRADIENTS[hash % AUTHOR_GRADIENTS.length];
}
