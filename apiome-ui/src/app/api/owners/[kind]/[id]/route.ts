/**
 * An entity's owner (CDG-2.4, #5963): `GET` / `PUT /v1/tenants/{tenant}/owners/{kind}/{id}`.
 *
 * `PUT` takes `{team}`. The entity kind's own `view` / `edit` permission is REST's.
 */

import { NextRequest, NextResponse } from 'next/server';
import { forwardOwnersRequest, isEntityRef, resolveTenant, tenantUrl } from '@lib/owners-proxy';

export const dynamic = 'force-dynamic';

type Params = { params: Promise<{ kind: string; id: string }> };

async function forward(method: 'GET' | 'PUT', context: Params, body?: unknown) {
  const { kind, id } = await context.params;
  if (!isEntityRef(kind, id)) {
    return NextResponse.json({ success: false, error: 'Not an ownable entity' }, { status: 400 });
  }
  const resolved = await resolveTenant();
  if ('error' in resolved) return resolved.error;
  return forwardOwnersRequest(tenantUrl(resolved.slug, `owners/${kind}/${id}`), {
    method,
    user: resolved.user,
    body,
  });
}

export async function GET(_request: NextRequest, context: Params) {
  return forward('GET', context);
}

export async function PUT(request: NextRequest, context: Params) {
  const raw = (await request.json().catch(() => ({}))) as { team?: unknown };
  return forward('PUT', context, { team: typeof raw.team === 'string' ? raw.team : '' });
}
