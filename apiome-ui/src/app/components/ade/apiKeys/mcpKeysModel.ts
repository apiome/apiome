import type { McpApiKeyMetadata } from '@/app/ade/dashboard/tenants/mcpKeysApi';

import { copyableApiKeyPrefix, parseApiKeyExpiry, validateApiKeyDraft } from './apiKeysModel';

/**
 * The derivations behind the API keys page's **MCP server** tab.
 *
 * MCP API keys authenticate agents calling Apiome's MCP server; they are a different table
 * (`apiome.mcp_api_keys`) and a different lifecycle from the REST keys beside them. A REST key
 * is switched off and deleted; an MCP key is **revoked**, which is permanent and keeps the row
 * for audit. So the status set here is Active / Revoked / Expired, with no Disabled.
 *
 * Pure and unit-tested, like {@link ./apiKeysModel}.
 */

/** An MCP key's status. Revoked out-ranks expired: it is the reader's own decision. */
export type McpKeyStatus = 'active' | 'revoked' | 'expired';

/** The label each status carries. */
export const MCP_KEY_STATUS_LABEL: Readonly<Record<McpKeyStatus, string>> = {
  active: 'Active',
  revoked: 'Revoked',
  expired: 'Expired',
};

/**
 * The key's status.
 *
 * @param key The key.
 * @param now The moment to judge expiry against.
 * @returns `revoked`, else `expired` when its expiry has passed, else `active`.
 */
export function mcpKeyStatus(
  key: Pick<McpApiKeyMetadata, 'revoked_at' | 'expires_at'>,
  now: Date = new Date()
): McpKeyStatus {
  if (key.revoked_at) return 'revoked';
  if (key.expires_at) {
    const at = new Date(key.expires_at).getTime();
    if (!Number.isNaN(at) && at < now.getTime()) return 'expired';
  }
  return 'active';
}

/**
 * What the key may call, in a few words.
 *
 * @param key The key.
 * @returns "Workspace defaults" for an inheriting key, else the size of its custom set.
 */
export function describeMcpKeyCapabilities(
  key: Pick<McpApiKeyMetadata, 'capability_mode' | 'enabled_tools'>
): string {
  if (key.capability_mode !== 'explicit') return 'Workspace defaults';
  const count = key.enabled_tools?.length ?? 0;
  return `Custom · ${count} ${count === 1 ? 'tool' : 'tools'}`;
}

/** The status chips, in toolbar order. */
export const MCP_KEY_FACETS = ['all', 'active', 'revoked', 'expired'] as const;

/** One of {@link MCP_KEY_FACETS}. */
export type McpKeyFacet = (typeof MCP_KEY_FACETS)[number];

/** Each chip's label. */
export const MCP_KEY_FACET_LABELS: Readonly<Record<McpKeyFacet, string>> = {
  all: 'All',
  active: 'Active',
  revoked: 'Revoked',
  expired: 'Expired',
};

/**
 * Whether a key belongs under a chip.
 *
 * @param key The key.
 * @param facet The chip.
 * @param now The moment to judge expiry against.
 * @returns True when the chip includes the key.
 */
export function matchesMcpKeyFacet(
  key: McpApiKeyMetadata,
  facet: McpKeyFacet,
  now: Date = new Date()
): boolean {
  return facet === 'all' || mcpKeyStatus(key, now) === facet;
}

/**
 * How many keys each chip holds.
 *
 * @param keys The keys.
 * @param now The moment to judge expiry against.
 * @returns A count per chip.
 */
export function mcpKeyFacetCounts(
  keys: readonly McpApiKeyMetadata[],
  now: Date = new Date()
): Record<McpKeyFacet, number> {
  const counts: Record<McpKeyFacet, number> = { all: keys.length, active: 0, revoked: 0, expired: 0 };
  for (const key of keys) counts[mcpKeyStatus(key, now)] += 1;
  return counts;
}

/**
 * The keys whose label or prefix contains the query.
 *
 * A trailing ellipsis is ignored, so a prefix pasted from the table still matches.
 *
 * @param keys The keys.
 * @param query What the reader typed.
 * @returns The matching keys, in their original order.
 */
export function searchMcpKeys(
  keys: readonly McpApiKeyMetadata[],
  query: string
): McpApiKeyMetadata[] {
  const needle = copyableApiKeyPrefix(query.trim()).toLowerCase();
  if (!needle) return [...keys];
  return keys.filter(
    (key) =>
      key.label.toLowerCase().includes(needle) ||
      copyableApiKeyPrefix(key.prefix).toLowerCase().includes(needle)
  );
}

/** The sorted column and direction. */
export interface McpKeySortState {
  column: string;
  direction: 'asc' | 'desc';
}

/**
 * The value a column sorts on — timestamps as numbers, as in the REST table.
 *
 * @param key The key.
 * @param column The column id.
 * @param now The moment to judge status against.
 * @returns A comparable value.
 */
function mcpKeySortValue(key: McpApiKeyMetadata, column: string, now: Date): string | number {
  const time = (iso: string | null | undefined, missing: number) =>
    iso ? new Date(iso).getTime() : missing;
  switch (column) {
    case 'prefix':
      return copyableApiKeyPrefix(key.prefix).toLowerCase();
    case 'capabilities':
      return describeMcpKeyCapabilities(key);
    case 'status':
      return mcpKeyStatus(key, now);
    case 'lastUsed':
      return time(key.last_used_at, 0);
    case 'created':
      return time(key.created_at, 0);
    case 'expires':
      // No expiry sorts last ascending, as in the REST table.
      return time(key.expires_at, Number.MAX_SAFE_INTEGER);
    default:
      return key.label.toLowerCase();
  }
}

/**
 * The keys in the order the header asks for.
 *
 * @param keys The keys.
 * @param sort The sorted column, or `null` for the server's order.
 * @param now The moment to judge status against.
 * @returns A new, ordered array.
 */
export function sortMcpKeys(
  keys: readonly McpApiKeyMetadata[],
  sort: McpKeySortState | null | undefined,
  now: Date = new Date()
): McpApiKeyMetadata[] {
  const ordered = [...keys];
  if (!sort) return ordered;
  const sign = sort.direction === 'desc' ? -1 : 1;
  return ordered.sort((left, right) => {
    const a = mcpKeySortValue(left, sort.column, now);
    const b = mcpKeySortValue(right, sort.column, now);
    if (a === b) return left.label.localeCompare(right.label);
    return (a < b ? -1 : 1) * sign;
  });
}

/**
 * The table foot's count — "3 keys · 2 active · 1 revoked".
 *
 * @param keys The keys.
 * @param now The moment to judge status against.
 * @returns The sentence.
 */
export function describeMcpKeyBreakdown(
  keys: readonly McpApiKeyMetadata[],
  now: Date = new Date()
): string {
  const counts = mcpKeyFacetCounts(keys, now);
  const parts = [`${counts.all} ${counts.all === 1 ? 'key' : 'keys'}`];
  for (const status of ['active', 'revoked', 'expired'] as const) {
    if (counts[status] > 0) parts.push(`${counts[status]} ${status}`);
  }
  return parts.join(' · ');
}

/** What the create dialog holds. */
export interface McpKeyDraft {
  label: string;
  expiresInDays: string;
}

/** A fresh create form. */
export const EMPTY_MCP_KEY_DRAFT: McpKeyDraft = { label: '', expiresInDays: '' };

/**
 * Why the draft cannot be sent, or `null`.
 *
 * @param draft The form.
 * @returns The sentence to show beside the form.
 */
export function validateMcpKeyDraft(draft: McpKeyDraft): string | null {
  if (!draft.label.trim()) return 'Label is required';
  // The expiry rule is the REST form's, so the two tabs accept and refuse the same input.
  return validateApiKeyDraft({
    name: draft.label,
    description: '',
    expiresInDays: draft.expiresInDays,
    preset: 'full',
  });
}

/**
 * The `expires_at` the server wants, from the days typed.
 *
 * @param expiresInDays The form's value.
 * @param now The moment to count from.
 * @returns An ISO timestamp, or `null` for a key that never expires.
 */
export function mcpKeyExpiresAt(expiresInDays: string, now: Date = new Date()): string | null {
  const days = parseApiKeyExpiry(expiresInDays);
  if (days === null) return null;
  return new Date(now.getTime() + days * 24 * 60 * 60 * 1000).toISOString();
}

/**
 * The reveal dialog's summary line, in the REST dialog's shape.
 *
 * @param draft The form the key was created from.
 * @returns `“Claude Desktop” · workspace default tools · expires never`.
 */
export function describeCreatedMcpKey(draft: McpKeyDraft): string {
  const days = parseApiKeyExpiry(draft.expiresInDays);
  const expiry =
    days === null ? 'expires never' : `expires in ${days} ${days === 1 ? 'day' : 'days'}`;
  return `“${draft.label.trim()}” · workspace default tools · ${expiry}`;
}
