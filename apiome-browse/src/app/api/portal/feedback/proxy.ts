/**
 * Shared body of the portal feedback route handlers — COL-4.4 (#4528).
 *
 * The browser cannot read the reader session (an `HttpOnly` cookie), so the Feedback tab calls
 * Browse's own routes, and these forward to apiome-rest with `Authorization: Reader <token>`.
 *
 * Guards, in order:
 * 1. Every path segment is checked (`isTenantSlug`, `isFeedbackSegment`, `isThreadId`), so nothing
 *    in the URL can change the upstream path.
 * 2. A state-changing call must be a same-origin POST (`isSameOriginPost`).
 * 3. The cookie must hold a session for **the tenant in the URL**; anything else is a 401, the same
 *    answer apiome-rest gives, without a round trip.
 *
 * Bodies are passed through as JSON (apiome-rest validates them); the upstream status and JSON body
 * come back unchanged, so the tab reads `detail.code` the same way it would from apiome-rest.
 */

import { NextResponse, type NextRequest } from 'next/server';

import { serverRestBase } from '../../../../../lib/portal/api';
import { feedbackRestUrl, isFeedbackSegment, isThreadId, type FeedbackAction } from '../../../../../lib/portal/feedback';
import {
  isSameOriginPost,
  isTenantSlug,
  parseReaderCookie,
  readerAuthHeader,
  READER_SESSION_COOKIE,
} from '../../../../../lib/portal/session';

/** Where a call is going. */
export interface FeedbackRoute {
  tenant: string;
  project: string;
  version: string;
  threadId?: string;
  action?: FeedbackAction;
}

/** The largest request body forwarded (a message is at most 20,000 characters upstream). */
const MAX_BODY_BYTES = 128 * 1024;

/**
 * A JSON error in apiome-rest's shape.
 *
 * @param status - The HTTP status.
 * @param code - The stable code.
 * @param message - The sentence.
 * @returns The response.
 */
function refuse(status: number, code: string, message: string): NextResponse {
  return NextResponse.json({ detail: { code, message } }, { status, headers: { 'Cache-Control': 'no-store' } });
}

/**
 * Forward one feedback call to apiome-rest as the signed-in reader.
 *
 * @param request - The browser's request.
 * @param route - The (unchecked) route segments.
 * @param method - `GET` (list) or `POST` (open, reply, resolve, reopen).
 * @returns apiome-rest's status and JSON body, or a local refusal.
 */
export async function forwardFeedback(
  request: NextRequest,
  route: FeedbackRoute,
  method: 'GET' | 'POST',
): Promise<NextResponse> {
  const { tenant, project, version, threadId, action } = route;
  if (
    !isTenantSlug(tenant) ||
    !isFeedbackSegment(project) ||
    !isFeedbackSegment(version) ||
    (threadId !== undefined && !isThreadId(threadId))
  ) {
    return refuse(404, 'feedback-not-found', 'Not found.');
  }
  if (method === 'POST' && !isSameOriginPost(request.headers.get('origin'), request.url)) {
    return refuse(403, 'feedback-cross-site', 'Forbidden.');
  }
  const session = parseReaderCookie(request.cookies.get(READER_SESSION_COOKIE)?.value);
  if (!session || session.tenantSlug !== tenant) {
    return refuse(401, 'portal-session-invalid', 'Sign in to this portal to send feedback.');
  }

  let body: string | undefined;
  if (method === 'POST') {
    body = await request.text();
    if (body.length > MAX_BODY_BYTES) return refuse(413, 'feedback-too-large', 'That message is too long.');
    if (!body) body = '{}';
  }

  try {
    const upstream = await fetch(
      feedbackRestUrl(serverRestBase(process.env), tenant, project, version, threadId, action),
      {
        method,
        headers: { ...readerAuthHeader(session.token), ...(body ? { 'Content-Type': 'application/json' } : {}) },
        body,
        cache: 'no-store',
      },
    );
    const text = await upstream.text();
    return new NextResponse(text || '{}', {
      status: upstream.status,
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
    });
  } catch {
    return refuse(502, 'feedback-unavailable', 'Feedback is unavailable right now.');
  }
}
