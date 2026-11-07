'use client';

import * as React from 'react';
import { Ban, Check, CircleAlert, Copy, KeyRound, Plus, RefreshCw, Trash2 } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import {
  DataTable,
  DataTableCellPrimary,
  DataTableCellSub,
  DataTableFilterChip,
  DataTableFoot,
  DataTableSearch,
  DataTableToolbar,
  type DataTableColumn,
  type DataTableSortState,
} from '@/app/components/ui/DataTable';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { Segmented, SegmentedItem } from '@/app/components/ui/Segmented';
import { Switch } from '@/app/components/ui/Switch';
import { useClipboardCopy } from '@/app/hooks/useClipboardCopy';

import {
  apiKeyRowActions,
  apiKeyScopeList,
  copyableApiKeyPrefix,
  displayApiKeyPrefix,
  formatApiKeyDate,
  formatApiKeyTimestamp,
  isFullAccessKey,
  type ApiKeyRecord,
} from './apiKeysModel';
import { describeMcpKeyCapabilities } from './mcpKeysModel';
import type { McpApiKeyMetadata } from '@/app/ade/dashboard/tenants/mcpKeysApi';
import {
  describeWorkspaceKeyBreakdown,
  matchesWorkspaceKeyFacet,
  matchesWorkspaceKeyType,
  searchWorkspaceKeys,
  sortWorkspaceKeys,
  visibleWorkspaceKeyFacets,
  workspaceKeyFacetCounts,
  workspaceKeyName,
  workspaceKeyPrefix,
  workspaceKeyRegeneration,
  workspaceKeyRowId,
  workspaceKeyStatus,
  WORKSPACE_KEY_FACET_LABELS,
  WORKSPACE_KEY_KIND_LABEL,
  WORKSPACE_KEY_STATUS_LABEL,
  WORKSPACE_KEY_TYPE_FILTERS,
  WORKSPACE_KEY_TYPE_FILTER_LABELS,
  type WorkspaceKeyFacet,
  type WorkspaceKeyRow,
  type WorkspaceKeyTypeFilter,
} from './workspaceKeysModel';

/**
 * The workspace's keys, both kinds, in one list.
 *
 * Authority: `docs/mockups/workspace/api-keys.html`, the `.table-wrap` section; DESIGN.md §8
 * (list page) and §3.1 (the shared status vocabulary).
 *
 * REST API keys and MCP server keys sit in one table, each row badged with its kind, and the
 * toolbar's Type control narrows to one kind. Where the two lifecycles differ, the row follows
 * its own: a REST key has a switch and is deleted, an MCP key is revoked — permanently, and its
 * row stays for audit. Both are **regenerated** the same way, from the row's Regenerate
 * button.
 *
 * The two lists load separately, so one failing read cannot empty the other: a failed REST read
 * is the table's error state (it is the list the page always had), and a failed MCP read is a
 * notice above the table with its own retry, beside the REST rows that did load.
 *
 * Expired, disabled and revoked rows are tinted rather than faded, for the reason HIVE-4.8
 * measured: dimming text is the one way to make a row distinct that can fail a contrast check.
 */

/** Props for {@link WorkspaceKeysTable}. */
export interface WorkspaceKeysTableProps {
  /** Every row, both kinds. */
  rows: readonly WorkspaceKeyRow[];
  /** True while the REST read is in flight. */
  loading?: boolean;
  /** Why the REST list could not be read. Replaces the body with a retry. */
  error?: string | null;
  /** Retry the REST read. */
  onRetry?: () => void;
  /** Why the MCP list could not be read; shown above the table. */
  mcpError?: string | null;
  /** Retry the MCP read. */
  onRetryMcp?: () => void;
  /**
   * A sentence under the table when MCP keys are not listed to this reader — they are for
   * workspace administrators.
   */
  mcpNotice?: string | null;
  /** The row a write is running against, by {@link workspaceKeyRowId}. */
  busyRowId?: string | null;
  /** Ask to enable or disable a REST key. Disabling is confirmed by the caller. */
  onToggleEnabled: (key: ApiKeyRecord, next: boolean) => void;
  /** Ask to delete a REST key. Confirmed by the caller. */
  onDelete: (key: ApiKeyRecord) => void;
  /** Ask to revoke an MCP key. Confirmed by the caller. */
  onRevoke: (key: McpApiKeyMetadata) => void;
  /** Ask to regenerate a key's secret. Confirmed by the caller. */
  onRegenerate: (row: WorkspaceKeyRow) => void;
  /** Open the REST create dialog, from the empty state. */
  onCreate: () => void;
  /** Open the MCP create dialog, from the empty state; omitted when the reader may not. */
  onCreateMcp?: () => void;
  /** The moment status is judged against. */
  now?: Date;
}

/**
 * The copy-prefix button of one row — its own component so only the pressed one says "Copied".
 *
 * @param props.prefix The stored prefix.
 * @param props.name The key's name, for the button's accessible name.
 * @returns The button.
 */
function CopyPrefixButton({ prefix, name }: { prefix: string; name: string }) {
  const { copied, copy } = useClipboardCopy();
  return (
    <Button
      variant="ghost"
      size="sm"
      className="akey-prefix-copy"
      title={copied ? 'Copied!' : 'Copy prefix'}
      aria-label={copied ? `Copied the prefix of ${name}` : `Copy the prefix of ${name}`}
      onClick={() => void copy(copyableApiKeyPrefix(prefix))}
    >
      {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
    </Button>
  );
}

/**
 * What a REST key may reach: "Full access", or a badge per scope.
 *
 * @param props.apiKey The key.
 * @returns The cell.
 */
function RestAccess({ apiKey }: { apiKey: ApiKeyRecord }) {
  if (isFullAccessKey(apiKey)) return <span className="akey-scopes__full">Full access</span>;
  return (
    <span className="akey-scopes">
      {apiKeyScopeList(apiKey).map((scope) => (
        <Badge key={scope} variant="accent" mono>
          {scope}
        </Badge>
      ))}
    </span>
  );
}

/**
 * The list, its toolbar, its foot and its per-row controls.
 *
 * @param props See {@link WorkspaceKeysTableProps}.
 * @returns The table card, with the MCP read's notice above it when that read failed.
 */
export default function WorkspaceKeysTable({
  rows,
  loading = false,
  error = null,
  onRetry,
  mcpError = null,
  onRetryMcp,
  mcpNotice = null,
  busyRowId = null,
  onToggleEnabled,
  onDelete,
  onRevoke,
  onRegenerate,
  onCreate,
  onCreateMcp,
  now,
}: WorkspaceKeysTableProps) {
  const [query, setQuery] = React.useState('');
  const [type, setType] = React.useState<WorkspaceKeyTypeFilter>('all');
  const [facet, setFacet] = React.useState<WorkspaceKeyFacet>('all');
  const [sort, setSort] = React.useState<DataTableSortState | null>(null);

  // One `Date` for the whole render, so a row's badge, its tint and the chip that counted it
  // are judged against the same moment.
  const at = React.useMemo(() => now ?? new Date(), [now]);

  const searched = React.useMemo(
    () => searchWorkspaceKeys(rows, query).filter((row) => matchesWorkspaceKeyType(row, type)),
    [rows, query, type]
  );
  const counts = React.useMemo(() => workspaceKeyFacetCounts(searched, at), [searched, at]);
  const facets = React.useMemo(
    () => visibleWorkspaceKeyFacets(workspaceKeyFacetCounts(rows, at), facet),
    [rows, at, facet]
  );
  const visible = React.useMemo(
    () => sortWorkspaceKeys(searched.filter((row) => matchesWorkspaceKeyFacet(row, facet, at)), sort, at),
    [searched, facet, sort, at]
  );
  const narrowed = query.trim().length > 0 || facet !== 'all' || type !== 'all';

  const columns = React.useMemo<DataTableColumn<WorkspaceKeyRow>[]>(
    () => [
      {
        id: 'name',
        header: 'Name',
        sortable: true,
        cell: (row) => {
          const status = workspaceKeyStatus(row, at);
          const identity =
            row.kind === 'rest'
              ? { 'data-testid': 'api-key-row', 'data-api-key-name': row.key.name }
              : { 'data-testid': 'mcp-key-row', 'data-mcp-key-label': row.key.label };
          return (
            <div className="akey-identity" {...identity}>
              <span
                className="tnt-icon-tile"
                data-tone={status === 'expired' || status === 'revoked' ? 'danger' : 'honey'}
              >
                <KeyRound aria-hidden />
              </span>
              <span className="akey-identity__text">
                <DataTableCellPrimary className="akey-identity__name">
                  {workspaceKeyName(row)}
                </DataTableCellPrimary>
                {row.kind === 'rest' && row.key.description ? (
                  <DataTableCellSub className="akey-identity__desc">{row.key.description}</DataTableCellSub>
                ) : null}
              </span>
            </div>
          );
        },
        skeletonWidth: '11rem',
      },
      {
        id: 'type',
        header: 'Type',
        sortable: true,
        cell: (row) => (
          <Badge
            variant={row.kind === 'mcp' ? 'violet' : 'neutral'}
            data-testid={`key-type-${row.kind}-${row.key.id}`}
          >
            {WORKSPACE_KEY_KIND_LABEL[row.kind]}
          </Badge>
        ),
        skeletonWidth: '5rem',
      },
      {
        id: 'prefix',
        header: 'Prefix',
        sortable: true,
        cell: (row) => (
          <span className="akey-prefix">
            <code className="akey-prefix__value mono">{displayApiKeyPrefix(workspaceKeyPrefix(row))}</code>
            <CopyPrefixButton prefix={workspaceKeyPrefix(row)} name={workspaceKeyName(row)} />
          </span>
        ),
        skeletonWidth: '7rem',
      },
      {
        id: 'access',
        header: 'Access',
        sortable: true,
        cell: (row) =>
          row.kind === 'rest' ? (
            <RestAccess apiKey={row.key} />
          ) : (
            <span className="akey-stamp" data-testid={`mcp-key-capabilities-${row.key.id}`}>
              {describeMcpKeyCapabilities(row.key)}
            </span>
          ),
        skeletonWidth: '6rem',
      },
      {
        id: 'status',
        header: 'Status',
        sortable: true,
        cell: (row) => {
          const status = workspaceKeyStatus(row, at);
          return (
            <Badge status={status} dot={status === 'active' || status === 'disabled'}>
              {status === 'expired' && <CircleAlert aria-hidden />}
              {WORKSPACE_KEY_STATUS_LABEL[status]}
            </Badge>
          );
        },
        skeletonWidth: '4.5rem',
      },
      {
        id: 'lastUsed',
        header: 'Last used',
        sortable: true,
        cell: (row) => <span className="akey-stamp">{formatApiKeyTimestamp(row.key.last_used_at)}</span>,
        skeletonWidth: '7rem',
      },
      {
        id: 'created',
        header: 'Created',
        sortable: true,
        cell: (row) => <span className="akey-stamp">{formatApiKeyTimestamp(row.key.created_at)}</span>,
        skeletonWidth: '7rem',
      },
      {
        id: 'expires',
        header: 'Expires',
        sortable: true,
        cell: (row) => (
          <span
            className={
              workspaceKeyStatus(row, at) === 'expired' ? 'akey-stamp akey-stamp--past' : 'akey-stamp'
            }
          >
            {formatApiKeyDate(row.key.expires_at)}
          </span>
        ),
        skeletonWidth: '4.5rem',
      },
      {
        id: 'enabled',
        header: 'Enabled',
        sortable: true,
        cell: (row) => {
          // An MCP key has no switch: it is live until it is revoked.
          if (row.kind === 'mcp') return null;
          const key = row.key;
          const actions = apiKeyRowActions(key, at);
          const inert = !actions.canToggle || busyRowId === workspaceKeyRowId(row);
          return (
            <span className="akey-toggle" title={actions.toggleDisabledReason ?? undefined}>
              <Switch
                checked={key.enabled}
                disabled={inert}
                aria-label={`Enabled: ${key.name}`}
                data-testid={`api-key-toggle-${key.id}`}
                onCheckedChange={(next) => onToggleEnabled(key, next)}
              />
              <span className="akey-toggle__label">{key.enabled ? 'On' : 'Off'}</span>
            </span>
          );
        },
        skeletonWidth: '3.5rem',
      },
      {
        id: 'actions',
        headerLabel: 'Actions',
        actions: true,
        cell: (row) => {
          const busy = busyRowId === workspaceKeyRowId(row);
          const name = workspaceKeyName(row);
          // A revoked MCP key has nothing left to do; revoking twice would claim a change.
          if (row.kind === 'mcp' && row.key.revoked_at) return null;
          const regeneration = workspaceKeyRegeneration(row, at);
          return (
            <span className="akey-row-actions">
              {regeneration.canRegenerate && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="px-1.5"
                  disabled={busy}
                  title="Regenerate secret"
                  aria-label={`Regenerate ${name}`}
                  data-testid={`key-regenerate-${row.kind}-${row.key.id}`}
                  onClick={() => onRegenerate(row)}
                >
                  <RefreshCw aria-hidden />
                </Button>
              )}
              {row.kind === 'rest' ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="px-1.5"
                  disabled={busy}
                  title="Delete API key"
                  aria-label={`Delete ${name}`}
                  data-testid={`api-key-delete-${row.key.id}`}
                  onClick={() => onDelete(row.key)}
                >
                  <Trash2 aria-hidden />
                </Button>
              ) : (
                <Button
                  variant="ghost"
                  size="sm"
                  className="px-1.5"
                  disabled={busy}
                  title="Revoke MCP key"
                  aria-label={`Revoke ${name}`}
                  data-testid={`mcp-key-revoke-${row.key.id}`}
                  onClick={() => onRevoke(row.key)}
                >
                  <Ban aria-hidden />
                </Button>
              )}
            </span>
          );
        },
        skeletonWidth: '4rem',
      },
    ],
    [at, busyRowId, onDelete, onRegenerate, onRevoke, onToggleEnabled]
  );

  const clearFilters = () => {
    setQuery('');
    setType('all');
    setFacet('all');
  };

  return (
    <>
      {mcpError && (
        <Alert
          variant="error"
          data-testid="mcp-keys-load-error"
          actions={
            onRetryMcp ? (
              <Button variant="outline" size="sm" onClick={onRetryMcp}>
                Retry
              </Button>
            ) : undefined
          }
        >
          MCP server keys could not be loaded: {mcpError}
        </Alert>
      )}

      <DataTable
        columns={columns}
        rows={visible}
        getRowId={workspaceKeyRowId}
        getRowLabel={workspaceKeyName}
        caption="API keys for this workspace — REST API and MCP server"
        scrollX
        loading={loading}
        loadingLabel="Loading API keys…"
        error={error}
        onRetry={onRetry}
        sort={sort}
        onSortChange={setSort}
        rowClassName={(row) => {
          const status = workspaceKeyStatus(row, at);
          if (status === 'expired') return 'akey-row--expired';
          // Revoked is "set aside", the same tint as a disabled REST key.
          if (status === 'disabled' || status === 'revoked') return 'akey-row--disabled';
          return undefined;
        }}
        data-testid="api-keys-table"
        toolbar={
          <DataTableToolbar>
            <DataTableSearch
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Filter by name or prefix…"
              aria-label="Filter API keys"
            />
            <Segmented
              value={type}
              onValueChange={(value) => setType(value as WorkspaceKeyTypeFilter)}
              aria-label="Key type"
              data-testid="api-keys-type-filter"
            >
              {WORKSPACE_KEY_TYPE_FILTERS.map((entry) => (
                <SegmentedItem key={entry} value={entry}>
                  {WORKSPACE_KEY_TYPE_FILTER_LABELS[entry]}
                </SegmentedItem>
              ))}
            </Segmented>
            {facets.map((entry) => (
              <DataTableFilterChip
                key={entry}
                active={facet === entry}
                count={counts[entry]}
                onClick={() => setFacet(entry)}
              >
                {WORKSPACE_KEY_FACET_LABELS[entry]}
              </DataTableFilterChip>
            ))}
          </DataTableToolbar>
        }
        empty={
          narrowed ? (
            <EmptyState
              variant="compact"
              icon={<KeyRound aria-hidden />}
              title="No API keys match these filters"
              description="Clear the search box or pick a different type or status."
              action={
                <Button variant="outline" size="sm" onClick={clearFilters}>
                  Clear filters
                </Button>
              }
            />
          ) : (
            <EmptyState
              icon={<KeyRound aria-hidden />}
              title="No API keys yet"
              description="Create a REST API key for pipelines, or an MCP key for a host."
              action={
                <span className="akey-empty-actions">
                  <Button onClick={onCreate}>
                    <Plus aria-hidden />
                    Create API key
                  </Button>
                  {onCreateMcp && (
                    <Button variant="outline" onClick={onCreateMcp}>
                      <Plus aria-hidden />
                      Create MCP key
                    </Button>
                  )}
                </span>
              }
            />
          )
        }
        footer={
          <DataTableFoot>
            <span data-testid="api-keys-summary">{describeWorkspaceKeyBreakdown(rows, at)}</span>
            {mcpNotice ? (
              <span className="akey-foot-legend" data-testid="mcp-keys-admin-only">
                {mcpNotice}
              </span>
            ) : (
              <span className="akey-foot-legend">
                ↻ regenerates a key&apos;s secret and keeps its name, access and expiry.
              </span>
            )}
          </DataTableFoot>
        }
      />
    </>
  );
}
