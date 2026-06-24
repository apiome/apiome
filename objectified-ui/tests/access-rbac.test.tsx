/**
 * Access / IAM (RBAC) UI tests — #3611
 *
 * Renders the three tenant-facing client components (Roles, Members, Audit) against a
 * mocked `global.fetch` that returns the documented `{ success, data }` proxy shapes,
 * and asserts the key UI surfaces: the permission matrix (10 resources x 5 actions),
 * the members table + the "Coming soon" SSO/SCIM cards, and the audit filter tabs +
 * an event row.
 */

import React from 'react';
import { render, screen, within, findByText } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import RolesClient from '../src/app/ade/dashboard/roles/RolesClient';
import MembersClient from '../src/app/ade/dashboard/members/MembersClient';
import AuditClient from '../src/app/ade/dashboard/audit/AuditClient';

const ROLES = [
  {
    id: 'role-owner',
    slug: 'owner',
    name: 'Owner',
    description: 'Built-in · full control',
    is_builtin: true,
    member_count: 1,
    permissions: [
      { resource: 'versions', action: 'view' },
      { resource: 'versions', action: 'publish' },
    ],
  },
  {
    id: 'role-rm',
    slug: 'release-manager',
    name: 'Release Manager',
    description: 'Can publish versions.',
    is_builtin: false,
    member_count: 2,
    permissions: [{ resource: 'versions', action: 'publish' }],
  },
];

const MEMBERS = [
  {
    user_id: 'user-1',
    name: 'Dana Okoro',
    email: 'dana@acme.io',
    status: 'active',
    member_since: '2026-01-01T00:00:00Z',
    role_id: 'role-owner',
    role_name: 'Owner',
    role_slug: 'owner',
    is_admin: true,
  },
  {
    user_id: 'user-2',
    name: 'Noah Partner',
    email: 'noah@partner.com',
    status: 'pending',
    member_since: '2026-06-01T00:00:00Z',
    role_id: 'role-rm',
    role_name: 'Release Manager',
    role_slug: 'release-manager',
    is_admin: false,
  },
];

const AUDIT = [
  {
    id: 'evt-1',
    actor_id: 'user-1',
    actor_label: 'dana@acme.io',
    action: 'role.assigned',
    target: 'noah@partner.com → Release Manager',
    source: 'Web',
    detail: '',
    created_at: '2026-06-20T12:04:22Z',
  },
];

const PERMS_ADMIN = { is_admin: true, permissions: [] as string[] };

function jsonResponse(data: unknown) {
  return Promise.resolve({
    status: 200,
    json: () => Promise.resolve({ success: true, data }),
  } as Response);
}

function mockFetch() {
  const fn = jest.fn((input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input.toString();
    if (url.includes('/api/access/permissions/me')) return jsonResponse(PERMS_ADMIN);
    if (url.includes('/api/access/roles')) return jsonResponse(ROLES);
    if (url.includes('/api/access/members')) return jsonResponse(MEMBERS);
    if (url.includes('/api/access/audit')) return jsonResponse(AUDIT);
    return jsonResponse([]);
  });
  // @ts-expect-error - assigning a test double to the global
  global.fetch = fn;
  return fn;
}

beforeEach(() => {
  mockFetch();
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('RolesClient (#3611)', () => {
  it('renders the role list and a 10x5 permission matrix', async () => {
    render(<RolesClient />);

    // Role names appear in the left list.
    expect(await screen.findByText('Owner')).toBeInTheDocument();
    expect(screen.getByText('Release Manager')).toBeInTheDocument();

    // All 10 resources render as rows.
    for (const label of [
      'Projects',
      'Versions',
      'Classes',
      'Properties',
      'Paths',
      'Primitives / Types',
      'Imports',
      'Members',
      'API Keys',
      'Billing',
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }

    // All 5 action columns render as headers.
    const matrix = screen.getByRole('table');
    const headers = within(matrix).getAllByRole('columnheader').map((h) => h.textContent);
    expect(headers).toEqual(['Resource', 'View', 'Create', 'Edit', 'Delete', 'Publish']);

    // 10 resources x 5 actions = 50 toggle cells.
    const toggles = within(matrix).getAllByRole('button');
    expect(toggles).toHaveLength(50);
  });
});

describe('MembersClient (#3611)', () => {
  it('renders a member row and the Coming soon SSO/SCIM cards', async () => {
    render(<MembersClient />);

    // A member row.
    expect(await screen.findByText('Dana Okoro')).toBeInTheDocument();
    expect(screen.getByText('dana@acme.io')).toBeInTheDocument();

    // SSO / SCIM coming-soon cards.
    expect(screen.getByText('Single Sign-On (OIDC/SAML)')).toBeInTheDocument();
    expect(screen.getByText('SCIM 2.0 provisioning')).toBeInTheDocument();
    expect(screen.getAllByText('Coming soon').length).toBeGreaterThanOrEqual(2);

    // Disabled (non-functional) controls.
    expect(screen.getByRole('button', { name: 'Configure SSO' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Enable SCIM' })).toBeDisabled();
  });
});

describe('AuditClient (#3611)', () => {
  it('renders the filter tabs and an event row', async () => {
    render(<AuditClient />);

    // Filter tabs.
    for (const tab of ['All events', 'Role changes', 'Permissions', 'Members', 'Admin overrides']) {
      expect(screen.getByRole('button', { name: tab })).toBeInTheDocument();
    }

    // An event row resolves after the async fetch.
    expect(await screen.findByText('role.assigned')).toBeInTheDocument();
    expect(screen.getByText('noah@partner.com → Release Manager')).toBeInTheDocument();

    // Compliance note.
    const note = await findByText(document.body, /append-only and hash-chained/i);
    expect(note).toBeInTheDocument();
  });
});
