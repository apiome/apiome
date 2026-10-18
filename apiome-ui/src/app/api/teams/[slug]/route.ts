/**
 * One team with its members (CDG-2.4, #5963): `GET /v1/tenants/{tenant}/teams/{slug}`.
 */

import { NextResponse } from 'next/server';
import { forwardOwnersRequest, isTeamSlug, resolveTenant, tenantUrl } from '@lib/owners-proxy';

export const dynamic = 'force-dynamic';

export async function GET(_request: Request, context: { params: Promise<{ slug: string }> }) {
  const { slug } = await context.params;
  if (!isTeamSlug(slug)) {
    return NextResponse.json({ success: false, error: 'Not a team slug' }, { status: 400 });
  }
  const resolved = await resolveTenant();
  if ('error' in resolved) return resolved.error;
  return forwardOwnersRequest(tenantUrl(resolved.slug, `teams/${slug}`), { method: 'GET', user: resolved.user });
}
