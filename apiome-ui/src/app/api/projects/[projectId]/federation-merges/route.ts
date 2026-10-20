/**
 * A project's federation merge history — V2-REPO-8.2 (#2806).
 *
 * `GET` forwards to apiome-rest's `…/projects/{project}/federation-merges`, which enforces
 * `projects:view`.
 */

import { NextRequest, NextResponse } from 'next/server';

import { bindingsErrorResponse, callRestProject, resolveBindingsAuth } from '../bindings/bindings-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/projects/[projectId]/federation-merges
 *
 * @param _request - Unused.
 * @param context - The route parameters.
 * @returns `{success: true, merges}` or `{success: false, error}`.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ projectId: string }> }
): Promise<NextResponse> {
  try {
    const { projectId } = await params;
    const auth = await resolveBindingsAuth();
    if (auth instanceof NextResponse) return auth;
    const reply = await callRestProject(auth, projectId, { suffix: '/federation-merges' });
    return NextResponse.json({ success: true, ...(reply as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'project federation merges GET');
  }
}
