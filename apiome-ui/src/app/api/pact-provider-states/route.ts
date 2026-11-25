/**
 * The providers the **Provider states** page can pick from — PFX-3.3 (#6933).
 *
 * Proxies `GET /v1/tenants/{slug}/pacticipants?limit=100` (the first page, by handle).
 * Permissions (`pacts:view`) and tenant scoping are REST's.
 */

import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { PROVIDERS_PROXY_PATH } from '@lib/pact-provider-states';

export const dynamic = 'force-dynamic';

/** What the browser is told when apiome-rest cannot be reached. */
const UNAVAILABLE = 'The providers are unavailable (apiome-rest not reachable). Try again shortly.';

export async function GET() {
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(tenantUrl(resolved.slug, PROVIDERS_PROXY_PATH), {
    method: 'GET',
    user: resolved.user,
    unavailable: UNAVAILABLE,
  });
}
