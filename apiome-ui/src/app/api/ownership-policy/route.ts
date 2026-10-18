/**
 * The tenant's ownership policy (CDG-2.5, #5964): `GET` / `PUT /v1/tenants/{slug}/ownership-policy`.
 *
 * `PUT` forwards only the two policy fields. `teams:view` / `teams:edit` are REST's.
 */

import { NextRequest } from 'next/server';
import { forwardOwnersRequest, resolveTenant, tenantUrl } from '@lib/owners-proxy';

export const dynamic = 'force-dynamic';

export async function GET() {
  const resolved = await resolveTenant();
  if ('error' in resolved) return resolved.error;
  return forwardOwnersRequest(tenantUrl(resolved.slug, 'ownership-policy'), { method: 'GET', user: resolved.user });
}

export async function PUT(request: NextRequest) {
  const resolved = await resolveTenant();
  if ('error' in resolved) return resolved.error;
  const raw = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const body: Record<string, unknown> = {};
  if ('unowned_findings_team' in raw) {
    body.unowned_findings_team = typeof raw.unowned_findings_team === 'string' && raw.unowned_findings_team ? raw.unowned_findings_team : null;
  }
  if (typeof raw.require_owner_to_publish === 'boolean') body.require_owner_to_publish = raw.require_owner_to_publish;
  return forwardOwnersRequest(tenantUrl(resolved.slug, 'ownership-policy'), { method: 'PUT', user: resolved.user, body });
}
