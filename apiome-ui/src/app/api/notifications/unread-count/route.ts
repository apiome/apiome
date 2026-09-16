/**
 * `GET /api/notifications/unread-count` — the bell badge's one number (COL-3.2, #4522).
 *
 * Answers apiome-rest's `{total, by_type}` unchanged. `by_type` reports every type with
 * its zeroes, which is what lets the badge be recomputed for the subset of types the
 * reader has left switched on without a second request — see
 * `lib/notification-preferences.ts` § `visibleUnreadTotal`.
 */

import { NextResponse } from 'next/server';

import {
  callRestNotifications,
  notificationsErrorResponse,
  resolveNotificationsAuth,
} from '../notifications-proxy';

export const dynamic = 'force-dynamic';

/**
 * Read the caller's unread tallies.
 *
 * @returns `{success: true, unread: {total, by_type}}`, or `{success: false, error}` with
 *   the upstream status.
 */
export async function GET(): Promise<NextResponse> {
  try {
    const auth = await resolveNotificationsAuth();
    if (auth instanceof NextResponse) return auth;

    const unread = await callRestNotifications(auth, '/unread-count');
    return NextResponse.json({ success: true, unread });
  } catch (error) {
    return notificationsErrorResponse(error, 'Failed to read the unread count');
  }
}
