'use client';

/**
 * Shadowed-names panel (CLX-3.4, #4858).
 *
 * Surfaces tool/resource/prompt names exposed by more than one *enabled* endpoint in the tenant's
 * host scope — tool shadowing (OWASP MCP09), where an agent routing by name can be steered to the
 * wrong server. A collision whose endpoints all share a host is flagged strongest (`same_host`); a
 * cross-host collision is advisory. The panel owns its fetch and renders nothing intrusive when the
 * scope is clean.
 */

import * as React from 'react';
import { Copy, ShieldCheck } from 'lucide-react';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { parseShadowReport, type ShadowReport } from '@/app/utils/mcp-trust-drift';

const CHIP_BASE =
  'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium';

/** CSS classes for the host-scope chip (same-host is the stronger signal). */
export function shadowScopeClass(hostScope: string): string {
  return hostScope === 'same_host'
    ? 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300'
    : 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300';
}

export function ShadowedNamesPanel() {
  const [report, setReport] = React.useState<ShadowReport | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch('/api/mcp/data-quality/shadowing', { credentials: 'include' });
        if (cancelled) return;
        if (!res.ok) {
          setError(`Request failed (${res.status})`);
          setLoading(false);
          return;
        }
        const payload = await res.json();
        if (cancelled) return;
        setReport(parseShadowReport(payload));
        setLoading(false);
      } catch {
        if (!cancelled) {
          setError('Could not load shadowing report.');
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return <LoadingState message="Scanning enabled endpoints for shadowed names…" />;
  }
  if (error || !report) {
    return (
      <EmptyState
        icon={<Copy className="h-8 w-8 text-white" aria-hidden />}
        title="Shadowing report unavailable"
        description={error ?? 'The shadowing report could not be loaded.'}
      />
    );
  }
  if (report.groupCount === 0) {
    return (
      <EmptyState
        icon={<ShieldCheck className="h-8 w-8 text-white" aria-hidden />}
        title="No shadowed names"
        description="No tool, resource, or prompt name is exposed by more than one enabled endpoint in this host scope."
      />
    );
  }

  return (
    <ul className="space-y-2">
      {report.groups.map((group) => (
        <li
          key={`${group.itemType}:${group.name}`}
          className="rounded-md border border-gray-200 p-2 dark:border-gray-800"
        >
          <div className="flex flex-wrap items-center gap-2">
            <span className={`${CHIP_BASE} ${shadowScopeClass(group.hostScope)}`}>
              {group.hostScope === 'same_host' ? 'Same host' : 'Cross host'}
            </span>
            <span className="font-mono text-xs text-gray-700 dark:text-gray-300">
              {group.itemType}:{group.name}
            </span>
            <span className="text-xs text-gray-500 dark:text-gray-400">
              exposed by {group.endpointCount} endpoints
            </span>
          </div>
          <p className="mt-1 text-xs text-gray-600 dark:text-gray-400">
            {group.endpoints.map((endpoint) => endpoint.name || endpoint.slug || endpoint.id).join(', ')}
          </p>
        </li>
      ))}
    </ul>
  );
}

export default ShadowedNamesPanel;
