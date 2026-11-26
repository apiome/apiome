/**
 * The workspace's contract webhooks — PFX-5.6 (#6950).
 *
 * `GET` reads `GET /v1/tenants/{slug}/pact-broker/webhooks` and
 * `GET /v1/tenants/{slug}/pact-webhook-deliveries/latest` as the signed-in user and answers
 * `{ webhooks, latest }` (every webhook, and the newest firing of each). It takes no parameter;
 * any is a 400 naming it.
 *
 * `POST` creates a webhook: `POST …/pact-broker/webhooks` with a body `pickWebhookBody` accepts
 * (a JSON object of the webhook fields; any other field is a 400 naming it). REST checks the
 * values (a 422 names the field) and the `pacts` permission (`create`).
 */

import { NextRequest } from 'next/server';
import { WEBHOOKS_PROXY_PATH, pickWebhookBody } from '@lib/pact-webhooks';
import { forwardPactWrite, forwardWebhooksOverview, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function GET(request: NextRequest) {
  const [first] = request.nextUrl.searchParams.keys();
  if (first !== undefined) return pactError(400, `Unsupported parameter ${first}: the webhook list takes none.`);
  return forwardWebhooksOverview();
}

export async function POST(request: NextRequest) {
  const picked = pickWebhookBody(await request.json().catch(() => null));
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactWrite(WEBHOOKS_PROXY_PATH, 'POST', picked.body);
}
