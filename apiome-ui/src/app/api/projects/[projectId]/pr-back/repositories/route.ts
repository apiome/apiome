/**
 * The repositories a project can PR back into — REPO-5.8 (#2793).
 *
 * `GET` forwards to apiome-rest's `…/projects/{project_ref}/pr-back/repositories`, which enforces
 * `projects:view` and says, for every repository the project was imported from, whether its
 * PR-back settings let the project open pull requests (and why not).
 */

import { NextResponse } from 'next/server';

import { bindingsErrorResponse, callRestProject, resolveBindingsAuth } from '../../bindings/bindings-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/projects/[projectId]/pr-back/repositories
 *
 * @param _request - Unused.
 * @param context - The route parameters.
 * @returns `{success: true, projectId, repositories}` or `{success: false, error}`.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ projectId: string }> }
): Promise<NextResponse> {
  try {
    const { projectId } = await params;
    const auth = await resolveBindingsAuth();
    if (auth instanceof NextResponse) return auth;

    const reply = await callRestProject(auth, projectId, { suffix: '/pr-back/repositories' });
    return NextResponse.json({ success: true, ...(reply as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'project pr-back repositories GET');
  }
}
