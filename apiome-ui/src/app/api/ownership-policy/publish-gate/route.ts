/**
 * The owner gate's verdict for one project (CDG-2.5, #5964), for the publish dialog:
 * `GET /v1/tenants/{slug}/ownership-policy/publish-gate?project=<id>`.
 */

import { NextRequest, NextResponse } from 'next/server';
import { forwardOwnersRequest, resolveTenant, tenantUrl } from '@lib/owners-proxy';

export const dynamic = 'force-dynamic';

const ID = /^[0-9a-fA-F-]{36}$/;

export async function GET(request: NextRequest) {
  const project = request.nextUrl.searchParams.get('project') ?? '';
  if (!ID.test(project)) {
    return NextResponse.json({ success: false, error: 'project must be an id' }, { status: 400 });
  }
  const resolved = await resolveTenant();
  if ('error' in resolved) return resolved.error;
  return forwardOwnersRequest(
    tenantUrl(resolved.slug, `ownership-policy/publish-gate?project=${encodeURIComponent(project)}`),
    { method: 'GET', user: resolved.user }
  );
}
