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
import * as adminHelper from '../lib/db/admin-helper';
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

jest.mock('../lib/db/admin-helper', () => ({
  getAllSignups: jest.fn(),
  createUser: jest.fn(),
  createUserFromSignup: jest.fn(),
  deleteSignup: jest.fn(),
  updateUser: jest.fn(),
  deleteUser: jest.fn(),
  getUserStats: jest.fn(),
  getSignupStats: jest.fn(),
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
  ['u-priya', 'Priya Raman', 'priya.raman@northwind.io', true, true, '2026-02-03T09:12:00Z', 'lic-team', 'Team', 'paid'],
  ['u-marcus', 'Marcus Lee', 'marcus.lee@northwind.io', true, true, '2026-02-03T09:40:00Z', 'lic-team', 'Team', 'paid'],
  ['u-sam', 'Sam Okafor', 'sam.okafor@northwind.io', true, true, '2026-03-17T14:05:00Z', null, null, null],
  ['u-elena', 'Elena Vasquez', 'elena.vasquez@northwind.io', false, true, '2026-06-11T16:22:00Z', null, null, null],
  ['u-jb', 'Jordan Blake', 'contractor.jb@partner.dev', true, false, '2026-04-29T08:51:00Z', 'lic-community', 'Community', 'free'],
].map(([id, name, email, verified, enabled, created, licenseId, licenseName, licenseType]) => ({
  id,
  name,
  email,
  verified,
  enabled,
  created_at: created,
  updated_at: created,
  license_id: licenseId,
  license_name: licenseName,
  license_type: licenseType,
}));

/** Three people waiting for an account. */
const DOCS_SIGNUPS = [
  ['Tomas Berg', 'tomas.berg@northwind.io', 'website', '2026-06-15T07:48:00Z'],
  ['Aiko Tanaka', 'aiko.tanaka@harbor-labs.com', 'github', '2026-06-14T18:03:00Z'],
  ['Lena Fischer', 'lena.fischer@quayside.dev', '', '2026-06-10T11:30:00Z'],
].map(([name, email, source, date]) => ({
  name,
  email_address: email,
  signup_source: source,
  signup_date: date,
  password: '',
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
  helper.getAllSignups.mockImplementation(ok({ signups: DOCS_SIGNUPS }));
  helper.getAllLicenses.mockImplementation(ok({ licenses: DOCS_LICENSES }));
  helper.getUserStats.mockImplementation(
    ok({ stats: { total_users: 5, enabled_users: 4, verified_users: 4, new_users_30_days: 1, new_users_7_days: 0 } }),
  );
  helper.getSignupStats.mockImplementation(
    ok({ stats: { total_signups: 3, signups_30_days: 3, signups_7_days: 2, signups_today: 1 } }),
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
  it('opens on Pending Signups, with the queue and its counts', async () => {
    renderConsole('/admin/dashboard/users', <UserManagementClient />);

    expect(await screen.findByText('aiko.tanaka@harbor-labs.com')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Pending Signups/ })).toHaveAttribute('aria-selected', 'true');
    // A blank source reads "Direct".
    expect(screen.getByText('Direct')).toBeInTheDocument();
    expect(screen.getByText('1 today')).toBeInTheDocument();
    writeA11yFixture('admin-users-signups', bodyMarkup());
  });

  it('lists active users with their license and status', async () => {
    const user = userEvent.setup();
    renderConsole('/admin/dashboard/users', <UserManagementClient />);
    await screen.findByText('aiko.tanaka@harbor-labs.com');

    await user.click(screen.getByRole('tab', { name: 'Active Users' }));
    const table = screen.getByRole('table');
    expect(within(table).getByText('priya.raman@northwind.io')).toBeInTheDocument();
    expect(within(table).getAllByText('Team')).toHaveLength(2);
    expect(within(table).getAllByText('No license')).toHaveLength(2);
    expect(within(table).getByText('Unverified')).toBeInTheDocument();
    expect(within(table).getByText('Disabled')).toBeInTheDocument();
    writeA11yFixture('admin-users', bodyMarkup());
  });

  it('opens a user’s actions, with the license list expanded', async () => {
    const user = userEvent.setup();
    renderConsole('/admin/dashboard/users', <UserManagementClient />);
    await screen.findByText('aiko.tanaka@harbor-labs.com');
    await user.click(screen.getByRole('tab', { name: 'Active Users' }));

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

  it('creates a user from New User, then shows the Active Users tab', async () => {
    const user = userEvent.setup();
    helper.createUser.mockResolvedValue(JSON.stringify({ success: true }));
    renderConsole('/admin/dashboard/users', <UserManagementClient />);
    await screen.findByText('aiko.tanaka@harbor-labs.com');

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
    expect(screen.getByRole('tab', { name: 'Active Users' })).toHaveAttribute('aria-selected', 'true');
  });

  it('approves a signup after confirming', async () => {
    const user = userEvent.setup();
    helper.createUserFromSignup.mockResolvedValue(JSON.stringify({ success: true }));
    renderConsole('/admin/dashboard/users', <UserManagementClient />);
    await screen.findByText('aiko.tanaka@harbor-labs.com');

    const row = screen.getByText('tomas.berg@northwind.io').closest('tr') as HTMLElement;
    await user.click(within(row).getByRole('button'));
    await user.click(screen.getByRole('button', { name: 'Create User' }));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Create an account for Tomas Berg?');
    await user.click(within(dialog).getByRole('button', { name: 'Create account' }));
    await waitFor(() => expect(helper.createUserFromSignup).toHaveBeenCalledWith('tomas.berg@northwind.io', true, true));
  });

  it('asks for the email to be typed before deleting a user', async () => {
    const user = userEvent.setup();
    renderConsole('/admin/dashboard/users', <UserManagementClient />);
    await screen.findByText('aiko.tanaka@harbor-labs.com');
    await user.click(screen.getByRole('tab', { name: 'Active Users' }));

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
});
