/**
 * A merge request's actions — COL-4.3 (#4527).
 *
 * POST /api/merge-requests/[mergeRequestId]/check  → run a merge session for the current tips
 * POST /api/merge-requests/[mergeRequestId]/merge  → merge (body: optional immutability override)
 * POST /api/merge-requests/[mergeRequestId]/close  → close without merging
 * POST /api/merge-requests/[mergeRequestId]/review → review the branch's current tip
 *
 * Each answers `{success, mergeRequest}` with the updated detail, or a failure envelope whose
 * `code` and `detail` are apiome-rest's (`mr-not-ready` + `blockers`, `mr-conflicts` + `conflicts`,
 * `STALE_HEAD`, `PUBLISHED_IMMUTABLE` …). apiome-rest enforces the permissions.
 */

import { NextRequest, NextResponse } from 'next/server';
import { proxyRestPost } from '@lib/primitives-api-proxy';
import { reviewFailure } from '../../../reviews/review-proxy';
import {
  mergeRequestRestPath,
  mergeRequestRouteError,
  relayRest,
  resolveMergeRequestContext,
} from '../../merge-request-proxy';

/** The actions this route relays, by URL segment. */
const ACTIONS = new Set(['check', 'merge', 'close', 'review']);

/** The body fields each action may forward; anything else is dropped. */
const FORWARDED_FIELDS: Readonly<Record<string, ReadonlyArray<string>>> = {
  check: ['override_published_immutability', 'override_reason'],
  merge: ['override_published_immutability', 'override_reason'],
  close: [],
  review: ['reviewers'],
};

/**
 * Run one action.
 *
 * @param request - The browser's request.
 * @param context - The route parameters.
 * @returns `{success: true, mergeRequest}` or a failure envelope.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ mergeRequestId: string; action: string }> }
) {
  try {
    const { mergeRequestId, action } = await params;
    if (!ACTIONS.has(action)) return reviewFailure('Unknown action', 404);
    const ctx = await resolveMergeRequestContext(mergeRequestId);
    if (ctx instanceof NextResponse) return ctx;
    const raw = (await request.json().catch(() => ({}))) as Record<string, unknown> | null;
    const body: Record<string, unknown> = {};
    for (const field of FORWARDED_FIELDS[action]) {
      if (raw && raw[field] !== undefined) body[field] = raw[field];
    }
    const path = mergeRequestRestPath(ctx, `/${action}`);
    return relayRest(await proxyRestPost(ctx.user, path, action === 'close' ? undefined : body), 'mergeRequest');
  } catch (error) {
    return mergeRequestRouteError(error, 'merge request action POST');
  }
}
