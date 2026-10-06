/**
 * One agent toolset — AGX-3.4 (#4540).
 *
 * Forwards to apiome-rest `GET`/`PATCH`/`DELETE /v1/tenants/{t}/agent-toolsets/{id}` (AGX-1.2):
 * describe it with every tool, change `enabled` / `target`, or delete it (which deletes its agent
 * keys and upstream credentials too).
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardAgentAccess, readJsonBody } from '../../agent-access-proxy';

export const dynamic = 'force-dynamic';

/** The route parameters. */
type Context = { params: Promise<{ toolsetId: string }> };

/** The REST path of the addressed toolset. */
async function toolsetPath(context: Context): Promise<string> {
  const { toolsetId } = await context.params;
  return `/agent-toolsets/${encodeURIComponent(toolsetId)}`;
}

/**
 * GET /api/agent-access/toolsets/[toolsetId]
 *
 * @returns `{success, data: toolset with tools}` or `{success: false, error, code?}`.
 */
export async function GET(_request: NextRequest, context: Context): Promise<NextResponse> {
  return forwardAgentAccess('GET', await toolsetPath(context));
}

/**
 * PATCH /api/agent-access/toolsets/[toolsetId] with `{enabled?, target?}`.
 *
 * @returns `{success, data: toolset}` or `{success: false, error, code?}`.
 */
export async function PATCH(request: NextRequest, context: Context): Promise<NextResponse> {
  const body = await readJsonBody(request);
  if (body instanceof NextResponse) return body;
  return forwardAgentAccess('PATCH', await toolsetPath(context), body);
}

/**
 * DELETE /api/agent-access/toolsets/[toolsetId]
 *
 * @returns `{success, data: null}` or `{success: false, error, code?}`.
 */
export async function DELETE(_request: NextRequest, context: Context): Promise<NextResponse> {
  return forwardAgentAccess('DELETE', await toolsetPath(context));
}
