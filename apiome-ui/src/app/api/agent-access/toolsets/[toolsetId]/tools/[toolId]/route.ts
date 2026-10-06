/**
 * Enable or disable one tool of an agent toolset — AGX-3.4 (#4540).
 *
 * Forwards to apiome-rest `PATCH /v1/tenants/{t}/agent-toolsets/{id}/tools/{toolId}` (AGX-1.2)
 * with `{enabled, confirmWriteOp?}`. Enabling a write operation without `confirmWriteOp: true`
 * is refused with the code `agent-toolset-write-op-unconfirmed`, which this route passes through.
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardAgentAccess, readJsonBody } from '../../../../agent-access-proxy';

export const dynamic = 'force-dynamic';

/**
 * PATCH /api/agent-access/toolsets/[toolsetId]/tools/[toolId]
 *
 * @param request - The browser's request, with `{enabled, confirmWriteOp?}`.
 * @param context - The route parameters.
 * @returns `{success, data: tool}` or `{success: false, error, code?}`.
 */
export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ toolsetId: string; toolId: string }> }
): Promise<NextResponse> {
  const body = await readJsonBody(request);
  if (body instanceof NextResponse) return body;
  const { toolsetId, toolId } = await context.params;
  return forwardAgentAccess(
    'PATCH',
    `/agent-toolsets/${encodeURIComponent(toolsetId)}/tools/${encodeURIComponent(toolId)}`,
    body
  );
}
