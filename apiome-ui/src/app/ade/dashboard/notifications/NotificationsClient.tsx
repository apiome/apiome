'use client';

import * as React from 'react';
import Link from 'next/link';
import { CheckCheck, RefreshCw, Settings2 } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { DataTableFilterChip } from '@/app/components/ui/DataTable';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import NotificationRowContent from '@/app/components/ade/notifications/NotificationRowContent';
import { openPreferences } from '@/app/components/ade/preferences/preferencesDrawerBus';
import { useAuthSession } from '@lib/auth/session-client';
import { useNotifications } from '@/app/hooks/useNotifications';
import { useNotificationPreferences } from '@/app/hooks/useNotificationPreferences';
import {
  NOTIFICATION_TYPE_LABELS,
  groupNotificationsByTime,
  notificationHref,
  type NotificationType,
} from '@lib/notifications';

/**
 * The notification centre — `/ade/dashboard/notifications` (COL-3.2, #4522).
 *
 * The rail bell is a glance at the newest twenty; this is the whole inbox, with the two
 * narrowings a glance cannot offer — unread only, and one event type — and paging through
 * however much of it COL-3.1's five-hundred-row retention has kept.
 *
 * ### What this page owns, and what it does not
 *
 * It owns the two narrowings that are *server* parameters, the paging, and which rows have
 * been marked. What a notification says and where it goes is `lib/notifications.ts` and
 * `NotificationRowContent`, shared with the bell, so the two surfaces cannot drift. Which
 * types are shown at all is the reader's preference, applied inside `useNotifications`.
 *
 * ### Why the counts on the chips are unread counts
 *
 * A chip's number is what it would leave *unread*, not how many rows it would leave: the
 * unread tallies arrive with every read (`by_type`, zeroes included), while the total per
 * type would cost one request per chip. It is also the number a reader is actually asking
 * for — "how much do I still have to look at" — and the chip is labelled accordingly.
 *
 * ### Marking
 *
 * Following a notification marks it read, because the reader has plainly seen it. A row can
 * also be marked without being followed, for the notification whose subject line was the
 * whole message. Neither removes the row: it dims. Rows only leave the list when the
 * reader asks for unread only, which is a filter they chose and can undo.
 */

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/**
 * The notification centre.
 *
 * @param props.now - Reference time for the relative dates, in epoch ms; tests pin it.
 * @returns The page.
 */
export default function NotificationsClient({ now }: { now?: number }) {
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)
    ?.current_tenant_id;

  const [mountedAt] = React.useState(() => Date.now());
  const referenceTime = now ?? mountedAt;

  const [unreadOnly, setUnreadOnly] = React.useState(false);
  const [type, setType] = React.useState<NotificationType | null>(null);

  const { preferences, visibleTypes, allMuted } = useNotificationPreferences();
  const {
    rows,
    counts,
    unreadTotal,
    hasMore,
    loading,
    loadingMore,
    error,
    loadMore,
    refresh,
    markRead,
    markAllRead,
  } = useNotifications({ enabled: Boolean(tenantId), unreadOnly, type });

  // A type the reader has just muted must not stay selected: the page would then filter to
  // a type it also hides, and answer every question with "nothing here".
  React.useEffect(() => {
    if (type && preferences[type] === 'off') setType(null);
  }, [type, preferences]);

  const groups = React.useMemo(
    () => groupNotificationsByTime(rows, referenceTime),
    [rows, referenceTime]
  );

  /** How many of the five the reader has switched off, for the note under the chips. */
  const mutedCount = 5 - visibleTypes.length;

  const handleOpenPreferences = React.useCallback(() => {
    openPreferences('notifications');
  }, []);

  return (
    <Page>
      <PageHeader
        breadcrumb={[{ label: 'Home', href: HOME_ROUTE }, { label: 'Notifications' }]}
        title="Notifications"
        description="Mentions, review requests, decisions, resolutions and publishes that concern you."
        actions={
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={refresh}
              data-testid="notifications-refresh"
            >
              <RefreshCw aria-hidden />
              Refresh
            </Button>
            <Button
              variant="soft"
              size="sm"
              disabled={unreadTotal === 0}
              onClick={() => void markAllRead()}
              data-testid="notifications-mark-all"
            >
              <CheckCheck aria-hidden />
              Mark all read
            </Button>
          </>
        }
      />

      <PageBody>
        <div className="ntf-filters" data-testid="notifications-filters">
          <DataTableFilterChip
            active={unreadOnly}
            count={unreadTotal}
            onClick={() => setUnreadOnly((value) => !value)}
            data-testid="notifications-filter-unread"
          >
            Unread only
          </DataTableFilterChip>

          <span role="none" className="ntf-filters__rule" />

          <DataTableFilterChip
            active={type === null}
            onClick={() => setType(null)}
            data-testid="notifications-filter-all"
          >
            All types
          </DataTableFilterChip>
          {visibleTypes.map((candidate) => (
            <DataTableFilterChip
              key={candidate}
              active={type === candidate}
              count={counts.by_type[candidate] ?? 0}
              onClick={() => setType((current) => (current === candidate ? null : candidate))}
              data-testid={`notifications-filter-${candidate}`}
            >
              {NOTIFICATION_TYPE_LABELS[candidate]}
            </DataTableFilterChip>
          ))}
        </div>

        {mutedCount > 0 ? (
          <p className="ntf-note" data-testid="notifications-muted-note">
            {mutedCount === 1
              ? 'One notification type is switched off on this device.'
              : `${mutedCount} notification types are switched off on this device.`}{' '}
            <button type="button" className="ntf-note__link" onClick={handleOpenPreferences}>
              <Settings2 aria-hidden className="ntf-note__glyph" />
              Change what you see
            </button>
          </p>
        ) : null}

        {error ? (
          <Alert
            variant="error"
            data-testid="notifications-error"
            actions={
              <Button variant="ghost" size="sm" onClick={refresh}>
                Try again
              </Button>
            }
          >
            {error}
          </Alert>
        ) : null}

        {loading ? (
          <p className="ntf-note" data-testid="notifications-loading">
            Reading your inbox…
          </p>
        ) : null}

        {!loading && !error && rows.length === 0 ? (
          <div className="ntf-empty" data-testid="notifications-empty">
            <p className="ntf-empty__title">
              {allMuted
                ? 'Every notification type is switched off'
                : unreadOnly || type
                  ? 'Nothing matches these filters'
                  : 'Nothing yet'}
            </p>
            <p className="ntf-empty__body">
              {allMuted
                ? 'Turn a type back on and its notifications reappear — nothing was discarded.'
                : 'Mentions, review requests, decisions, resolutions and publishes land here.'}
            </p>
            {allMuted ? (
              <Button variant="soft" size="sm" onClick={handleOpenPreferences}>
                <Settings2 aria-hidden />
                Open notification preferences
              </Button>
            ) : null}
          </div>
        ) : null}

        {groups.map((group) => (
          <section key={group.bucket} className="ntf-group" aria-label={group.label}>
            <h2 className="ntf-group__label">{group.label}</h2>
            <ul className="ntf-list">
              {group.rows.map((row) => {
                const href = notificationHref(row);
                const unread = row.read_at === null;
                return (
                  <li
                    key={row.id}
                    className="ntf-item"
                    data-testid={`notification-${row.id}`}
                    data-unread={unread ? 'true' : undefined}
                  >
                    {href ? (
                      <Link
                        href={href}
                        className="ntf-row ntf-row--page"
                        onClick={() => {
                          if (unread) void markRead([row.id]);
                        }}
                      >
                        <NotificationRowContent row={row} now={referenceTime} />
                      </Link>
                    ) : (
                      // A notification whose project or version has been deleted keeps its
                      // sentence and loses only its link — "somebody mentioned you" is worth
                      // reading after the project is gone.
                      <div className="ntf-row ntf-row--page ntf-row--inert">
                        <NotificationRowContent row={row} now={referenceTime} />
                      </div>
                    )}
                    {unread ? (
                      <button
                        type="button"
                        className="ntf-item__mark"
                        onClick={() => void markRead([row.id])}
                        data-testid={`notification-mark-${row.id}`}
                      >
                        <CheckCheck aria-hidden className="ntf-item__mark-glyph" />
                        <span className="sr-only">Mark read</span>
                      </button>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </section>
        ))}

        {hasMore ? (
          <div className="ntf-more">
            <Button
              variant="outline"
              size="sm"
              onClick={loadMore}
              disabled={loadingMore}
              data-testid="notifications-load-more"
            >
              {loadingMore ? 'Loading…' : 'Load more'}
            </Button>
          </div>
        ) : null}
      </PageBody>
    </Page>
  );
}
