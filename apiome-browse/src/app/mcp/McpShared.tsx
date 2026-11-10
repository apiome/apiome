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
      return 'bg-ok-soft text-ok-fg ring-ok/30';
    case 'B':
      return 'bg-ok-soft text-ok-fg ring-ok/30';
    case 'C':
      return 'bg-honey-soft text-honey-fg ring-honey/30';
    case 'D':
      return 'bg-orange-soft text-orange-fg ring-orange/30';
    case 'F':
      return 'bg-danger-soft text-danger-fg ring-danger/30';
    default:
      return 'bg-subtle text-fg-muted ring-border-strong/30';
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
  const dims = size === 'sm' ? 'px-1.5 py-0.5 text-2xs' : 'px-2 py-0.5 text-xs';
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
    <span className="inline-flex items-center rounded-xs bg-subtle px-1.5 py-0.5 font-mono text-2xs uppercase tracking-wide text-fg-muted">
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
    <span className="text-2xs text-fg-muted">
      {parts.length ? parts.join(' · ') : 'No capabilities discovered'}
    </span>
  );
}

/** A grade-led endpoint card linking to its detail page. */
export function McpEndpointCard({ endpoint }: { endpoint: McpPublicEndpoint }) {
  return (
    <Link
      href={`/mcp/${endpoint.tenant_slug}/${endpoint.slug}`}
      className="group flex h-full flex-col gap-2 rounded-lg border border-border bg-surface p-4 shadow-xs transition-all hover:-translate-y-0.5 hover:border-border-strong hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-2">
        <GradeBadge grade={endpoint.grade} score={endpoint.score} />
        <TransportBadge transport={endpoint.transport} />
      </div>
      <div className="min-w-0">
        <h3 className="truncate text-lg font-semibold text-fg transition-colors group-hover:text-accent-fg">
          {endpoint.name}
        </h3>
        <p className="truncate text-xs text-fg-muted">{endpoint.host ?? 'Unknown host'}</p>
      </div>
      {endpoint.description && (
        <p className="line-clamp-2 text-sm leading-snug text-fg-muted">
          {endpoint.description}
        </p>
      )}
      <div className="mt-auto border-t border-border pt-2">
        <CapabilityCounts endpoint={endpoint} />
      </div>
    </Link>
  );
}
