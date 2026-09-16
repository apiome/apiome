/**
 * Settle one outstanding sync candidate — GNC-2.1 (#4737).
 *
 * Forwards to apiome-rest's `POST …/binding/candidates/{id}`. Only `applied` and `dismissed` are
 * forwarded: `superseded` is what the system records when a newer update replaces an older one,
 * and letting a browser claim it would rewrite history nobody observed.
 */

import { NextRequest, NextResponse } from 'next/server';

import { sanitizeResolveRequest } from '@lib/draft-bindings';
import {
  bindingsErrorResponse,
  callRestBinding,
  missingVersionResponse,
  resolveBindingsAuth,
  versionRefFromQuery,
} from '../../bindings-proxy';

export const dynamic = 'force-dynamic';

/**
 * POST /api/projects/[projectId]/bindings/candidates/[candidateId]?version=<revision id or label>
 *
 * @param request - The browser's request; its body carries `status` and an optional `note`.
 * @param context - The route parameters.
 * @returns `{success: true, ...binding}`, or `{success: false, error, code?}` — 400 when the
 *   status is not one a person may record.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ projectId: string; candidateId: string }> }
): Promise<NextResponse> {
  try {
    const { projectId, candidateId } = await params;
    const version = versionRefFromQuery(request.url);
    if (!version) return missingVersionResponse();

    const body = sanitizeResolveRequest(await request.json().catch(() => ({})));
    if (!body) {
      return NextResponse.json(
        { success: false, error: 'A candidate can only be applied or dismissed' },
        { status: 400 }
      );
    }

    const auth = await resolveBindingsAuth();
    if (auth instanceof NextResponse) return auth;

    const detail = await callRestBinding(auth, projectId, version, {
      method: 'POST',
      suffix: `/candidates/${encodeURIComponent(candidateId)}`,
      body,
    });
    return NextResponse.json({ success: true, ...(detail as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'project binding candidate');
  }
}
