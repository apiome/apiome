/**
 * A provider's registered provider states — PFX-3.3 (#6933).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-verifier/providers/{provider}/provider-states`; a malformed
 * handle is a 404 without calling apiome-rest. Permissions (`pacts:view`) and tenant scoping are
 * REST's.
 */

import { NextRequest, NextResponse } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { statesProxyPath } from '@lib/pact-provider-states';

export const dynamic = 'force-dynamic';

/** What the browser is told when apiome-rest cannot be reached. */
const UNAVAILABLE = 'Provider states are unavailable (apiome-rest not reachable). Try again shortly.';

export async function GET(_request: NextRequest, context: { params: Promise<{ provider: string }> }) {
  const { provider } = await context.params;
  const path = statesProxyPath(provider);
  if (path === null) return NextResponse.json({ success: false, error: 'Unknown provider.' }, { status: 404 });
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(tenantUrl(resolved.slug, path), {
    method: 'GET',
    user: resolved.user,
    unavailable: UNAVAILABLE,
  });
}
