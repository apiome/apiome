'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';
import { FileCode2, GitBranch, Github, Gitlab, Globe, Loader2 } from 'lucide-react';
import { SiBitbucket } from 'react-icons/si';
import { cn } from '@lib/utils';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/app/components/ui/Tooltip';
import { RepositoryRowMenu } from './RepositoryRowMenu';

export type RepositoryProvider = 'github' | 'gitlab' | 'bitbucket' | 'public_url';
export type RepositoryStatus = 'pending' | 'scanning' | 'ready' | 'error' | 'archived';

export interface DashboardRepository {
  id: string;
  name: string;
  full_name: string;
  description?: string | null;
  provider: RepositoryProvider;
  default_branch: string;
  visibility?: 'public' | 'private';
  status: RepositoryStatus;
  last_scanned_at?: string | null;
  total_files?: number | null;
  importable_count?: number | null;
  /** Git remote branches (GitHub list-branches at registration); null if unknown. */
  branch_count?: number | null;
  clone_url?: string | null;
  source?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

function normalizeProvider(p: unknown): RepositoryProvider {
  const s = String(p ?? '').toLowerCase();
  if (s === 'gitlab') return 'gitlab';
  if (s === 'bitbucket') return 'bitbucket';
  if (s === 'public_url' || s === 'publicurl') return 'public_url';
  return 'github';
}

function normalizeStatus(s: unknown): RepositoryStatus {
  const v = String(s ?? '').toLowerCase();
  if (v === 'pending') return 'pending';
  if (v === 'scanning') return 'scanning';
  if (v === 'error') return 'error';
  if (v === 'archived') return 'archived';
  return 'ready';
}

/** Parse a repository object from the REST / Next API (list or detail). */
export function dashboardRepositoryFromApi(x: unknown): DashboardRepository | null {
  if (!x || typeof x !== 'object') return null;
  const o = x as Record<string, unknown>;
  const id = String(o.id ?? '');
  if (!id) return null;
  const vis = o.visibility;
  const visibility =
    vis === 'private' ? 'private' : vis === 'public' ? 'public' : undefined;
  return {
    id,
    name: String(o.name ?? o.full_name ?? 'Repository'),
    full_name: String(o.full_name ?? o.clone_url ?? o.name ?? ''),
    description: o.description != null ? String(o.description) : null,
    provider: normalizeProvider(o.provider),
    default_branch: String(o.default_branch ?? 'main'),
    visibility,
    status: normalizeStatus(o.status),
    last_scanned_at: o.last_scanned_at != null ? String(o.last_scanned_at) : null,
    total_files: typeof o.total_files === 'number' ? o.total_files : null,
    importable_count: typeof o.importable_count === 'number' ? o.importable_count : null,
    branch_count: typeof o.branch_count === 'number' ? o.branch_count : null,
    clone_url: o.clone_url != null ? String(o.clone_url) : null,
    source: o.source != null ? String(o.source) : null,
    created_at: o.created_at != null ? String(o.created_at) : null,
    updated_at: o.updated_at != null ? String(o.updated_at) : null,
  };
}

export function dashboardRepositoriesFromListPayload(data: unknown): DashboardRepository[] {
  if (!data || typeof data !== 'object') return [];
  const raw = (data as { repositories?: unknown }).repositories;
  if (!Array.isArray(raw)) return [];
  return raw.map(dashboardRepositoryFromApi).filter((r): r is DashboardRepository => r != null);
}

function hashSeed(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}

export type EstimatedImportableMix = {
  openapi: number;
  arazzo: number;
  jsonSchema: number;
};

/**
 * Deterministic split of a repo's `importable_count` into UI kinds until the API returns
 * real per-kind tallies. The three counts always sum to `importable_count` (or all zero).
 */
export function estimatedImportableMixForRepo(
  importableCount: number | null | undefined,
  repositoryId: string,
): EstimatedImportableMix {
  const T =
    typeof importableCount === 'number' && importableCount > 0
      ? Math.floor(importableCount)
      : 0;
  if (T === 0) return { openapi: 0, arazzo: 0, jsonSchema: 0 };
  const h = hashSeed(repositoryId);
  const w0 = 300 + (h % 700);
  const w1 = 200 + ((h >> 10) % 600);
  const w2 = 400 + ((h >> 20) % 500);
  const s = w0 + w1 + w2;
  const openapi = Math.floor((T * w0) / s);
  const arazzo = Math.floor((T * w1) / s);
  const jsonSchema = T - openapi - arazzo;
  return { openapi, arazzo, jsonSchema };
}

export function aggregateEstimatedImportableMix(
  repos: DashboardRepository[],
): EstimatedImportableMix & { total: number } {
  let openapi = 0;
  let arazzo = 0;
  let jsonSchema = 0;
  let total = 0;
  for (const r of repos) {
    const t = r.importable_count ?? 0;
    total += t;
    const m = estimatedImportableMixForRepo(r.importable_count, r.id);
    openapi += m.openapi;
    arazzo += m.arazzo;
    jsonSchema += m.jsonSchema;
  }
  return { openapi, arazzo, jsonSchema, total };
}

export function formatEstimatedImportableMixInline(mix: EstimatedImportableMix): string {
  return `OpenAPI ${mix.openapi} · Arazzo ${mix.arazzo} · JSON Schema ${mix.jsonSchema}`;
}

export const IMPORTABLE_ESTIMATE_DISCLAIMER =
  'This is an estimated count of the importable files - actual count may vary.';

/** Summary metric card — label + value; `subtitle` is shown as a hover tooltip only. */
export function RepositoryKpiCard({
  label,
  value,
  subtitle,
  footnote,
  valueClassName,
  valuePending = false,
}: {
  label: string;
  value: ReactNode;
  subtitle: string;
  /** Optional short text shown under the value (not only in the tooltip). */
  footnote?: string;
  valueClassName?: string;
  /** When true (e.g. repository scan in progress), show a spinner beside the value. */
  valuePending?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div
          className={cn(
            'rounded-lg border border-gray-200 bg-white p-4 text-left outline-none transition-colors',
            'cursor-default hover:border-gray-300 dark:border-gray-700 dark:bg-gray-800 dark:hover:border-gray-600',
            'focus-visible:ring-2 focus-visible:ring-indigo-500/50 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-gray-900'
          )}
          aria-busy={valuePending}
          tabIndex={0}
        >
          <p className="text-[10px] uppercase tracking-wider text-gray-500 dark:text-gray-400">{label}</p>
          <div
            className={cn(
              'mt-1',
              valuePending
                ? 'inline-flex min-h-8 items-center gap-2'
                : 'font-mono text-2xl font-bold tabular-nums tracking-tight',
              !valuePending && valueClassName
            )}
          >
            {valuePending ? (
              <>
                <Loader2
                  className="h-6 w-6 shrink-0 animate-spin text-indigo-500 dark:text-indigo-400"
                  aria-hidden
                />
                <span className={cn('font-mono text-2xl font-bold tabular-nums tracking-tight', valueClassName)}>
                  {value}
                </span>
              </>
            ) : (
              value
            )}
          </div>
          {footnote ? (
            <p className="mt-2 text-xs leading-snug text-gray-500 dark:text-gray-400">{footnote}</p>
          ) : null}
        </div>
      </TooltipTrigger>
      <TooltipContent side="bottom" align="start" className="max-w-xs text-left leading-snug">
        {subtitle}
      </TooltipContent>
    </Tooltip>
  );
}

export function repoInitials(name: string): string {
  const parts = name.replace(/[/_-]+/g, ' ').trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  const compact = name.replace(/[^a-zA-Z0-9]/g, '');
  return compact.slice(0, 2).toUpperCase() || 'R';
}

export function RepositorySparkline({ seed, errorTint }: { seed: string; errorTint?: boolean }) {
  const h = hashSeed(seed);
  const heights = Array.from({ length: 8 }, (_, i) => 4 + ((h >> (i * 3)) % 14));
  return (
    <div className="flex h-5 items-end gap-[2px]">
      {heights.map((px, i) => (
        <span
          key={i}
          className={cn('inline-block w-[3px] rounded-sm', errorTint && i >= 5 ? 'bg-rose-400/70' : 'bg-indigo-400/70')}
          style={{ height: `${px}px` }}
        />
      ))}
    </div>
  );
}

export function repositoryStatusLabel(status: RepositoryStatus): string {
  switch (status) {
    case 'pending':
      return 'Pending';
    case 'scanning':
      return 'Scanning';
    case 'ready':
      return 'Ready';
    case 'error':
      return 'Error';
    case 'archived':
      return 'Archived';
    default:
      return status;
  }
}

export function repositoryStatusClass(status: RepositoryStatus): string {
  switch (status) {
    case 'pending':
      return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300';
    case 'scanning':
      return 'bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-200';
    case 'ready':
      return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300';
    case 'error':
      return 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300';
    case 'archived':
      return 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-400';
    default:
      return 'bg-slate-100 text-slate-700';
  }
}

export function ProviderBadge({ provider }: { provider: RepositoryProvider }) {
  if (provider === 'github') {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] text-gray-500 dark:text-gray-400">
        <Github className="h-3 w-3" aria-hidden />
        GitHub
      </span>
    );
  }
  if (provider === 'gitlab') {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] text-gray-500 dark:text-gray-400">
        <Gitlab className="h-3 w-3 text-orange-500" aria-hidden />
        GitLab
      </span>
    );
  }
  if (provider === 'bitbucket') {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] text-gray-500 dark:text-gray-400">
        <SiBitbucket className="h-3 w-3 text-sky-600" aria-hidden />
        Bitbucket
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-gray-500 dark:text-gray-400">
      <Globe className="h-3 w-3 text-indigo-500" aria-hidden />
      Public URL
    </span>
  );
}

const gradientForIndex = (i: number) => {
  const g = [
    'from-emerald-500 to-teal-500',
    'from-indigo-500 to-purple-500',
    'from-purple-500 to-pink-500',
    'from-amber-500 to-orange-500',
    'from-rose-500 to-pink-500',
    'from-cyan-500 to-blue-500',
  ];
  return g[i % g.length];
};

export function RepositoryCard({
  repo,
  index,
  detailHref,
  onRemoved,
}: {
  repo: DashboardRepository;
  index: number;
  detailHref?: string;
  /** When set with `detailHref`, shows an actions menu (e.g. remove from tenant list). */
  onRemoved?: () => void;
}) {
  const files = repo.total_files ?? 0;
  const scanLabel = formatLastScan(repo.last_scanned_at, repo.status === 'error');
  const grad = gradientForIndex(index);

  const shellClass = cn(
    'relative isolate rounded-xl border border-gray-200 bg-white p-5 transition-all duration-200 dark:border-gray-700 dark:bg-gray-800',
    detailHref && 'hover:-translate-y-0.5 hover:shadow-lg hover:shadow-indigo-500/15'
  );

  const inner = (
    <>
      <div className="mb-3 flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <span
            className={cn(
              'flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-gradient-to-br font-mono text-xs font-bold text-white',
              grad
            )}
          >
            {repoInitials(repo.name)}
          </span>
          <div className="min-w-0">
            <p className="truncate font-semibold">{repo.name}</p>
            <p className="truncate font-mono text-[11px] text-gray-500 dark:text-gray-400">{repo.full_name}</p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <span
            className={cn(
              'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider',
              repositoryStatusClass(repo.status)
            )}
          >
            {repo.status === 'scanning' ? (
              <Loader2 className="h-3 w-3 shrink-0 animate-spin" aria-hidden />
            ) : null}
            {repositoryStatusLabel(repo.status)}
          </span>
          {detailHref && onRemoved ? (
            <div className="pointer-events-auto" onPointerDown={(e) => e.stopPropagation()}>
              <RepositoryRowMenu
                repositoryId={repo.id}
                label={repo.name}
                onRemoved={onRemoved}
                triggerClassName="-mr-1"
              />
            </div>
          ) : null}
        </div>
      </div>
      {repo.description ? (
        <p className="mb-3 line-clamp-2 text-xs text-gray-500 dark:text-gray-400">{repo.description}</p>
      ) : (
        <p className="mb-3 text-xs text-gray-400 dark:text-gray-500">No description</p>
      )}
      <div className="mb-3 flex flex-wrap items-center gap-3 text-[11px] text-gray-500 dark:text-gray-400">
        <ProviderBadge provider={repo.provider} />
        <span className="inline-flex items-center gap-1">
          <GitBranch className="h-3 w-3" aria-hidden />
          {repo.default_branch}
        </span>
        <span className="inline-flex items-center gap-1">
          <FileCode2 className="h-3 w-3" aria-hidden />
          {files.toLocaleString()} files
        </span>
      </div>
      <div className="flex items-center justify-between border-t border-gray-100 pt-3 dark:border-gray-700">
        <span className="text-[11px] text-gray-500 dark:text-gray-400">{scanLabel}</span>
        <RepositorySparkline seed={repo.id} errorTint={repo.status === 'error'} />
      </div>
    </>
  );

  if (detailHref) {
    return (
      <div className={shellClass}>
        <Link
          href={detailHref}
          className="absolute inset-0 z-0 rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500/70 focus-visible:ring-offset-2 ring-offset-white dark:ring-offset-gray-900"
          aria-label={`Open repository ${repo.full_name || repo.name}`}
        />
        <div className="relative z-10 pointer-events-none">{inner}</div>
      </div>
    );
  }

  return <div className={shellClass}>{inner}</div>;
}

export function formatLastScan(iso: string | null | undefined, failed: boolean): string {
  if (failed) return 'Scan failed';
  if (!iso) return 'Never scanned';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '—';
  const diff = Date.now() - then;
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

export function ManageLinkedAccountsLink() {
  return (
    <Link href="/ade/dashboard/linked-accounts" className="text-[11px] font-medium text-indigo-600 hover:text-indigo-500 dark:text-indigo-400">
      Manage linked accounts →
    </Link>
  );
}

export function SourceOptionCard({
  selected,
  icon,
  title,
  description,
  onSelect,
  radioName,
}: {
  selected: boolean;
  icon: ReactNode;
  title: string;
  description: string;
  onSelect: () => void;
  radioName: string;
}) {
  return (
    <label
      className={cn(
        'cursor-pointer rounded-lg border-2 p-4 transition-colors',
        selected
          ? 'border-indigo-500 bg-indigo-50/40 dark:border-indigo-500 dark:bg-indigo-900/10'
          : 'border-gray-200 hover:border-indigo-300 dark:border-gray-700 dark:hover:border-indigo-600'
      )}
    >
      <div className="flex items-start gap-3">
        <input type="radio" name={radioName} checked={selected} onChange={onSelect} className="mt-1" />
        <div>
          <p className="inline-flex items-center gap-2 text-sm font-semibold">
            {icon}
            {title}
          </p>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{description}</p>
        </div>
      </div>
    </label>
  );
}

export function LinkedAccountIcon({ provider }: { provider: string }) {
  const p = provider.toLowerCase();
  if (p === 'gitlab') return <Gitlab className="h-4 w-4 text-orange-500" aria-hidden />;
  if (p === 'bitbucket') return <SiBitbucket className="h-4 w-4 text-sky-600" aria-hidden />;
  return <Github className="h-4 w-4" aria-hidden />;
}
