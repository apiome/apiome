/**
 * One contract webhook — PFX-5.6 (#6950).
 *
 * Proxies `GET`, `PUT` and `DELETE /v1/tenants/{slug}/pact-broker/webhooks/{uuid}`. A malformed id
 * is a 404 without calling REST. `PUT` replaces the whole webhook with a body `pickWebhookBody`
 * accepts; a secret sent back as `**********` keeps the stored one. Permissions (`pacts` view, edit,
 * delete) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { isWebhookId, pickWebhookBody, webhookProxyPath } from '@lib/pact-webhooks';
import { forwardPactRead, forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ webhookId: string }> };

/** The checked id, or `null` for a malformed one. */
async function webhookId(context: Context): Promise<string | null> {
  const { webhookId: id } = await context.params;
  return isWebhookId(id) ? id : null;
}

export async function GET(_request: NextRequest, context: Context) {
  const id = await webhookId(context);
  if (!id) return pactError(404, 'Unknown webhook.');
  return forwardPactRead(webhookProxyPath(id));
}

export async function PUT(request: NextRequest, context: Context) {
  const id = await webhookId(context);
  if (!id) return pactError(404, 'Unknown webhook.');
  const picked = pickWebhookBody(await request.json().catch(() => null));
  if (!picked.ok) return pactError(400, picked.error);
  return forwardPactWrite(webhookProxyPath(id), 'PUT', picked.body);
}

export async function DELETE(_request: NextRequest, context: Context) {
  const id = await webhookId(context);
  if (!id) return pactError(404, 'Unknown webhook.');
  return forwardPactWrite(webhookProxyPath(id), 'DELETE');
}
