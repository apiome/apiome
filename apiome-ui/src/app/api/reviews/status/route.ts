/**
 * `GET /api/reviews/status` — the review status surfaces' one read (COL-2.4, #4520).
 *
 * Answers `{success: true, reviews: ReviewStatusRow[]}`: every **open** review of the session's
 * tenant, with the tally of its current round. Three surfaces share it:
 *
 * - the revisions table and the publish dialog pass `?projectId=` and index the reply by revision;
 * - the projects list passes nothing and collapses the reply to one summary per project.
 *
 * Why not apiome-rest: its review routes are addressed per project, so the projects list would
 * cost one upstream call per card. The read is a tenant-bound statement instead
 * (`lib/db/review-status.ts`), the way `/api/database/versions/has-class-schema` reads its map —
 * the tenant comes from the session and nothing in the query is taken on the caller's word.
 *
 * Home's "Needs attention" panel does **not** use this route: it is server-rendered and runs its
 * own section query in `lib/db/dashboard-home.ts`, which is also the only one that needs to know
 * who the reader is.
 */

import { NextRequest, NextResponse } from 'next/server';

import { getAuthSession } from '@lib/auth/server-session';
import { isUuid } from '@lib/comment-discussion';
import { listOpenReviews } from '@lib/db/review-status';

export const dynamic = 'force-dynamic';

/**
 * Read the tenant's open reviews.
 *
 * @param request - The incoming request; `?projectId=` narrows the read to one project.
 * @returns `{success: true, reviews}`, or `{success: false, error}` with 401 / 400 / 500.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const session = await getAuthSession();
    const user = session?.user as { current_tenant_id?: string } | undefined;
    if (!user) {
      return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
    }
    const tenantId = user.current_tenant_id;
    if (!tenantId) {
      return NextResponse.json({ success: false, error: 'No tenant selected' }, { status: 400 });
    }

    // An unparseable project id is refused here rather than handed to Postgres, whose `::uuid`
    // cast would abort the statement and turn a typo in a query string into a 500.
    const raw = new URL(request.url).searchParams.get('projectId')?.trim() ?? '';
    if (raw && !isUuid(raw)) {
      return NextResponse.json({ success: false, error: 'projectId must be a UUID' }, { status: 400 });
    }

    const reviews = await listOpenReviews(tenantId, raw || null);
    return NextResponse.json({ success: true, reviews });
  } catch (error) {
    console.error('Error reading review status:', error);
    const message = error instanceof Error ? error.message : 'Internal server error';
    return NextResponse.json({ success: false, error: message }, { status: 500 });
  }
}
