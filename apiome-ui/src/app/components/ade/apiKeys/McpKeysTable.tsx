'use client';

import * as React from 'react';
import { Ban, Check, CircleAlert, Copy, KeyRound, Plus } from 'lucide-react';

import type { McpApiKeyMetadata } from '@/app/ade/dashboard/tenants/mcpKeysApi';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import {
  DataTable,
  DataTableCellPrimary,
  DataTableFilterChip,
  DataTableFoot,
  DataTableSearch,
  DataTableToolbar,
  type DataTableColumn,
  type DataTableSortState,
} from '@/app/components/ui/DataTable';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { useClipboardCopy } from '@/app/hooks/useClipboardCopy';

import {
  copyableApiKeyPrefix,
  displayApiKeyPrefix,
  formatApiKeyDate,
  formatApiKeyTimestamp,
} from './apiKeysModel';
import {
  describeMcpKeyBreakdown,
  describeMcpKeyCapabilities,
  matchesMcpKeyFacet,
  mcpKeyFacetCounts,
  mcpKeyStatus,
  searchMcpKeys,
  sortMcpKeys,
  MCP_KEY_FACETS,
  MCP_KEY_FACET_LABELS,
  MCP_KEY_STATUS_LABEL,
  type McpKeyFacet,
} from './mcpKeysModel';

/**
 * The MCP keys list — the API keys page's **MCP server** tab.
 *
 * The REST table's shape ({@link ./ApiKeysTable}) over `apiome.mcp_api_keys`: the same
 * toolbar, prefix cell, timestamp formats and row tints, so the two tabs read as one page.
 * Where the two lifecycles differ, the table follows the MCP one: a key is **revoked** rather
 * than switched off or deleted, revocation is permanent, and a revoked row stays for audit
 * with nothing left to press.
 */

/** Props for {@link McpKeysTable}. */
export interface McpKeysTableProps {
  /** Every MCP key of the tenant, revoked ones included. */
  keys: readonly McpApiKeyMetadata[];
  /** True while the read is in flight. */
  loading?: boolean;
  /** Why the list could not be read. Replaces the body with a retry. */
  error?: string | null;
  /** Retry the read. */
  onRetry?: () => void;
  /** The key a write is running against, so only that row's control goes inert. */
  busyKeyId?: string | null;
  /** Ask to revoke a key. Confirmed by the caller. */
  onRevoke: (key: McpApiKeyMetadata) => void;
  /** Open the create dialog, from the empty state. */
  onCreate: () => void;
  /** The moment status is judged against. */
  now?: Date;
}

/**
 * The copy-prefix button of one row — its own component so only the pressed one says "Copied".
 *
 * @param props.prefix The stored prefix.
 * @param props.label The key's label, for the button's accessible name.
 * @returns The button.
 */
function CopyPrefixButton({ prefix, label }: { prefix: string; label: string }) {
  const { copied, copy } = useClipboardCopy();
  return (
    <Button
      variant="ghost"
      size="sm"
      className="akey-prefix-copy"
      title={copied ? 'Copied!' : 'Copy prefix'}
      aria-label={copied ? `Copied the prefix of ${label}` : `Copy the prefix of ${label}`}
      onClick={() => void copy(copyableApiKeyPrefix(prefix))}
    >
      {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
    </Button>
  );
}

/**
 * The MCP keys list, its toolbar, its foot and its per-row Revoke.
 *
 * @param props See {@link McpKeysTableProps}.
 * @returns The table card.
 */
export default function McpKeysTable({
  keys,
  loading = false,
  error = null,
  onRetry,
  busyKeyId = null,
  onRevoke,
  onCreate,
  now,
}: McpKeysTableProps) {
  const [query, setQuery] = React.useState('');
  const [facet, setFacet] = React.useState<McpKeyFacet>('all');
  const [sort, setSort] = React.useState<DataTableSortState | null>(null);

  const at = React.useMemo(() => now ?? new Date(), [now]);

  const searched = React.useMemo(() => searchMcpKeys(keys, query), [keys, query]);
  const counts = React.useMemo(() => mcpKeyFacetCounts(searched, at), [searched, at]);
  const visible = React.useMemo(
    () => sortMcpKeys(searched.filter((key) => matchesMcpKeyFacet(key, facet, at)), sort, at),
    [searched, facet, sort, at]
  );
  const narrowed = query.trim().length > 0 || facet !== 'all';

  const columns = React.useMemo<DataTableColumn<McpApiKeyMetadata>[]>(
    () => [
      {
        id: 'label',
        header: 'Label',
        sortable: true,
        cell: (key) => (
          <div className="akey-identity" data-testid="mcp-key-row" data-mcp-key-label={key.label}>
            <span
              className="tnt-icon-tile"
              data-tone={mcpKeyStatus(key, at) === 'active' ? 'honey' : 'danger'}
            >
              <KeyRound aria-hidden />
            </span>
            <span className="akey-identity__text">
              <DataTableCellPrimary className="akey-identity__name">{key.label}</DataTableCellPrimary>
            </span>
          </div>
        ),
        skeletonWidth: '11rem',
      },
      {
        id: 'prefix',
        header: 'Prefix',
        sortable: true,
        cell: (key) => (
          <span className="akey-prefix">
            <code className="akey-prefix__value mono">{displayApiKeyPrefix(key.prefix)}</code>
            <CopyPrefixButton prefix={key.prefix} label={key.label} />
          </span>
        ),
        skeletonWidth: '7rem',
      },
      {
        id: 'capabilities',
        header: 'Tools',
        sortable: true,
        cell: (key) => (
          <span className="akey-stamp" data-testid={`mcp-key-capabilities-${key.id}`}>
            {describeMcpKeyCapabilities(key)}
          </span>
        ),
        skeletonWidth: '8rem',
      },
      {
        id: 'status',
        header: 'Status',
        sortable: true,
        cell: (key) => {
          const status = mcpKeyStatus(key, at);
          return (
            <Badge status={status} dot={status === 'active'}>
              {status === 'expired' && <CircleAlert aria-hidden />}
              {MCP_KEY_STATUS_LABEL[status]}
            </Badge>
          );
        },
        skeletonWidth: '4.5rem',
      },
      {
        id: 'lastUsed',
        header: 'Last used',
        sortable: true,
        cell: (key) => <span className="akey-stamp">{formatApiKeyTimestamp(key.last_used_at)}</span>,
        skeletonWidth: '7rem',
      },
      {
        id: 'created',
        header: 'Created',
        sortable: true,
        cell: (key) => <span className="akey-stamp">{formatApiKeyTimestamp(key.created_at)}</span>,
        skeletonWidth: '7rem',
      },
      {
        id: 'expires',
        header: 'Expires',
        sortable: true,
        cell: (key) => (
          <span
            className={
              mcpKeyStatus(key, at) === 'expired' ? 'akey-stamp akey-stamp--past' : 'akey-stamp'
            }
          >
            {formatApiKeyDate(key.expires_at)}
          </span>
        ),
        skeletonWidth: '4.5rem',
      },
      {
        id: 'actions',
        headerLabel: 'Actions',
        actions: true,
        cell: (key) =>
          // A revoked key has nothing left to do; revoking twice would claim a change.
          key.revoked_at ? null : (
            <Button
              variant="ghost"
              size="sm"
              className="px-1.5"
              disabled={busyKeyId === key.id}
              title="Revoke MCP key"
              aria-label={`Revoke ${key.label}`}
              data-testid={`mcp-key-revoke-${key.id}`}
              onClick={() => onRevoke(key)}
            >
              <Ban aria-hidden />
            </Button>
          ),
        skeletonWidth: '2rem',
      },
    ],
    [at, busyKeyId, onRevoke]
  );

  return (
    <DataTable
      columns={columns}
      rows={visible}
      getRowId={(key) => key.id}
      getRowLabel={(key) => key.label}
      caption="MCP API keys for this workspace"
      scrollX
      loading={loading}
      loadingLabel="Loading MCP keys…"
      error={error}
      onRetry={onRetry}
      sort={sort}
      onSortChange={setSort}
      rowClassName={(key) => {
        const status = mcpKeyStatus(key, at);
        if (status === 'expired') return 'akey-row--expired';
        // Revoked is "set aside", the same tint as a disabled REST key.
        if (status === 'revoked') return 'akey-row--disabled';
        return undefined;
      }}
      data-testid="mcp-keys-table"
      toolbar={
        <DataTableToolbar>
          <DataTableSearch
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter by label or prefix…"
            aria-label="Filter MCP keys"
          />
          {MCP_KEY_FACETS.map((entry) => (
            <DataTableFilterChip
              key={entry}
              active={facet === entry}
              count={counts[entry]}
              onClick={() => setFacet(entry)}
            >
              {MCP_KEY_FACET_LABELS[entry]}
            </DataTableFilterChip>
          ))}
        </DataTableToolbar>
      }
      empty={
        narrowed ? (
          <EmptyState
            variant="compact"
            icon={<KeyRound aria-hidden />}
            title="No MCP keys match these filters"
            description="Clear the search box or pick a different status."
            action={
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setQuery('');
                  setFacet('all');
                }}
              >
                Clear filters
              </Button>
            }
          />
        ) : (
          <EmptyState
            icon={<KeyRound aria-hidden />}
            title="No MCP keys yet"
            description="Create a key for each MCP host or agent that calls Apiome."
            action={
              <Button onClick={onCreate}>
                <Plus aria-hidden />
                Create MCP key
              </Button>
            }
          />
        )
      }
      footer={
        <DataTableFoot>
          <span data-testid="mcp-keys-summary">{describeMcpKeyBreakdown(keys, at)}</span>
        </DataTableFoot>
      }
    />
  );
}
