/**
 * Where the workspace's documents are kept (COA-5.15, #7092):
 * `GET` / `PUT /v1/tenants/{slug}/document-store`.
 *
 * `PUT` forwards only the settings fields, and only well-formed ones. `document_store:manage` is
 * REST's. Nothing here carries a key: the bucket is reached with a storage credential named by id.
 */

import { NextRequest } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { settingsBody } from './body';

export const dynamic = 'force-dynamic';

/** What the browser is told when apiome-rest cannot be reached. */
const UNAVAILABLE = 'Document storage settings are unavailable (apiome-rest not reachable). Try again shortly.';

export async function GET() {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(tenantUrl(resolved.slug, 'document-store'), {
    method: 'GET',
    user: resolved.user,
    unavailable: UNAVAILABLE,
  });
}

export async function PUT(request: NextRequest) {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const body = settingsBody(await request.json().catch(() => ({})));
  return forwardConnectorRequest(tenantUrl(resolved.slug, 'document-store'), {
    method: 'PUT',
    user: resolved.user,
    body: body ?? {},
    unavailable: UNAVAILABLE,
  });
}
