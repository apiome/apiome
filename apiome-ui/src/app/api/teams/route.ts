/**
 * Teams (CDG-2.4, #5963): `GET /v1/tenants/{slug}/teams`. Needs `teams:view` (REST's).
 */

import { forwardOwnersRequest, resolveTenant, tenantUrl } from '@lib/owners-proxy';

export const dynamic = 'force-dynamic';

export async function GET() {
  const resolved = await resolveTenant();
  if ('error' in resolved) return resolved.error;
  return forwardOwnersRequest(tenantUrl(resolved.slug, 'teams'), { method: 'GET', user: resolved.user });
}
