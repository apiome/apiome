/**
 * Record the original document of an import (COA-5.3, #7079).
 *
 * Proxies `POST /v1/tenants/{slug}/import-originals`: after the import wizard or a repository file
 * import succeeds, the dialog sends the text it read so REST keeps it as the revision's original.
 * Auth and forwarding only — the `imports` permission, the secret scrub and every check are
 * REST's; a refusal keeps REST's status with `{ success: false, error }`.
 */

import { NextRequest, NextResponse } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';

export const dynamic = 'force-dynamic';

/** `POST /api/import-originals` — record one import's original. */
export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  if (body === null || typeof body !== 'object' || Array.isArray(body)) {
    return NextResponse.json({ success: false, error: 'Expected a JSON object.' }, { status: 400 });
  }
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(tenantUrl(resolved.slug, 'import-originals'), {
    method: 'POST',
    user: resolved.user,
    body,
  });
}
