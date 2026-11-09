/**
 * Finish an OAuth connection to an MCP endpoint — proxies to apiome-rest
 * POST /v1/mcp/{slug}/oauth/callback (V2-MCP-20.4 / MCAT-6.4, #3680).
 *
 * The callback page posts the authorization server's redirect parameters
 * (`{ state, code?, error?, error_description?, iss? }`); apiome-rest exchanges the code and stores
 * the tokens sealed. The answer is the endpoint id and its redacted credential status.
 */

import { NextRequest, NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestPost } from '@lib/primitives-api-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const ctx = await getAuthenticatedTenantContext();
  if (!ctx.ok) {
    return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ success: false, error: 'Invalid JSON body' }, { status: 400 });
  }

  const { data, error, status } = await proxyRestPost(
    ctx.user,
    `/mcp/${encodeURIComponent(ctx.tenantSlug)}/oauth/callback`,
    body,
  );
  if (error) {
    return NextResponse.json({ success: false, error }, { status: status >= 400 ? status : 502 });
  }
  return NextResponse.json(data, { status: status || 200 });
}
