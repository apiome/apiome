/**
 * Settle one conflict of a merge result — GNC-2.3 (#4739).
 *
 * Forwards to apiome-rest's `…/sync-plans/{plan}/conflicts/{conflict}`, which records which side
 * wins at one pointer: `git` takes the repository's value, `draft` keeps the version's.
 *
 * Settling **records a decision and nothing else** — it does not edit the draft, take anything
 * from the repository, or move the binding. A settlement is final, so a repeat is answered
 * `409 sync-conflict-resolved` rather than quietly re-deciding it.
 */

import { NextRequest, NextResponse } from 'next/server';

import { sanitizeResolveRequest } from '@lib/spec-sync';

import {
  bindingsErrorResponse,
  callRestProject,
  resolveBindingsAuth,
} from '../../../../../bindings-proxy';

export const dynamic = 'force-dynamic';

/**
 * POST /api/projects/[projectId]/bindings/sync/plans/[planId]/conflicts/[conflictId]
 *
 * @param request - The browser's request; its body names the `resolution` and an optional `note`.
 * @param context - The route parameters.
 * @returns `{success: true, ...plan detail}` or `{success: false, error, code?}`.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ projectId: string; planId: string; conflictId: string }> }
): Promise<NextResponse> {
  try {
    const { projectId, planId, conflictId } = await params;

    const auth = await resolveBindingsAuth();
    if (auth instanceof NextResponse) return auth;

    const body = sanitizeResolveRequest(await request.json().catch(() => ({})));
    if (!body) {
      return NextResponse.json(
        { success: false, error: 'A conflict is settled towards the repository or the draft' },
        { status: 400 }
      );
    }

    const detail = await callRestProject(auth, projectId, {
      method: 'POST',
      suffix:
        `/sync-plans/${encodeURIComponent(planId)}` +
        `/conflicts/${encodeURIComponent(conflictId)}`,
      body,
    });
    return NextResponse.json({ success: true, ...(detail as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'project sync conflict');
  }
}
