/**
 * `GET /api/notifications` — one page of the caller's inbox (COL-3.2, #4522).
 *
 * A straight read of apiome-rest's `GET /v1/tenants/{slug}/notifications` with the tenant
 * resolved from the session and the query narrowed to the four parameters COL-3.1 accepts.
 * Listing never marks anything read — that is `read/route.ts`, and it is the reader's
 * doing, not a side effect of looking.
 */

import { NextRequest, NextResponse } from 'next/server';

import { sanitizeNotificationListParams } from '@lib/notifications';
import {
  callRestNotifications,
  notificationsErrorResponse,
  resolveNotificationsAuth,
} from './notifications-proxy';

export const dynamic = 'force-dynamic';

/**
 * Read a page of the inbox.
 *
 * @param request - The incoming request; `unread`, `type`, `limit` and `offset` are
 *   forwarded, everything else is dropped.
 * @returns `{success: true, ...page}`, or `{success: false, error}` with the upstream
 *   status.
 */
export async function GET(request: NextRequest): Promise<NextResponse> {
  try {
    const auth = await resolveNotificationsAuth();
    if (auth instanceof NextResponse) return auth;

    const params = sanitizeNotificationListParams(new URL(request.url).searchParams);
    const page = await callRestNotifications(auth, '', { params });
    return NextResponse.json({ success: true, ...(page as Record<string, unknown>) });
  } catch (error) {
    return notificationsErrorResponse(error, 'Failed to read notifications');
  }
}
