/**
 * Revoke one tenant MCP API key — proxy for the API keys page's MCP tab.
 *
 * Forwards to apiome-rest `DELETE /v1/tenants/{slug}/mcp-keys/{key_id}` (MTG-3.2), which
 * soft-revokes the key (sets `revoked_at`); MCP auth refuses it on the next call. Requires a
 * tenant-admin user session on the REST side (MTG-3.4).
 */

import { NextResponse } from 'next/server';
import {
  getAuthenticatedTenantContext,
  proxyRestDelete,
} from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

function keyPath(tenantSlug: string, keyId: string): string {
  return `/tenants/${encodeURIComponent(tenantSlug)}/mcp-keys/${encodeURIComponent(keyId)}`;
}

export async function DELETE(
  _request: Request,
  context: { params: Promise<{ keyId: string }> },
) {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  const { keyId } = await context.params;
  if (!keyId) {
    return NextResponse.json({ success: false, error: 'Missing key id' }, { status: 400 });
  }

  try {
    const { error, status } = await proxyRestDelete(ctx.user, keyPath(ctx.tenantSlug, keyId));
    if (error) {
      return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
    }
    return NextResponse.json({ success: true, data: null });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
