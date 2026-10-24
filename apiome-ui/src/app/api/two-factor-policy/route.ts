/**
 * The tenant's two-factor policy (TFA-1.3, #5657): `GET` / `PUT /v1/tenants/{slug}/two-factor-policy`.
 *
 * `PUT` forwards only the two policy fields, and only well-formed ones. `members:view` /
 * `members:edit` are REST's.
 */

import { NextRequest } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { isValidGraceDays } from '@lib/two-factor-policy';

export const dynamic = 'force-dynamic';

/** What the browser is told when apiome-rest cannot be reached. */
const UNAVAILABLE = 'The two-factor policy is unavailable (apiome-rest not reachable). Try again shortly.';

export async function GET() {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(tenantUrl(resolved.slug, 'two-factor-policy'), {
    method: 'GET',
    user: resolved.user,
    unavailable: UNAVAILABLE,
  });
}

export async function PUT(request: NextRequest) {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const raw = (await request.json().catch(() => ({}))) as Record<string, unknown>;
  const body: Record<string, unknown> = {};
  if (typeof raw.require_two_factor === 'boolean') body.require_two_factor = raw.require_two_factor;
  if (isValidGraceDays(raw.grace_days)) body.grace_days = raw.grace_days;
  return forwardConnectorRequest(tenantUrl(resolved.slug, 'two-factor-policy'), {
    method: 'PUT',
    user: resolved.user,
    body,
    unavailable: UNAVAILABLE,
  });
}
