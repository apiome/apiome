'use client';

import * as React from 'react';
import { Badge } from '@/app/components/ui/Badge';
import {
  mcpUptimeBadge,
  mcpUptimeSummaryFromPayload,
  type McpUptimeSummary,
} from '@/app/components/ade/dashboard/mcp/mcpUptimeUi';

export interface UptimeBadgeProps {
  /** The catalog endpoint whose uptime to show. */
  endpointId: string;
}

/**
 * `<UptimeBadge>` — an endpoint's recent reachability as one status pill (V2-MCP-27.3 / MCAT-13.3).
 *
 * Reads `/api/mcp/endpoints/{id}/uptime` (the last 24 hours of lightweight `initialize` probes) and
 * prints the summary status with its uptime and median latency — `Up · 99.9% · 120 ms`,
 * `Degraded · 97.2% · 340 ms`, `Down · 80.0%` or `Uptime unknown` — with the probe counts in the
 * tooltip. Colours come from the shared status vocabulary through `<Badge status>`; all wording comes
 * from the pure {@link mcpUptimeBadge}. A failed read renders `Uptime unknown` rather than an error,
 * because the badge is a glance, not a panel.
 */
export function UptimeBadge({ endpointId }: UptimeBadgeProps) {
  const [summary, setSummary] = React.useState<McpUptimeSummary | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/mcp/endpoints/${endpointId}/uptime?limit=1`, {
          credentials: 'include',
        });
        const data = res.ok ? await res.json() : null;
        if (!cancelled) setSummary(mcpUptimeSummaryFromPayload(data));
      } catch {
        if (!cancelled) setSummary(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [endpointId]);

  const badge = mcpUptimeBadge(summary);
  return (
    <Badge status={badge.vocabulary} dot title={badge.title} data-testid="mcp-uptime-badge">
      {badge.text}
    </Badge>
  );
}
