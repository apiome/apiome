/**
 * One workspace secret — PFX-8.15 (#7312), the Secrets tab's **Replace value** / **Set value** and
 * **Delete**.
 *
 * `PUT` proxies `PUT /v1/tenants/{slug}/pact-secrets/{id}` with `{ value?, description? }`
 * (`checkSecretUpdate`; a rename or any other field is a 400 naming it). Setting the value of a secret
 * created without one turns on the webhooks that were waiting for it. `DELETE` deletes a secret nothing
 * uses; REST refuses one in use (409) with the webhooks and targets that use it. A malformed id is a
 * 404 without calling REST. Permissions (`pacts:edit` / `pacts:delete`) and tenant scoping are REST's.
 */

import { NextRequest } from 'next/server';
import { SECRETS_PROXY_PATH, checkSecretUpdate } from '@lib/pact-contract-settings';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

type Context = { params: Promise<{ secretId: string }> };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The REST path of a secret, or `null` for an id no secret can have. */
async function secretPath(context: Context): Promise<string | null> {
  const { secretId } = await context.params;
  return UUID.test(secretId) ? `${SECRETS_PROXY_PATH}/${secretId}` : null;
}

export async function PUT(request: NextRequest, context: Context) {
  const path = await secretPath(context);
  if (path === null) return pactError(404, 'Unknown secret.');
  const checked = checkSecretUpdate(await request.json().catch(() => null));
  if (!checked.ok) return pactError(400, checked.error);
  return forwardPactWrite(path, 'PUT', checked.body);
}

export async function DELETE(_request: NextRequest, context: Context) {
  const path = await secretPath(context);
  if (path === null) return pactError(404, 'Unknown secret.');
  return forwardPactWrite(path, 'DELETE');
}
