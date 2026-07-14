/**
 * MCP trust-posture rule catalog — proxies to apiome-rest (CLX-3.2, #4856).
 * GET /v1/mcp/trust-posture/rules.
 *
 * Registry-level: describes the engine (rules, profiles, and the OWASP MCP risk catalog), not any
 * one endpoint. Read-only pass-through; the optional `?profile` filter is forwarded.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  const profile = request.nextUrl.searchParams.get('profile');
  const query = profile ? `?profile=${encodeURIComponent(profile)}` : '';
  const { data, error, status } = await proxyRestGet(ctx.user, `/mcp/trust-posture/rules${query}`);
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
