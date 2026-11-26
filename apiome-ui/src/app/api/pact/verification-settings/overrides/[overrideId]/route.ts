/**
 * Remove one Pact verification override — PFX-6.2 (#6954).
 *
 * Proxies `DELETE /v1/tenants/{slug}/pact-verification-settings/overrides/{id}`. An id that is not
 * a UUID is a 404 without calling REST. Permissions (`pacts:edit`) and tenant scoping are REST's.
 */

import { isRecordId, overrideProxyPath } from '@lib/pact-remediation';
import { forwardPactWrite, pactError } from '@lib/pact-proxy';

export const dynamic = 'force-dynamic';

export async function DELETE(_request: Request, context: { params: Promise<{ overrideId: string }> }) {
  const { overrideId } = await context.params;
  if (!isRecordId(overrideId)) return pactError(404, 'Unknown override.');
  return forwardPactWrite(overrideProxyPath(overrideId), 'DELETE');
}
