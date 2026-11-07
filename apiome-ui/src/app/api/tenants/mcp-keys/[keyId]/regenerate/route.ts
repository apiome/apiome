/**
 * Regenerate one tenant MCP API key — proxy for the API keys page and the manage drawer.
 *
 * Forwards to apiome-rest `POST /v1/tenants/{slug}/mcp-keys/{key_id}/regenerate`, which replaces
 * the key's secret in place (same id, label, scope and tools) and answers with the new plaintext
 * secret once. Requires a tenant-admin user session on the REST side (MTG-3.4).
 */

import { NextResponse } from 'next/server';
import {
  getAuthenticatedTenantContext,
  proxyRestPost,
} from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

function regeneratePath(tenantSlug: string, keyId: string): string {
  return `/tenants/${encodeURIComponent(tenantSlug)}/mcp-keys/${encodeURIComponent(keyId)}/regenerate`;
}

export async function POST(
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
    const { data, error, status } = await proxyRestPost(
      ctx.user,
      regeneratePath(ctx.tenantSlug, keyId),
      {},
    );
    if (error) {
      return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
    }
    return NextResponse.json({ success: true, data });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
