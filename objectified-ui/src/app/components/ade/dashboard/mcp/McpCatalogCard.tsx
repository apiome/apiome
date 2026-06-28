'use client';

import * as React from 'react';
import Link from 'next/link';
import { ArrowRight, ShieldAlert, Sparkles } from 'lucide-react';
import { cn } from '@lib/utils';
import { GradeGlyph } from '../../../ui/mcp/GradeGlyph';
import { McpBadge } from '../../../ui/mcp/McpBadge';
import { HealthPill } from '../../../ui/mcp/HealthPill';
import { RecencyPill } from '../../../ui/mcp/RecencyPill';
import {
  mcpAuthBadge,
  mcpTransportBadge,
  mcpVisibilityBadge,
} from './mcpUiPrimitives';
import type { McpBrowseEndpoint } from './mcpBrowseUi';
import type { McpCatalogDensity } from './mcpCatalogUi';

export interface McpCatalogCardProps {
  endpoint: McpBrowseEndpoint;
  /** Detail route the card links to (e.g. `/ade/dashboard/mcp/<id>`). */
  href: string;
  /** Grid card (default) or a compact one-row dense-list entry. */
  density?: McpCatalogDensity;
  /** Render the "Changed since last view" marker (set by the page from the seen snapshot). */
  changed?: boolean;
}

/** The transport / visibility / auth badges an endpoint shows; auth only when the catalog has it. */
function EndpointBadges({ endpoint }: { endpoint: McpBrowseEndpoint }): React.ReactElement {
  const transport = mcpTransportBadge(endpoint.transport);
  const visibility = mcpVisibilityBadge(endpoint.visibility);
  const auth = endpoint.auth_scheme ? mcpAuthBadge(endpoint.auth_scheme) : null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <McpBadge tone={transport.tone}>{transport.label}</McpBadge>
      <McpBadge tone={visibility.tone}>{visibility.label}</McpBadge>
      {auth ? <McpBadge tone={auth.tone}>{auth.label}</McpBadge> : null}
    </div>
  );
}

/** Compact `3t · 2r · 1rt · 4p` capability counts with an accessible full label. */
function CapabilityCounts({
  endpoint,
  className,
}: {
  endpoint: McpBrowseEndpoint;
  className?: string;
}): React.ReactElement {
  return (
    <span
      className={cn('tabular-nums text-gray-600 dark:text-gray-300', className)}
      title="tools / resources / resource templates / prompts"
    >
      {endpoint.tool_count}t · {endpoint.resource_count}r · {endpoint.resource_template_count}rt ·{' '}
      {endpoint.prompt_count}p
    </span>
  );
}

/** The "Changed since last view" marker — an amber sparkle chip, only when `changed`. */
function ChangedMarker(): React.ReactElement {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-700 ring-1 ring-inset ring-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:ring-amber-800"
      title="This endpoint's surface has versioned since your last visit"
    >
      <Sparkles className="h-3 w-3 shrink-0" aria-hidden />
      Changed
    </span>
  );
}

/** The quarantined warning chip an endpoint shows when it is held back from discovery. */
function QuarantinedChip(): React.ReactElement {
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-600 dark:text-amber-400">
      <ShieldAlert className="h-3.5 w-3.5 shrink-0" aria-hidden />
      Quarantined
    </span>
  );
}

/**
 * `<McpCatalogCard>` — one endpoint in the grade-led catalog. The A–F grade glyph leads; the name
 * links to the endpoint detail; transport / visibility / auth render as badges; capability counts,
 * a health pill, and a recency pill summarize the surface. A "Changed" marker appears when the
 * endpoint versioned since the user's last visit. The `density` prop switches between the roomy
 * grid card and a compact dense-list row, sharing the same atoms (all from the 10.7 primitives).
 */
export const McpCatalogCard = React.forwardRef<HTMLAnchorElement, McpCatalogCardProps>(
  ({ endpoint, href, density = 'grid', changed = false }, ref) => {
    if (density === 'list') {
      return (
        <Link
          ref={ref}
          href={href}
          className={cn(
            'group flex items-center gap-3 px-4 py-2.5',
            'hover:bg-gray-50 dark:hover:bg-gray-900/50 focus-visible:outline-none',
            'focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-indigo-500',
          )}
          aria-label={`Open ${endpoint.name}`}
        >
          <GradeGlyph grade={endpoint.grade} score={endpoint.score} size="sm" showScore={false} />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate font-medium text-gray-900 group-hover:text-indigo-600 dark:text-white dark:group-hover:text-indigo-400">
                {endpoint.name}
              </span>
              {changed ? <ChangedMarker /> : null}
              {endpoint.quarantined ? <QuarantinedChip /> : null}
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
              <CapabilityCounts endpoint={endpoint} className="text-xs" />
              <span aria-hidden>·</span>
              <HealthPill discoveryStatus={endpoint.last_discovery_status} dotOnly />
            </div>
          </div>
          <div className="hidden shrink-0 sm:block">
            <EndpointBadges endpoint={endpoint} />
          </div>
          <RecencyPill
            timestamp={endpoint.last_discovered_at}
            prefix=""
            hideIcon
            className="hidden shrink-0 md:inline-flex"
          />
          <ArrowRight
            className="h-4 w-4 shrink-0 text-gray-300 transition-colors group-hover:text-indigo-600 dark:group-hover:text-indigo-400"
            aria-hidden
          />
        </Link>
      );
    }

    return (
      <Link
        ref={ref}
        href={href}
        className={cn(
          'group relative flex flex-col gap-3 rounded-lg border border-gray-200 bg-white p-4 shadow-sm transition-shadow',
          'hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500',
          'dark:border-gray-700 dark:bg-gray-800',
        )}
        aria-label={`Open ${endpoint.name}`}
      >
        <div className="flex items-start gap-3">
          <GradeGlyph grade={endpoint.grade} score={endpoint.score} size="md" />
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <h4 className="truncate font-semibold text-gray-900 group-hover:text-indigo-600 dark:text-white dark:group-hover:text-indigo-400">
                {endpoint.name}
              </h4>
              <ArrowRight
                className="mt-0.5 h-4 w-4 shrink-0 text-gray-300 transition-colors group-hover:text-indigo-600 dark:group-hover:text-indigo-400"
                aria-hidden
              />
            </div>
            <p className="mt-0.5 truncate text-xs text-gray-500 dark:text-gray-400">
              {endpoint.host}
            </p>
          </div>
        </div>

        <EndpointBadges endpoint={endpoint} />

        <div className="mt-auto flex items-center justify-between gap-2 text-xs">
          <CapabilityCounts endpoint={endpoint} className="text-xs" />
          <HealthPill discoveryStatus={endpoint.last_discovery_status} />
        </div>

        <div className="flex items-center justify-between gap-2">
          <RecencyPill timestamp={endpoint.last_discovered_at} />
          <div className="flex items-center gap-2">
            {endpoint.quarantined ? <QuarantinedChip /> : null}
            {changed ? <ChangedMarker /> : null}
          </div>
        </div>
      </Link>
    );
  },
);
McpCatalogCard.displayName = 'McpCatalogCard';
