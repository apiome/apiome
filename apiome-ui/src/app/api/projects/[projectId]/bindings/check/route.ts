/**
 * Check whether a bound branch has moved — GNC-2.1 (#4737).
 *
 * Forwards to apiome-rest's `POST …/binding/check`, which asks the provider where the ref is now
 * and records a **sync candidate** when it has moved. Nothing about the draft changes; a ref that
 * has not moved is a `409 binding-unchanged`, which the panel shows as a plain "already up to
 * date" rather than an error.
 */

import { NextRequest, NextResponse } from 'next/server';

import {
  bindingsErrorResponse,
  callRestBinding,
  missingVersionResponse,
  resolveBindingsAuth,
  versionRefFromQuery,
} from '../bindings-proxy';

export const dynamic = 'force-dynamic';

/**
 * POST /api/projects/[projectId]/bindings/check?version=<revision id or label>
 *
 * @param request - The browser's request; it carries no body.
 * @param context - The route parameters.
 * @returns `{success: true, ...binding}` or `{success: false, error, code?}`.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ projectId: string }> }
): Promise<NextResponse> {
  try {
    const { projectId } = await params;
    const version = versionRefFromQuery(request.url);
    if (!version) return missingVersionResponse();

    const auth = await resolveBindingsAuth();
    if (auth instanceof NextResponse) return auth;

    const detail = await callRestBinding(auth, projectId, version, {
      method: 'POST',
      suffix: '/check',
    });
    return NextResponse.json({ success: true, ...(detail as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'project binding check');
  }
}
