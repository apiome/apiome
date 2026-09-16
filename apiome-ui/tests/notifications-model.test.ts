/**
 * The notification centre's rules (COL-3.2, #4522).
 *
 * `lib/notifications.ts` is what both surfaces — the rail bell and
 * `/ade/dashboard/notifications` — ask "what does this row say, where does it go, and which
 * run of the list is it in". None of that needs a DOM, so it is pinned here, on its own.
 *
 * Four things this suite is really protecting:
 *
 * 1. **A missing payload key degrades rather than prints `undefined`.** COL-3.1 omits a key
 *    it could not resolve, so every reader has to treat absence as normal.
 * 2. **A deleted destination has no link.** `project_id` and `version_id` are columns, and a
 *    deleted project nulls them — the row must still be readable and must not link anywhere.
 * 3. **The buckets are calendar days**, not rolling windows, and clock skew never files a
 *    brand-new notification under "Older".
 * 4. **The BFF forwards a whitelist**, so a hand-made query cannot reach apiome-rest with a
 *    parameter this repository has never heard of.
 */

import { describe, expect, test } from '@jest/globals';

import {
  EMPTY_UNREAD_COUNTS,
  NOTIFICATION_MAX_LIMIT,
  NOTIFICATION_PAGE_SIZE,
  NOTIFICATION_TYPES,
  groupNotificationsByTime,
  isNotificationType,
  notificationBucket,
  notificationContext,
  notificationExcerpt,
  notificationHref,
  notificationSentence,
  parseUnreadCounts,
  sanitizeMarkReadBody,
  sanitizeNotificationListParams,
  type NotificationRow,
  type NotificationType,
} from '../lib/notifications';

const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const VERSION_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const THREAD_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const REVIEW_ID = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';

/**
 * A notification row.
 *
 * @param overrides - What this test cares about.
 * @returns The row.
 */
function row(overrides: Partial<NotificationRow> = {}): NotificationRow {
  return {
    id: 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee',
    tenant_id: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
    user_id: '11111111-1111-4111-8111-111111111111',
    type: 'mention',
    payload: {
      project_slug: 'payments',
      project_name: 'Payments',
      version_label: '1.2.0',
      thread_id: THREAD_ID,
    },
    actor_id: '22222222-2222-4222-8222-222222222222',
    actor_name: 'Alice Anders',
    project_id: PROJECT_ID,
    version_id: VERSION_ID,
    read_at: null,
    created_at: '2026-09-15T12:00:00Z',
    ...overrides,
  };
}

describe('the type vocabulary', () => {
  test('is the five COL-3.1 writes, and nothing else passes the guard', () => {
    expect(NOTIFICATION_TYPES).toEqual([
      'mention',
      'review_requested',
      'review_decision',
      'thread_resolved',
      'version_published',
    ]);
    for (const type of NOTIFICATION_TYPES) expect(isNotificationType(type)).toBe(true);
    for (const other of ['', 'Mention', 'email', null, 7, undefined]) {
      expect(isNotificationType(other)).toBe(false);
    }
  });

  test('the empty counts name every type, so a badge is never NaN', () => {
    expect(EMPTY_UNREAD_COUNTS.total).toBe(0);
    for (const type of NOTIFICATION_TYPES) expect(EMPTY_UNREAD_COUNTS.by_type[type]).toBe(0);
  });
});

describe('parseUnreadCounts', () => {
  test('completes a short reply with zeroes rather than rejecting it', () => {
    const counts = parseUnreadCounts({ total: 3, by_type: { mention: 2, review_requested: 1 } });
    expect(counts.total).toBe(3);
    expect(counts.by_type.mention).toBe(2);
    expect(counts.by_type.version_published).toBe(0);
  });

  test('derives a missing total from the per-type tallies', () => {
    const counts = parseUnreadCounts({ by_type: { mention: 2, thread_resolved: 3 } });
    expect(counts.total).toBe(5);
  });

  test('answers zeroes for a reply that is not an object at all', () => {
    expect(parseUnreadCounts(null).total).toBe(0);
    expect(parseUnreadCounts('nope').by_type.mention).toBe(0);
    // A non-numeric count is dropped rather than propagated into the badge.
    expect(parseUnreadCounts({ total: 'many', by_type: { mention: '3' } }).total).toBe(0);
  });
});

describe('notificationSentence', () => {
  const cases: ReadonlyArray<[NotificationType, Partial<NotificationRow>, string]> = [
    ['mention', {}, 'Alice Anders mentioned you in a comment'],
    ['review_requested', {}, 'Alice Anders requested your review'],
    [
      'review_decision',
      { payload: { decision: 'approve' } },
      'Alice Anders approved your review',
    ],
    [
      'review_decision',
      { payload: { decision: 'request_changes' } },
      'Alice Anders requested changes on your review',
    ],
    ['thread_resolved', {}, 'Alice Anders resolved a thread you took part in'],
    [
      'version_published',
      { payload: { version_label: '2.0.0' } },
      'Alice Anders published 2.0.0',
    ],
  ];

  test.each(cases)('says what happened for %s', (type, overrides, expected) => {
    expect(notificationSentence(row({ type, ...overrides }))).toBe(expected);
  });

  test('names an actor who has left the tenant without printing null', () => {
    const sentence = notificationSentence(row({ actor_id: null, actor_name: null }));
    expect(sentence).toBe('Someone mentioned you in a comment');
    expect(sentence).not.toMatch(/null|undefined/);
  });

  test('degrades a decision whose vocabulary it does not know', () => {
    expect(notificationSentence(row({ type: 'review_decision', payload: {} }))).toBe(
      'Alice Anders answered your review'
    );
  });

  test('degrades a publish that resolved no version label', () => {
    expect(notificationSentence(row({ type: 'version_published', payload: {} }))).toBe(
      'Alice Anders published a version'
    );
  });
});

describe('notificationContext', () => {
  test('is the project and the version', () => {
    expect(notificationContext(row())).toBe('Payments · 1.2.0');
  });

  test('falls back to the slug when no display name resolved', () => {
    expect(
      notificationContext(row({ payload: { project_slug: 'payments', version_label: '1.2.0' } }))
    ).toBe('payments · 1.2.0');
  });

  test('says nothing at all when neither resolved', () => {
    expect(notificationContext(row({ payload: {} }))).toBe('');
  });

  test('leaves the version out of a publish, whose sentence already says it', () => {
    expect(notificationContext(row({ type: 'version_published' }))).toBe('Payments');
  });
});

describe('notificationExcerpt', () => {
  test('is a mention’s own words', () => {
    const excerpt = notificationExcerpt(
      row({ payload: { excerpt: '@bob does Customer.email need a format?' } })
    );
    expect(excerpt).toBe('@bob does Customer.email need a format?');
  });

  test('is nothing for every other type, even when one carries the key', () => {
    expect(
      notificationExcerpt(row({ type: 'thread_resolved', payload: { excerpt: 'hello' } }))
    ).toBeNull();
  });
});

describe('notificationHref', () => {
  test('sends a mention to the project’s Discussion tab with its thread', () => {
    expect(notificationHref(row())).toBe(
      `/ade/dashboard/versions?projectId=${PROJECT_ID}&tab=discussion&thread=${THREAD_ID}`
    );
  });

  test('sends a resolved thread to the same place', () => {
    expect(notificationHref(row({ type: 'thread_resolved' }))).toContain('tab=discussion');
  });

  test('still reaches the Discussion tab when the thread id did not resolve', () => {
    const href = notificationHref(row({ payload: { project_slug: 'payments' } }));
    expect(href).toBe(`/ade/dashboard/versions?projectId=${PROJECT_ID}&tab=discussion`);
    expect(href).not.toContain('thread=');
  });

  test('sends both review types to the review page', () => {
    for (const type of ['review_requested', 'review_decision'] as const) {
      expect(notificationHref(row({ type, payload: { review_id: REVIEW_ID } }))).toBe(
        `/ade/reviews/${REVIEW_ID}`
      );
    }
  });

  test('sends a publish to the project’s timeline, not its Discussion tab', () => {
    const href = notificationHref(row({ type: 'version_published' }));
    expect(href).toBe(`/ade/dashboard/versions?projectId=${PROJECT_ID}`);
    expect(href).not.toContain('tab=');
  });

  test('has no link once the destination is deleted', () => {
    // A deleted project nulls the column; the row survives and must not link anywhere.
    expect(notificationHref(row({ project_id: null }))).toBeNull();
    expect(notificationHref(row({ type: 'version_published', project_id: null }))).toBeNull();
    // A review notification without a review id is the same situation by another route.
    expect(notificationHref(row({ type: 'review_requested', payload: {} }))).toBeNull();
  });
});

describe('time buckets', () => {
  /** 2026-09-15, mid-afternoon local. */
  const now = new Date(2026, 8, 15, 15, 0, 0).getTime();

  /**
   * A local timestamp, as an ISO string.
   *
   * @param day - Day of September 2026.
   * @param hour - Local hour.
   * @returns The ISO-8601 string.
   */
  const at = (day: number, hour: number) => new Date(2026, 8, day, hour).toISOString();

  test('puts this calendar day in Today, including one minute past midnight', () => {
    expect(notificationBucket(at(15, 14), now)).toBe('today');
    expect(notificationBucket(at(15, 0), now)).toBe('today');
  });

  test('puts late last night in Yesterday, not Today', () => {
    // The whole point of calendar days: 23:50 last night is eleven hours ago and is still
    // "yesterday" to the reader.
    expect(notificationBucket(at(14, 23), now)).toBe('yesterday');
  });

  test('walks back through the week and then to Older', () => {
    expect(notificationBucket(at(13, 12), now)).toBe('earlier-week');
    expect(notificationBucket(at(9, 12), now)).toBe('earlier-week');
    expect(notificationBucket(at(8, 12), now)).toBe('older');
  });

  test('never files a future or unreadable timestamp under Older', () => {
    expect(notificationBucket(at(16, 9), now)).toBe('today');
    expect(notificationBucket('not a date', now)).toBe('today');
  });

  test('groups in bucket order, drops empty runs and keeps the given order inside one', () => {
    const rows = [
      row({ id: 'n1', created_at: at(15, 14) }),
      row({ id: 'n2', created_at: at(15, 9) }),
      row({ id: 'n3', created_at: at(8, 9) }),
    ];
    const groups = groupNotificationsByTime(rows, now);
    expect(groups.map((group) => group.bucket)).toEqual(['today', 'older']);
    expect(groups[0].label).toBe('Today');
    expect(groups[0].rows.map((entry) => entry.id)).toEqual(['n1', 'n2']);
    expect(groups[1].rows.map((entry) => entry.id)).toEqual(['n3']);
  });

  test('groups nothing into nothing', () => {
    expect(groupNotificationsByTime([], now)).toEqual([]);
  });
});

describe('sanitizeNotificationListParams', () => {
  /**
   * Run the whitelist over a query string.
   *
   * @param query - The raw query.
   * @returns The forwarded parameters, as an object.
   */
  const sanitize = (query: string) =>
    Object.fromEntries(sanitizeNotificationListParams(new URLSearchParams(query)));

  test('forwards the four parameters apiome-rest accepts', () => {
    expect(sanitize('unread=true&type=mention&limit=10&offset=20')).toEqual({
      unread: 'true',
      type: 'mention',
      limit: '10',
      offset: '20',
    });
  });

  test('drops everything else, whatever the caller calls it', () => {
    const params = sanitize('user_id=someone-else&tenant=other&sql=--&order=asc');
    expect(Object.keys(params).sort()).toEqual(['limit', 'offset']);
  });

  test('defaults and clamps the page size', () => {
    expect(sanitize('')).toMatchObject({ limit: String(NOTIFICATION_PAGE_SIZE), offset: '0' });
    expect(sanitize('limit=0')).toMatchObject({ limit: String(NOTIFICATION_PAGE_SIZE) });
    expect(sanitize('limit=nonsense')).toMatchObject({ limit: String(NOTIFICATION_PAGE_SIZE) });
    expect(sanitize(`limit=${NOTIFICATION_MAX_LIMIT + 500}`)).toMatchObject({
      limit: String(NOTIFICATION_MAX_LIMIT),
    });
  });

  test('refuses a negative or unreadable offset rather than forwarding it', () => {
    expect(sanitize('offset=-5')).toMatchObject({ offset: '0' });
    expect(sanitize('offset=x')).toMatchObject({ offset: '0' });
  });

  test('only forwards `unread` when it is actually asked for', () => {
    expect(sanitize('unread=1')).toMatchObject({ unread: 'true' });
    expect(sanitize('unread=false')).not.toHaveProperty('unread');
    expect(sanitize('unread=maybe')).not.toHaveProperty('unread');
  });

  test('drops a type it does not know', () => {
    expect(sanitize('type=email')).not.toHaveProperty('type');
  });
});

describe('sanitizeMarkReadBody', () => {
  test('takes a list of UUIDs', () => {
    expect(sanitizeMarkReadBody({ ids: [THREAD_ID, REVIEW_ID] })).toEqual({
      ids: [THREAD_ID, REVIEW_ID],
    });
  });

  test('drops anything that is not a UUID, so nothing unparseable reaches a ::uuid cast', () => {
    expect(sanitizeMarkReadBody({ ids: ['nope', 7, null, THREAD_ID] })).toEqual({
      ids: [THREAD_ID],
    });
  });

  test('takes `all`, and prefers it when a body asks for both', () => {
    expect(sanitizeMarkReadBody({ all: true })).toEqual({ all: true });
    expect(sanitizeMarkReadBody({ all: true, ids: [THREAD_ID] })).toEqual({ all: true });
  });

  test('refuses a body that names nothing markable', () => {
    for (const body of [null, undefined, 'all', 42, {}, { all: 'yes' }, { ids: [] }, { ids: 'x' }]) {
      expect(sanitizeMarkReadBody(body)).toBeNull();
    }
  });

  test('caps how many ids one call may name', () => {
    const many = Array.from({ length: NOTIFICATION_MAX_LIMIT + 50 }, () => THREAD_ID);
    const sanitized = sanitizeMarkReadBody({ ids: many });
    expect(sanitized && 'ids' in sanitized && sanitized.ids.length).toBe(NOTIFICATION_MAX_LIMIT);
  });
});
