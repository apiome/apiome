'use client';

import * as React from 'react';
import {
  AtSign,
  CircleCheckBig,
  GitPullRequestArrow,
  MessageSquareCheck,
  Rocket,
  type LucideIcon,
} from 'lucide-react';

import { ICON_SIZE, ICON_STROKE_WIDTH } from '@/app/components/ui/iconSizes';
import { formatRelativeWhen } from '@/app/components/ade/repositories/repositoryDetailModel';
import {
  notificationContext,
  notificationExcerpt,
  notificationSentence,
  type NotificationRow,
  type NotificationType,
} from '@lib/notifications';

/**
 * What one notification looks like, wherever it is drawn — COL-3.2 (#4522).
 *
 * The rail dropdown and `/ade/dashboard/notifications` list the same rows in containers
 * with different semantics: a `role="menuitem"` inside a menu, and a list item inside a
 * `<ul>`. What the row *says* must not depend on which of those it is in, so the content
 * is this component and each surface supplies only the element around it.
 *
 * Four lines at most, in the order a reader needs them:
 *
 * 1. the sentence — who did what;
 * 2. the project and version it happened in;
 * 3. a mention's own excerpt, when there is one, because "somebody mentioned you" without
 *    the words is a notification that forces a click to learn anything;
 * 4. how long ago, and an unread dot.
 */

/** The glyph each event type is drawn with. */
export const NOTIFICATION_TYPE_ICONS: Readonly<Record<NotificationType, LucideIcon>> = {
  mention: AtSign,
  review_requested: GitPullRequestArrow,
  review_decision: CircleCheckBig,
  thread_resolved: MessageSquareCheck,
  version_published: Rocket,
};

/** Props for {@link NotificationRowContent}. */
export interface NotificationRowContentProps {
  /** The notification to draw. */
  row: Readonly<NotificationRow>;
  /** Reference time for the relative date, in epoch ms; tests pin it. */
  now: number;
  /** Drop the excerpt — the dropdown is a glance, not a reader. */
  compact?: boolean;
}

/**
 * One notification's content.
 *
 * @param props - See {@link NotificationRowContentProps}.
 * @returns The icon, the sentence, the context, the excerpt and the time.
 */
export default function NotificationRowContent({
  row,
  now,
  compact = false,
}: NotificationRowContentProps) {
  const Icon = NOTIFICATION_TYPE_ICONS[row.type];
  const context = notificationContext(row);
  const excerpt = compact ? null : notificationExcerpt(row);
  const unread = row.read_at === null;

  return (
    <>
      <span className="ntf-row__glyph" aria-hidden>
        {Icon ? <Icon size={ICON_SIZE.dense} strokeWidth={ICON_STROKE_WIDTH} /> : null}
      </span>

      <span className="ntf-row__body">
        <span className="ntf-row__sentence">{notificationSentence(row)}</span>
        {context ? <span className="ntf-row__context">{context}</span> : null}
        {excerpt ? <span className="ntf-row__excerpt">{excerpt}</span> : null}
        <span className="ntf-row__when">{formatRelativeWhen(row.created_at, now)}</span>
      </span>

      {unread && (
        <>
          <span className="ntf-row__dot" data-testid="notification-unread-dot" aria-hidden />
          {/* The dot is colour and position alone; this is the same fact in words. */}
          <span className="sr-only">Unread</span>
        </>
      )}
    </>
  );
}
