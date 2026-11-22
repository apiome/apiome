/**
 * Delete the copies a finished move left behind (COA-5.15, #7092):
 * `POST /v1/tenants/{slug}/document-store/cleanup`.
 *
 * The confirm is the browser's to give: this forwards `confirm` only when it is literally `true`.
 */

import { NextRequest } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const raw = (await request.json().catch(() => ({}))) as { confirm?: unknown };
  return forwardConnectorRequest(tenantUrl(resolved.slug, 'document-store/cleanup'), {
    method: 'POST',
    user: resolved.user,
    body: { confirm: raw.confirm === true },
    unavailable: 'Deleting old copies is unavailable (apiome-rest not reachable). Try again shortly.',
  });
}
