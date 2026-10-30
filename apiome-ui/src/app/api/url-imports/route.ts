/**
 * Record a URL import for auto-refresh (RAR-6.1, #3538).
 *
 * Proxies `POST /v1/tenants/{slug}/url-imports`: after an import from the **URL Import** source
 * succeeds, the import dialog records the URL so REST re-checks it on the refresh cadence. Auth and
 * forwarding only — the `imports` permission and every check are REST's; a refusal keeps REST's
 * status with `{ success: false, error }`.
 */

import { NextRequest, NextResponse } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';

export const dynamic = 'force-dynamic';

/** `POST /api/url-imports` — record one URL import. */
export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  if (body === null || typeof body !== 'object' || Array.isArray(body)) {
    return NextResponse.json({ success: false, error: 'Expected a JSON object.' }, { status: 400 });
  }
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(tenantUrl(resolved.slug, 'url-imports'), {
    method: 'POST',
    user: resolved.user,
    body,
  });
}
