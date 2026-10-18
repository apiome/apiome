/**
 * One catalog connector (CDG-1.7, #5958): read, change, delete.
 *
 * Proxies `GET` / `PATCH` / `DELETE /v1/tenants/{slug}/connectors/{id}`.
 */

import { NextRequest } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';

export const dynamic = 'force-dynamic';

type Params = { params: Promise<{ id: string }> };

function path(id: string): string {
  return `connectors/${encodeURIComponent(id)}`;
}

export async function GET(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(tenantUrl(resolved.slug, path(id)), { method: 'GET', user: resolved.user });
}

export async function PATCH(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const body = await request.json().catch(() => ({}));
  return forwardConnectorRequest(tenantUrl(resolved.slug, path(id)), { method: 'PATCH', user: resolved.user, body });
}

export async function DELETE(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(tenantUrl(resolved.slug, path(id)), { method: 'DELETE', user: resolved.user });
}
