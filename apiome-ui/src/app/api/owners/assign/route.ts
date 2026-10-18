/**
 * Assign one owner team to many entities (CDG-2.4, #5963): `POST /v1/tenants/{tenant}/owners:assign`.
 *
 * Body `{team, entities: [{kind, id}]}`, all or nothing; REST checks `edit` on every kind listed.
 */

import { NextRequest, NextResponse } from 'next/server';
import { forwardOwnersRequest, isEntityRef, resolveTenant, tenantUrl } from '@lib/owners-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const raw = (await request.json().catch(() => ({}))) as { team?: unknown; entities?: unknown };
  const entities = Array.isArray(raw.entities) ? raw.entities : [];
  const valid = entities.every(
    (entity) =>
      entity &&
      typeof entity === 'object' &&
      isEntityRef(String((entity as { kind?: unknown }).kind), String((entity as { id?: unknown }).id))
  );
  if (typeof raw.team !== 'string' || !raw.team || entities.length === 0 || !valid) {
    return NextResponse.json({ success: false, error: 'A team and at least one entity are required' }, { status: 400 });
  }
  const resolved = await resolveTenant();
  if ('error' in resolved) return resolved.error;
  return forwardOwnersRequest(tenantUrl(resolved.slug, 'owners:assign'), {
    method: 'POST',
    user: resolved.user,
    body: { team: raw.team, entities },
  });
}
