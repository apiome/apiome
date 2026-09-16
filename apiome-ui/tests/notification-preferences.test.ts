/**
 * Per-type in-app notification preferences (COL-3.2, #4522).
 *
 * The switches in the preferences pane decide which of COL-3.1's five events the bell and
 * the notification centre show. This suite pins the three promises that decision rests on:
 *
 * 1. **The default is on.** A reader who has never opened the tab is never quietly hiding a
 *    review request from themselves.
 * 2. **Muting is applied on read.** Nothing is discarded, so switching a type back on brings
 *    its history back — the rule `apiome-rest/docs/notifications.md` asks a client to follow.
 * 3. **Storage is never fatal.** A private window that throws on read or write leaves a
 *    working centre showing everything, rather than a shell that will not render.
 */

import { afterEach, beforeEach, describe, expect, jest, test } from '@jest/globals';

import {
  DEFAULT_NOTIFICATION_PREFERENCES,
  NOTIFICATION_PREFERENCES_EVENT,
  NOTIFICATION_PREFERENCE_KEYS,
  allNotificationsMuted,
  filterMutedNotifications,
  isNotificationMuted,
  readNotificationPreference,
  readNotificationPreferences,
  subscribeNotificationPreferences,
  visibleNotificationTypes,
  visibleUnreadTotal,
  writeNotificationPreference,
  type NotificationPreferences,
} from '../lib/notification-preferences';
import { NOTIFICATION_TYPES, type NotificationUnreadCounts } from '../lib/notifications';

/**
 * Preferences with the named types switched off.
 *
 * @param off - The types to mute.
 * @returns A complete preferences record.
 */
function mute(...off: readonly string[]): NotificationPreferences {
  return Object.fromEntries(
    NOTIFICATION_TYPES.map((type) => [type, off.includes(type) ? 'off' : 'on'])
  ) as NotificationPreferences;
}

/**
 * Unread tallies.
 *
 * @param byType - The per-type counts; missing types are zero.
 * @returns The counts, with a total that adds up.
 */
function counts(byType: Partial<Record<string, number>>): NotificationUnreadCounts {
  const resolved = Object.fromEntries(
    NOTIFICATION_TYPES.map((type) => [type, byType[type] ?? 0])
  ) as Record<(typeof NOTIFICATION_TYPES)[number], number>;
  return {
    total: Object.values(resolved).reduce((sum, value) => sum + value, 0),
    by_type: resolved,
  };
}

beforeEach(() => {
  window.localStorage.clear();
});

describe('storage', () => {
  test('keys every type under the shell’s own namespace', () => {
    expect(NOTIFICATION_PREFERENCE_KEYS.mention).toBe('hive.notify.mention');
    expect(Object.values(NOTIFICATION_PREFERENCE_KEYS)).toHaveLength(NOTIFICATION_TYPES.length);
    for (const key of Object.values(NOTIFICATION_PREFERENCE_KEYS)) {
      expect(key.startsWith('hive.')).toBe(true);
    }
  });

  test('defaults every type to on, so nothing is hidden by accident', () => {
    for (const type of NOTIFICATION_TYPES) {
      expect(DEFAULT_NOTIFICATION_PREFERENCES[type]).toBe('on');
      expect(readNotificationPreference(type)).toBe('on');
    }
    expect(readNotificationPreferences()).toEqual(DEFAULT_NOTIFICATION_PREFERENCES);
  });

  test('round-trips a choice', () => {
    writeNotificationPreference('mention', 'off');
    expect(window.localStorage.getItem('hive.notify.mention')).toBe('off');
    expect(readNotificationPreference('mention')).toBe('off');
    expect(readNotificationPreference('review_requested')).toBe('on');

    writeNotificationPreference('mention', 'on');
    expect(readNotificationPreference('mention')).toBe('on');
  });

  test('reads an unknown stored spelling as on rather than as broken', () => {
    window.localStorage.setItem('hive.notify.mention', 'maybe');
    expect(readNotificationPreference('mention')).toBe('on');
  });

  test('survives storage that throws', () => {
    const getItem = jest
      .spyOn(Storage.prototype, 'getItem')
      .mockImplementation(() => {
        throw new Error('blocked by policy');
      });
    const setItem = jest
      .spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => {
        throw new Error('blocked by policy');
      });

    expect(() => readNotificationPreferences()).not.toThrow();
    expect(readNotificationPreference('mention')).toBe('on');
    expect(() => writeNotificationPreference('mention', 'off')).not.toThrow();

    getItem.mockRestore();
    setItem.mockRestore();
  });
});

describe('subscribing', () => {
  const listeners: Array<() => void> = [];

  afterEach(() => {
    while (listeners.length) listeners.pop()?.();
  });

  test('tells this tab when a switch moves', () => {
    const listener = jest.fn();
    listeners.push(subscribeNotificationPreferences(listener));

    writeNotificationPreference('mention', 'off');
    expect(listener).toHaveBeenCalled();
  });

  test('tells this tab when another one writes the key', () => {
    const listener = jest.fn();
    listeners.push(subscribeNotificationPreferences(listener));

    window.dispatchEvent(new StorageEvent('storage', { key: 'hive.notify.mention' }));
    expect(listener).toHaveBeenCalledTimes(1);

    // Somebody else's key is not this module's business.
    window.dispatchEvent(new StorageEvent('storage', { key: 'hive.density' }));
    expect(listener).toHaveBeenCalledTimes(1);

    // `key === null` is `localStorage.clear()`, which resets all five at once.
    window.dispatchEvent(new StorageEvent('storage', { key: null }));
    expect(listener).toHaveBeenCalledTimes(2);
  });

  test('stops listening when unsubscribed', () => {
    const listener = jest.fn();
    subscribeNotificationPreferences(listener)();
    window.dispatchEvent(new Event(NOTIFICATION_PREFERENCES_EVENT));
    expect(listener).not.toHaveBeenCalled();
  });
});

describe('applying the preference', () => {
  test('the badge counts only the types still switched on', () => {
    const unread = counts({ mention: 4, review_requested: 2, version_published: 1 });
    expect(visibleUnreadTotal(unread, mute())).toBe(7);
    expect(visibleUnreadTotal(unread, mute('mention'))).toBe(3);
    expect(visibleUnreadTotal(unread, mute('mention', 'review_requested'))).toBe(1);
    expect(visibleUnreadTotal(unread, mute(...NOTIFICATION_TYPES))).toBe(0);
  });

  test('the badge is recomputed from by_type, never read from total', () => {
    // A `total` that disagrees with the per-type tallies must not leak into the badge: the
    // point of recomputing is that muting needs no second request.
    const unread: NotificationUnreadCounts = { ...counts({ mention: 2 }), total: 99 };
    expect(visibleUnreadTotal(unread, mute('mention'))).toBe(0);
  });

  test('a type missing from a short reply counts as zero', () => {
    const unread = { total: 1, by_type: { mention: 1 } } as unknown as NotificationUnreadCounts;
    expect(visibleUnreadTotal(unread, mute())).toBe(1);
  });

  test('the list drops muted rows and keeps the rest in order', () => {
    const rows = [
      { id: 'a', type: 'mention' as const },
      { id: 'b', type: 'review_requested' as const },
      { id: 'c', type: 'mention' as const },
    ];
    expect(filterMutedNotifications(rows, mute('mention')).map((entry) => entry.id)).toEqual([
      'b',
    ]);
    expect(filterMutedNotifications(rows, mute()).map((entry) => entry.id)).toEqual([
      'a',
      'b',
      'c',
    ]);
  });

  test('reports which types are muted, and when every one of them is', () => {
    expect(isNotificationMuted('mention', mute('mention'))).toBe(true);
    expect(isNotificationMuted('mention', mute())).toBe(false);
    expect(visibleNotificationTypes(mute('mention'))).not.toContain('mention');
    expect(allNotificationsMuted(mute())).toBe(false);
    expect(allNotificationsMuted(mute(...NOTIFICATION_TYPES))).toBe(true);
  });

  test('keeps the vocabulary order, so the chips never reshuffle', () => {
    expect(visibleNotificationTypes(mute('review_requested'))).toEqual([
      'mention',
      'review_decision',
      'thread_resolved',
      'version_published',
    ]);
  });
});
