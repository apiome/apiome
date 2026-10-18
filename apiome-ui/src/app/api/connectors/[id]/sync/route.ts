/**
 * Sync a connector now (CDG-1.7, #5958). Proxies `POST /v1/tenants/{slug}/connectors/{id}/sync`; the
 * answer is the finished run.
 */

import { NextRequest } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';

export const dynamic = 'force-dynamic';

export async function POST(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(tenantUrl(resolved.slug, `connectors/${encodeURIComponent(id)}/sync`), {
    method: 'POST',
    user: resolved.user,
  });
}
