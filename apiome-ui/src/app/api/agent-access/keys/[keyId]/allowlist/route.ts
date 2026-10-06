/**
 * Replace an agent key's tool allowlist — AGX-3.4 (#4540).
 *
 * Forwards to apiome-rest `PUT /v1/tenants/{t}/agent-keys/{id}/allowlist` (AGX-3.1) with
 * `{toolAllowlist}`. A revoked key's allowlist cannot change (`409 agent-key-revoked`).
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardAgentAccess, readJsonBody } from '../../../agent-access-proxy';

export const dynamic = 'force-dynamic';

/**
 * PUT /api/agent-access/keys/[keyId]/allowlist
 *
 * @param request - The browser's request, with `{toolAllowlist}`.
 * @param context - The route parameters.
 * @returns `{success, data: key}` or `{success: false, error, code?}`.
 */
export async function PUT(
  request: NextRequest,
  context: { params: Promise<{ keyId: string }> }
): Promise<NextResponse> {
  const body = await readJsonBody(request);
  if (body instanceof NextResponse) return body;
  const { keyId } = await context.params;
  return forwardAgentAccess('PUT', `/agent-keys/${encodeURIComponent(keyId)}/allowlist`, body);
}
