/**
 * One bi-directional result's fidelity report — PFX-2.5 (#6929).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-comparisons/{id}/fidelity`; a malformed id is a 404 without
 * calling apiome-rest. Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest, NextResponse } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { fidelityProxyPath } from '@lib/pact-comparisons';

export const dynamic = 'force-dynamic';

/** What the browser is told when apiome-rest cannot be reached. */
const UNAVAILABLE = 'The fidelity report is unavailable (apiome-rest not reachable). Try again shortly.';

export async function GET(_request: NextRequest, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  const path = fidelityProxyPath(id);
  if (path === null) return NextResponse.json({ success: false, error: 'Unknown comparison.' }, { status: 404 });
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(tenantUrl(resolved.slug, path), {
    method: 'GET',
    user: resolved.user,
    unavailable: UNAVAILABLE,
  });
}
