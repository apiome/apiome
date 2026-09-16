'use client';

import React from 'react';
import { Bell } from 'lucide-react';

import { useNotificationPreferences } from '@/app/hooks/useNotificationPreferences';
import {
  NOTIFICATIONS_ROUTE,
  NOTIFICATION_TYPES,
  NOTIFICATION_TYPE_DESCRIPTIONS,
  NOTIFICATION_TYPE_LABELS,
} from '@lib/notifications';
import SwitchRow from './SwitchRow';

/**
 * The Notifications tab of the preferences pane (HIVE-1.4, #5277; COL-3.2, #4522).
 *
 * HIVE-1.4 shipped this tab empty, and said why: the four notifications `DESIGN.md` §4.1
 * names are all *delivery* — email, alerts — and a switch that only wrote to
 * `localStorage` would have read as "you will be emailed" without being true.
 *
 * COL-3.2 gives the tab five switches that *are* true. They control the in-app
 * notification centre — the rail bell and `/ade/dashboard/notifications` — which is drawn
 * by this browser from rows it reads itself, so a device-local preference is exactly the
 * right scope for it and the switch does precisely what it says.
 *
 * ### What a switch does, and does not, do
 *
 * Turning a type off hides its notifications here. It does **not** stop them being
 * written: COL-3.1 records every event in the same transaction as the event itself, and
 * `apiome-rest/docs/notifications.md` asks a client to filter on *read* for the reason this
 * tab makes visible — a row muted at write time could never be recovered when the reader
 * changes their mind. Switching a type back on brings its history back with it, which the
 * copy below promises in as many words.
 *
 * Email (COL-3.3) and chat delivery (COL-3.4) are still not here, and the tab still says
 * so rather than implying that these five switches govern them.
 */

/** What the switches govern, said once above them. */
const INTRO =
  'Choose what the bell and the notification centre show you. Nothing is discarded — ' +
  'turn a type back on and its history comes back.';

/** The delivery channels that are still not built, named so the tab does not imply them. */
const NOT_YET = 'Email digests and chat delivery are not available yet.';

/**
 * The Notifications tab.
 *
 * @returns Five switches, one per event type, over the reader's device-local preferences.
 */
export default function NotificationsTab() {
  const { preferences, setPreference } = useNotificationPreferences();

  return (
    <div data-testid="preferences-notifications" className="flex flex-col gap-4">
      <div>
        <div className="flex items-center gap-2">
          <Bell className="h-4 w-4 text-fg-muted" aria-hidden />
          <h3 className="text-sm font-semibold text-fg">In-app notifications</h3>
        </div>
        <p className="mt-1 text-xs text-fg-muted">{INTRO}</p>
      </div>

      <div>
        {NOTIFICATION_TYPES.map((type) => (
          <SwitchRow
            key={type}
            name={`notify-${type}`}
            title={NOTIFICATION_TYPE_LABELS[type]}
            description={NOTIFICATION_TYPE_DESCRIPTIONS[type]}
            checked={preferences[type] === 'on'}
            onCheckedChange={(checked) => setPreference(type, checked)}
          />
        ))}
      </div>

      <p className="text-xs text-fg-muted">
        These switches apply to this device. {NOT_YET} See everything that has come in on the{' '}
        <a className="underline underline-offset-2 hover:text-fg" href={NOTIFICATIONS_ROUTE}>
          notifications page
        </a>
        .
      </p>
    </div>
  );
}
