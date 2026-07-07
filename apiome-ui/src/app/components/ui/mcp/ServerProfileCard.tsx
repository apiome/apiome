'use client';

import * as React from 'react';
import { ExternalLink, FileText, Server, ShieldCheck } from 'lucide-react';
import { cn } from '../../../../../lib/utils';
import { GradeGlyph } from './GradeGlyph';
import { HealthPill } from './HealthPill';
import { RecencyPill } from './RecencyPill';
import { McpBadge } from './McpBadge';
import { mcpTransportBadge } from '../../ade/dashboard/mcp/mcpUiPrimitives';
import { mcpVersionSeqLabel } from '../../ade/dashboard/mcp/mcpVersionsUi';
import {
  mcpTypeCountTiles,
  type McpServerProfile,
} from '../../ade/dashboard/mcp/mcpInsightUi';

export interface ServerProfileCardProps extends React.HTMLAttributes<HTMLElement> {
  /** The assembled, presentation-ready server identity (see {@link mcpServerProfileFrom}). */
  profile: McpServerProfile;
  /**
   * Optional in-page href to the composite trust radar (MCAT-17.4) so the compact trust snapshot
   * links to the full signal. When omitted, the snapshot renders as static text.
   */
  trustHref?: string;
  /** Current time in epoch ms, injected for deterministic recency in tests. Defaults to "now". */
  nowMs?: number;
}

/**
 * The card's leading identity glyph: the server's advertised logo when it has one (V2-MCP-34.2),
 * otherwise the generic server icon. The logo is a *referenced* `https` URL the REST side already
 * validated (SSRF-safe, length-bounded); it is rendered with `referrerPolicy="no-referrer"` so
 * browsing it leaks nothing, and any load failure (dead link, non-image) falls back to the generic
 * glyph so the card is never broken.
 */
function ServerIdentityGlyph({ iconUrl, name }: { iconUrl: string | null; name: string }) {
  const [failed, setFailed] = React.useState(false);
  if (iconUrl !== null && !failed) {
    // A remote, per-server logo URL is not a build-time asset and must not go through the Next image
    // optimizer (which would proxy-fetch it) — so a plain <img> referencing the validated URL is intended.
    return (
      // eslint-disable-next-line @next/next/no-img-element -- see note above
      <img
        src={iconUrl}
        alt={`${name} logo`}
        className="h-5 w-5 shrink-0 rounded object-contain"
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
      />
    );
  }
  return (
    <Server className="h-5 w-5 shrink-0 text-indigo-600 dark:text-indigo-400" aria-hidden />
  );
}

/** One compact capability-count chip (kind → count), rendered from the surface metrics. */
function CountChip({ label, value }: { label: string; value: number }) {
  return (
    <span className="inline-flex items-baseline gap-1 rounded-md bg-gray-100 px-2 py-1 text-xs text-gray-600 dark:bg-gray-700/60 dark:text-gray-300">
      <span className="font-semibold tabular-nums text-gray-900 dark:text-white">{value}</span>
      {label}
    </span>
  );
}

/**
 * `<ServerProfileCard>` — the at-a-glance "who is this server" identity card (V2-MCP-29.1 /
 * MCAT-15.1) that heads the endpoint Insight tab. It composes the shared MCP primitives (grade
 * glyph, transport badge, health & recency pills) into one header: the server's name/title/version,
 * negotiated protocol, transport, quality grade, capability counts, discovery-health, the "surface
 * last changed" recency, a compact trust snapshot linking to the composite trust radar (17.4), and
 * the server's `instructions` rendered prominently when present.
 *
 * It is purely presentational — every field is read from the pre-assembled {@link McpServerProfile},
 * which degrades each value to `null` — so an older (2025-03-26) server missing a title, an unscored
 * snapshot, or an unavailable surface all render a coherent card rather than a broken one. All colors
 * and spacing come from the shared tokens/primitives; no literals live here.
 */
export const ServerProfileCard = React.forwardRef<HTMLElement, ServerProfileCardProps>(
  ({ profile, trustHref, nowMs, className, ...props }, ref) => {
    const transport = mcpTransportBadge(profile.transport);
    // The catalog name is a useful subtitle only when it differs from the server-reported name shown
    // as the headline (otherwise it would just repeat it).
    const showEndpointSubtitle =
      profile.endpointName !== null && profile.endpointName !== profile.displayName;
    const counts = profile.capabilityCounts;
    const countTiles = counts ? mcpTypeCountTiles(counts) : [];

    return (
      <section
        ref={ref}
        aria-label={`Server profile — ${profile.displayName}`}
        className={cn(
          'rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800',
          className,
        )}
        {...props}
      >
        <div className="flex flex-wrap items-start justify-between gap-4">
          {/* Identity: grade glyph + name, url, and the protocol / transport / snapshot chips. */}
          <div className="flex min-w-0 items-start gap-4">
            <GradeGlyph
              variant="gauge"
              size="sm"
              grade={profile.grade}
              score={profile.score}
              className="mt-0.5"
            />
            <div className="min-w-0">
              <h3 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-white">
                <ServerIdentityGlyph iconUrl={profile.iconUrl} name={profile.displayName} />
                <span className="truncate">{profile.displayName}</span>
                {profile.serverVersion ? (
                  <span className="shrink-0 text-sm font-medium text-gray-400 dark:text-gray-500">
                    {profile.serverVersion}
                  </span>
                ) : null}
              </h3>
              {showEndpointSubtitle ? (
                <div className="mt-0.5 truncate text-sm text-gray-500 dark:text-gray-400">
                  {profile.endpointName}
                </div>
              ) : null}
              {profile.endpointUrl ? (
                <div className="mt-0.5 truncate font-mono text-xs text-gray-500 dark:text-gray-400">
                  {profile.endpointUrl}
                </div>
              ) : null}
              {profile.websiteUrl ? (
                <a
                  href={profile.websiteUrl}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  referrerPolicy="no-referrer"
                  className="mt-0.5 inline-flex max-w-full items-center gap-1 text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                >
                  <ExternalLink className="h-3 w-3 shrink-0" aria-hidden />
                  <span className="truncate">{profile.websiteUrl}</span>
                </a>
              ) : null}
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <McpBadge tone={transport.tone}>{transport.label}</McpBadge>
                {profile.protocolVersion ? (
                  <McpBadge tone="slate" title="Negotiated MCP protocol version">
                    MCP {profile.protocolVersion}
                  </McpBadge>
                ) : (
                  <span className="text-xs text-gray-400 dark:text-gray-500">
                    protocol unknown
                  </span>
                )}
                {profile.versionSeq !== null ? (
                  <McpBadge tone={profile.isCurrent ? 'green' : 'indigo'}>
                    {mcpVersionSeqLabel(profile.versionSeq)}
                    {profile.isCurrent ? ' · current' : ''}
                  </McpBadge>
                ) : null}
              </div>
            </div>
          </div>

          {/* Health + "surface last changed" recency, right-aligned. */}
          <div className="flex shrink-0 flex-col items-end gap-1.5">
            <HealthPill discoveryStatus={profile.discoveryStatus} />
            <RecencyPill
              timestamp={profile.lastChangedAt}
              prefix="Surface changed"
              nowMs={nowMs}
            />
          </div>
        </div>

        {/* Capability counts — only when the surface resolved. */}
        {counts ? (
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <CountChip label="capabilities" value={counts.total} />
            <span className="text-gray-300 dark:text-gray-600" aria-hidden>
              ·
            </span>
            {countTiles.map((tile) => (
              <CountChip key={tile.key} label={tile.label.toLowerCase()} value={tile.value} />
            ))}
          </div>
        ) : null}

        {/* Compact trust snapshot — a teaser for the composite trust radar (MCAT-17.4). */}
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-gray-100 pt-3 text-xs text-gray-500 dark:border-gray-700/60 dark:text-gray-400">
          <ShieldCheck className="h-3.5 w-3.5 text-indigo-400" aria-hidden />
          <span className="font-medium text-gray-600 dark:text-gray-300">Trust</span>
          <span>
            Quality grade{' '}
            <span className="font-semibold text-gray-700 dark:text-gray-200">
              {profile.grade ?? '—'}
            </span>
            {profile.score !== null ? ` (${Math.round(profile.score)}/100)` : ''}
          </span>
          {trustHref ? (
            <a
              href={trustHref}
              className="ml-auto font-medium text-indigo-600 hover:underline dark:text-indigo-400"
            >
              Composite trust radar →
            </a>
          ) : (
            <span className="ml-auto text-gray-400 dark:text-gray-500">
              Composite trust radar coming soon
            </span>
          )}
        </div>

        {/* Server instructions, rendered prominently when present. */}
        {profile.instructions ? (
          <div className="mt-4">
            <h4 className="mb-1.5 flex items-center gap-1.5 text-sm font-semibold text-gray-900 dark:text-white">
              <FileText className="h-4 w-4 text-indigo-500" aria-hidden />
              Instructions
            </h4>
            <div className="rounded-lg bg-gray-50 p-3 dark:bg-gray-900/40">
              <p className="whitespace-pre-wrap text-sm text-gray-600 dark:text-gray-300">
                {profile.instructions}
              </p>
            </div>
          </div>
        ) : null}
      </section>
    );
  },
);
ServerProfileCard.displayName = 'ServerProfileCard';
