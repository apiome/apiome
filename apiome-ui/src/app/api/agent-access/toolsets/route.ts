/**
 * Agent toolsets list + create — AGX-3.4 (#4540).
 *
 * Forwards to apiome-rest `GET`/`POST /v1/tenants/{t}/agent-toolsets` (AGX-1.2). `GET` accepts
 * `?versionId=`; `POST` takes `{versionId, enabled?, target?}` and seeds the toolset with the
 * version's read operations enabled and its write operations disabled.
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardAgentAccess, forwardQuery, readJsonBody } from '../agent-access-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/agent-access/toolsets?versionId=…
 *
 * @param request - The browser's request.
 * @returns `{success, data: {toolsets}}` or `{success: false, error, code?}`.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  return forwardAgentAccess('GET', `/agent-toolsets${forwardQuery(request.url, ['versionId'])}`);
}

/**
 * POST /api/agent-access/toolsets
 *
 * @param request - The browser's request, with `{versionId, enabled?, target?}`.
 * @returns `{success, data: toolset}` (201) or `{success: false, error, code?}`.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const body = await readJsonBody(request);
  if (body instanceof NextResponse) return body;
  return forwardAgentAccess('POST', '/agent-toolsets', body);
}
