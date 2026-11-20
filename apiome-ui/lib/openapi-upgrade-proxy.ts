/**
 * Shared forwarding for the `/api/openapi-upgrade/*` proxy routes — COA-2.6 (#7049).
 *
 * Both routes take a JSON body from the Upgrade OpenAPI version dialog and pass it to
 * `POST /v1/openapi-upgrade/{slug}/plan` or `…/apply` as is. The tenant comes from the session, never
 * from the browser, and permissions are REST's (`imports:view` to plan a version, `imports:create` +
 * `projects:edit` to apply), so a refusal keeps REST's status with `{ success: false, error }`.
 */

import { NextRequest, NextResponse } from 'next/server';
import { REST_API_BASE_URL } from '@lib/rest-auth';
import { forwardConnectorRequest, resolveConnectorTenant } from '@lib/connectors-proxy';

/** Shown when apiome-rest cannot be reached. */
export const OPENAPI_UPGRADE_UNAVAILABLE =
  'The upgrade service is unavailable (apiome-rest not reachable). Try again shortly.';

/**
 * Forward one upgrade request (`plan` or `apply`) to REST.
 *
 * @param request - The incoming request; its body must be a JSON object.
 * @param step - Which REST route to call.
 * @returns REST's answer, or a 400 when the body is not a JSON object.
 */
export async function forwardOpenapiUpgrade(request: NextRequest, step: 'plan' | 'apply'): Promise<NextResponse> {
  const body = await request.json().catch(() => null);
  if (body === null || typeof body !== 'object' || Array.isArray(body)) {
    return NextResponse.json({ success: false, error: 'Expected a JSON object.' }, { status: 400 });
  }
  const resolved = await resolveConnectorTenant();
  if ('error' in resolved) return resolved.error;
  const url = `${REST_API_BASE_URL}/openapi-upgrade/${encodeURIComponent(resolved.slug)}/${step}`;
  return forwardConnectorRequest(url, {
    method: 'POST',
    user: resolved.user,
    body,
    unavailable: OPENAPI_UPGRADE_UNAVAILABLE,
  });
}
