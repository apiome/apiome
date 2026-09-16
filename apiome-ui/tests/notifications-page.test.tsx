/**
 * The notification centre page — `/ade/dashboard/notifications` (COL-3.2, #4522).
 *
 * The bell is a glance at the newest twenty; this is the whole inbox. What the suite pins
 * is the part that is only true here: the two narrowings that are *server* parameters
 * (unread only, and one type), paging through more than one page, marking a row without
 * following it, and the three empty states — nothing yet, nothing matching the filters, and
 * everything silenced — which must not be the same screen.
 */

import React from 'react';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

const mockOpenPreferences = jest.fn<boolean, [string | undefined]>(() => true);

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

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({
    data: { user: { user_id: 'u-ada', current_tenant_id: '550e8400-e29b-41d4-a716-446655440000' } },
  }),
}));

jest.mock('@/app/components/ade/preferences/preferencesDrawerBus', () => ({
  openPreferences: (tab?: string) => mockOpenPreferences(tab),
}));

import NotificationsClient from '../src/app/ade/dashboard/notifications/NotificationsClient';
import { NOTIFICATION_TYPES, type NotificationRow } from '../lib/notifications';
import { NOTIFICATION_PREFERENCE_KEYS } from '../lib/notification-preferences';

const TENANT_ID = '550e8400-e29b-41d4-a716-446655440000';
const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const THREAD_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

/** 2026-09-15, mid-afternoon local. */
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
    user_id: 'u-ada',
    type: 'mention',
    payload: {
      project_slug: 'payments',
      project_name: 'Payments',
      version_label: '1.2.0',
      thread_id: THREAD_ID,
      excerpt: 'does Customer.email need a format?',
    },
    actor_id: 'u-alice',
    actor_name: 'Alice Anders',
    project_id: PROJECT_ID,
    version_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    read_at: null,
    created_at: new Date(2026, 8, 15, 12, 0, 0).toISOString(),
    ...overrides,
  };
}

/** Per-type unread tallies with every type present. */
function byType(counts: Partial<Record<string, number>>) {
  return Object.fromEntries(NOTIFICATION_TYPES.map((type) => [type, counts[type] ?? 0]));
}

/** The whole fake inbox, in the order the endpoint would return it. */
let inbox: NotificationRow[] = [];
/** Per-type unread tallies. */
let unread: Record<string, number> = {};
/** Every mark-read body posted. */
let marked: unknown[] = [];
/** Every list query the page asked for. */
let queries: URLSearchParams[] = [];
/** Force the list read to fail. */
let listFails = false;

/**
 * One reply, shaped the way the hook reads it.
 *
 * jsdom has no WHATWG `Response`, and the hook only asks for `ok`, `status` and `json()`.
 *
 * @param body - The JSON body.
 * @param status - The HTTP status.
 * @returns The stand-in.
 */
function reply(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

/**
 * Route `fetch` at the three BFF endpoints, honouring the filters and the paging.
 *
 * @returns The jest mock.
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
      if (listFails) return reply({ success: false, error: 'Inbox unavailable' }, 503);

      const params = new URLSearchParams(url.split('?')[1] ?? '');
      queries.push(params);

      // The fake endpoint applies the filters, so a test that asserts on the screen is also
      // asserting that the page sent the right query.
      let matching = inbox;
      if (params.get('unread') === 'true') matching = matching.filter((entry) => !entry.read_at);
      const type = params.get('type');
      if (type) matching = matching.filter((entry) => entry.type === type);

      const offset = Number(params.get('offset') ?? 0);
      const limit = Number(params.get('limit') ?? 50);
      const page = matching.slice(offset, offset + limit);
      return reply({
        success: true,
        notifications: page,
        count: page.length,
        total: matching.length,
        limit,
        offset,
      });
    }

    return reply({ success: false, error: 'not routed' }, 404);
  });
  global.fetch = mock as unknown as typeof fetch;
  return mock;
}

/**
 * Mount the page and wait for its first read.
 *
 * @returns The Testing Library result.
 */
async function renderPage() {
  const result = render(<NotificationsClient now={NOW} />);
  await waitFor(() =>
    expect(screen.queryByTestId('notifications-loading')).not.toBeInTheDocument()
  );
  return result;
}

beforeEach(() => {
  jest.clearAllMocks();
  window.localStorage.clear();
  inbox = [];
  unread = {};
  marked = [];
  queries = [];
  listFails = false;
  installFetch();
});

describe('the list', () => {
  test('names the page and lists the inbox under its time buckets', async () => {
    inbox = [row('n1'), row('n2', { created_at: new Date(2026, 8, 1, 9).toISOString() })];
    await renderPage();

    expect(screen.getByRole('heading', { level: 1, name: /^Notifications/ })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Today' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Older' })).toBeInTheDocument();
    expect(screen.getByTestId('notification-n1')).toBeInTheDocument();
  });

  test('shows a mention’s own words, which the dropdown leaves out', async () => {
    inbox = [row('n1')];
    await renderPage();
    expect(screen.getByTestId('notification-n1')).toHaveTextContent(
      'does Customer.email need a format?'
    );
  });

  test('links each row at its source', async () => {
    inbox = [row('n1')];
    await renderPage();
    expect(within(screen.getByTestId('notification-n1')).getByRole('link')).toHaveAttribute(
      'href',
      `/ade/dashboard/versions?projectId=${PROJECT_ID}&tab=discussion&thread=${THREAD_ID}`
    );
  });

  test('keeps a row whose project has been deleted, without a link', async () => {
    inbox = [row('n1', { project_id: null })];
    await renderPage();
    const entry = screen.getByTestId('notification-n1');
    expect(entry).toHaveTextContent('Alice Anders mentioned you');
    expect(within(entry).queryByRole('link')).not.toBeInTheDocument();
  });

  test('says what went wrong, with a way to try again', async () => {
    listFails = true;
    await renderPage();
    const alert = await screen.findByTestId('notifications-error');
    expect(alert).toHaveTextContent('Inbox unavailable');
    expect(within(alert).getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});

describe('the filters', () => {
  test('narrows to unread, and says how many that is', async () => {
    const user = userEvent.setup();
    unread = { mention: 1 };
    inbox = [row('n1'), row('n2', { read_at: '2026-09-15T13:00:00Z' })];
    await renderPage();

    expect(screen.getByTestId('notification-n2')).toBeInTheDocument();
    expect(screen.getByTestId('notifications-filter-unread')).toHaveTextContent('1');

    await user.click(screen.getByTestId('notifications-filter-unread'));

    await waitFor(() =>
      expect(screen.queryByTestId('notification-n2')).not.toBeInTheDocument()
    );
    expect(screen.getByTestId('notification-n1')).toBeInTheDocument();
    expect(queries.at(-1)?.get('unread')).toBe('true');
  });

  test('narrows to one type, and back again', async () => {
    const user = userEvent.setup();
    inbox = [row('n1'), row('n2', { type: 'version_published' })];
    await renderPage();

    await user.click(screen.getByTestId('notifications-filter-version_published'));
    await waitFor(() => expect(queries.at(-1)?.get('type')).toBe('version_published'));
    await waitFor(() =>
      expect(screen.queryByTestId('notification-n1')).not.toBeInTheDocument()
    );

    // The same chip again is "stop narrowing", and so is "All types".
    await user.click(screen.getByTestId('notifications-filter-version_published'));
    await waitFor(() => expect(queries.at(-1)?.get('type')).toBeNull());
    expect(await screen.findByTestId('notification-n1')).toBeInTheDocument();
  });

  test('offers a chip only for a type the reader has left switched on', async () => {
    window.localStorage.setItem(NOTIFICATION_PREFERENCE_KEYS.mention, 'off');
    await renderPage();

    expect(screen.queryByTestId('notifications-filter-mention')).not.toBeInTheDocument();
    expect(screen.getByTestId('notifications-filter-review_requested')).toBeInTheDocument();
    expect(screen.getByTestId('notifications-muted-note')).toHaveTextContent(
      'One notification type is switched off'
    );
  });

  test('drops a type filter the reader has just muted', async () => {
    const user = userEvent.setup();
    inbox = [row('n1')];
    await renderPage();

    await user.click(screen.getByTestId('notifications-filter-mention'));
    await waitFor(() => expect(queries.at(-1)?.get('type')).toBe('mention'));

    await act(async () => {
      window.localStorage.setItem(NOTIFICATION_PREFERENCE_KEYS.mention, 'off');
      window.dispatchEvent(new Event('hive:notification-preferences'));
    });

    // Otherwise the page would filter to a type it also hides, and answer every question
    // with "nothing here".
    await waitFor(() => expect(queries.at(-1)?.get('type')).toBeNull());
  });

  test('sends the reader to the tab that changes what they see', async () => {
    const user = userEvent.setup();
    window.localStorage.setItem(NOTIFICATION_PREFERENCE_KEYS.mention, 'off');
    await renderPage();

    await user.click(
      within(screen.getByTestId('notifications-muted-note')).getByRole('button')
    );
    expect(mockOpenPreferences).toHaveBeenCalledWith('notifications');
  });
});

describe('paging', () => {
  test('reads the next page and appends it', async () => {
    const user = userEvent.setup();
    inbox = Array.from({ length: 60 }, (_, index) => row(`n${index}`));
    await renderPage();

    expect(screen.getByTestId('notification-n0')).toBeInTheDocument();
    expect(screen.queryByTestId('notification-n50')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('notifications-load-more'));

    expect(await screen.findByTestId('notification-n50')).toBeInTheDocument();
    // Still there: a page is appended, never swapped.
    expect(screen.getByTestId('notification-n0')).toBeInTheDocument();
    expect(queries.at(-1)?.get('offset')).toBe('50');
  });

  test('offers no more when there is no more', async () => {
    inbox = [row('n1')];
    await renderPage();
    expect(screen.queryByTestId('notifications-load-more')).not.toBeInTheDocument();
  });
});

describe('marking', () => {
  test('marks a row without following it', async () => {
    const user = userEvent.setup();
    unread = { mention: 1 };
    inbox = [row('n1')];
    await renderPage();

    await user.click(screen.getByTestId('notification-mark-n1'));

    await waitFor(() => expect(marked).toEqual([{ ids: ['n1'] }]));
    // The row dims rather than leaving: it is still the answer to "what happened".
    await waitFor(() =>
      expect(screen.getByTestId('notification-n1')).not.toHaveAttribute('data-unread')
    );
    expect(screen.queryByTestId('notification-mark-n1')).not.toBeInTheDocument();
  });

  test('marks the whole inbox, and the button goes quiet', async () => {
    const user = userEvent.setup();
    unread = { mention: 2 };
    inbox = [row('n1'), row('n2')];
    await renderPage();

    const button = screen.getByTestId('notifications-mark-all');
    expect(button).toBeEnabled();
    await user.click(button);

    await waitFor(() => expect(marked).toEqual([{ all: true }]));
    await waitFor(() => expect(screen.getByTestId('notifications-mark-all')).toBeDisabled());
    expect(screen.getByTestId('notification-n1')).not.toHaveAttribute('data-unread');
  });

  test('following a row marks it read', async () => {
    const user = userEvent.setup();
    unread = { mention: 1 };
    inbox = [row('n1')];
    await renderPage();

    await user.click(within(screen.getByTestId('notification-n1')).getByRole('link'));
    await waitFor(() => expect(marked).toEqual([{ ids: ['n1'] }]));
  });
});

describe('the empty states', () => {
  test('an inbox with nothing in it yet', async () => {
    await renderPage();
    const empty = screen.getByTestId('notifications-empty');
    expect(empty).toHaveTextContent('Nothing yet');
    expect(empty).toHaveTextContent('Mentions, review requests');
  });

  test('a filter that matches nothing says so, rather than claiming the inbox is empty', async () => {
    const user = userEvent.setup();
    inbox = [row('n1', { read_at: '2026-09-15T13:00:00Z' })];
    await renderPage();

    await user.click(screen.getByTestId('notifications-filter-unread'));
    expect(await screen.findByTestId('notifications-empty')).toHaveTextContent(
      'Nothing matches these filters'
    );
  });

  test('an inbox the reader has silenced says that, and offers the way back', async () => {
    const user = userEvent.setup();
    for (const type of NOTIFICATION_TYPES) {
      window.localStorage.setItem(NOTIFICATION_PREFERENCE_KEYS[type], 'off');
    }
    inbox = [row('n1')];
    await renderPage();

    const empty = screen.getByTestId('notifications-empty');
    expect(empty).toHaveTextContent('Every notification type is switched off');
    expect(empty).toHaveTextContent('nothing was discarded');

    await user.click(
      within(empty).getByRole('button', { name: /Open notification preferences/ })
    );
    expect(mockOpenPreferences).toHaveBeenCalledWith('notifications');
  });
});
