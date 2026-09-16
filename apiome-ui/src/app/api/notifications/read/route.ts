/**
 * `POST /api/notifications/read` — mark notifications read (COL-3.2, #4522).
 *
 * Forwards `{ids: [...]}` or `{all: true}` to apiome-rest, which is idempotent and scoped:
 * an already-read row is not counted again, and an id that is not the caller's own matches
 * nothing — an inbox must not become an oracle for which notification ids exist.
 *
 * The reply carries the unread count that follows, so a caller folds it straight into the
 * badge rather than reading the count again.
 */

import { NextRequest, NextResponse } from 'next/server';

import { sanitizeMarkReadBody } from '@lib/notifications';
import {
  callRestNotifications,
  notificationsErrorResponse,
  resolveNotificationsAuth,
} from '../notifications-proxy';

export const dynamic = 'force-dynamic';

/**
 * Mark some or all of the caller's notifications read.
 *
 * @param request - The incoming request; the body must name `ids` (UUIDs) or `all: true`.
 * @returns `{success: true, marked, unread}`, or `{success: false, error}` with 400 for a
 *   body that names nothing markable and the upstream status for a refusal.
 */
export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const auth = await resolveNotificationsAuth();
    if (auth instanceof NextResponse) return auth;

    let parsed: unknown = null;
    try {
      parsed = await request.json();
    } catch {
      parsed = null;
    }

    const body = sanitizeMarkReadBody(parsed);
    if (!body) {
      return NextResponse.json(
        { success: false, error: 'Name the notification ids to mark, or all: true' },
        { status: 400 }
      );
    }

    const result = await callRestNotifications(auth, '/read', { method: 'POST', body });
    return NextResponse.json({ success: true, ...(result as Record<string, unknown>) });
  } catch (error) {
    return notificationsErrorResponse(error, 'Failed to mark notifications read');
  }
}
