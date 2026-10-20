/**
 * Sync a project version back to its repository as a pull request — REPO-5.8 (#2793).
 *
 * `POST` forwards to apiome-rest's `…/projects/{project_ref}/pr-back`, which enforces
 * `versions:publish` (`projects:view` for a dry run), checks the repository's allow/deny list and
 * audits every pull request it opens. Only `repositoryId`, `version` and `dryRun` are forwarded
 * ({@link sanitizePrBackRequest}).
 */

import { NextRequest, NextResponse } from 'next/server';

import { sanitizePrBackRequest } from '@lib/pr-back';

import { bindingsErrorResponse, callRestProject, resolveBindingsAuth } from '../bindings/bindings-proxy';

export const dynamic = 'force-dynamic';

/**
 * POST /api/projects/[projectId]/pr-back
 *
 * @param request - Carries `{ repositoryId, version?, dryRun? }`.
 * @param context - The route parameters.
 * @returns `{success: true, ...outcome}` or `{success: false, error, code?}`.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ projectId: string }> }
): Promise<NextResponse> {
  try {
    const { projectId } = await params;
    const body = sanitizePrBackRequest(await request.json().catch(() => null));
    if (!body) {
      return NextResponse.json({ success: false, error: 'A repository id is required' }, { status: 400 });
    }

    const auth = await resolveBindingsAuth();
    if (auth instanceof NextResponse) return auth;

    const reply = await callRestProject(auth, projectId, { method: 'POST', suffix: '/pr-back', body });
    return NextResponse.json({ success: true, ...(reply as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'project pr-back POST');
  }
}
