/**
 * A draft version's repository binding — GNC-2.1 (#4737).
 *
 * `GET` reads where the version stands, `POST` binds it to a repository ref and source path, and
 * `DELETE` releases it. All three name the version with `?version=` and forward to apiome-rest,
 * which owns every rule: only a draft can be bound, a draft has at most one active binding, and
 * the caller's **stored** credential must read the repository before anything is written.
 */

import { NextRequest, NextResponse } from 'next/server';

import { sanitizeBindRequest } from '@lib/draft-bindings';
import {
  bindingsErrorResponse,
  callRestBinding,
  missingVersionResponse,
  resolveBindingsAuth,
  versionRefFromQuery,
} from './bindings-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/projects/[projectId]/bindings?version=<revision id or label>
 *
 * @param request - The browser's request.
 * @param context - The route parameters.
 * @returns `{success: true, ...status}` or `{success: false, error, code?}`.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ projectId: string }> }
): Promise<NextResponse> {
  try {
    const { projectId } = await params;
    const version = versionRefFromQuery(request.url);
    if (!version) return missingVersionResponse();

    const auth = await resolveBindingsAuth();
    if (auth instanceof NextResponse) return auth;

    const status = await callRestBinding(auth, projectId, version);
    return NextResponse.json({ success: true, ...(status as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'project binding GET');
  }
}

/**
 * POST /api/projects/[projectId]/bindings?version=<revision id or label>
 *
 * Only the whitelisted fields reach apiome-rest; a credential in the body is dropped rather than
 * forwarded, because a private repository is read with a stored linked-account token.
 *
 * @param request - The browser's request, whose body names the repository, ref and path.
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

    const body = sanitizeBindRequest(await request.json().catch(() => ({})));
    const detail = await callRestBinding(auth, projectId, version, { method: 'POST', body });
    return NextResponse.json({ success: true, ...(detail as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'project binding POST');
  }
}

/**
 * DELETE /api/projects/[projectId]/bindings?version=<revision id or label>
 *
 * Releases the binding; apiome-rest keeps the row as history.
 *
 * @param request - The browser's request.
 * @param context - The route parameters.
 * @returns `{success: true, ...releasedBinding}` or `{success: false, error, code?}`.
 */
export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ projectId: string }> }
): Promise<NextResponse> {
  try {
    const { projectId } = await params;
    const version = versionRefFromQuery(request.url);
    if (!version) return missingVersionResponse();

    const auth = await resolveBindingsAuth();
    if (auth instanceof NextResponse) return auth;

    const released = await callRestBinding(auth, projectId, version, { method: 'DELETE' });
    return NextResponse.json({ success: true, ...(released as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'project binding DELETE');
  }
}
