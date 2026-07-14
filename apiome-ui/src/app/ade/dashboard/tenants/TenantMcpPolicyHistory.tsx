'use client';

/**
 * Tenant MCP policy change history — MTG-5.2 (#4786).
 *
 * Loads newest-first audit rows from `/api/tenants/mcp-policy/history` and
 * expands a row to show before/after tool enablement (and top-level fields).
 */

import { useCallback, useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, History, Loader2, RefreshCw } from 'lucide-react';
import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import {
  fetchMcpPolicyHistory,
  type TenantMcpPolicyChangeEntry,
} from './mcpPolicyApi';
import {
  diffMcpPolicySnapshots,
  formatToolFlagValue,
  type McpPolicySnapshotDiff,
} from './mcpPolicyHistoryDiff';

export interface TenantMcpPolicyHistoryProps {
  /** Bumped after a successful policy save so the list refreshes. */
  reloadToken?: number;
}

function formatWhen(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function ChangeDetail({ diff }: { diff: McpPolicySnapshotDiff }) {
  if (diff.topLevel.length === 0 && diff.tools.length === 0) {
    return (
      <p className="text-xs text-gray-500 dark:text-gray-400 px-4 py-3">
        No field-level differences in this snapshot pair.
      </p>
    );
  }

  return (
    <div className="space-y-3 border-t border-slate-100 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/50">
      {diff.topLevel.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
            Policy fields
          </h4>
          <ul className="space-y-1.5">
            {diff.topLevel.map((change) => (
              <li
                key={change.field}
                className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-sm text-gray-800 dark:text-gray-200"
              >
                <span className="font-medium">{change.label}</span>
                <span className="text-gray-500 dark:text-gray-400">{change.before}</span>
                <span className="text-gray-400 dark:text-gray-500" aria-hidden>
                  →
                </span>
                <span className="font-medium text-indigo-700 dark:text-indigo-300">
                  {change.after}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {diff.tools.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-2">
            Tool enablement
          </h4>
          <ul className="divide-y divide-slate-200 dark:divide-slate-800 rounded-lg border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900 overflow-hidden">
            {diff.tools.map((change) => (
              <li
                key={`${change.tool_id}:${change.flag}`}
                className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
              >
                <div className="min-w-0">
                  <span className="font-medium text-gray-900 dark:text-white">
                    {change.tool_id}
                  </span>
                  <span className="ml-2 text-xs text-gray-500 dark:text-gray-400">
                    {change.label}
                  </span>
                </div>
                <div className="flex items-center gap-2 text-xs tabular-nums">
                  <span className="text-gray-500 dark:text-gray-400">
                    {formatToolFlagValue(change.before)}
                  </span>
                  <span className="text-gray-400 dark:text-gray-500" aria-hidden>
                    →
                  </span>
                  <span className="font-medium text-indigo-700 dark:text-indigo-300">
                    {formatToolFlagValue(change.after)}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function HistoryRow({ change }: { change: TenantMcpPolicyChangeEntry }) {
  const [open, setOpen] = useState(false);
  const diff = diffMcpPolicySnapshots(change.before_policy, change.after_policy);
  const actor = change.actor_label || change.actor_user_id || 'Unknown';

  return (
    <li className="border-b border-slate-100 last:border-b-0 dark:border-slate-800">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
        aria-expanded={open}
      >
        <span className="mt-0.5 text-gray-400 dark:text-gray-500" aria-hidden>
          {open ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </span>
        <div className="min-w-0 flex-1 grid gap-1 sm:grid-cols-[minmax(0,11rem)_minmax(0,8rem)_1fr] sm:gap-3">
          <span className="text-sm text-gray-700 dark:text-gray-300 tabular-nums">
            {formatWhen(change.created_at)}
          </span>
          <span className="text-sm font-medium text-gray-900 dark:text-white truncate">
            {actor}
          </span>
          <span className="text-sm text-gray-500 dark:text-gray-400">{diff.summary}</span>
        </div>
      </button>
      {open ? <ChangeDetail diff={diff} /> : null}
    </li>
  );
}

export default function TenantMcpPolicyHistory({
  reloadToken = 0,
}: TenantMcpPolicyHistoryProps) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [changes, setChanges] = useState<TenantMcpPolicyChangeEntry[]>([]);
  const [loadedOnce, setLoadedOnce] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const body = await fetchMcpPolicyHistory(50);
      setChanges(body.changes ?? []);
      setLoadedOnce(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load policy history');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!expanded) return;
    void load();
  }, [expanded, reloadToken, load]);

  return (
    <section
      aria-label="MCP policy history"
      className="overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900"
    >
      <div className="flex items-center justify-between gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/50">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-2 text-sm font-semibold text-gray-800 dark:text-gray-200 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors"
          aria-expanded={expanded}
        >
          <History className="h-4 w-4 text-indigo-600 dark:text-indigo-400" aria-hidden />
          Policy history
          {expanded ? (
            <ChevronDown className="h-4 w-4" aria-hidden />
          ) : (
            <ChevronRight className="h-4 w-4" aria-hidden />
          )}
        </button>
        {expanded ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void load()}
            disabled={loading}
            aria-label="Refresh policy history"
          >
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            Refresh
          </Button>
        ) : null}
      </div>

      {expanded && (
        <div>
          {error ? (
            <div className="p-4">
              <Alert variant="error">{error}</Alert>
            </div>
          ) : null}

          {loading && !loadedOnce ? (
            <div className="flex items-center gap-2 px-4 py-6 text-sm text-gray-500 dark:text-gray-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading policy history…
            </div>
          ) : changes.length === 0 ? (
            <p className="px-4 py-6 text-sm text-gray-500 dark:text-gray-400">
              No policy changes recorded yet. Saving MCP settings will start this audit trail.
            </p>
          ) : (
            <>
              <div className="hidden sm:grid sm:grid-cols-[minmax(0,11rem)_minmax(0,8rem)_1fr] gap-3 px-4 pl-11 py-2 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 border-b border-slate-100 dark:border-slate-800">
                <span>When</span>
                <span>Actor</span>
                <span>Change</span>
              </div>
              <ul>{changes.map((change) => <HistoryRow key={change.id} change={change} />)}</ul>
            </>
          )}
        </div>
      )}
    </section>
  );
}
