import NotificationsClient from './NotificationsClient';

/**
 * `/ade/dashboard/notifications` — the notification centre (COL-3.2, #4522).
 *
 * A thin route shell, like `audit/page.tsx`: everything the screen does needs the session
 * and the reader's device-local preferences, so the whole of it is a client component.
 *
 * @returns The notification centre.
 */
export default function NotificationsPage() {
  return <NotificationsClient />;
}
