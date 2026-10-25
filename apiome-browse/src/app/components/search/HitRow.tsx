'use client';

import Link from 'next/link';
import { Fragment } from 'react';
import { formatLabel, paradigmLabel } from '../../../../lib/browseFacets';
import { excerptAround } from '../../../../lib/search/highlight';
import { hitCrumbs, hitHref, hitKindLabel, type CatalogSearchHit } from '../../../../lib/search/hits';
import type { HitKind } from '../../../../lib/search/kinds';
import { Highlight } from './Highlight';
import { MethodBadge } from './httpMethodTone';

/** The icon tile tone per kind: what a visitor scans first. */
const KIND_TONE: Record<HitKind, string> = {
  organization: 'bg-sky-500/10 text-sky-700 dark:text-sky-300',
  project: 'bg-blue-700/10 text-blue-800 dark:text-blue-300',
  version: 'bg-amber-400/15 text-amber-700 dark:text-amber-300',
  tag: 'bg-amber-400/15 text-amber-700 dark:text-amber-300',
  operation: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  parameter: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
  request_body: 'bg-cyan-500/10 text-cyan-700 dark:text-cyan-300',
  response: 'bg-cyan-500/10 text-cyan-700 dark:text-cyan-300',
  schema: 'bg-violet-500/10 text-violet-700 dark:text-violet-300',
  property: 'bg-violet-500/10 text-violet-700 dark:text-violet-300',
};

function KindIcon({ kind }: { kind: HitKind }) {
  const common = 'h-4.5 w-4.5';
  switch (kind) {
    case 'organization':
      return (
        <svg className={common} fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 21h18M5 21V7l8-4v18M19 21V11l-6-4" />
        </svg>
      );
    case 'project':
      return (
        <svg className={common} fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      );
    case 'version':
      return (
        <svg className={common} fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a3 3 0 11-6 0 3 3 0 016 0zM6 21l5-5m0 0l5 5m-5-5V3" />
        </svg>
      );
    case 'tag':
      return (
        <svg className={common} fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
        </svg>
      );
    case 'schema':
    case 'property':
      return (
        <svg className={common} fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
        </svg>
      );
    case 'request_body':
    case 'response':
      return (
        <svg className={common} fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M8 7h8m-8 4h8m-8 4h5M5 3h14a2 2 0 012 2v14a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2z" />
        </svg>
      );
    default:
      return (
        <svg className={common} fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
        </svg>
      );
  }
}

function formatPublished(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

/**
 * One search result. A density switch keeps the same row usable in the palette (`compact`) and on
 * the results page.
 */
export function HitRow({
  hit,
  needles,
  compact = false,
  active = false,
  id,
  onSelect,
}: {
  hit: CatalogSearchHit;
  needles: readonly string[];
  compact?: boolean;
  /** Keyboard-focused row (results page `j`/`k`, palette arrows). */
  active?: boolean;
  id?: string;
  onSelect?: () => void;
}) {
  const href = hitHref(hit);
  const crumbs = hitCrumbs(hit);
  const published = formatPublished(hit.published_at);
  const isOperation = hit.hit_type === 'operation' && hit.method && hit.path;
  const snippet = hit.snippet ? excerptAround(hit.snippet, needles, compact ? 70 : 140) : '';
  const facetChips = [hit.paradigm ? paradigmLabel(hit.paradigm) : null, hit.source_format ? formatLabel(hit.source_format) : null].filter(
    Boolean
  ) as string[];

  return (
    <li id={id} className="list-none">
      <Link
        href={href}
        onClick={onSelect}
        aria-current={active ? 'true' : undefined}
        className={`group block rounded-xl border bg-white transition-colors dark:bg-zinc-950 ${
          compact ? 'px-3 py-2' : 'p-4'
        } ${
          active
            ? 'border-[var(--brand)] shadow-sm ring-1 ring-[var(--brand)]/30'
            : 'border-zinc-200 hover:border-sky-300 dark:border-zinc-800 dark:hover:border-sky-700'
        }`}
      >
        <div className="flex items-start gap-3">
          <div
            className={`flex shrink-0 items-center justify-center rounded-lg ${compact ? 'h-8 w-8' : 'h-10 w-10'} ${KIND_TONE[hit.hit_type]}`}
            aria-hidden="true"
          >
            <KindIcon kind={hit.hit_type} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-zinc-500 dark:text-zinc-400">
              <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                {hitKindLabel(hit.hit_type)}
              </span>
              <span className="flex min-w-0 items-center gap-1 truncate">
                {crumbs.map((crumb, i) => (
                  <Fragment key={crumb.href}>
                    {i > 0 && <span aria-hidden="true" className="text-zinc-300 dark:text-zinc-700">›</span>}
                    <span className="truncate">{crumb.label}</span>
                  </Fragment>
                ))}
              </span>
            </div>

            <div className={`mt-1 flex items-center gap-2 ${compact ? '' : 'flex-wrap'}`}>
              {isOperation && <MethodBadge method={hit.method as string} size={compact ? 'sm' : 'md'} />}
              {isOperation ? (
                <code className={`min-w-0 truncate font-mono font-medium text-zinc-900 group-hover:text-[var(--brand)] dark:text-zinc-50 ${compact ? 'text-[13px]' : 'text-[14px]'}`}>
                  <Highlight text={hit.path as string} needles={needles} />
                </code>
              ) : (
                <h3 className={`min-w-0 truncate font-semibold text-zinc-900 group-hover:text-[var(--brand)] dark:text-zinc-50 ${compact ? 'text-[13px]!' : 'text-[15px]!'}`}>
                  <Highlight text={hit.title} needles={needles} />
                </h3>
              )}
            </div>

            {isOperation && hit.title !== `${hit.method} ${hit.path}` && (
              <p className={`mt-0.5 truncate text-zinc-700 dark:text-zinc-300 ${compact ? 'text-[12px]' : 'text-[13px]'}`}>
                <Highlight text={hit.title} needles={needles} />
              </p>
            )}

            {snippet && !(compact && isOperation) && (
              <p className={`mt-1 text-zinc-600 dark:text-zinc-400 ${compact ? 'line-clamp-1 text-[12px]' : 'line-clamp-2 text-[13px] leading-relaxed'}`}>
                <Highlight text={snippet} needles={needles} />
              </p>
            )}

            {!compact && (
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-zinc-500 dark:text-zinc-400">
                {hit.subtitle && !isOperation && <span className="truncate">{hit.subtitle}</span>}
                {facetChips.map((chip) => (
                  <span key={chip} className="rounded-full bg-zinc-100 px-2 py-0.5 text-[10.5px] font-medium text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                    {chip}
                  </span>
                ))}
                {published && (
                  <span className="flex items-center gap-1 tabular-nums">
                    <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden="true">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                    </svg>
                    {published}
                  </span>
                )}
                {(hit.hit_type === 'operation' || hit.hit_type === 'schema' || hit.hit_type === 'property') && (
                  <span className="ml-auto hidden text-[var(--brand-soft-text)] group-hover:inline">Open in spec →</span>
                )}
              </div>
            )}
          </div>
        </div>
      </Link>
    </li>
  );
}
