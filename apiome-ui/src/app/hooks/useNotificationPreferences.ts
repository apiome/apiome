'use client';

import { useCallback, useMemo, useSyncExternalStore } from 'react';

import {
  DEFAULT_NOTIFICATION_PREFERENCES,
  allNotificationsMuted,
  readNotificationPreferences,
  subscribeNotificationPreferences,
  visibleNotificationTypes,
  writeNotificationPreference,
  type NotificationPreferences,
} from '@lib/notification-preferences';
import type { NotificationType } from '@lib/notifications';

/**
 * The reader's per-type notification switches, as React state — COL-3.2 (#4522).
 *
 * `localStorage` is treated as what it is, an external store, and read through
 * {@link useSyncExternalStore} — the same shape `PreferencesProvider` uses for the shell's
 * own preferences. That is what keeps this SSR-safe (the server and the hydrating render
 * both see "all five on"), keeps two tabs of the app in step, and avoids reading storage
 * into state from an effect.
 *
 * The values themselves, and the reason they are device-local rather than account-level,
 * are documented in `lib/notification-preferences.ts`.
 */

/**
 * The last value read out of storage.
 *
 * {@link useSyncExternalStore} compares snapshots by identity, so re-reading storage on
 * every render would loop forever. The snapshot is cached until something invalidates it.
 */
let cached: NotificationPreferences | null = null;

/**
 * The current preferences, re-read only when the cache has been dropped.
 *
 * @returns The stored preferences, stable by identity between changes.
 */
function snapshot(): NotificationPreferences {
  if (!cached) cached = readNotificationPreferences();
  return cached;
}

/**
 * The value the server renders and the client hydrates with.
 *
 * @returns The defaults — storage is a device fact the server cannot know.
 */
function serverSnapshot(): Readonly<NotificationPreferences> {
  return DEFAULT_NOTIFICATION_PREFERENCES;
}

/**
 * Subscribe to changes, dropping the cache first.
 *
 * Storage may have moved on while nothing was listening — a second tab, or simply the last
 * time the app was open.
 *
 * @param listener - Called whenever a stored value may have changed.
 * @returns The unsubscribe function.
 */
function subscribe(listener: () => void): () => void {
  cached = null;
  return subscribeNotificationPreferences(() => {
    cached = null;
    listener();
  });
}

/** What {@link useNotificationPreferences} gives back. */
export interface UseNotificationPreferencesResult {
  /** The reader's choice for each of the five types. */
  preferences: Readonly<NotificationPreferences>;
  /** The types still switched on, in vocabulary order. */
  visibleTypes: readonly NotificationType[];
  /** True when all five are off — a state the surfaces explain rather than draw. */
  allMuted: boolean;
  /** Turn one type's in-app notifications on or off. Applies immediately. */
  setPreference: (type: NotificationType, on: boolean) => void;
}

/**
 * Read and write the per-type notification switches.
 *
 * @returns See {@link UseNotificationPreferencesResult}.
 */
export function useNotificationPreferences(): UseNotificationPreferencesResult {
  const preferences = useSyncExternalStore(subscribe, snapshot, serverSnapshot);

  const setPreference = useCallback((type: NotificationType, on: boolean) => {
    writeNotificationPreference(type, on ? 'on' : 'off');
  }, []);

  const visibleTypes = useMemo(() => visibleNotificationTypes(preferences), [preferences]);

  return {
    preferences,
    visibleTypes,
    allMuted: allNotificationsMuted(preferences),
    setPreference,
  };
}

export default useNotificationPreferences;
