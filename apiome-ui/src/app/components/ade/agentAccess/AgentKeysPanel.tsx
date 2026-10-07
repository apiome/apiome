'use client';

import * as React from 'react';
import { KeyRound, ListChecks, Plus, Ban } from 'lucide-react';

import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { Label } from '@/app/components/ui/Label';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { Switch } from '@/app/components/ui/Switch';
import { Meter } from '@/app/components/ui/metrics';

import {
  agentKeyIsMutable,
  dailyQuotaMeter,
  describeCaps,
  formatCount,
  toolsetLabel,
  type AgentKey,
  type AgentKeyUsage,
  type AgentToolset,
  type PublishedVersionOption,
} from './agentAccessModel';

/**
 * Agent key management — AGX-3.4 (#4540), over AGX-3.1 keys and AGX-3.2 usage.
 *
 * One row per key: what it is called and its prefix, the toolset it is bound to, its status,
 * how many tools it may call, when it expires, and **today's calls against the tier's daily cap**
 * (a meter, or a plain count when the cap is unlimited). The two writes — edit the allowlist,
 * revoke — are the row's; creating a key is the panel's.
 *
 * Presentational: the page owns keys, usage and writes.
 */

/** A key's usage as the page has it: loaded, failed, or not yet. */
export type AgentKeyUsageState = AgentKeyUsage | 'error' | undefined;

/** Props for {@link AgentKeysPanel}. */
export interface AgentKeysPanelProps {
  keys: readonly AgentKey[];
  toolsets: readonly AgentToolset[];
  versions: readonly PublishedVersionOption[];
  usage: Readonly<Record<string, AgentKeyUsageState>>;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  includeRevoked: boolean;
  onIncludeRevokedChange: (next: boolean) => void;
  onCreate: () => void;
  onEditAllowlist: (key: AgentKey) => void;
  onRevoke: (key: AgentKey) => void;
}

/**
 * Format an ISO instant as a short date.
 *
 * @param iso - The instant, or null.
 * @param fallback - What to show without one.
 * @returns e.g. `Oct 6, 2026`.
 */
function shortDate(iso: string | null, fallback: string): string {
  if (!iso) return fallback;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return fallback;
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

/**
 * Today's usage cell.
 *
 * @param props - The key's usage state.
 * @returns A meter, a plain count, or a placeholder.
 */
function UsageCell({ usage, name }: { usage: AgentKeyUsageState; name: string }) {
  if (usage === undefined) return <span className="agx-hint">…</span>;
  if (usage === 'error') return <span className="agx-hint">Unavailable</span>;
  const meter = dailyQuotaMeter(usage);
  return (
    <div className="agx-usage-cell">
      {meter ? (
        <Meter
          label={`${name}: calls today`}
          value={meter.value}
          max={meter.max}
          valueText={meter.valueText}
          showLabel={false}
          thin
          valueLabel={`${formatCount(usage.used)} / ${formatCount(meter.max)}`}
        />
      ) : (
        <span>{formatCount(usage.used)} calls today</span>
      )}
      <span className="agx-hint">{describeCaps(usage)}</span>
    </div>
  );
}

/**
 * The keys panel.
 *
 * @param props See {@link AgentKeysPanelProps}.
 * @returns The toolbar and the keys table, or its loading / error / empty state.
 */
export default function AgentKeysPanel({
  keys,
  toolsets,
  versions,
  usage,
  loading,
  error,
  onRetry,
  includeRevoked,
  onIncludeRevokedChange,
  onCreate,
  onEditAllowlist,
  onRevoke,
}: AgentKeysPanelProps) {
  const toolsetsById = React.useMemo(
    () => new Map(toolsets.map((t) => [t.id, t])),
    [toolsets]
  );

  let body: React.ReactNode;
  if (loading && keys.length === 0) {
    body = <LoadingState message="Loading agent keys…" data-testid="agx-keys-loading" />;
  } else if (error) {
    body = (
      <ErrorState
        title="Agent keys could not be loaded"
        description={error}
        onRetry={onRetry}
        data-testid="agx-keys-error"
      />
    );
  } else if (keys.length === 0) {
    body = (
      <EmptyState
        icon={<KeyRound aria-hidden />}
        title="No agent keys yet"
        description={
          toolsets.length === 0
            ? 'Enable Agent Access on a published version first; each key binds to one toolset.'
            : 'Give an agent like Claude Desktop a key scoped to the tools you allow.'
        }
        action={
          toolsets.length > 0 ? (
            <Button onClick={onCreate} data-testid="agx-keys-empty-create">
              <Plus aria-hidden />
              Create agent key
            </Button>
          ) : undefined
        }
        data-testid="agx-keys-empty"
      />
    );
  } else {
    body = (
      <div className="agx-table-wrap">
        <table className="agx-table" data-testid="agx-keys-table">
          <caption className="sr-only">Agent keys</caption>
          <thead>
            <tr>
              <th scope="col">Key</th>
              <th scope="col">Toolset</th>
              <th scope="col">Status</th>
              <th scope="col">Tools</th>
              <th scope="col">Expires</th>
              <th scope="col">Today</th>
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {keys.map((key) => {
              const toolset = toolsetsById.get(key.toolsetId);
              const mutable = agentKeyIsMutable(key);
              return (
                <tr key={key.id} data-testid={`agx-key-row-${key.id}`} data-status={key.status}>
                  <td>
                    <div className="agx-key-identity">
                      <span className="agx-key-identity__name">{key.name}</span>
                      <code className="agx-hint mono">{key.keyPrefix}</code>
                    </div>
                  </td>
                  <td>{toolset ? toolsetLabel(toolset, versions) : 'Deleted toolset'}</td>
                  <td>
                    <Badge status={key.status} dot>
                      {key.status}
                    </Badge>
                  </td>
                  <td>{key.toolAllowlist.length}</td>
                  <td>{shortDate(key.expiresAt, 'Never')}</td>
                  <td>
                    <UsageCell usage={usage[key.id]} name={key.name} />
                  </td>
                  <td>
                    <div className="agx-row-actions">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={!mutable}
                        onClick={() => onEditAllowlist(key)}
                        data-testid={`agx-key-allowlist-${key.id}`}
                      >
                        <ListChecks aria-hidden />
                        Tools
                      </Button>
                      <Button
                        variant="danger-soft"
                        size="sm"
                        disabled={!mutable}
                        onClick={() => onRevoke(key)}
                        data-testid={`agx-key-revoke-${key.id}`}
                      >
                        <Ban aria-hidden />
                        Revoke
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <section className="agx-panel" aria-label="Agent keys" data-testid="agx-keys">
      <div className="agx-toolbar">
        <div className="agx-inline-field">
          <Switch
            id="agx-keys-include-revoked"
            checked={includeRevoked}
            onCheckedChange={onIncludeRevokedChange}
            data-testid="agx-keys-include-revoked"
          />
          <Label htmlFor="agx-keys-include-revoked">Show revoked keys</Label>
        </div>
        {toolsets.length > 0 && keys.length > 0 && (
          <Button size="sm" onClick={onCreate} data-testid="agx-keys-create">
            <Plus aria-hidden />
            Create agent key
          </Button>
        )}
      </div>
      {body}
    </section>
  );
}
