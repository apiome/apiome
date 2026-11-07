import type { McpApiKeyMetadata } from '@/app/ade/dashboard/tenants/mcpKeysApi';

import {
  apiKeyScopeList,
  apiKeyStatus,
  copyableApiKeyPrefix,
  isApiKeyExpired,
  isFullAccessKey,
  type ApiKeyRecord,
} from './apiKeysModel';
import { describeMcpKeyCapabilities, mcpKeyStatus } from './mcpKeysModel';

/**
 * The derivations behind the API keys page's one list of keys.
 *
 * A workspace has two kinds of API key: **REST API** keys (`apiome.api_keys`), which call the
 * REST API and are switched off and deleted, and **MCP server** keys (`apiome.mcp_api_keys`),
 * which agents and MCP hosts call the MCP server with and which are revoked. The server accepts
 * neither in place of the other, but a reader looking for "the key" should find both in one
 * place — so they share one table, each row says which kind it is, and the Type filter narrows
 * to one kind.
 *
 * Every row can be **regenerated**: its secret is replaced in place and everything else about
 * the key — id, name, scopes or tools, switch, expiry — carries over, so a leaked or lost secret
 * does not cost a new key and its set-up.
 *
 * Pure and unit-tested, like {@link ./apiKeysModel} and {@link ./mcpKeysModel}, which this
 * builds on rather than restates.
 */

/** Which kind of key a row is. */
export type WorkspaceKeyKind = 'rest' | 'mcp';

/** One row of the list: a key and which table it came from. */
export type WorkspaceKeyRow =
  | { kind: 'rest'; key: ApiKeyRecord }
  | { kind: 'mcp'; key: McpApiKeyMetadata };

/** What each kind is called in the Type column and filter. */
export const WORKSPACE_KEY_KIND_LABEL: Readonly<Record<WorkspaceKeyKind, string>> = {
  rest: 'REST API',
  mcp: 'MCP server',
};

/**
 * A row's status, in the vocabulary both kinds share.
 *
 * `disabled` is only ever a REST key (its switch is off); `revoked` is only ever an MCP key.
 */
export type WorkspaceKeyStatus = 'active' | 'disabled' | 'expired' | 'revoked';

/** The label each status carries. */
export const WORKSPACE_KEY_STATUS_LABEL: Readonly<Record<WorkspaceKeyStatus, string>> = {
  active: 'Active',
  disabled: 'Disabled',
  expired: 'Expired',
  revoked: 'Revoked',
};

/**
 * Both lists as one, newest first.
 *
 * @param restKeys The REST keys.
 * @param mcpKeys The MCP keys.
 * @returns The rows, ordered by `created_at` descending.
 */
export function toWorkspaceKeyRows(
  restKeys: readonly ApiKeyRecord[],
  mcpKeys: readonly McpApiKeyMetadata[]
): WorkspaceKeyRow[] {
  const rows: WorkspaceKeyRow[] = [
    ...restKeys.map((key): WorkspaceKeyRow => ({ kind: 'rest', key })),
    ...mcpKeys.map((key): WorkspaceKeyRow => ({ kind: 'mcp', key })),
  ];
  const created = (row: WorkspaceKeyRow) => {
    const at = new Date(row.key.created_at).getTime();
    return Number.isNaN(at) ? 0 : at;
  };
  return rows.sort((a, b) => created(b) - created(a));
}

/**
 * A row id unique across both tables, which may each use the same UUID space.
 *
 * @param row The row.
 * @returns `rest:<id>` or `mcp:<id>`.
 */
export function workspaceKeyRowId(row: WorkspaceKeyRow): string {
  return `${row.kind}:${row.key.id}`;
}

/**
 * The key's name — a REST key's `name`, an MCP key's `label`.
 *
 * @param row The row.
 * @returns The name.
 */
export function workspaceKeyName(row: WorkspaceKeyRow): string {
  return row.kind === 'rest' ? row.key.name : row.key.label;
}

/**
 * The key's stored prefix.
 *
 * @param row The row.
 * @returns The prefix, with its stored trailing `...`.
 */
export function workspaceKeyPrefix(row: WorkspaceKeyRow): string {
  return row.kind === 'rest' ? row.key.key_prefix : row.key.prefix;
}

/**
 * The row's status.
 *
 * @param row The row.
 * @param now The moment to judge expiry against.
 * @returns The status.
 */
export function workspaceKeyStatus(
  row: WorkspaceKeyRow,
  now: Date = new Date()
): WorkspaceKeyStatus {
  return row.kind === 'rest' ? apiKeyStatus(row.key, now) : mcpKeyStatus(row.key, now);
}

/**
 * What the key may reach, in a few words — for sorting and the reveal dialog's summary.
 *
 * @param row The row.
 * @returns "Full access", the comma-joined scopes, or the MCP tool description.
 */
export function describeWorkspaceKeyAccess(row: WorkspaceKeyRow): string {
  if (row.kind === 'mcp') return describeMcpKeyCapabilities(row.key);
  return isFullAccessKey(row.key) ? 'Full access' : apiKeyScopeList(row.key).join(', ');
}

/**
 * Whether the key's secret may be regenerated, and why not.
 *
 * A revoked MCP key is gone for good, and an expired key of either kind would come back with a
 * secret that is already refused — regenerating keeps the expiry. A disabled REST key may be
 * regenerated: it stays off, and is ready with a fresh secret when it is switched back on.
 *
 * @param row The row.
 * @param now The moment to judge expiry against.
 * @returns Whether Regenerate is offered, and the tooltip for a refused one.
 */
export function workspaceKeyRegeneration(
  row: WorkspaceKeyRow,
  now: Date = new Date()
): { canRegenerate: boolean; reason: string | null } {
  if (row.kind === 'mcp' && row.key.revoked_at) {
    return { canRegenerate: false, reason: 'This key is revoked. Create a new MCP key instead.' };
  }
  const expired =
    row.kind === 'rest' ? isApiKeyExpired(row.key, now) : mcpKeyStatus(row.key, now) === 'expired';
  if (expired) {
    return { canRegenerate: false, reason: 'This key has expired. Create a new key instead.' };
  }
  return { canRegenerate: true, reason: null };
}

/**
 * The reveal dialog's summary line after a regenerate.
 *
 * @param row The row that was regenerated.
 * @returns `“CI gate” · REST API · same scopes and expiry`.
 */
export function describeRegeneratedKey(row: WorkspaceKeyRow): string {
  const kept = row.kind === 'rest' ? 'same scopes and expiry' : 'same tools and expiry';
  return `“${workspaceKeyName(row)}” · ${WORKSPACE_KEY_KIND_LABEL[row.kind]} · ${kept}`;
}

// ---------------------------------------------------------------------------------------
// The toolbar: Type and Status
// ---------------------------------------------------------------------------------------

/** The Type control's options, in toolbar order. */
export const WORKSPACE_KEY_TYPE_FILTERS = ['all', 'rest', 'mcp'] as const;

/** One of {@link WORKSPACE_KEY_TYPE_FILTERS}. */
export type WorkspaceKeyTypeFilter = (typeof WORKSPACE_KEY_TYPE_FILTERS)[number];

/** Each Type option's label. */
export const WORKSPACE_KEY_TYPE_FILTER_LABELS: Readonly<Record<WorkspaceKeyTypeFilter, string>> = {
  all: 'All types',
  rest: WORKSPACE_KEY_KIND_LABEL.rest,
  mcp: WORKSPACE_KEY_KIND_LABEL.mcp,
};

/** The status chips, in toolbar order. */
export const WORKSPACE_KEY_FACETS = ['all', 'active', 'disabled', 'expired', 'revoked'] as const;

/** One of {@link WORKSPACE_KEY_FACETS}. */
export type WorkspaceKeyFacet = (typeof WORKSPACE_KEY_FACETS)[number];

/** Each chip's label. */
export const WORKSPACE_KEY_FACET_LABELS: Readonly<Record<WorkspaceKeyFacet, string>> = {
  all: 'All',
  ...WORKSPACE_KEY_STATUS_LABEL,
};

/**
 * Whether a row survives the Type filter.
 *
 * @param row The row.
 * @param type The Type option.
 * @returns True when the option includes the row.
 */
export function matchesWorkspaceKeyType(row: WorkspaceKeyRow, type: WorkspaceKeyTypeFilter): boolean {
  return type === 'all' || row.kind === type;
}

/**
 * Whether a row belongs under a status chip.
 *
 * @param row The row.
 * @param facet The chip.
 * @param now The moment to judge status against.
 * @returns True when the chip includes the row.
 */
export function matchesWorkspaceKeyFacet(
  row: WorkspaceKeyRow,
  facet: WorkspaceKeyFacet,
  now: Date = new Date()
): boolean {
  return facet === 'all' || workspaceKeyStatus(row, now) === facet;
}

/**
 * How many rows each status chip holds.
 *
 * @param rows The rows the search and Type filter have already narrowed to.
 * @param now The moment to judge status against.
 * @returns A count per chip.
 */
export function workspaceKeyFacetCounts(
  rows: readonly WorkspaceKeyRow[],
  now: Date = new Date()
): Record<WorkspaceKeyFacet, number> {
  const counts: Record<WorkspaceKeyFacet, number> = {
    all: rows.length,
    active: 0,
    disabled: 0,
    expired: 0,
    revoked: 0,
  };
  for (const row of rows) counts[workspaceKeyStatus(row, now)] += 1;
  return counts;
}

/**
 * The status chips worth drawing: All, plus every status some row is in.
 *
 * A workspace with no MCP keys has nothing revoked and one with no REST keys has nothing
 * disabled; a chip that can only ever say 0 is noise. The active chip stays, so the toolbar
 * keeps its shape while the list is empty.
 *
 * @param counts From {@link workspaceKeyFacetCounts}, over the unfiltered rows.
 * @param current The chip in use, which stays even when its count has dropped to 0.
 * @returns The chips, in toolbar order.
 */
export function visibleWorkspaceKeyFacets(
  counts: Readonly<Record<WorkspaceKeyFacet, number>>,
  current: WorkspaceKeyFacet
): WorkspaceKeyFacet[] {
  return WORKSPACE_KEY_FACETS.filter(
    (facet) => facet === 'all' || facet === 'active' || facet === current || counts[facet] > 0
  );
}

/**
 * The rows whose name, description or prefix contains the query.
 *
 * A trailing ellipsis is ignored, so a prefix pasted from the table or from a log still matches.
 *
 * @param rows The rows.
 * @param query What the reader typed.
 * @returns The matching rows, in their original order.
 */
export function searchWorkspaceKeys(
  rows: readonly WorkspaceKeyRow[],
  query: string
): WorkspaceKeyRow[] {
  const needle = copyableApiKeyPrefix(query.trim()).toLowerCase();
  if (!needle) return [...rows];
  return rows.filter((row) => {
    const description = row.kind === 'rest' ? row.key.description ?? '' : '';
    return [workspaceKeyName(row), description, copyableApiKeyPrefix(workspaceKeyPrefix(row))]
      .join(' ')
      .toLowerCase()
      .includes(needle);
  });
}

// ---------------------------------------------------------------------------------------
// Sorting and counting
// ---------------------------------------------------------------------------------------

/** The sorted column and direction. */
export interface WorkspaceKeySortState {
  column: string;
  direction: 'asc' | 'desc';
}

/**
 * The value a column sorts on — timestamps as numbers, as in the per-kind models.
 *
 * @param row The row.
 * @param column The column id.
 * @param now The moment to judge status against.
 * @returns A comparable value.
 */
function workspaceKeySortValue(row: WorkspaceKeyRow, column: string, now: Date): string | number {
  const time = (iso: string | null | undefined, missing: number) => {
    if (!iso) return missing;
    const at = new Date(iso).getTime();
    return Number.isNaN(at) ? missing : at;
  };
  switch (column) {
    case 'type':
      return WORKSPACE_KEY_KIND_LABEL[row.kind];
    case 'prefix':
      return copyableApiKeyPrefix(workspaceKeyPrefix(row)).toLowerCase();
    case 'access':
      return describeWorkspaceKeyAccess(row).toLowerCase();
    case 'status':
      return workspaceKeyStatus(row, now);
    case 'lastUsed':
      return time(row.key.last_used_at, 0);
    case 'created':
      return time(row.key.created_at, 0);
    case 'expires':
      // No expiry is further away than any date, so it sorts last ascending.
      return time(row.key.expires_at, Number.MAX_SAFE_INTEGER);
    case 'enabled':
      // MCP keys have no switch; they sort with the switched-on keys while active.
      return row.kind === 'rest' ? (row.key.enabled ? 1 : 0) : row.key.revoked_at ? 0 : 1;
    default:
      return workspaceKeyName(row).toLowerCase();
  }
}

/**
 * The rows in the order the header asks for.
 *
 * @param rows The rows.
 * @param sort The sorted column, or `null` for newest first.
 * @param now The moment to judge status against.
 * @returns A new, ordered array.
 */
export function sortWorkspaceKeys(
  rows: readonly WorkspaceKeyRow[],
  sort: WorkspaceKeySortState | null | undefined,
  now: Date = new Date()
): WorkspaceKeyRow[] {
  const ordered = [...rows];
  if (!sort) return ordered;
  const sign = sort.direction === 'desc' ? -1 : 1;
  return ordered.sort((left, right) => {
    const a = workspaceKeySortValue(left, sort.column, now);
    const b = workspaceKeySortValue(right, sort.column, now);
    if (a === b) return workspaceKeyName(left).localeCompare(workspaceKeyName(right));
    return (a < b ? -1 : 1) * sign;
  });
}

/**
 * The table foot's sentence — `6 keys · 4 REST API · 2 MCP server · 4 active · 1 revoked`.
 *
 * The per-kind counts appear only when both kinds are present; statuses with no keys are left
 * out, so a healthy single-kind workspace reads `3 keys · 3 active`.
 *
 * @param rows Every row.
 * @param now The moment to judge status against.
 * @returns The sentence.
 */
export function describeWorkspaceKeyBreakdown(
  rows: readonly WorkspaceKeyRow[],
  now: Date = new Date()
): string {
  const total = rows.length;
  const parts = [`${total} ${total === 1 ? 'key' : 'keys'}`];
  const rest = rows.filter((row) => row.kind === 'rest').length;
  const mcp = total - rest;
  if (rest > 0 && mcp > 0) {
    parts.push(`${rest} ${WORKSPACE_KEY_KIND_LABEL.rest}`, `${mcp} ${WORKSPACE_KEY_KIND_LABEL.mcp}`);
  }
  const counts = workspaceKeyFacetCounts(rows, now);
  for (const status of ['active', 'disabled', 'expired', 'revoked'] as const) {
    if (counts[status] > 0) parts.push(`${counts[status]} ${status}`);
  }
  return parts.join(' · ');
}
