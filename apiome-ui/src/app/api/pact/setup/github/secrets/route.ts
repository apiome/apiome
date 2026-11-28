/**
 * Write the two broker secrets into repositories — PFX-8.20 (#7317), **Set up contracts → Connect
 * your pipelines**.
 *
 * `POST { repository_ids, token }` (`checkSecretsBody`) forwards
 * `POST /v1/tenants/{slug}/pact-setup/github/secrets`. The broker address is not the browser's to
 * choose: it is the signed-in workspace's own, built here from REST's public base. The key passes
 * through to REST, which seals it for GitHub; nothing here stores or logs it. REST answers per
 * repository — `written`, or `skipped` with the reason — and owns `pacts:delete` and tenant scoping.
 */

import { NextRequest } from 'next/server';
import { forwardConnectorRequest, resolveConnectorTenant, tenantUrl } from '@lib/connectors-proxy';
import { PUBLIC_REST_BASE_URL } from '@lib/pact-badges';
import { brokerBaseUrl } from '@lib/pact-contract-settings';
import { PACT_UNAVAILABLE, pactError } from '@lib/pact-proxy';
import { SETUP_SECRETS_PROXY_PATH, checkSecretsBody } from '@lib/pact-setup';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const checked = checkSecretsBody(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  return forwardConnectorRequest(tenantUrl(resolved.slug, SETUP_SECRETS_PROXY_PATH), {
    method: 'POST',
    user: resolved.user,
    body: { ...checked.body, broker_base_url: brokerBaseUrl(PUBLIC_REST_BASE_URL, resolved.slug) },
    unavailable: PACT_UNAVAILABLE,
  });
}
