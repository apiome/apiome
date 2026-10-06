/**
 * Revoke an agent key — AGX-3.4 (#4540).
 *
 * Forwards to apiome-rest `DELETE /v1/tenants/{t}/agent-keys/{id}` (AGX-3.1). Revoking is
 * idempotent; the agent's next request is refused.
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardAgentAccess } from '../../agent-access-proxy';

export const dynamic = 'force-dynamic';

/**
 * DELETE /api/agent-access/keys/[keyId]
 *
 * @param _request - Unused.
 * @param context - The route parameters.
 * @returns `{success, data: null}` or `{success: false, error, code?}`.
 */
export async function DELETE(
  _request: NextRequest,
  context: { params: Promise<{ keyId: string }> }
): Promise<NextResponse> {
  const { keyId } = await context.params;
  return forwardAgentAccess('DELETE', `/agent-keys/${encodeURIComponent(keyId)}`);
}
