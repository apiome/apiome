import type { McpApiKeyMetadata } from '@/app/ade/dashboard/tenants/mcpKeysApi';

import { parseApiKeyExpiry, validateApiKeyDraft } from './apiKeysModel';

/**
 * The MCP-specific derivations behind the API keys page's **MCP server** keys.
 *
 * MCP API keys authenticate agents calling Apiome's MCP server; they are a different table
 * (`apiome.mcp_api_keys`) and a different lifecycle from the REST keys beside them. A REST key
 * is switched off and deleted; an MCP key is **revoked**, which is permanent and keeps the row
 * for audit. So the status set here is Active / Revoked / Expired, with no Disabled.
 *
 * Listing, filtering and sorting both kinds together is {@link ./workspaceKeysModel}. Pure and
 * unit-tested, like {@link ./apiKeysModel}.
 */

/** An MCP key's status. Revoked out-ranks expired: it is the reader's own decision. */
export type McpKeyStatus = 'active' | 'revoked' | 'expired';

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
  // The expiry rule is the REST form's, so the two create dialogs accept and refuse the same input.
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
