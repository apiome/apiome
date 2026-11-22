/**
 * Test the workspace's bucket (COA-5.15, #7092): `POST /v1/tenants/{slug}/document-store/test`.
 *
 * With settings in the body, those are tested before they are saved; with none, the saved ones.
 */

import { NextRequest } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { settingsBody } from '../body';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const body = settingsBody(await request.json().catch(() => ({})));
  return forwardConnectorRequest(tenantUrl(resolved.slug, 'document-store/test'), {
    method: 'POST',
    user: resolved.user,
    ...(body ? { body } : {}),
    unavailable: 'The bucket test is unavailable (apiome-rest not reachable). Try again shortly.',
  });
}
