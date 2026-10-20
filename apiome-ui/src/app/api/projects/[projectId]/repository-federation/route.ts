/**
 * A project's multi-repository federation switch — V2-REPO-8.2 (#2806).
 *
 * Proxies `GET/PUT /v1/tenants/{slug}/projects/{project}/repository-federation`; apiome-rest
 * enforces `projects:view` / `projects:edit` and audits the change. Only `enabled` is forwarded.
 */

import { NextRequest, NextResponse } from 'next/server';

import { bindingsErrorResponse, callRestProject, resolveBindingsAuth } from '../bindings/bindings-proxy';

export const dynamic = 'force-dynamic';

type Params = { params: Promise<{ projectId: string }> };

/**
 * GET /api/projects/[projectId]/repository-federation
 *
 * @param _request - Unused.
 * @param context - The route parameters.
 * @returns `{success: true, projectId, enabled}` or `{success: false, error}`.
 */
export async function GET(_request: NextRequest, { params }: Params): Promise<NextResponse> {
  try {
    const { projectId } = await params;
    const auth = await resolveBindingsAuth();
    if (auth instanceof NextResponse) return auth;
    const reply = await callRestProject(auth, projectId, { suffix: '/repository-federation' });
    return NextResponse.json({ success: true, ...(reply as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'repository federation GET');
  }
}

/**
 * PUT /api/projects/[projectId]/repository-federation
 *
 * @param request - Carries `{ enabled: boolean }`.
 * @param context - The route parameters.
 * @returns `{success: true, projectId, enabled}` or `{success: false, error}`.
 */
export async function PUT(request: NextRequest, { params }: Params): Promise<NextResponse> {
  try {
    const { projectId } = await params;
    const body = (await request.json().catch(() => null)) as { enabled?: unknown } | null;
    if (typeof body?.enabled !== 'boolean') {
      return NextResponse.json({ success: false, error: '`enabled` must be true or false' }, { status: 400 });
    }
    const auth = await resolveBindingsAuth();
    if (auth instanceof NextResponse) return auth;
    const reply = await callRestProject(auth, projectId, {
      method: 'PUT',
      suffix: '/repository-federation',
      body: { enabled: body.enabled },
    });
    return NextResponse.json({ success: true, ...(reply as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'repository federation PUT');
  }
}
