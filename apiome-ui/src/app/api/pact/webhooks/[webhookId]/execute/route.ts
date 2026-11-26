/**
 * Test a saved webhook — PFX-5.6 (#6950).
 *
 * Proxies `POST /v1/tenants/{slug}/pact-broker/webhooks/{uuid}/execute`: send the webhook once,
 * now, with the latest matching pact (or placeholders); nothing is queued or retried. A malformed
 * id is a 404 without calling REST. The `pacts` permission (`edit`) and the test budget (a 429) are
 * REST's.
 */

import { NextRequest } from 'next/server';
import { executeProxyPath, isWebhookId } from '@lib/pact-webhooks';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(_request: NextRequest, context: { params: Promise<{ webhookId: string }> }) {
  const { webhookId } = await context.params;
  if (!isWebhookId(webhookId)) return pactError(404, 'Unknown webhook.');
  return forwardPactWrite(executeProxyPath(webhookId), 'POST');
}
