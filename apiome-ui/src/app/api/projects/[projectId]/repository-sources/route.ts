/**
 * A project's contributing repositories and per-entity provenance — REPO-5.7 (#2792).
 *
 * `GET` forwards to apiome-rest's `…/projects/{project_ref}/repository-sources`, which enforces
 * `projects:view` and scopes the read to the caller's tenant. `?version=` (revision id or label)
 * picks the version; the newest one when omitted. Session, tenant and token plumbing is the
 * project BFF's shared helper ({@link callRestProject}).
 */

import { NextRequest, NextResponse } from 'next/server';

import {
  bindingsErrorResponse,
  callRestProject,
  resolveBindingsAuth,
  versionRefFromQuery,
} from '../bindings/bindings-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/projects/[projectId]/repository-sources?version=<revision id or label>
 *
 * @param request - The browser's request.
 * @param context - The route parameters.
 * @returns `{success: true, ...reply}` or `{success: false, error}`.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ projectId: string }> }
): Promise<NextResponse> {
  try {
    const { projectId } = await params;
    const version = versionRefFromQuery(request.url);

    const auth = await resolveBindingsAuth();
    if (auth instanceof NextResponse) return auth;

    const query = version ? `?version=${encodeURIComponent(version)}` : '';
    const reply = await callRestProject(auth, projectId, { suffix: `/repository-sources${query}` });
    return NextResponse.json({ success: true, ...(reply as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'project repository sources GET');
  }
}
