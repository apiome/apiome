/**
 * Redeliver a webhook delivery — PFX-5.6 (#6950).
 *
 * Proxies `POST /v1/tenants/{slug}/pact-webhook-deliveries/{id}/redeliver`: queue a finished firing
 * again as a new firing. A malformed id is a 404 without calling REST. REST refuses a firing still
 * queued or retrying, or one whose webhook is disabled, with a 409 saying so; the `pacts`
 * permission (`edit`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { isWebhookId, redeliverProxyPath } from '@lib/pact-webhooks';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(_request: NextRequest, context: { params: Promise<{ deliveryId: string }> }) {
  const { deliveryId } = await context.params;
  if (!isWebhookId(deliveryId)) return pactError(404, 'Unknown delivery.');
  return forwardPactWrite(redeliverProxyPath(deliveryId), 'POST');
}
