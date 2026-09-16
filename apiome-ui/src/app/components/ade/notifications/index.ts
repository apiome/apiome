/**
 * The notification centre's components — COL-3.2 (#4522).
 *
 * The rail bell lives with the shell (`components/shell/NotificationsMenu.tsx`) because it
 * is rail furniture; what a notification *says* lives here, because the full page at
 * `/ade/dashboard/notifications` draws the same rows in a list rather than a menu.
 */

export { default as NotificationRowContent, NOTIFICATION_TYPE_ICONS } from './NotificationRowContent';
export type { NotificationRowContentProps } from './NotificationRowContent';
