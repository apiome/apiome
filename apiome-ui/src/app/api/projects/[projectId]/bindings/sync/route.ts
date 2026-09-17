/**
 * Three-way synchronization of a bound draft — GNC-2.3 (#4739).
 *
 * `GET` forwards to apiome-rest's `…/binding/sync`, which answers with what is already known: the
 * most recent merge of this draft against its repository ref, with its conflicts, and the merges
 * before it. No provider is contacted.
 *
 * `POST` forwards to the same path, which reads the bound selection at the commit the draft is
 * synchronized with and at the commit its branch moved to, rebuilds the draft's own document, and
 * merges the three. **Nothing about the draft changes** — the answer is a merge result to read.
 */

import { NextRequest, NextResponse } from 'next/server';

import { sanitizeComputeRequest } from '@lib/spec-sync';

import {
  bindingsErrorResponse,
  callRestBinding,
  missingVersionResponse,
  resolveBindingsAuth,
  versionRefFromQuery,
} from '../bindings-proxy';

export const dynamic = 'force-dynamic';

/**
 * GET /api/projects/[projectId]/bindings/sync?version=<revision id or label>
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

    const status = await callRestBinding(auth, projectId, version, { suffix: '/sync' });
    return NextResponse.json({ success: true, ...(status as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'project sync status');
  }
}

/**
 * POST /api/projects/[projectId]/bindings/sync?version=<revision id or label>
 *
 * @param request - The browser's request; its body may name a `candidate_id` and ask to `refresh`.
 * @param context - The route parameters.
 * @returns `{success: true, ...plan detail}` or `{success: false, error, code?}`.
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

    const body = await request.json().catch(() => ({}));
    const detail = await callRestBinding(auth, projectId, version, {
      method: 'POST',
      suffix: '/sync',
      body: sanitizeComputeRequest(body),
    });
    return NextResponse.json({ success: true, ...(detail as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'project sync merge');
  }
}
