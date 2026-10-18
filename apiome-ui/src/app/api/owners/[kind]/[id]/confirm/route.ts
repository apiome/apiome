/**
 * Confirm a suggested owner (CDG-2.4, #5963): `POST /v1/tenants/{tenant}/owners/{kind}/{id}/confirm`.
 *
 * Body `{team?}`; REST records who confirmed it.
 */

import { NextRequest, NextResponse } from 'next/server';
import { forwardOwnersRequest, isEntityRef, resolveTenant, tenantUrl } from '@lib/owners-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest, context: { params: Promise<{ kind: string; id: string }> }) {
  const { kind, id } = await context.params;
  if (!isEntityRef(kind, id)) {
    return NextResponse.json({ success: false, error: 'Not an ownable entity' }, { status: 400 });
  }
  const raw = (await request.json().catch(() => ({}))) as { team?: unknown };
  const resolved = await resolveTenant();
  if ('error' in resolved) return resolved.error;
  return forwardOwnersRequest(tenantUrl(resolved.slug, `owners/${kind}/${id}/confirm`), {
    method: 'POST',
    user: resolved.user,
    body: typeof raw.team === 'string' && raw.team ? { team: raw.team } : {},
  });
}
