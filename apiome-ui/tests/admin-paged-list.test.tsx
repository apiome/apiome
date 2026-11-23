/**
 * Paging of the admin console's lists (DBP-1.13, #7196).
 *
 * `useAdminPagedList` holds what a paged admin action has returned so far; `AdminLoadMore` is the
 * control under a list that asks for the next page. The Users screen is mounted at the end to pin
 * the whole loop: the first page, a search applied by the server, and "Load more" appending.
 */

import '@testing-library/jest-dom';
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';

import {
  ADMIN_SEARCH_DEBOUNCE_MS,
  AdminLoadMore,
  useAdminPagedList,
  useSettledChange,
} from '../src/app/admin/dashboard/components/adminPagedList';

const mockGetAllUsersWithLicenses = jest.fn();
jest.mock('../lib/db/admin-actions', () => ({
  getAllUsersWithLicenses: (...args: unknown[]) => mockGetAllUsersWithLicenses(...args),
  getUserStats: jest.fn(async () =>
    JSON.stringify({
      success: true,
      stats: { total_users: 120, enabled_users: 118, verified_users: 100 },
    }),
  ),
  getAllLicenses: jest.fn(async () => JSON.stringify({ success: true, licenses: [] })),
  createUser: jest.fn(),
  updateUser: jest.fn(),
  deleteUser: jest.fn(),
  assignLicenseToUser: jest.fn(),
  removeUserLicense: jest.fn(),
  getAllFeatureFlags: jest.fn(),
  getAllFeatureFlagGroups: jest.fn(),
  getUserLicense: jest.fn(),
  setUserFeatureFlag: jest.fn(),
  removeUserFeatureFlag: jest.fn(),
}));

jest.mock('@/app/components/providers/DialogProvider', () => ({
  useDialog: () => ({ confirm: jest.fn(async () => true) }),
}));

import UserManagementClient from '../src/app/admin/dashboard/users/UserManagementClient';

interface Row {
  id: string;
  name: string;
}

/** A page response as the admin actions return it. */
const page = (rows: Row[], nextCursor: string | null = null, extra: Record<string, unknown> = {}) =>
  JSON.stringify({
    success: true,
    users: rows,
    hasMore: nextCursor !== null,
    nextCursor,
    ...extra,
  });

/** A read whose answer the test releases by hand. */
function deferred(): { promise: Promise<string>; resolve: (value: string) => void } {
  let resolve!: (value: string) => void;
  const promise = new Promise<string>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

afterEach(() => {
  jest.useRealTimers();
});

describe('useAdminPagedList', () => {
  it('reads the first page, then appends the page after its cursor', async () => {
    const read = jest
      .fn<Promise<string>, [{ cursor: string | null }]>()
      .mockResolvedValueOnce(page([{ id: 'a', name: 'A' }], 'c1', { totals: { n: 3 } }))
      .mockResolvedValueOnce(page([{ id: 'b', name: 'B' }], 'c2'))
      .mockResolvedValueOnce(page([{ id: 'c', name: 'C' }]));
    const { result } = renderHook(() =>
      useAdminPagedList<Row, { totals?: { n: number } }>(read, 'users'),
    );

    await act(async () => {
      expect(await result.current.reload()).toBe(true);
    });
    expect(result.current.items).toEqual([{ id: 'a', name: 'A' }]);
    expect(result.current.hasMore).toBe(true);
    expect(result.current.extra?.totals).toEqual({ n: 3 });

    await act(async () => {
      await result.current.loadMore();
    });
    await act(async () => {
      await result.current.loadMore();
    });

    expect(read.mock.calls.map(([request]) => request.cursor)).toEqual([null, 'c1', 'c2']);
    expect(result.current.items.map((row) => row.id)).toEqual(['a', 'b', 'c']);
    expect(result.current.hasMore).toBe(false);
    // The totals are the first page's; a later page does not replace them.
    expect(result.current.extra?.totals).toEqual({ n: 3 });

    // Nothing further to read: no call is made.
    await act(async () => {
      await result.current.loadMore();
    });
    expect(read).toHaveBeenCalledTimes(3);
  });

  it('maps each row as it arrives', async () => {
    const read = jest.fn(async () => page([{ id: 'a', name: 'a' }]));
    const { result } = renderHook(() =>
      useAdminPagedList<Row>(read, 'users', (row) => ({ ...row, name: row.name.toUpperCase() })),
    );
    await act(async () => {
      await result.current.reload();
    });
    expect(result.current.items).toEqual([{ id: 'a', name: 'A' }]);
  });

  it('keeps what is loaded when a read is refused', async () => {
    const read = jest
      .fn<Promise<string>, [{ cursor: string | null }]>()
      .mockResolvedValueOnce(page([{ id: 'a', name: 'A' }], 'c1'))
      .mockResolvedValueOnce(JSON.stringify({ success: false, error: 'Unauthorized' }))
      .mockResolvedValueOnce(JSON.stringify({ success: false, error: 'Invalid cursor' }));
    const { result } = renderHook(() => useAdminPagedList<Row>(read, 'users'));

    await act(async () => {
      await result.current.reload();
    });
    await act(async () => {
      expect(await result.current.reload()).toBe(false);
    });
    await act(async () => {
      await result.current.loadMore();
    });

    expect(result.current.items).toEqual([{ id: 'a', name: 'A' }]);
    expect(result.current.hasMore).toBe(true);
    expect(result.current.loadingMore).toBe(false);
  });

  it('drops an answer that arrives after a newer read was started', async () => {
    const slow = deferred();
    const read = jest
      .fn<Promise<string>, [{ cursor: string | null }]>()
      .mockReturnValueOnce(slow.promise)
      .mockResolvedValueOnce(page([{ id: 'new', name: 'Newer search' }]));
    const { result } = renderHook(() => useAdminPagedList<Row>(read, 'users'));

    let first!: Promise<boolean>;
    act(() => {
      first = result.current.reload();
    });
    await act(async () => {
      await result.current.reload();
    });
    await act(async () => {
      slow.resolve(page([{ id: 'old', name: 'Older search' }], 'stale'));
      await first;
    });

    expect(result.current.items).toEqual([{ id: 'new', name: 'Newer search' }]);
    expect(result.current.hasMore).toBe(false);
  });

  it('drops a "load more" answered after the list was read again', async () => {
    const slow = deferred();
    const read = jest
      .fn<Promise<string>, [{ cursor: string | null }]>()
      .mockResolvedValueOnce(page([{ id: 'a', name: 'A' }], 'c1'))
      .mockReturnValueOnce(slow.promise)
      .mockResolvedValueOnce(page([{ id: 'z', name: 'Z' }]));
    const { result } = renderHook(() => useAdminPagedList<Row>(read, 'users'));

    await act(async () => {
      await result.current.reload();
    });
    let more!: Promise<void>;
    act(() => {
      more = result.current.loadMore();
    });
    await act(async () => {
      await result.current.reload();
    });
    await act(async () => {
      slow.resolve(page([{ id: 'b', name: 'B' }], 'c2'));
      await more;
    });

    expect(result.current.items).toEqual([{ id: 'z', name: 'Z' }]);
  });

  it('clear forgets the rows and the cursor', async () => {
    const read = jest.fn(async () => page([{ id: 'a', name: 'A' }], 'c1'));
    const { result } = renderHook(() => useAdminPagedList<Row>(read, 'users'));
    await act(async () => {
      await result.current.reload();
    });
    act(() => result.current.clear());

    expect(result.current.items).toEqual([]);
    expect(result.current.hasMore).toBe(false);
    await act(async () => {
      await result.current.loadMore();
    });
    expect(read).toHaveBeenCalledTimes(1);
  });
});

describe('useSettledChange', () => {
  it('runs once the value has stopped changing, and not for the first render', () => {
    jest.useFakeTimers();
    const effect = jest.fn();
    const { rerender } = renderHook(({ value }) => useSettledChange(value, effect), {
      initialProps: { value: '' },
    });

    act(() => {
      jest.advanceTimersByTime(ADMIN_SEARCH_DEBOUNCE_MS * 2);
    });
    expect(effect).not.toHaveBeenCalled();

    rerender({ value: 'a' });
    rerender({ value: 'ad' });
    rerender({ value: 'ada' });
    act(() => {
      jest.advanceTimersByTime(ADMIN_SEARCH_DEBOUNCE_MS - 1);
    });
    expect(effect).not.toHaveBeenCalled();
    act(() => {
      jest.advanceTimersByTime(1);
    });
    expect(effect).toHaveBeenCalledTimes(1);
  });
});

describe('AdminLoadMore', () => {
  const list = (overrides: Partial<Parameters<typeof AdminLoadMore>[0]['list']> = {}) => ({
    items: [{}, {}, {}],
    hasMore: true,
    loadingMore: false,
    loadMore: jest.fn(async () => undefined),
    ...overrides,
  });

  it('draws nothing once everything is loaded', () => {
    const { container } = render(
      <AdminLoadMore list={list({ hasMore: false })} noun="users" testId="more" />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('says how many rows are loaded and reads the next page on click', () => {
    const state = list();
    render(<AdminLoadMore list={state} noun="users" testId="more" />);

    expect(screen.getByTestId('more')).toHaveTextContent('Showing the first 3 users');
    fireEvent.click(screen.getByRole('button', { name: 'Load more' }));
    expect(state.loadMore).toHaveBeenCalledTimes(1);
  });

  it('is disabled while a page is being read', () => {
    render(<AdminLoadMore list={list({ loadingMore: true })} noun="users" testId="more" />);
    expect(screen.getByTestId('more-button')).toBeDisabled();
    expect(screen.getByTestId('more-button')).toHaveTextContent('Loading…');
  });
});

describe('the Users screen pages and searches on the server', () => {
  const user = (index: number) => ({
    id: `u-${index}`,
    name: `User ${index}`,
    email: `user${index}@example.com`,
    enabled: true,
    verified: true,
    suite_access: false,
    created_at: '2026-10-25T10:00:00.000Z',
    last_active_at: null,
    two_factor_enabled: false,
    license_id: null,
    license_name: null,
    license_type: null,
  });

  beforeEach(() => {
    mockGetAllUsersWithLicenses.mockReset();
  });

  it('shows the first page, appends the next, and sends the search to the server', async () => {
    mockGetAllUsersWithLicenses
      .mockResolvedValueOnce(page([user(1), user(2)], 'cursor-2'))
      .mockResolvedValueOnce(page([user(3)]))
      .mockResolvedValue(page([user(2)]));

    render(<UserManagementClient />);

    expect(await screen.findByText('User 1')).toBeInTheDocument();
    expect(mockGetAllUsersWithLicenses).toHaveBeenNthCalledWith(1, { cursor: null, search: '' });
    expect(screen.getByTestId('admin-users-load-more')).toHaveTextContent(
      'Showing the first 2 users',
    );

    await act(async () => {
      fireEvent.click(screen.getByTestId('admin-users-load-more-button'));
    });
    expect(await screen.findByText('User 3')).toBeInTheDocument();
    expect(mockGetAllUsersWithLicenses).toHaveBeenNthCalledWith(2, {
      cursor: 'cursor-2',
      search: '',
    });
    expect(screen.queryByTestId('admin-users-load-more')).not.toBeInTheDocument();

    fireEvent.change(screen.getByTestId('admin-users-search'), { target: { value: 'user 2' } });
    await waitFor(() =>
      expect(mockGetAllUsersWithLicenses).toHaveBeenNthCalledWith(3, {
        cursor: null,
        search: 'user 2',
      }),
    );
    await waitFor(() => expect(screen.queryByText('User 1')).not.toBeInTheDocument());
    expect(screen.getByText('User 2')).toBeInTheDocument();
  });

  it('says a search matched nothing, rather than that there are no users', async () => {
    mockGetAllUsersWithLicenses.mockResolvedValueOnce(page([user(1)])).mockResolvedValue(page([]));

    render(<UserManagementClient />);
    expect(await screen.findByText('User 1')).toBeInTheDocument();

    fireEvent.change(screen.getByTestId('admin-users-search'), { target: { value: 'nobody' } });
    expect(await screen.findByText('No matching users')).toBeInTheDocument();
  });
});
