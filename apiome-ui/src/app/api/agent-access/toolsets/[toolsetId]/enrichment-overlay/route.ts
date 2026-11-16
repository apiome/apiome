/**
 * A toolset's accepted enrichment as an Overlay — GVM-4.3 (#5878).
 *
 * `GET /api/agent-access/toolsets/[toolsetId]/enrichment-overlay` forwards to apiome-rest
 * `GET /v1/tenants/{t}/agent-toolsets/{id}/enrichment/overlay`, a read-only projection of the
 * accepted AGX-1.3 proposals that **Save as overlay** stores in a draft revision's chain.
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardAgentAccess } from '../../../agent-access-proxy';

export const dynamic = 'force-dynamic';

/** The route parameters. */
type Context = { params: Promise<{ toolsetId: string }> };

/**
 * Project the accepted enrichment.
 *
 * @returns `{success, data: {document, action_count, project_id, …}}` or `{success: false, …}`.
 */
export async function GET(_request: NextRequest, context: Context): Promise<NextResponse> {
  const { toolsetId } = await context.params;
  return forwardAgentAccess('GET', `/agent-toolsets/${encodeURIComponent(toolsetId)}/enrichment/overlay`);
}
