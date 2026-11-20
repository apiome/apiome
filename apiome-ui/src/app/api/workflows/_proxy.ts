/**
 * Shared GET proxy for the Arazzo workflow viewer's routes (COA-1.3, #7039).
 *
 * The three `/api/workflows/*` routes differ only in the REST path they forward to and the key
 * they put the payload under, so the session check, status pass-through and error shape live
 * here once.
 */

import { NextResponse } from 'next/server';
import { getAuthenticatedTenantContext, proxyRestGet } from '@lib/primitives-api-proxy';

/**
 * Forward a GET to `REST /v1/workflows/{tenant}/{suffix}`.
 *
 * Authorization is the REST endpoint's: the caller's identity is forwarded and the upstream
 * status is passed through unchanged, so a 404 (not in this tenant) or 400 (malformed id)
 * reaches the panel as itself rather than as a generic failure.
 *
 * @param suffix The path after the tenant slug — already URI-encoded by the caller.
 * @param key The response key the payload is returned under (`workflows` or `operation`).
 * @param what What is being read, for the server log.
 * @returns `{ success: true, [key]: payload }`, or `{ success: false, error }` with the status.
 */
export async function proxyWorkflowsGet(suffix: string, key: string, what: string): Promise<NextResponse> {
  try {
    const ctx = await getAuthenticatedTenantContext();
    if (!ctx.ok) {
      return NextResponse.json({ success: false, error: ctx.error }, { status: ctx.status });
    }
    const { data, error, status } = await proxyRestGet(ctx.user, `/workflows/${ctx.tenantSlug}/${suffix}`);
    if (error) {
      return NextResponse.json({ success: false, error }, { status });
    }
    return NextResponse.json({ success: true, [key]: data });
  } catch (error) {
    console.error(`Error fetching ${what}:`, error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
