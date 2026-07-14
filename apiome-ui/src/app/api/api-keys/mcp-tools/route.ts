/**
 * MCP tool catalog proxy — MTG-4.1 (#4780).
 *
 * Forwards to apiome-rest `GET /api-keys/mcp-tools` (MTG-1.1) so the Tenants
 * MCP Settings panel can label every registry tool. The catalog lives at the
 * API root (not under `/v1`), unlike most other REST proxies.
 */

import { NextResponse } from 'next/server';
import { getAuthenticatedTenantContext } from '@lib/primitives-api-proxy';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

/** Origin for routes that are not under the `/v1` prefix. */
function restApiOrigin(): string {
  return REST_API_BASE_URL.replace(/\/v1\/?$/, '');
}

export async function GET() {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  const url = `${restApiOrigin()}/api-keys/mcp-tools`;
  try {
    const rest = await fetch(url, {
      method: 'GET',
      headers: createRestAuthHeaders(ctx.user),
      cache: 'no-store',
    });
    const contentType = rest.headers.get('content-type');
    if (!contentType?.includes('application/json')) {
      const text = await rest.text();
      return NextResponse.json(
        { success: false, error: text || 'Request failed' },
        { status: rest.status >= 400 ? rest.status : 502 },
      );
    }
    const data = await rest.json();
    if (!rest.ok) {
      const detail = typeof data?.detail === 'string' ? data.detail : 'Request failed';
      return NextResponse.json(
        { success: false, error: detail },
        { status: rest.status >= 400 ? rest.status : 502 },
      );
    }
    return NextResponse.json({ success: true, data });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
