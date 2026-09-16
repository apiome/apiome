/**
 * The rail footer's notification bell (COL-3.2, #4522).
 *
 * COL-3.1 writes the inbox; this is the first surface that reads it, so the suite starts
 * with the ticket's own acceptance criteria:
 *
 * - **the badge matches the inbox**, and **mark-all-read clears it**;
 * - **a deep link lands on the right thread, review or version**;
 * - **per-type preferences are honoured** — a muted type leaves the badge *and* the list,
 *   and nothing is discarded by muting it.
 *
 * On top of those, the three behaviours the rail's other two menus already promise and this
 * one inherits from `railMenu.tsx`: arrow keys walk the rows, `Esc` returns to the trigger,
 * and a collapsed rail keeps the count reachable when the label is gone.
 */

import React from 'react';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockOpenPreferences = jest.fn<boolean, [string | undefined]>(() => true);

// A real anchor, so the rows keep their link semantics for axe and for the `href`
// assertions — but with the navigation suppressed, which jsdom answers with a
// "Not implemented" console error rather than by navigating.
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({
    href,
    children,
    onClick,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
    onClick?: (event: React.MouseEvent<HTMLAnchorElement>) => void;
  }) => (
    <a
      href={href}
      onClick={(event) => {
        event.preventDefault();
        onClick?.(event);
      }}
      {...rest}
    >
      {children}
    </a>
  ),
}));

jest.mock('@/app/components/ade/preferences/preferencesDrawerBus', () => ({
  openPreferences: (tab?: string) => mockOpenPreferences(tab),
}));

import NotificationsMenu from '../src/app/components/shell/NotificationsMenu';
import { TooltipProvider } from '../src/app/components/ui/Tooltip';
import { NOTIFICATION_TYPES, type NotificationRow } from '../lib/notifications';
import { NOTIFICATION_PREFERENCE_KEYS } from '../lib/notification-preferences';

const TENANT_ID = '550e8400-e29b-41d4-a716-446655440000';
const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const THREAD_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const REVIEW_ID = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';

/** 2026-09-15, mid-afternoon local — the reference time every test pins. */
const NOW = new Date(2026, 8, 15, 15, 0, 0).getTime();

/**
 * A notification row.
 *
 * @param id - Its id.
 * @param overrides - What this test cares about.
 * @returns The row.
 */
function row(id: string, overrides: Partial<NotificationRow> = {}): NotificationRow {
  return {
    id,
    tenant_id: TENANT_ID,
    user_id: '11111111-1111-4111-8111-111111111111',
    type: 'mention',
    payload: {
      project_slug: 'payments',
      project_name: 'Payments',
      version_label: '1.2.0',
      thread_id: THREAD_ID,
      excerpt: 'does Customer.email need a format?',
    },
    actor_id: '22222222-2222-4222-8222-222222222222',
    actor_name: 'Alice Anders',
    project_id: PROJECT_ID,
    version_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    read_at: null,
    created_at: new Date(2026, 8, 15, 12, 0, 0).toISOString(),
    ...overrides,
  };
}

/** Per-type unread tallies with every type present, as the endpoint reports them. */
function byType(counts: Partial<Record<string, number>>) {
  return Object.fromEntries(NOTIFICATION_TYPES.map((type) => [type, counts[type] ?? 0]));
}

/** What the fake endpoints are currently holding. */
let inbox: NotificationRow[] = [];
/** How many the read route says are unread, per type. */
let unread: Record<string, number> = {};
/** Every mark-read body the component posted. */
let marked: unknown[] = [];
/** Force the list read to fail. */
let listFails = false;

/**
 * One reply, shaped the way the hook reads it.
 *
 * A plain object rather than a `Response`: jsdom has no WHATWG `Response` constructor, and
 * the hook only ever asks a reply for `ok`, `status` and `json()`.
 *
 * @param body - The JSON body.
 * @param status - The HTTP status.
 * @returns The stand-in.
 */
function reply(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

/**
 * Route `fetch` at the three BFF endpoints, as the browser would reach them.
 *
 * @returns The jest mock, for call assertions.
 */
function installFetch() {
  const mock = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : String(input);

    if (url.startsWith('/api/notifications/unread-count')) {
      const total = Object.values(unread).reduce((sum, value) => sum + value, 0);
      return reply({ success: true, unread: { total, by_type: byType(unread) } });
    }

    if (url.startsWith('/api/notifications/read')) {
      marked.push(JSON.parse(String(init?.body)));
      unread = {};
      return reply({ success: true, marked: 1, unread: { total: 0, by_type: byType({}) } });
    }

    if (url.startsWith('/api/notifications')) {
      if (listFails) {
        return reply({ success: false, error: 'Inbox unavailable' }, 503);
      }
      return reply({
        success: true,
        notifications: inbox,
        count: inbox.length,
        total: inbox.length,
        limit: 20,
        offset: 0,
      });
    }

    return reply({ success: false, error: 'not routed' }, 404);
  });
  global.fetch = mock as unknown as typeof fetch;
  return mock;
}

/**
 * Mount the bell.
 *
 * @param props - Overrides; `iconRail` for the collapsed rail.
 * @returns The Testing Library result.
 */
function renderBell(props: Partial<React.ComponentProps<typeof NotificationsMenu>> = {}) {
  return render(
    <TooltipProvider>
      <NotificationsMenu currentTenantId={TENANT_ID} iconRail={false} now={NOW} {...props} />
    </TooltipProvider>
  );
}

/**
 * Open the dropdown and wait for its rows.
 *
 * @param user - The userEvent session.
 */
async function openMenu(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId('rail-notifications'));
  await screen.findByTestId('notifications-menu');
}

beforeEach(() => {
  jest.clearAllMocks();
  window.localStorage.clear();
  inbox = [];
  unread = {};
  marked = [];
  listFails = false;
  installFetch();
});

describe('the badge', () => {
  test('counts what the inbox says is unread', async () => {
    unread = { mention: 2, review_requested: 1 };
    renderBell();
    const badge = await screen.findByTestId('rail-notifications-badge');
    expect(badge).toHaveTextContent('3');
  });

  test('says the count in words as well as in colour', async () => {
    unread = { mention: 1 };
    renderBell();
    await screen.findByTestId('rail-notifications-badge');
    expect(screen.getByTestId('rail-notifications')).toHaveAccessibleName(
      /1 unread notification$/
    );
  });

  test('draws nothing at all at zero', async () => {
    renderBell();
    await waitFor(() =>
      expect(screen.getByTestId('rail-notifications')).toHaveAccessibleName(
        /no unread notifications/
      )
    );
    expect(screen.queryByTestId('rail-notifications-badge')).not.toBeInTheDocument();
    expect(screen.queryByTestId('rail-notifications-dot')).not.toBeInTheDocument();
  });

  test('stops counting past ninety-nine rather than widening the rail', async () => {
    unread = { mention: 240 };
    renderBell();
    expect(await screen.findByTestId('rail-notifications-badge')).toHaveTextContent('99+');
    // The exact number is still available to a reader who cannot see the badge.
    expect(screen.getByTestId('rail-notifications')).toHaveAccessibleName(/240 unread/);
  });

  test('keeps a dot on the glyph, which the collapsed rail cannot take away', async () => {
    unread = { mention: 1 };
    renderBell({ iconRail: true });
    expect(await screen.findByTestId('rail-notifications-dot')).toBeInTheDocument();
  });

  test('reads nothing without a workspace', async () => {
    const fetchMock = installFetch();
    renderBell({ currentTenantId: null });
    await waitFor(() => expect(screen.getByTestId('rail-notifications')).toBeInTheDocument());
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test('reads only the count while the menu is shut', async () => {
    const fetchMock = installFetch();
    unread = { mention: 1 };
    renderBell();
    await screen.findByTestId('rail-notifications-badge');
    const urls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(urls.some((url) => url.startsWith('/api/notifications/unread-count'))).toBe(true);
    expect(urls.some((url) => /^\/api\/notifications\?/.test(url))).toBe(false);
  });
});

describe('the dropdown', () => {
  test('lists the inbox under time-bucket headings', async () => {
    const user = userEvent.setup();
    unread = { mention: 2 };
    inbox = [
      row('n1'),
      row('n2', { created_at: new Date(2026, 8, 14, 23, 0, 0).toISOString() }),
      row('n3', { created_at: new Date(2026, 8, 1, 9, 0, 0).toISOString() }),
    ];
    renderBell();
    await openMenu(user);

    await screen.findByTestId('notification-n1');
    expect(screen.getByRole('group', { name: 'Today' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Yesterday' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Older' })).toBeInTheDocument();
    expect(screen.queryByRole('group', { name: 'Earlier this week' })).not.toBeInTheDocument();
  });

  test('says who did what, and where', async () => {
    const user = userEvent.setup();
    inbox = [row('n1')];
    renderBell();
    await openMenu(user);

    const entry = await screen.findByTestId('notification-n1');
    expect(entry).toHaveTextContent('Alice Anders mentioned you in a comment');
    expect(entry).toHaveTextContent('Payments · 1.2.0');
    // The dropdown is a glance: the excerpt belongs to the full page.
    expect(entry).not.toHaveTextContent('does Customer.email need a format?');
  });

  test('says so when there is nothing yet', async () => {
    const user = userEvent.setup();
    renderBell();
    await openMenu(user);
    expect(await screen.findByTestId('notifications-empty')).toBeInTheDocument();
  });

  test('says what went wrong without shouting about it', async () => {
    const user = userEvent.setup();
    listFails = true;
    renderBell();
    await openMenu(user);
    expect(await screen.findByTestId('notifications-error')).toHaveTextContent(
      'Inbox unavailable'
    );
    // A failed read is a line of text, never a banner with a role that interrupts.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('deep links', () => {
  test('a mention lands on its thread', async () => {
    const user = userEvent.setup();
    inbox = [row('n1')];
    renderBell();
    await openMenu(user);
    expect(await screen.findByTestId('notification-n1')).toHaveAttribute(
      'href',
      `/ade/dashboard/versions?projectId=${PROJECT_ID}&tab=discussion&thread=${THREAD_ID}`
    );
  });

  test('a review request lands on the review page', async () => {
    const user = userEvent.setup();
    inbox = [
      row('n1', { type: 'review_requested', payload: { review_id: REVIEW_ID, round: 1 } }),
    ];
    renderBell();
    await openMenu(user);
    expect(await screen.findByTestId('notification-n1')).toHaveAttribute(
      'href',
      `/ade/reviews/${REVIEW_ID}`
    );
  });

  test('a publish lands on the version’s project', async () => {
    const user = userEvent.setup();
    inbox = [row('n1', { type: 'version_published' })];
    renderBell();
    await openMenu(user);
    expect(await screen.findByTestId('notification-n1')).toHaveAttribute(
      'href',
      `/ade/dashboard/versions?projectId=${PROJECT_ID}`
    );
  });

  test('a notification whose project is gone is still readable, and links nowhere', async () => {
    const user = userEvent.setup();
    inbox = [row('n1', { project_id: null })];
    renderBell();
    await openMenu(user);
    const entry = await screen.findByTestId('notification-n1');
    expect(entry).toHaveTextContent('Alice Anders mentioned you');
    expect(entry).not.toHaveAttribute('href');
  });

  test('following a notification marks it read and puts the menu away', async () => {
    const user = userEvent.setup();
    unread = { mention: 1 };
    inbox = [row('n1')];
    renderBell();
    await openMenu(user);

    await user.click(await screen.findByTestId('notification-n1'));
    await waitFor(() => expect(marked).toEqual([{ ids: ['n1'] }]));
    expect(screen.queryByTestId('notifications-menu')).not.toBeInTheDocument();
  });
});

describe('mark all read', () => {
  test('clears the badge, and leaves the list on screen', async () => {
    const user = userEvent.setup();
    unread = { mention: 2 };
    inbox = [row('n1'), row('n2')];
    renderBell();
    await openMenu(user);
    await screen.findByTestId('notification-n1');

    await user.click(screen.getByTestId('notifications-mark-all'));

    await waitFor(() =>
      expect(screen.queryByTestId('rail-notifications-badge')).not.toBeInTheDocument()
    );
    expect(marked).toEqual([{ all: true }]);
    // The reader is looking at the list; acknowledging it must not hide it.
    expect(screen.getByTestId('notification-n1')).toBeInTheDocument();
    expect(screen.queryAllByTestId('notification-unread-dot')).toHaveLength(0);
  });

  test('is offered but inert when there is nothing unread', async () => {
    const user = userEvent.setup();
    inbox = [row('n1', { read_at: '2026-09-15T13:00:00Z' })];
    renderBell();
    await openMenu(user);

    const button = screen.getByTestId('notifications-mark-all');
    // `aria-disabled`, not `disabled`: a row nobody can reach is a row nobody can be told
    // the reason for — the rule `railMenu.tsx` states for every unavailable item.
    expect(button).toHaveAttribute('aria-disabled', 'true');
    expect(button).not.toBeDisabled();
    await user.click(button);
    expect(marked).toEqual([]);
  });
});

describe('per-type preferences', () => {
  test('a muted type leaves the badge', async () => {
    window.localStorage.setItem(NOTIFICATION_PREFERENCE_KEYS.mention, 'off');
    unread = { mention: 5, review_requested: 2 };
    renderBell();
    expect(await screen.findByTestId('rail-notifications-badge')).toHaveTextContent('2');
  });

  test('a muted type leaves the list, and the rest stay', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(NOTIFICATION_PREFERENCE_KEYS.mention, 'off');
    inbox = [
      row('n1'),
      row('n2', { type: 'review_requested', payload: { review_id: REVIEW_ID } }),
    ];
    renderBell();
    await openMenu(user);

    await screen.findByTestId('notification-n2');
    expect(screen.queryByTestId('notification-n1')).not.toBeInTheDocument();
  });

  test('says so, and offers the way back, when every type is off', async () => {
    const user = userEvent.setup();
    for (const type of NOTIFICATION_TYPES) {
      window.localStorage.setItem(NOTIFICATION_PREFERENCE_KEYS[type], 'off');
    }
    inbox = [row('n1')];
    renderBell();
    await openMenu(user);

    const note = await screen.findByTestId('notifications-muted');
    expect(note).toHaveTextContent('Every notification type is switched off');
    await user.click(within(note).getByRole('button', { name: 'Turn some back on' }));
    expect(mockOpenPreferences).toHaveBeenCalledWith('notifications');
  });

  test('turning a type back on brings its history back, with no new request', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(NOTIFICATION_PREFERENCE_KEYS.mention, 'off');
    inbox = [row('n1')];
    renderBell();
    await openMenu(user);
    expect(screen.queryByTestId('notification-n1')).not.toBeInTheDocument();

    const fetchMock = global.fetch as unknown as jest.Mock;
    const before = fetchMock.mock.calls.length;
    await act(async () => {
      window.localStorage.setItem(NOTIFICATION_PREFERENCE_KEYS.mention, 'on');
      window.dispatchEvent(new Event('hive:notification-preferences'));
    });

    expect(await screen.findByTestId('notification-n1')).toBeInTheDocument();
    expect(fetchMock.mock.calls.length).toBe(before);
  });
});

describe('the keyboard, and everyone else', () => {
  test('opens onto the first row and closes back onto the trigger', async () => {
    const user = userEvent.setup();
    inbox = [row('n1')];
    renderBell();

    const trigger = screen.getByTestId('rail-notifications');
    trigger.focus();
    await user.keyboard('{ArrowDown}');

    await screen.findByTestId('notifications-menu');
    await waitFor(() =>
      expect(screen.getByTestId('notifications-mark-all')).toHaveFocus()
    );

    await user.keyboard('{Escape}');
    expect(screen.queryByTestId('notifications-menu')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  test('walks the rows with the arrow keys', async () => {
    const user = userEvent.setup();
    inbox = [row('n1'), row('n2')];
    renderBell();
    await openMenu(user);
    await screen.findByTestId('notification-n2');

    // From "Mark all read" down through the two notifications to "See all".
    await user.keyboard('{ArrowDown}');
    expect(screen.getByTestId('notification-n1')).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByTestId('notification-n2')).toHaveFocus();
    await user.keyboard('{ArrowDown}');
    expect(screen.getByTestId('notifications-see-all')).toHaveFocus();
    // And wraps back to the top.
    await user.keyboard('{ArrowDown}');
    expect(screen.getByTestId('notifications-mark-all')).toHaveFocus();
  });

  test('offers the whole inbox at the end of the glance', async () => {
    const user = userEvent.setup();
    inbox = [row('n1')];
    renderBell();
    await openMenu(user);
    expect(screen.getByTestId('notifications-see-all')).toHaveAttribute(
      'href',
      '/ade/dashboard/notifications'
    );
  });

  test('has no axe violations with rows on screen', async () => {
    const user = userEvent.setup();
    unread = { mention: 1 };
    inbox = [row('n1'), row('n2', { type: 'version_published' })];
    const { container } = renderBell();
    await openMenu(user);
    await screen.findByTestId('notification-n1');

    expect(await axe(container)).toHaveNoViolations();
  });
});
