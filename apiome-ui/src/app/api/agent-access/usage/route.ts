/**
 * Agent usage rollups — AGX-3.4 (#4540).
 *
 * Forwards to apiome-rest `GET /v1/tenants/{t}/agent-usage?days=N`: calls, errors and latency per
 * day, per tool and per agent key, from the AGX-3.3 daily rollups.
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardAgentAccess, forwardQuery } from '../agent-access-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/agent-access/usage?days=30
 *
 * @param request - The browser's request.
 * @returns `{success, data: usage}` or `{success: false, error, code?}`.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  return forwardAgentAccess('GET', `/agent-usage${forwardQuery(request.url, ['days'])}`);
}
