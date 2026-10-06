/**
 * One agent key's usage today against its caps — AGX-3.4 (#4540).
 *
 * Forwards to apiome-rest `GET /v1/tenants/{t}/agent-keys/{id}/usage` (AGX-3.2).
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardAgentAccess } from '../../../agent-access-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/agent-access/keys/[keyId]/usage
 *
 * @param _request - Unused.
 * @param context - The route parameters.
 * @returns `{success, data: usage}` or `{success: false, error, code?}`.
 */
export async function GET(
  _request: NextRequest,
  context: { params: Promise<{ keyId: string }> }
): Promise<NextResponse> {
  const { keyId } = await context.params;
  return forwardAgentAccess('GET', `/agent-keys/${encodeURIComponent(keyId)}/usage`);
}
