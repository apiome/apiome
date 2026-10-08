/**
 * @jest-environment jsdom
 */

/**
 * Docs fixtures for the admin console's Tenants, Licenses and Feature flags screens
 * (DOCS-1.10, #5627).
 *
 * The admin console is the legacy UI and sits behind its own password, so the documentation
 * site's screenshot pipeline cannot open it against the seeded stack. Instead this suite renders
 * each screen inside the console's real layout (sidebar + content column) with the server actions
 * of `lib/db/admin-helper` mocked, checks the content, and — with `A11Y_FIXTURE_DUMP=1` — writes
 * the markup to `e2e/fixtures/hive-a11y/admin-*.html`, which `apiome-docs/screens.json` captures:
 *
 *     A11Y_FIXTURE_DUMP=1 npx jest tests/docs-admin-licensing.test.tsx
 *
 * Without the variable the screens still render and are asserted, so a change that would leave a
 * fixture stale fails here first.
 */

import React from 'react';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

// ---------------------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------------------

/** The admin route the sidebar marks current; each test sets it before rendering. */
let currentPath = '/admin/dashboard/tenants';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn(), replace: jest.fn() }),
  usePathname: () => currentPath,
}));

jest.mock('@/app/components/providers/DialogProvider', () => ({
  useDialog: () => ({ confirm: jest.fn(async () => false), alert: jest.fn(async () => undefined) }),
}));

/** Every server action the three screens call, answered from the fixtures below. */
jest.mock('../lib/db/admin-helper', () => ({
  getTenantStats: jest.fn(),
  getTenantUsers: jest.fn(),
  getUsersNotInTenant: jest.fn(),
  getAllUsers: jest.fn(),
  createTenant: jest.fn(),
  updateTenant: jest.fn(),
  deleteTenant: jest.fn(),
  addUserToTenant: jest.fn(),
  removeUserFromTenant: jest.fn(),
  addTenantAdministrator: jest.fn(),
  removeTenantAdministrator: jest.fn(),
  provisionSampleProject: jest.fn(),
  getAllLicenses: jest.fn(),
  createLicense: jest.fn(),
  updateLicense: jest.fn(),
  deleteLicense: jest.fn(),
  getAllFeatureFlags: jest.fn(),
  createFeatureFlag: jest.fn(),
  updateFeatureFlag: jest.fn(),
  deleteFeatureFlag: jest.fn(),
  getAllFeatureFlagGroups: jest.fn(),
  createFeatureFlagGroup: jest.fn(),
  updateFeatureFlagGroup: jest.fn(),
  deleteFeatureFlagGroup: jest.fn(),
  getAllUsersWithLicenses: jest.fn(),
  assignLicenseToUser: jest.fn(),
  removeUserLicense: jest.fn(),
  getUserLicense: jest.fn(),
  setUserFeatureFlag: jest.fn(),
  removeUserFeatureFlag: jest.fn(),
}));

// eslint-disable-next-line @typescript-eslint/no-require-imports
const helper = require('../lib/db/admin-helper') as Record<string, jest.Mock<(...args: unknown[]) => Promise<string>>>;

import AdminSidebar from '../src/app/admin/dashboard/AdminSidebar';
import TenantManagementClient from '../src/app/admin/dashboard/tenants/TenantManagementClient';
import LicenseManagementClient from '../src/app/admin/dashboard/licenses/LicenseManagementClient';

// ---------------------------------------------------------------------------------------
// Fixtures — one Northwind installation
// ---------------------------------------------------------------------------------------

const STAMP = '2026-09-01T10:00:00Z';

/** Every account on the installation. */
const USERS = [
  ['u-priya', 'Priya Raman', 'priya.raman@northwind.io'],
  ['u-marcus', 'Marcus Lee', 'marcus.lee@northwind.io'],
  ['u-sam', 'Sam Okafor', 'sam.okafor@northwind.io'],
  ['u-elena', 'Elena Vasquez', 'elena.vasquez@northwind.io'],
  ['u-tomas', 'Tomas Berg', 'tomas.berg@northwind.io'],
  ['u-jb', 'Jordan Blake', 'contractor.jb@partner.dev'],
].map(([id, name, email]) => ({ id, name, email, verified: true, enabled: true }));

const TENANTS = [
  { id: 't-northwind', name: 'Northwind', slug: 'northwind', description: 'Production APIs', enabled: true, user_count: 5, admin_count: 2, project_count: 14 },
  { id: 't-sandbox', name: 'Northwind Sandbox', slug: 'northwind-sandbox', description: 'Partner trials', enabled: true, user_count: 3, admin_count: 1, project_count: 4 },
  { id: 't-labs', name: 'Northwind Labs', slug: 'northwind-labs', description: 'Experiments', enabled: true, user_count: 2, admin_count: 1, project_count: 6 },
  { id: 't-legacy', name: 'Legacy Gateway', slug: 'legacy-gateway', description: 'Retired 2026-08', enabled: false, user_count: 1, admin_count: 1, project_count: 2 },
].map((t) => ({ ...t, created_at: STAMP, updated_at: STAMP }));

/** Northwind's members; the first two administer it. */
const NORTHWIND_MEMBERS = USERS.slice(0, 5).map((u, i) => ({ ...u, added_at: STAMP, is_admin: i < 2 }));

/** The flags a fresh installation seeds (V097, V116), plus one an operator added and switched off. */
const FLAGS = [
  { id: 'ff-designer', name: 'designer', label: 'Schema Designer', description: 'Visual schema designer and class editor.', url_patterns: ['/ade/dashboard', '/api/classes', '/api/properties', '/api/primitives'], is_preview: false, enabled: true },
  { id: 'ff-paths', name: 'paths', label: 'API Paths', description: 'OpenAPI path editor and path management tools.', url_patterns: ['/ade/database', '/api/paths', '/api/versions'], is_preview: false, enabled: true },
  { id: 'ff-ai', name: 'ai_assistant', label: 'AI Assistant', description: 'Ollama-powered chatbot and schema generation assistant.', url_patterns: ['/ade/studio', '/api/ollama'], is_preview: true, enabled: true },
  { id: 'ff-repos', name: 'repositories', label: 'Repositories', description: 'Git-backed schema repository browser and diff viewer.', url_patterns: ['/ade/migration', '/api/repositories'], is_preview: true, enabled: true },
  { id: 'ff-registry', name: 'primitives-registry', label: 'Primitives Type Registry', description: 'Advanced JSON Schema type registry: $ref resolver, namespaces, registry settings, coverage stats, and the import pipeline.', url_patterns: ['/ade/dashboard/primitives', '/api/types'], is_preview: true, enabled: true },
  { id: 'ff-partner', name: 'partner_sandbox', label: 'Partner sandbox', description: 'Early access for the Northwind partner pilot.', url_patterns: [], is_preview: true, enabled: false },
].map((f) => ({ ...f, created_at: STAMP, updated_at: STAMP }));

const ref = (id: string) => {
  const f = FLAGS.find((x) => x.id === id)!;
  return { id: f.id, name: f.name, label: f.label, is_preview: f.is_preview };
};

const EVERY_SEEDED = ['ff-designer', 'ff-paths', 'ff-ai', 'ff-repos', 'ff-registry'].map(ref);

/** The three seeded plans (V097) and one an operator added and has not enabled. */
const LICENSES = [
  {
    id: 'lic-free', name: 'Free', description: 'Default free-tier plan with basic schema designer access.', license_type: 'free',
    seats: { max_tenants: 1, max_users_per_tenant: 5 }, enabled: true, feature_flags: [ref('ff-designer')],
  },
  {
    id: 'lic-paid', name: 'Paid', description: 'Standard paid plan — Designer, Paths, AI Assistant and Repositories included.', license_type: 'paid',
    seats: { max_tenants: 5, max_users_per_tenant: 25, max_projects: 100, max_ai_requests: 2000 }, enabled: true,
    feature_flags: EVERY_SEEDED,
  },
  {
    id: 'lic-sponsor', name: 'Sponsor', description: 'Sponsor plan — all features, elevated tenant and user limits.', license_type: 'sponsor',
    seats: { max_tenants: 20, max_users_per_tenant: 100, max_ai_requests: -1 }, enabled: true, feature_flags: EVERY_SEEDED,
  },
  {
    id: 'lic-pilot', name: 'Partner pilot', description: 'Ninety-day pilot for Northwind partners.', license_type: 'paid',
    seats: { max_tenants: 1, max_users_per_tenant: 10 }, enabled: false, feature_flags: [ref('ff-designer'), ref('ff-partner')],
  },
].map((l) => ({ ...l, created_at: STAMP, updated_at: STAMP }));

const GROUPS = [
  { id: 'g-design', name: 'design_tools', label: 'Design tools', description: 'Schema Designer and API Paths together.', feature_flags: [ref('ff-designer'), ref('ff-paths')] },
  { id: 'g-preview', name: 'preview_features', label: 'Preview features', description: 'Everything still marked Preview.', feature_flags: [ref('ff-ai'), ref('ff-repos'), ref('ff-registry')] },
].map((g) => ({ ...g, created_at: STAMP, updated_at: STAMP }));

const paid = LICENSES[1];
const sponsor = LICENSES[2];
const free = LICENSES[0];
const USERS_WITH_LICENSES = USERS.map((u, i) => {
  const lic = i === 0 ? sponsor : i < 3 ? paid : i === 3 ? free : null;
  return {
    ...u,
    license_id: lic?.id ?? null,
    license_name: lic?.name ?? null,
    license_type: lic?.license_type ?? null,
    seats: lic?.seats ?? null,
    plan_code: null,
  };
});

/** JSON the way the server actions return it. */
const ok = (body: Record<string, unknown>) => async () => JSON.stringify({ success: true, ...body });

beforeEach(() => {
  helper.getTenantStats.mockImplementation(ok({ tenants: TENANTS }));
  helper.getAllUsers.mockImplementation(ok({ users: USERS }));
  helper.getTenantUsers.mockImplementation(ok({ users: NORTHWIND_MEMBERS }));
  helper.getUsersNotInTenant.mockImplementation(ok({ users: USERS.slice(5) }));
  helper.getAllLicenses.mockImplementation(ok({ licenses: LICENSES }));
  helper.getAllFeatureFlags.mockImplementation(ok({ featureFlags: FLAGS }));
  helper.getAllFeatureFlagGroups.mockImplementation(ok({ groups: GROUPS }));
  helper.getAllUsersWithLicenses.mockImplementation(ok({ users: USERS_WITH_LICENSES }));
  // Elena holds Free (Schema Designer) and has been granted the AI Assistant and the pilot on top.
  helper.getUserLicense.mockImplementation(
    ok({
      license: {
        license_feature_flags: free.feature_flags.map((f) => ({ id: f.id })),
        user_overrides: [{ id: 'ff-ai', enabled: true }, { id: 'ff-partner', enabled: true }],
      },
    })
  );
});

// ---------------------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------------------

/**
 * Render a screen inside the admin console's layout, exactly as `admin/dashboard/layout.tsx`
 * composes it.
 *
 * @param path The route the sidebar marks current.
 * @param page The page client.
 */
function renderAdmin(path: string, page: React.ReactElement) {
  currentPath = path;
  return render(
    <div className="flex h-screen overflow-hidden bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <AdminSidebar />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">{page}</div>
    </div>
  );
}

/** Everything rendered — the layout and anything portalled beside it — without `<body>`. */
const bodyMarkup = () => liveMarkup(document.body).replace(/^<body[^>]*>|<\/body>$/g, '');

// ---------------------------------------------------------------------------------------
// The docs fixtures
// ---------------------------------------------------------------------------------------

describe('the docs fixtures', () => {
  it('renders Tenants with a tenant selected, and the create dialog', async () => {
    const user = userEvent.setup();
    renderAdmin('/admin/dashboard/tenants', <TenantManagementClient />);

    await user.click(await screen.findByText('Northwind Sandbox'));
    await user.click(screen.getAllByText('Northwind')[0]);
    expect(await screen.findByText('Users in Northwind')).toBeInTheDocument();
    expect(await screen.findByText('priya.raman@northwind.io')).toBeInTheDocument();
    expect(screen.getByText('Total Tenants').parentElement).toHaveTextContent('4');
    expect(screen.getByText('Active Tenants').parentElement).toHaveTextContent('3');
    writeA11yFixture('admin-tenants', bodyMarkup());

    await user.click(screen.getByRole('button', { name: /Create Tenant/ }));
    const dialogTitle = await screen.findByText('Create New Tenant');
    const form = dialogTitle.closest('div')!.parentElement as HTMLElement;
    await user.type(within(form).getByPlaceholderText('Acme Corporation'), 'Northwind Payments');
    // The slug is suggested from the first keystroke only, so it is set by hand — as the docs say.
    const slug = within(form).getByPlaceholderText('acme-corporation');
    await user.clear(slug);
    await user.type(slug, 'northwind-payments');
    await user.type(within(form).getByPlaceholderText('Description of the tenant...'), 'Card and ledger APIs');
    await user.selectOptions(within(form).getByRole('combobox'), 'u-marcus');
    await user.click(within(form).getByLabelText(/Make this user a tenant administrator/));
    writeA11yFixture('admin-tenants-create', bodyMarkup());
  });

  it('renders Licenses with a plan expanded, the plan form and the assignments', async () => {
    const user = userEvent.setup();
    renderAdmin('/admin/dashboard/licenses', <LicenseManagementClient />);

    expect(await screen.findByText('Partner pilot')).toBeInTheDocument();
    const paidRow = (await screen.findByText('Paid', { selector: 'span.font-semibold' })).closest('.rounded-xl') as HTMLElement;
    await user.click(within(paidRow).getByTitle('Toggle feature flags'));
    expect(within(paidRow).getByText('Included Feature Flags')).toBeInTheDocument();
    expect(screen.getByText('disabled')).toBeInTheDocument();
    writeA11yFixture('admin-licenses', bodyMarkup());

    await user.click(within(paidRow).getByTitle('Edit'));
    expect(await screen.findByText('Edit — Paid')).toBeInTheDocument();
    expect(screen.getByText('Commercial applications')).toBeInTheDocument();
    expect(screen.getByText('Additional platform features')).toBeInTheDocument();
    writeA11yFixture('admin-license-form', bodyMarkup());
    await user.click(screen.getByRole('button', { name: 'Cancel' }));

    await user.click(screen.getByRole('tab', { name: /Assignments/ }));
    expect(await screen.findAllByText('No license')).toHaveLength(2);
    expect(screen.getAllByText('Sponsor').length).toBeGreaterThan(0);
    writeA11yFixture('admin-license-assignments', bodyMarkup());
  });

  it('renders Feature flags, Flag packages and a user’s overrides', async () => {
    const user = userEvent.setup();
    renderAdmin('/admin/dashboard/feature-flags', <LicenseManagementClient initialTab="featureFlags" />);

    expect(await screen.findByText('ai_assistant')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Feature Flags/ })).toHaveAttribute('aria-selected', 'true');
    writeA11yFixture('admin-feature-flags', bodyMarkup());

    await user.click(screen.getByRole('tab', { name: /Flag packages/ }));
    expect(await screen.findByText('design_tools')).toBeInTheDocument();
    writeA11yFixture('admin-flag-packages', bodyMarkup());

    await user.click(screen.getByRole('tab', { name: /Assignments/ }));
    const elenaRow = (await screen.findByText('elena.vasquez@northwind.io')).closest('tr') as HTMLElement;
    await user.click(within(elenaRow).getByRole('button', { name: /Assign/ }));
    await user.click(await screen.findByRole('button', { name: /Override feature flags/ }));
    expect(await screen.findByText('Feature flags — Elena Vasquez')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('Granted for this user')).toBeInTheDocument());
    expect(screen.getByText('All flags — add')).toBeInTheDocument();
    writeA11yFixture('admin-feature-flag-overrides', bodyMarkup());
  });
});
