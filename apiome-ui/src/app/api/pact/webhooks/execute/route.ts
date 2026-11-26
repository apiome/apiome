/**
 * Test an unsaved webhook — PFX-5.6 (#6950).
 *
 * Proxies `POST /v1/tenants/{slug}/pact-broker/webhooks/execute`: the editor's **Test** sends the
 * webhook it holds once, now, without saving it. The body is checked by `pickWebhookBody`. REST
 * checks the values, the `pacts` permission (`create`) and the test budget (a 429 asks to wait); an
 * unsaved webhook cannot keep a stored secret, so a `**********` value is REST's 422.
 */

import { NextRequest } from 'next/server';
import { UNSAVED_EXECUTE_PROXY_PATH, pickWebhookBody } from '@lib/pact-webhooks';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function POST(request: NextRequest) {
  const picked = pickWebhookBody(await request.json().catch(() => null));
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactWrite(UNSAVED_EXECUTE_PROXY_PATH, 'POST', picked.body);
}
