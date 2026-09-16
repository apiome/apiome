/**
 * Per-type in-app notification preferences — COL-3.2 (#4522).
 *
 * The reader decides which of COL-3.1's five events the notification centre shows them.
 * The switches live in the preferences pane's Notifications tab; this module is where the
 * five values are stored, read and applied.
 *
 * ### Why the preference is honoured on *read*
 *
 * COL-3.1 deliberately stores nothing about delivery and says so in
 * `apiome-rest/docs/notifications.md`: a row suppressed at write time can never be
 * recovered when the preference changes, so the inbox keeps everything and the reader's
 * choice narrows what is *shown*. Turning `mention` back on in a month brings last month's
 * mentions back with it.
 *
 * ### Why the values are device-local
 *
 * They are stored the way every other Hive preference is — a `hive.*` key in
 * `localStorage` — rather than against the account. Two consequences, both deliberate:
 *
 * - Nothing has to be migrated, no route has to be added, and no inbox row is ever muted
 *   for a reader who has not asked for it on the device they are reading on.
 * - A reader with two machines sets the switches twice. The tab says so in as many words,
 *   because a preference that silently fails to follow you is worse than one that admits
 *   it does not.
 *
 * They are **not** added to `config/preferences.ts`: every key in that record is applied
 * to `<html>` as a `data-*` attribute by a blocking boot script, and these five change no
 * token and no layout. Putting them there would cost every page five attributes and five
 * lines of pre-paint script to decide which rows a dropdown draws.
 *
 * Every read and write is guarded, like `components/shell/whatsNewSeen.ts`: storage
 * disabled, a private window that throws, or a server render all resolve to "everything is
 * on", which is the state a reader who has never opened the tab is in anyway.
 */

import {
  NOTIFICATION_TYPES,
  type NotificationType,
  type NotificationUnreadCounts,
} from './notifications';

/** Whether a type's notifications are shown in the app. */
export type NotificationChannelState = 'on' | 'off';

/** The reader's choice for each of the five types. */
export type NotificationPreferences = Record<NotificationType, NotificationChannelState>;

/**
 * The `localStorage` key each type is stored under.
 *
 * Namespaced with the rest of the shell's keys (`hive.*`) so a future "reset preferences"
 * can find them, and keyed per type rather than as one JSON blob so a corrupt value costs
 * one switch rather than all five.
 */
export const NOTIFICATION_PREFERENCE_KEYS: Readonly<Record<NotificationType, string>> =
  Object.freeze(
    Object.fromEntries(
      NOTIFICATION_TYPES.map((type) => [type, `hive.notify.${type}`])
    ) as Record<NotificationType, string>
  );

/** Every key this module owns, for a `storage` listener to filter on. */
const OWNED_KEYS: ReadonlySet<string> = new Set(Object.values(NOTIFICATION_PREFERENCE_KEYS));

/**
 * What a reader who has never opened the tab gets: all five on.
 *
 * Also the server snapshot. Defaulting to *on* is the only safe direction — a default of
 * off would hide a review request from somebody who never asked for it to be hidden.
 */
export const DEFAULT_NOTIFICATION_PREFERENCES: Readonly<NotificationPreferences> =
  Object.freeze(
    Object.fromEntries(NOTIFICATION_TYPES.map((type) => [type, 'on'])) as NotificationPreferences
  );

/**
 * Same-tab notification that a switch moved.
 *
 * `storage` events only reach *other* tabs, so the tab that made the change needs its own
 * signal. A dedicated name rather than the shell's `hive:preferences`, so flipping a
 * notification switch does not make `PreferencesProvider` re-read six unrelated keys.
 */
export const NOTIFICATION_PREFERENCES_EVENT = 'hive:notification-preferences';

/**
 * Read one type's stored value.
 *
 * @param type - The event type.
 * @returns Its state; `on` when nothing is stored, the stored value is not one of the two
 *   spellings, or storage cannot be read at all.
 */
export function readNotificationPreference(type: NotificationType): NotificationChannelState {
  if (typeof window === 'undefined') return 'on';
  try {
    return window.localStorage.getItem(NOTIFICATION_PREFERENCE_KEYS[type]) === 'off'
      ? 'off'
      : 'on';
  } catch {
    // Storage disabled or blocked by policy: show everything, which is the default anyway.
    return 'on';
  }
}

/**
 * Read all five.
 *
 * @returns The reader's preferences, complete.
 */
export function readNotificationPreferences(): NotificationPreferences {
  return Object.fromEntries(
    NOTIFICATION_TYPES.map((type) => [type, readNotificationPreference(type)])
  ) as NotificationPreferences;
}

/**
 * Store one type's value and tell this tab about it.
 *
 * @param type - The event type.
 * @param state - `on` to show its notifications, `off` to hide them.
 */
export function writeNotificationPreference(
  type: NotificationType,
  state: NotificationChannelState
): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(NOTIFICATION_PREFERENCE_KEYS[type], state);
  } catch {
    // A write that fails costs the reader a switch that forgets itself on reload; the
    // event below still fires, so the current page reflects what they just chose.
  }
  window.dispatchEvent(new Event(NOTIFICATION_PREFERENCES_EVENT));
}

/**
 * Subscribe to changes from this tab or another one.
 *
 * @param listener - Called whenever a stored value may have changed.
 * @returns The unsubscribe function.
 */
export function subscribeNotificationPreferences(listener: () => void): () => void {
  if (typeof window === 'undefined') return () => {};

  const handleStorage = (event: StorageEvent) => {
    // `key === null` is `localStorage.clear()`, which resets all five at once.
    if (event.key !== null && !OWNED_KEYS.has(event.key)) return;
    listener();
  };

  window.addEventListener('storage', handleStorage);
  window.addEventListener(NOTIFICATION_PREFERENCES_EVENT, listener);
  return () => {
    window.removeEventListener('storage', handleStorage);
    window.removeEventListener(NOTIFICATION_PREFERENCES_EVENT, listener);
  };
}

/**
 * Whether a type's notifications are hidden right now.
 *
 * @param type - The event type.
 * @param preferences - The reader's preferences.
 * @returns True when the reader has switched it off.
 */
export function isNotificationMuted(
  type: NotificationType,
  preferences: Readonly<NotificationPreferences>
): boolean {
  return preferences[type] === 'off';
}

/** The types the reader still wants to see, in vocabulary order. */
export function visibleNotificationTypes(
  preferences: Readonly<NotificationPreferences>
): NotificationType[] {
  return NOTIFICATION_TYPES.filter((type) => !isNotificationMuted(type, preferences));
}

/**
 * The number the bell badge shows.
 *
 * Recomputed from `by_type` rather than read from `total`, which is why muting needs no
 * second request and no upstream change: the endpoint reports every type, zeroes included,
 * so the subset the reader wants is always a sum of numbers already in hand.
 *
 * @param counts - The unread tallies from apiome-rest.
 * @param preferences - The reader's preferences.
 * @returns Unread rows of the types the reader has left switched on.
 */
export function visibleUnreadTotal(
  counts: Readonly<NotificationUnreadCounts>,
  preferences: Readonly<NotificationPreferences>
): number {
  return visibleNotificationTypes(preferences).reduce(
    (sum, type) => sum + (counts.by_type[type] ?? 0),
    0
  );
}

/**
 * Drop the rows whose type the reader has switched off.
 *
 * Applied after the read rather than as a query parameter: apiome-rest's `type` filter
 * takes one value, and the badge needs the whole `by_type` map regardless, so one
 * unfiltered read answers both questions. The cost is that a page can come back mostly
 * muted — which is why every surface counts what it *shows* rather than echoing `total`.
 *
 * @param rows - The notifications as read.
 * @param preferences - The reader's preferences.
 * @returns The rows to draw, in the order they were given.
 */
export function filterMutedNotifications<T extends { type: NotificationType }>(
  rows: readonly T[],
  preferences: Readonly<NotificationPreferences>
): T[] {
  return rows.filter((row) => !isNotificationMuted(row.type, preferences));
}

/**
 * Whether every type is switched off.
 *
 * The one state a surface has to explain rather than draw: an empty centre because there
 * is nothing to say, and an empty centre because the reader silenced all five, must not be
 * the same screen.
 *
 * @param preferences - The reader's preferences.
 * @returns True when nothing at all would be shown.
 */
export function allNotificationsMuted(
  preferences: Readonly<NotificationPreferences>
): boolean {
  return visibleNotificationTypes(preferences).length === 0;
}
