/**
 * Per-key MCP capabilities preview proxy — MTG-4.3 (#4782).
 *
 * Forwards to apiome-rest
 * `POST /v1/tenants/{slug}/mcp-keys/{key_id}/capabilities/preview` (MTG-3.3).
 * Dry-run only; does not persist.
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  getAuthenticatedTenantContext,
  proxyRestPost,
} from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

function previewPath(tenantSlug: string, keyId: string): string {
  return `/tenants/${encodeURIComponent(tenantSlug)}/mcp-keys/${encodeURIComponent(keyId)}/capabilities/preview`;
}

export async function POST(
  request: NextRequest,
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

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON body' }, { status: 400 });
  }

  try {
    const { data, error, status } = await proxyRestPost(
      ctx.user,
      previewPath(ctx.tenantSlug, keyId),
      body,
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
