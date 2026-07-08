/**
 * Capability directory — proxies to apiome-rest GET /v1/mcp/{slug}/capabilities (V2-MCP-35.4).
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext } from '@lib/primitives-api-proxy';
import { createRestAuthHeaders, REST_API_BASE_URL } from '@lib/rest-auth';

export const dynamic = 'force-dynamic';

const EMPTY_DIRECTORY = { success: true, limit: 50, offset: 0, total: 0, count: 0, items: [] };

export async function GET(request: NextRequest) {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  const query = request.nextUrl.searchParams.toString();
  const path = `/mcp/${encodeURIComponent(ctx.tenantSlug)}/capabilities${query ? `?${query}` : ''}`;
  try {
    const rest = await fetch(`${REST_API_BASE_URL}${path}`, {
      method: 'GET',
      headers: createRestAuthHeaders(ctx.user),
      cache: 'no-store',
    });
    if (rest.ok) {
      const data = await rest.json().catch(() => null);
      if (data && typeof data === 'object' && 'items' in data) {
        return NextResponse.json(data);
      }
    }
    return NextResponse.json(EMPTY_DIRECTORY);
  } catch {
    return NextResponse.json(EMPTY_DIRECTORY);
  }
}
