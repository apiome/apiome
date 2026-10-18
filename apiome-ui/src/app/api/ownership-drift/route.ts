/**
 * The ownership drift report (CDG-2.5, #5964): `GET /v1/tenants/{slug}/ownership-drift`.
 */

import { forwardOwnersRequest, resolveTenant, tenantUrl } from '@lib/owners-proxy';

export const dynamic = 'force-dynamic';

export async function GET() {
  const resolved = await resolveTenant();
  if ('error' in resolved) return resolved.error;
  return forwardOwnersRequest(tenantUrl(resolved.slug, 'ownership-drift'), { method: 'GET', user: resolved.user });
}
