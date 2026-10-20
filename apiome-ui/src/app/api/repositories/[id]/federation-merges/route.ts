/**
 * A repository's sync history: the federation merges its files were imported in — V2-REPO-8.2 (#2806).
 *
 * `GET` forwards to apiome-rest's `…/repositories/{id}/federation-merges`, which enforces
 * `imports:view`.
 */

import { NextRequest, NextResponse } from 'next/server';

import {
  bindingsErrorResponse,
  callRestUrl,
  resolveBindingsAuth,
  restRepositoryUrl,
} from '../../../projects/[projectId]/bindings/bindings-proxy';

export const dynamic = 'force-dynamic';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/**
 * GET /api/repositories/[id]/federation-merges
 *
 * @param _request - Unused.
 * @param context - Route params carrying the repository id.
 * @returns `{success: true, merges}` or `{success: false, error}`.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
): Promise<NextResponse> {
  try {
    const { id } = await params;
    if (!UUID_RE.test(id)) {
      return NextResponse.json({ success: false, error: 'Invalid repository id' }, { status: 400 });
    }
    const auth = await resolveBindingsAuth();
    if (auth instanceof NextResponse) return auth;
    const reply = await callRestUrl(auth, restRepositoryUrl(auth.tenantSlug, id, '/federation-merges'), {});
    return NextResponse.json({ success: true, ...(reply as Record<string, unknown>) });
  } catch (error) {
    return bindingsErrorResponse(error, 'repository federation merges GET');
  }
}
