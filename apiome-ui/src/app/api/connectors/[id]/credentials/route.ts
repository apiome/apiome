/**
 * Store or replace a connector's credential (CDG-1.7, #5958). Proxies
 * `PUT /v1/tenants/{slug}/connectors/{id}/credentials`; REST seals it and returns only field names.
 */

import { NextRequest } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';

export const dynamic = 'force-dynamic';

export async function PUT(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const body = await request.json().catch(() => ({}));
  return forwardConnectorRequest(tenantUrl(resolved.slug, `connectors/${encodeURIComponent(id)}/credentials`), {
    method: 'PUT',
    user: resolved.user,
    body,
  });
}
