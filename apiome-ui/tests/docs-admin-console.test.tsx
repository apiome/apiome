/**
 * The documentation site's admin console pages (DOCS-1.10, #5627) — sign-in, Overview and Users.
 *
 * The admin console sits behind its own password session and reads the database through server
 * actions, so the docs screenshots (`apiome-docs/screens.json`, tagged `legacy`) are captured
 * from these jsdom dumps rather than from the golden-path stack:
 *
 *     A11Y_FIXTURE_DUMP=1 npx jest tests/docs-admin-console.test.tsx
 *
 * Without the variable the suite still renders every screen and checks what it shows, so a
 * change that would leave a page or a fixture stale fails here first.
 */
import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import AdminLoginClient from '../src/app/admin/AdminLoginClient';
import AdminSidebar from '../src/app/admin/dashboard/AdminSidebar';
import DashboardOverview from '../src/app/admin/dashboard/DashboardOverview';
import UserManagementClient from '../src/app/admin/dashboard/users/UserManagementClient';
import { DialogProvider } from '../src/app/components/providers/DialogProvider';
import * as adminHelper from '../lib/db/admin-actions';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

// ---------------------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------------------

/** The path `usePathname` reports, so the sidebar highlights the screen being dumped. */
let currentPath = '/admin/dashboard';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn(), replace: jest.fn(), back: jest.fn(), prefetch: jest.fn() }),
  usePathname: () => currentPath,
  useSearchParams: () => new URLSearchParams(),
}));

jest.mock('../lib/db/admin-actions', () => ({
  createUser: jest.fn(),
  updateUser: jest.fn(),
  deleteUser: jest.fn(),
  getUserStats: jest.fn(),
  getAllUsersWithLicenses: jest.fn(),
  getAllLicenses: jest.fn(),
  assignLicenseToUser: jest.fn(),
  removeUserLicense: jest.fn(),
  getAllFeatureFlags: jest.fn(),
  getAllFeatureFlagGroups: jest.fn(),
  getUserLicense: jest.fn(),
  getUserFeatureFlagOverrides: jest.fn(),
  setUserFeatureFlagOverride: jest.fn(),
}));

const helper = adminHelper as unknown as Record<string, jest.Mock<(...args: unknown[]) => Promise<string>>>;

// ---------------------------------------------------------------------------------------
// Data — a self-hosted installation serving Northwind and two smaller workspaces
// ---------------------------------------------------------------------------------------

/** Five accounts, two licensed, one unverified and one disabled. */
const DOCS_USERS = [
  ['u-priya', 'Priya Raman', 'priya.raman@northwind.io', true, true, '2026-02-03T09:12:00Z', '2026-10-24T16:40:00Z', 'lic-team', 'Team', 'paid'],
  ['u-marcus', 'Marcus Lee', 'marcus.lee@northwind.io', true, true, '2026-02-03T09:40:00Z', '2026-10-22T08:15:00Z', 'lic-team', 'Team', 'paid'],
  ['u-sam', 'Sam Okafor', 'sam.okafor@northwind.io', true, true, '2026-03-17T14:05:00Z', '2026-09-30T13:02:00Z', null, null, null],
  ['u-elena', 'Elena Vasquez', 'elena.vasquez@northwind.io', false, true, '2026-06-11T16:22:00Z', null, null, null, null],
  ['u-jb', 'Jordan Blake', 'contractor.jb@partner.dev', true, false, '2026-04-29T08:51:00Z', '2026-05-02T10:30:00Z', 'lic-community', 'Community', 'free'],
].map(([id, name, email, verified, enabled, created, lastActive, licenseId, licenseName, licenseType]) => ({
  id,
  name,
  email,
  verified,
  enabled,
  created_at: created,
  updated_at: created,
  last_login_at: lastActive,
  last_active_at: lastActive,
  license_id: licenseId,
  license_name: licenseName,
  license_type: licenseType,
}));

/** The licenses an administrator can assign. */
const DOCS_LICENSES = [
  { id: 'lic-community', name: 'Community', license_type: 'free', enabled: true },
  { id: 'lic-team', name: 'Team', license_type: 'paid', enabled: true },
  { id: 'lic-oss', name: 'Open-source sponsor', license_type: 'sponsor', enabled: true },
];

/** Answer every read the Users screen makes. */
function stubUsersScreen(): void {
  const ok = (body: object) => async () => JSON.stringify({ success: true, ...body });
  helper.getAllUsersWithLicenses.mockImplementation(ok({ users: DOCS_USERS }));
  helper.getAllLicenses.mockImplementation(ok({ licenses: DOCS_LICENSES }));
  helper.getUserStats.mockImplementation(
    ok({ stats: { total_users: 5, enabled_users: 4, verified_users: 4, new_users_30_days: 1, new_users_7_days: 0 } }),
  );
}

// ---------------------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------------------

/**
 * A console screen inside the dashboard frame.
 *
 * `app/admin/dashboard/layout.tsx` is an async server component (it checks the admin session),
 * so it cannot render here; this is its markup, sidebar and all, around the page.
 *
 * @param path The route, for the sidebar's active item.
 * @param page The page component.
 */
function renderConsole(path: string, page: React.ReactElement) {
  currentPath = path;
  return render(
    <DialogProvider>
      <div
        data-testid="admin-console"
        className="flex h-screen overflow-hidden bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-slate-100"
      >
        <AdminSidebar />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">{page}</div>
      </div>
    </DialogProvider>,
  );
}

/** Everything rendered — the frame and any dialog portalled beside it — without the `<body>`. */
const bodyMarkup = () => liveMarkup(document.body).replace(/^<body[^>]*>|<\/body>$/g, '');

/**
 * Place a row's "more" button where it sits at 1440 px, so the fixed-position menu it opens
 * lands under it in the capture (jsdom lays nothing out, so every rect is zero).
 *
 * @param button The row's menu button.
 * @param top Its top edge, in px.
 */
function placeMenuButton(button: HTMLElement, top: number): void {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 });
  button.getBoundingClientRect = () =>
    ({ top, bottom: top + 32, left: 1368, right: 1400, width: 32, height: 32, x: 1368, y: top, toJSON: () => ({}) }) as DOMRect;
}

beforeEach(() => {
  jest.clearAllMocks();
  window.localStorage.clear();
  stubUsersScreen();
});

// ---------------------------------------------------------------------------------------
// The screens
// ---------------------------------------------------------------------------------------

describe('signing in', () => {
  it('asks for the admin password and keeps the button off until one is typed', async () => {
    const user = userEvent.setup();
    render(<AdminLoginClient />);

    expect(screen.getByRole('heading', { name: 'Super Admin' })).toBeInTheDocument();
    expect(screen.getByText('Apiome Administration Portal')).toBeInTheDocument();
    const submit = screen.getByRole('button', { name: /Access Admin Portal/ });
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText('Admin Password'), 'correct horse battery');
    expect(submit).toBeEnabled();
    expect(screen.getByText(/This is a restricted area/)).toBeInTheDocument();
    writeA11yFixture('admin-sign-in', liveMarkup(document.body.firstElementChild as Element));
  });
});

describe('the Overview', () => {
  it('shows the sidebar with Overview current and the four summary cards', () => {
    renderConsole('/admin/dashboard', <DashboardOverview />);

    const sidebar = screen.getByText('Apiome Console').closest('aside, nav, div') as HTMLElement;
    expect(sidebar).toBeInTheDocument();
    for (const item of ['Overview', 'Users', 'Tenants', 'Licenses', 'Feature Flags', 'Property Templates', 'Payments', 'Database', 'Monitoring', 'System settings']) {
      expect(screen.getByRole('button', { name: item })).toBeInTheDocument();
    }
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Dashboard Overview' })).toBeInTheDocument();
    for (const card of ['Total Users', 'Active Subscriptions', 'Revenue (MTD)', 'System Status']) {
      expect(screen.getByText(card)).toBeInTheDocument();
    }
    writeA11yFixture('admin-overview', bodyMarkup());
  });
});

describe('Users', () => {
  // SGN-1.3 (#5652): the Pending Signups tab is gone; the page is the user list.
  it('opens on the user list, with no sign-up queue', async () => {
    renderConsole('/admin/dashboard/users', <UserManagementClient />);

    expect(await screen.findByText('priya.raman@northwind.io')).toBeInTheDocument();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    expect(screen.queryByText(/Pending Signups/)).not.toBeInTheDocument();
    expect(screen.getByText('New Users')).toBeInTheDocument();
  });

  it('lists active users with their license and status', async () => {
    renderConsole('/admin/dashboard/users', <UserManagementClient />);
    await screen.findByText('priya.raman@northwind.io');

    const table = screen.getByRole('table');
    expect(within(table).getByText('priya.raman@northwind.io')).toBeInTheDocument();
    expect(within(table).getAllByText('Team')).toHaveLength(2);
    expect(within(table).getAllByText('No license')).toHaveLength(2);
    expect(within(table).getByText('Unverified')).toBeInTheDocument();
    expect(within(table).getByText('Disabled')).toBeInTheDocument();
    // Created and Last active: real dates, and "Never" for an account no one has signed in to.
    expect(within(table).getByRole('columnheader', { name: 'Last active' })).toBeInTheDocument();
    expect(within(table).getAllByTestId('admin-user-last-active').map((cell) => cell.textContent)).toEqual(
      expect.arrayContaining(['Never'])
    );
    expect(within(table).queryByText(/Invalid Date/)).not.toBeInTheDocument();
    writeA11yFixture('admin-users', bodyMarkup());
  });

  it('never shows "Invalid Date" when a row has no dates', async () => {
    helper.getAllUsersWithLicenses.mockImplementation(async () =>
      JSON.stringify({
        success: true,
        users: [{ ...DOCS_USERS[0], created_at: undefined, last_login_at: null, last_active_at: null }],
      })
    );
    renderConsole('/admin/dashboard/users', <UserManagementClient />);
    await screen.findByText('priya.raman@northwind.io');

    const table = screen.getByRole('table');
    expect(within(table).queryByText(/Invalid Date/)).not.toBeInTheDocument();
    expect(within(table).getByText('—')).toBeInTheDocument();
    expect(within(table).getByTestId('admin-user-last-active')).toHaveTextContent('Never');
  });

  it('opens a user’s actions, with the license list expanded', async () => {
    const user = userEvent.setup();
    renderConsole('/admin/dashboard/users', <UserManagementClient />);
    await screen.findByText('priya.raman@northwind.io');

    const row = screen.getByText('sam.okafor@northwind.io').closest('tr') as HTMLElement;
    const more = within(row).getAllByRole('button').at(-1) as HTMLElement;
    placeMenuButton(more, 498);
    await user.click(more);

    for (const action of ['Mark Unverified', 'Disable User', 'Assign License…', 'Manage Feature Flags…', 'Delete User']) {
      expect(screen.getByRole('button', { name: action })).toBeInTheDocument();
    }
    await user.click(screen.getByRole('button', { name: 'Assign License…' }));
    expect(screen.getByRole('button', { name: 'Open-source sponsor' })).toBeInTheDocument();
    // Sam has no license, so there is nothing to remove.
    expect(screen.queryByRole('button', { name: 'Remove License' })).not.toBeInTheDocument();
    writeA11yFixture('admin-users-menu', bodyMarkup());
  });

  it('creates a user from New User', async () => {
    const user = userEvent.setup();
    helper.createUser.mockResolvedValue(JSON.stringify({ success: true }));
    renderConsole('/admin/dashboard/users', <UserManagementClient />);
    await screen.findByText('priya.raman@northwind.io');

    await user.click(screen.getByRole('button', { name: /New User/ }));
    expect(screen.getByRole('heading', { name: 'Create New User' })).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText('Jane Doe'), 'Noor Haddad');
    await user.type(screen.getByPlaceholderText('jane@example.com'), 'Noor.Haddad@northwind.io');
    await user.type(screen.getByPlaceholderText('Temporary password'), 'Welcome-2026!');
    expect(screen.getByLabelText('Mark email as verified')).toBeChecked();
    expect(screen.getByLabelText('Enable account immediately')).toBeChecked();
    writeA11yFixture('admin-users-create-dialog', bodyMarkup());

    await user.click(screen.getByRole('button', { name: 'Create User' }));
    // The email is trimmed and lower-cased before it is stored.
    expect(helper.createUser).toHaveBeenCalledWith('Noor Haddad', 'noor.haddad@northwind.io', 'Welcome-2026!', true, true);
    expect(await screen.findByText('User created successfully for Noor Haddad')).toBeInTheDocument();
  });

  it('asks for the email to be typed before deleting a user', async () => {
    const user = userEvent.setup();
    renderConsole('/admin/dashboard/users', <UserManagementClient />);
    await screen.findByText('priya.raman@northwind.io');

    const row = screen.getByText('contractor.jb@partner.dev').closest('tr') as HTMLElement;
    await user.click(within(row).getAllByRole('button').at(-1) as HTMLElement);
    await user.click(screen.getByRole('button', { name: 'Delete User' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Jordan Blake loses their account');
    const confirm = within(dialog).getByRole('button', { name: 'Delete user' });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByRole('textbox'), 'contractor.jb@partner.dev');
    expect(confirm).toBeEnabled();
    writeA11yFixture('admin-users-delete-dialog', bodyMarkup());
    expect(helper.deleteUser).not.toHaveBeenCalled();
  });

  // TFA-1.2 (#5656): a locked-out user's second factor can be cleared from their row.
  describe('resetting a user’s two-factor', () => {
    /** The docs roster, with two-factor on for Priya only. */
    const withPriyaEnrolled = () =>
      helper.getAllUsersWithLicenses.mockImplementation(async () =>
        JSON.stringify({
          success: true,
          users: DOCS_USERS.map((entry) => ({ ...entry, two_factor_enabled: entry.id === 'u-priya' })),
        }),
      );

    /** Open one user's actions menu. */
    async function openMenuFor(email: string) {
      const user = userEvent.setup();
      renderConsole('/admin/dashboard/users', <UserManagementClient />);
      await screen.findByText('priya.raman@northwind.io');
      const row = screen.getByText(email).closest('tr') as HTMLElement;
      await user.click(within(row).getAllByRole('button').at(-1) as HTMLElement);
      return user;
    }

    it('offers the action only for a user who has two-factor on', async () => {
      withPriyaEnrolled();
      await openMenuFor('marcus.lee@northwind.io');
      expect(screen.queryByRole('button', { name: 'Reset two-factor…' })).not.toBeInTheDocument();
    });

    it('asks for a reason and the email, resets through the admin route, and says the user was emailed', async () => {
      withPriyaEnrolled();
      const fetchMock = jest.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => ({
          success: true,
          data: { userId: 'u-priya', hadTwoFactor: true, sessionsRevoked: 2, trustedDevicesRevoked: 1, emailSent: true },
        }),
      }));
      global.fetch = fetchMock as unknown as typeof fetch;

      const user = await openMenuFor('priya.raman@northwind.io');
      await user.click(screen.getByRole('button', { name: 'Reset two-factor…' }));

      const dialog = await screen.findByTestId('reset-two-factor-dialog');
      expect(dialog).toHaveTextContent('Reset two-factor for Priya Raman?');
      const submit = within(dialog).getByRole('button', { name: 'Reset two-factor' });
      expect(submit).toBeDisabled();

      await user.type(within(dialog).getByLabelText('Reason'), 'Lost her phone and her backup codes.');
      await user.type(within(dialog).getByLabelText(/to confirm/), 'priya.raman@northwind.io');
      expect(submit).toBeEnabled();
      writeA11yFixture('admin-users-reset-two-factor', bodyMarkup());

      await user.click(submit);

      await waitFor(() =>
        expect(fetchMock).toHaveBeenCalledWith('/api/admin/users/u-priya/two-factor/reset', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            reason: 'Lost her phone and her backup codes.',
            confirm: 'priya.raman@northwind.io',
          }),
        }),
      );
      expect(await within(dialog).findByTestId('reset-two-factor-result')).toHaveTextContent(
        'They have been emailed.',
      );
      // The roster is read again, so the action leaves the menu of a user with no factor left.
      await waitFor(() => expect(helper.getAllUsersWithLicenses).toHaveBeenCalledTimes(2));
    });
  });
});
