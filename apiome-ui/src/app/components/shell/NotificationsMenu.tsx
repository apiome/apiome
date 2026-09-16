'use client';

import * as React from 'react';
import Link from 'next/link';
import { Bell, CheckCheck, Inbox } from 'lucide-react';

import { ICON_SIZE, ICON_STROKE_WIDTH } from '@/app/components/ui/iconSizes';
import NotificationRowContent from '@/app/components/ade/notifications/NotificationRowContent';
import { openPreferences } from '@/app/components/ade/preferences/preferencesDrawerBus';
import { useNotifications } from '@/app/hooks/useNotifications';
import { useNotificationPreferences } from '@/app/hooks/useNotificationPreferences';
import {
  NOTIFICATIONS_ROUTE,
  NOTIFICATION_MENU_LIMIT,
  groupNotificationsByTime,
  notificationHref,
} from '@lib/notifications';
import { cn } from '@lib/utils';
import { RAIL_ITEM_CLASS, RAIL_ITEM_HOVER_CLASS, RailTooltip } from './railChrome';
import {
  RAIL_MENU_ABOVE_CLASS,
  RAIL_MENU_ITEM_CLASS,
  RAIL_MENU_ITEM_DISABLED_CLASS,
  RAIL_MENU_SEPARATOR_CLASS,
  RAIL_MENU_SURFACE_CLASS,
  useRailMenu,
} from './railMenu';

/**
 * The rail footer's notification bell and its dropdown (COL-3.2, #4522).
 *
 * COL-3.1 (#4521) writes an inbox row for every mention, review request, decision, thread
 * resolution and publish that concerns the reader. This is where those rows become
 * visible: a count they can see from any page, a list they can glance at without leaving
 * the one they are on, and a link to each notification's source.
 *
 * ### Why the bell is in the rail, not above the page
 *
 * The ticket says "bell in the ADE header". HIVE-3.8 (#5294) retired that header, and the
 * rail footer is where the rest of its right-hand cluster went — the profile menu, the
 * build badge, the release notes. Re-adding a strip for one glyph would undo that, so the
 * bell joins the footer as a row of its own, above Help & docs.
 *
 * ### The same menu as the two above it
 *
 * `useRailMenu` from `railMenu.tsx` owns the roving arrow keys, `Esc` back to the trigger,
 * and dismissal on an outside click or on focus leaving — the workspace switcher and the
 * user menu behave identically because all three *are* the same menu.
 *
 * Two things this one adds:
 *
 * - **Rows are grouped by time** (`groupNotificationsByTime`), and a `role="menu"` may own
 *   nothing but menu items — so each run is a `role="group"` whose `aria-label` is the
 *   heading, which is a legal child of a menu and announces the run without a second
 *   element to read.
 * - **The list is read when the menu opens**, not every minute. While it is shut the hook
 *   is in `countsOnly` mode: the badge is one small request a minute, and the twenty rows
 *   behind it are worth reading when somebody can actually see them.
 *
 * ### What muting does here
 *
 * The badge is the sum of the types the reader has left switched on, not the endpoint's
 * `total`, and the list drops the rest — see `lib/notification-preferences.ts`. When every
 * type is off the menu says so and offers the tab that turns them back on, because an
 * empty inbox and a silenced one must not be the same screen.
 */

/** `id` of the popup, so the trigger's `aria-controls` can point at it. */
const MENU_POPUP_ID = 'rail-notifications-menu';

/** The row's label, and the accessible name of the menu it opens. */
const MENU_LABEL = 'Notifications';

/** Above this, the badge stops counting and starts saying "a lot". */
const BADGE_CAP = 99;

/** Props for {@link NotificationsMenu}. */
export interface NotificationsMenuProps {
  /**
   * The caller's current tenant, when the session names one.
   *
   * An inbox is tenant-scoped, so without one there is nothing to read and the row draws no
   * badge rather than a zero.
   */
  currentTenantId?: string | null;
  /** Whether the rail is drawing icon-only, in which case the label moves to a tooltip. */
  iconRail: boolean;
  /** Reference time for the relative dates, in epoch ms; tests pin it. */
  now?: number;
}

/**
 * The notification row and, when open, the dropdown it controls.
 *
 * @param props - See {@link NotificationsMenuProps}.
 * @returns The rail row and its menu.
 */
export default function NotificationsMenu({
  currentTenantId,
  iconRail,
  now,
}: NotificationsMenuProps) {
  const [open, setOpen] = React.useState(false);
  const [mountedAt] = React.useState(() => Date.now());
  const referenceTime = now ?? mountedAt;
  const enabled = Boolean(currentTenantId);
  const { allMuted } = useNotificationPreferences();

  const { rows, unreadTotal, loading, error, markRead, markAllRead } = useNotifications({
    enabled,
    countsOnly: !open,
    limit: NOTIFICATION_MENU_LIMIT,
  });

  const {
    anchorRef,
    triggerRef,
    menuRef,
    closeMenu,
    onMenuKeyDown,
    focusFirstItem,
    focusLastItem,
    itemTabIndex,
    onItemFocus,
  } = useRailMenu({ open, onClose: () => setOpen(false) });

  /**
   * Which end of the list the next open should land on.
   *
   * A ref rather than state: it is read once, by the effect below, in the same commit the
   * menu opens — rendering never depends on it.
   */
  const landOnLastRef = React.useRef(false);

  // Opening a menu moves the caret into it (the WAI-ARIA menu-button pattern), and the
  // arrow handler lives on the menu element, so without this the reader would open the
  // menu and still be outside anything that listens.
  //
  // `rows.length` is a dependency because the first open has nothing in it yet: the list is
  // read when the menu opens, so the focus lands on "Mark all read" and then moves to the
  // first notification the moment the rows arrive.
  React.useEffect(() => {
    if (!open) return;
    if (landOnLastRef.current) focusLastItem();
    else focusFirstItem();
    landOnLastRef.current = false;
  }, [open, rows.length, focusFirstItem, focusLastItem]);

  const groups = React.useMemo(
    () => groupNotificationsByTime(rows, referenceTime),
    [rows, referenceTime]
  );

  /** Every row in the order the arrow keys walk them; the roving index counts through it. */
  const flatRows = React.useMemo(() => groups.flatMap((group) => group.rows), [groups]);

  /** `Mark all read` is the first item, so every notification is offset by one. */
  const MARK_ALL_INDEX = 0;

  /**
   * Mark everything read without closing the menu.
   *
   * The reader is looking at the list; taking it away the moment they clear the badge
   * would hide the very thing they just acknowledged.
   */
  const handleMarkAllRead = React.useCallback(() => {
    void markAllRead();
  }, [markAllRead]);

  /**
   * Follow a notification: mark it read, then let the link navigate.
   *
   * The mark is fire-and-forget and deliberately not awaited — a navigation must not wait
   * on a POST, and the row is stamped locally either way. The menu closes without
   * restoring focus, because the reader has already said where they want to be.
   *
   * @param id - The notification's id.
   * @param unread - Whether it still needs marking.
   */
  const handleFollow = React.useCallback(
    (id: string, unread: boolean) => {
      if (unread) void markRead([id]);
      closeMenu(false);
    },
    [closeMenu, markRead]
  );

  /** Open the preferences pane on its Notifications tab, from the all-muted notice. */
  const handleOpenPreferences = React.useCallback(() => {
    closeMenu(true);
    openPreferences('notifications');
  }, [closeMenu]);

  const badge = unreadTotal > BADGE_CAP ? `${BADGE_CAP}+` : String(unreadTotal);
  const unreadPhrase =
    unreadTotal === 0
      ? 'no unread notifications'
      : `${unreadTotal} unread notification${unreadTotal === 1 ? '' : 's'}`;

  return (
    <div ref={anchorRef} className="relative">
      <RailTooltip label={`${MENU_LABEL} — ${unreadPhrase}`} when={iconRail}>
        <button
          ref={triggerRef}
          type="button"
          data-testid="rail-notifications"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={open ? MENU_POPUP_ID : undefined}
          onClick={() => setOpen((current) => !current)}
          onKeyDown={(event) => {
            // ↓ opens onto the first row, ↑ onto the last — the two chords a menu button
            // is expected to answer even when it is closed.
            if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
            event.preventDefault();
            landOnLastRef.current = event.key === 'ArrowUp';
            setOpen(true);
          }}
          className={cn(RAIL_ITEM_CLASS, RAIL_ITEM_HOVER_CLASS, 'text-fg-muted')}
        >
          <span className="ntf-bell">
            <Bell
              size={ICON_SIZE.rail}
              strokeWidth={ICON_STROKE_WIDTH}
              aria-hidden
              className="shrink-0 text-fg-subtle group-hover/item:text-fg"
            />
            {/* The badge rides the glyph as well as the label, because a collapsed rail
                takes the label away — and an unread count nobody can see is not one. */}
            {unreadTotal > 0 && (
              <span className="ntf-bell__dot" data-testid="rail-notifications-dot" aria-hidden />
            )}
          </span>
          <span className="rail-label min-w-0 flex-1 items-center justify-between gap-2">
            <span className="truncate">{MENU_LABEL}</span>
            {unreadTotal > 0 && (
              <span className="ntf-badge" data-testid="rail-notifications-badge" aria-hidden>
                {badge}
              </span>
            )}
          </span>
          {/* The count in words, for a reader who has neither the badge nor the dot. */}
          <span className="sr-only">
            {MENU_LABEL} — {unreadPhrase}
          </span>
        </button>
      </RailTooltip>

      {open && (
        <div
          id={MENU_POPUP_ID}
          data-testid="notifications-menu"
          className={cn(RAIL_MENU_SURFACE_CLASS, RAIL_MENU_ABOVE_CLASS, 'ntf-menu')}
        >
          {/* The heading is chrome *around* the menu, not part of it: `role="menu"` may own
              nothing but menu items and groups (axe `aria-required-children`, critical),
              the rule the user menu's identity block follows for the same reason. */}
          <p className="ntf-menu__title">
            {MENU_LABEL}
            {unreadTotal > 0 ? <span className="ntf-menu__count">{unreadTotal}</span> : null}
          </p>

          <div
            ref={menuRef}
            role="menu"
            aria-label={MENU_LABEL}
            onKeyDown={onMenuKeyDown}
            className="ntf-menu__list"
          >
            {/* First, so the arrow keys reach it: a "mark all read" that only a pointer can
                press is the one affordance this menu cannot afford to hide. */}
            <button
              type="button"
              role="menuitem"
              data-testid="notifications-mark-all"
              aria-disabled={unreadTotal === 0}
              tabIndex={itemTabIndex(MARK_ALL_INDEX)}
              onFocus={() => onItemFocus(MARK_ALL_INDEX)}
              onClick={unreadTotal === 0 ? undefined : handleMarkAllRead}
              className={cn(
                RAIL_MENU_ITEM_CLASS,
                unreadTotal === 0 && RAIL_MENU_ITEM_DISABLED_CLASS
              )}
            >
              <CheckCheck
                size={ICON_SIZE.dense}
                strokeWidth={ICON_STROKE_WIDTH}
                aria-hidden
                className="shrink-0 text-fg-subtle"
              />
              <span className="min-w-0 flex-1 truncate">Mark all read</span>
            </button>

            <div role="none" className={RAIL_MENU_SEPARATOR_CLASS} />

            {groups.map((group) => (
              // A `group` is a legal child of `menu`, so the run's heading can be announced
              // as the group's name rather than as an element the reader has to step over.
              <div key={group.bucket} role="group" aria-label={group.label}>
                <p className="ntf-menu__bucket" aria-hidden>
                  {group.label}
                </p>
                {group.rows.map((row) => {
                  const index = flatRows.indexOf(row) + 1;
                  const href = notificationHref(row);
                  const unread = row.read_at === null;
                  const shared = {
                    role: 'menuitem' as const,
                    tabIndex: itemTabIndex(index),
                    onFocus: () => onItemFocus(index),
                    'data-testid': `notification-${row.id}`,
                    'data-unread': unread ? 'true' : undefined,
                    className: cn(RAIL_MENU_ITEM_CLASS, 'ntf-row'),
                  };

                  // A notification whose destination has been deleted arrives with its
                  // project or version nulled. It is still worth reading — "somebody
                  // mentioned you" survives the project going away — so the row is drawn,
                  // and only its link is withheld.
                  return href ? (
                    <Link
                      key={row.id}
                      href={href}
                      onClick={() => handleFollow(row.id, unread)}
                      {...shared}
                    >
                      <NotificationRowContent row={row} now={referenceTime} compact />
                    </Link>
                  ) : (
                    <button
                      key={row.id}
                      type="button"
                      onClick={() => handleFollow(row.id, unread)}
                      {...shared}
                    >
                      <NotificationRowContent row={row} now={referenceTime} compact />
                    </button>
                  );
                })}
              </div>
            ))}

            <div role="none" className={RAIL_MENU_SEPARATOR_CLASS} />

            <Link
              href={NOTIFICATIONS_ROUTE}
              role="menuitem"
              data-testid="notifications-see-all"
              tabIndex={itemTabIndex(flatRows.length + 1)}
              onFocus={() => onItemFocus(flatRows.length + 1)}
              onClick={() => closeMenu(false)}
              className={RAIL_MENU_ITEM_CLASS}
            >
              <Inbox
                size={ICON_SIZE.dense}
                strokeWidth={ICON_STROKE_WIDTH}
                aria-hidden
                className="shrink-0 text-fg-subtle"
              />
              <span className="min-w-0 flex-1 truncate">See all notifications</span>
            </Link>
          </div>

          {/* The three things that are not a list, each one line — never a banner. A bell
              that shouts about its own failure is louder than the notifications it is for. */}
          {loading && rows.length === 0 ? (
            <p className="ntf-menu__note" data-testid="notifications-loading">
              Reading your inbox…
            </p>
          ) : null}
          {error ? (
            <p className="ntf-menu__note" data-testid="notifications-error">
              {error}
            </p>
          ) : null}
          {!loading && !error && rows.length === 0 ? (
            allMuted ? (
              <p className="ntf-menu__note" data-testid="notifications-muted">
                Every notification type is switched off.{' '}
                <button type="button" className="ntf-menu__link" onClick={handleOpenPreferences}>
                  Turn some back on
                </button>
              </p>
            ) : (
              <p className="ntf-menu__note" data-testid="notifications-empty">
                Nothing yet. Mentions, review requests and publishes land here.
              </p>
            )
          ) : null}
        </div>
      )}
    </div>
  );
}
