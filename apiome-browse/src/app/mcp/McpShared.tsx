'use client';

import Link from 'next/link';
import type { McpPublicEndpoint } from '../../../lib/types';

/**
 * Shared visual atoms for the public MCP catalog pages (MCAT-9.6/9.7): the grade glyph (the lead
 * signal everywhere), the transport badge, capability-count pills, and the grade-led endpoint card.
 * Kept in one place so the index, detail, and search screens stay visually consistent.
 */

/** Tailwind tone classes per A–F grade; neutral when ungraded. */
function gradeToneClass(grade: string | null): string {
  switch ((grade ?? '').toUpperCase()) {
    case 'A':
      return 'bg-emerald-100 text-emerald-700 ring-emerald-500/30 dark:bg-emerald-900/40 dark:text-emerald-300';
    case 'B':
      return 'bg-green-100 text-green-700 ring-green-500/30 dark:bg-green-900/40 dark:text-green-300';
    case 'C':
      return 'bg-amber-100 text-amber-700 ring-amber-500/30 dark:bg-amber-900/40 dark:text-amber-300';
    case 'D':
      return 'bg-orange-100 text-orange-700 ring-orange-500/30 dark:bg-orange-900/40 dark:text-orange-300';
    case 'F':
      return 'bg-red-100 text-red-700 ring-red-500/30 dark:bg-red-900/40 dark:text-red-300';
    default:
      return 'bg-zinc-100 text-zinc-600 ring-zinc-400/30 dark:bg-zinc-800 dark:text-zinc-300';
  }
}

/** The grade glyph: `B · 82`, `B`, or `—` (ungraded). The lead signal on every endpoint. */
export function GradeBadge({
  grade,
  score,
  size = 'md',
}: {
  grade: string | null;
  score: number | null;
  size?: 'sm' | 'md';
}) {
  const label =
    grade && score != null ? `${grade} · ${score}` : grade ? grade : score != null ? `${score}` : '—';
  const dims = size === 'sm' ? 'px-1.5 py-0.5 text-[11px]' : 'px-2 py-0.5 text-xs';
  return (
    <span
      title={grade ? `Grade ${grade}${score != null ? ` · score ${score}` : ''}` : 'Not yet graded'}
      className={`inline-flex items-center rounded-full font-semibold tabular-nums ring-1 ring-inset ${dims} ${gradeToneClass(
        grade
      )}`}
    >
      {label}
    </span>
  );
}

/** Transport pill (streamable_http / sse / stdio). */
export function TransportBadge({ transport }: { transport: string }) {
  return (
    <span className="inline-flex items-center rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
      {transport}
    </span>
  );
}

/** Compact capability counts (tools / resources / templates / prompts), zeros omitted. */
export function CapabilityCounts({ endpoint }: { endpoint: McpPublicEndpoint }) {
  const parts: string[] = [];
  if (endpoint.tool_count) parts.push(`${endpoint.tool_count} tool${endpoint.tool_count === 1 ? '' : 's'}`);
  if (endpoint.resource_count)
    parts.push(`${endpoint.resource_count} resource${endpoint.resource_count === 1 ? '' : 's'}`);
  if (endpoint.resource_template_count)
    parts.push(
      `${endpoint.resource_template_count} template${endpoint.resource_template_count === 1 ? '' : 's'}`
    );
  if (endpoint.prompt_count)
    parts.push(`${endpoint.prompt_count} prompt${endpoint.prompt_count === 1 ? '' : 's'}`);
  return (
    <span className="text-[11px] text-zinc-500 dark:text-zinc-400">
      {parts.length ? parts.join(' · ') : 'No capabilities discovered'}
    </span>
  );
}

/** A grade-led endpoint card linking to its detail page. */
export function McpEndpointCard({ endpoint }: { endpoint: McpPublicEndpoint }) {
  return (
    <Link
      href={`/mcp/${endpoint.tenant_slug}/${endpoint.slug}`}
      className="group flex h-full flex-col gap-2 rounded-xl border border-zinc-200 bg-white p-4 shadow-xs transition-all hover:-translate-y-0.5 hover:border-zinc-300 hover:shadow-md dark:border-zinc-800 dark:bg-zinc-950 dark:hover:border-zinc-700"
    >
      <div className="flex items-start justify-between gap-2">
        <GradeBadge grade={endpoint.grade} score={endpoint.score} />
        <TransportBadge transport={endpoint.transport} />
      </div>
      <div className="min-w-0">
        <h3 className="truncate text-[15px] font-semibold text-zinc-900 transition-colors group-hover:text-[var(--brand)] dark:text-zinc-50">
          {endpoint.name}
        </h3>
        <p className="truncate text-xs text-zinc-500 dark:text-zinc-400">{endpoint.host ?? 'Unknown host'}</p>
      </div>
      {endpoint.description && (
        <p className="line-clamp-2 text-[13px] leading-snug text-zinc-600 dark:text-zinc-400">
          {endpoint.description}
        </p>
      )}
      <div className="mt-auto border-t border-zinc-100 pt-2 dark:border-zinc-800/80">
        <CapabilityCounts endpoint={endpoint} />
      </div>
    </Link>
  );
}
