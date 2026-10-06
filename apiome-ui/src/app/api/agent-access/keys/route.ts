/**
 * Agent keys list + create — AGX-3.4 (#4540).
 *
 * Forwards to apiome-rest `GET`/`POST /v1/tenants/{t}/agent-keys` (AGX-3.1). `GET` accepts
 * `?toolsetId=` and `?includeRevoked=true`. The `POST` reply carries the key's secret, shown once:
 * it is passed straight back to the browser and never logged.
 */

import { NextRequest, NextResponse } from 'next/server';

import { forwardAgentAccess, forwardQuery, readJsonBody } from '../agent-access-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/agent-access/keys?toolsetId=…&includeRevoked=true
 *
 * @param request - The browser's request.
 * @returns `{success, data: {keys}}` or `{success: false, error, code?}`.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  return forwardAgentAccess(
    'GET',
    `/agent-keys${forwardQuery(request.url, ['toolsetId', 'includeRevoked'])}`
  );
}

/**
 * POST /api/agent-access/keys with `{name, description?, toolsetId, toolAllowlist, expiresAt?}`.
 *
 * @param request - The browser's request.
 * @returns `{success, data: key with secret}` (201) or `{success: false, error, code?}`.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  const body = await readJsonBody(request);
  if (body instanceof NextResponse) return body;
  return forwardAgentAccess('POST', '/agent-keys', body);
}
