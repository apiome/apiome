/**
 * One webhook delivery and its attempts — PFX-5.6 (#6950).
 *
 * Proxies `GET /v1/tenants/{slug}/pact-webhook-deliveries/{id}`. A malformed id is a 404 without
 * calling REST. The `pacts` permission (`view`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { deliveryProxyPath, isWebhookId } from '@lib/pact-webhooks';
import { forwardPactRead, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(_request: NextRequest, context: { params: Promise<{ deliveryId: string }> }) {
  const { deliveryId } = await context.params;
  if (!isWebhookId(deliveryId)) return pactError(404, 'Unknown delivery.');
  return forwardPactRead(deliveryProxyPath(deliveryId));
}
