/**
 * Check a provider's pacts against its provider states before a run — PFX-3.3 (#6933).
 *
 * Proxies `POST /v1/tenants/{slug}/pact-verifier/providers/{provider}/provider-states/check` with the
 * default selection and, when the browser names one, a `target_ref` — nothing else of the posted
 * body is forwarded. A malformed handle is a 404 without calling apiome-rest. Permissions
 * (`pacts:view`) and tenant scoping are REST's.
 */

import { NextRequest, NextResponse } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { checkBody, checkProxyPath } from '@lib/pact-provider-states';

export const dynamic = 'force-dynamic';

/** What the browser is told when apiome-rest cannot be reached. */
const UNAVAILABLE = 'The provider-state check is unavailable (apiome-rest not reachable). Try again shortly.';

export async function POST(request: NextRequest, context: { params: Promise<{ provider: string }> }) {
  const { provider } = await context.params;
  const path = checkProxyPath(provider);
  if (path === null) return NextResponse.json({ success: false, error: 'Unknown provider.' }, { status: 404 });
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const posted = await request.json().catch(() => ({}));
  return forwardConnectorRequest(tenantUrl(resolved.slug, path), {
    method: 'POST',
    user: resolved.user,
    body: checkBody(posted),
    unavailable: UNAVAILABLE,
  });
}
