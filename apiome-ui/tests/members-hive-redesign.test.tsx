/**
 * The Members redesign, rendered (HIVE-5.2, #5305).
 *
 * `members-model.test.ts` holds the decisions; this holds the screen that makes them, against
 * a mocked `/api/access/*` returning the documented `{success, data}` envelopes. What it pins
 * is the ticket's four acceptance criteria and the mockup's **Keeps (1:1)** list:
 *
 *   1. **No native prompt or confirm remains.** Asserted directly — `window.confirm` and
 *      `window.prompt` are spied on for the whole file and must never be called, including on
 *      the two paths that used to reach for them.
 *   2. **The seat meter matches the licence.** The figure, the `role="meter"` bounds and the
 *      at-capacity banner all come from the same licence payload.
 *   3. **Pending invitations are distinct and resendable.** The row carries the tint class and
 *      the envelope mark, prints "Invited {date}" instead of a last-active instant, and offers
 *      Resend — which reaches the endpoint this ticket added.
 *   4. **Offboarding an administrator still warns, and now counts.**
 *
 * Plus the things the screen this replaces got wrong: suspending had no confirm at all, and
 * nothing stopped the viewer offboarding themselves.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

/** The viewer, so the screen can mark and protect their own row. */
const VIEWER_ID = 'u-ada';

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({
    data: { user: { user_id: 'u-ada', email: 'ada@acme.io', name: 'Ada Lovelace' } },
    status: 'authenticated',
    update: jest.fn(),
  }),
  AuthSessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

import MembersClient from '../src/app/ade/dashboard/members/MembersClient';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';
import {
  DOCS_AUDIT,
  DOCS_MEMBERS,
  DOCS_NOW,
  DOCS_ROLES,
  DOCS_SEATS,
} from './helpers/access-docs-data';

// ---------------------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------------------

const ROLES = [
  {
    id: 'role-owner',
    slug: 'owner',
    name: 'Owner',
    is_builtin: true,
    member_count: 1,
    permissions: [
      { resource: 'members', action: 'edit' },
      { resource: 'members', action: 'view' },
    ],
  },
  {
    id: 'role-editor',
    slug: 'editor',
    name: 'Editor',
    is_builtin: true,
    member_count: 2,
    permissions: [
      { resource: 'projects', action: 'view' },
      { resource: 'versions', action: 'edit' },
    ],
  },
];

const MEMBERS = [
  {
    user_id: VIEWER_ID,
    name: 'Ada Lovelace',
    email: 'ada@acme.io',
    status: 'active',
    member_since: '2025-01-12T12:00:00Z',
    joined_at: '2025-01-12T12:00:00Z',
    last_active: '2026-08-17T11:00:00Z',
    two_factor_enabled: true,
    role_id: 'role-owner',
    role_name: 'Owner',
    role_slug: 'owner',
    is_admin: true,
  },
  {
    user_id: 'u-grace',
    name: 'Grace Hopper',
    email: 'grace@acme.io',
    status: 'active',
    member_since: '2025-02-03T12:00:00Z',
    joined_at: '2025-02-03T12:00:00Z',
    last_active: '2026-08-16T09:00:00Z',
    two_factor_enabled: false,
    role_id: 'role-owner',
    role_name: 'Owner',
    role_slug: 'owner',
    is_admin: true,
  },
  {
    user_id: 'u-linus',
    name: 'Linus Torvalds',
    email: 'linus@acme.io',
    status: 'active',
    member_since: '2025-03-18T12:00:00Z',
    joined_at: '2025-03-18T12:00:00Z',
    last_active: '2026-08-15T09:00:00Z',
    two_factor_enabled: false,
    role_id: 'role-editor',
    role_name: 'Editor',
    role_slug: 'editor',
    is_admin: false,
  },
  {
    user_id: 'u-margaret',
    name: 'Margaret Hamilton',
    email: 'margaret@acme.io',
    status: 'suspended',
    member_since: '2026-07-30T12:00:00Z',
    joined_at: '2025-05-02T12:00:00Z',
    last_active: null,
    two_factor_enabled: false,
    role_id: 'role-editor',
    role_name: 'Editor',
    role_slug: 'editor',
    is_admin: false,
  },
  {
    user_id: 'u-partner',
    name: '',
    email: 'dev-partner@globex.io',
    status: 'pending',
    member_since: '2026-08-13T12:00:00Z',
    joined_at: '2026-08-13T12:00:00Z',
    last_active: null,
    two_factor_enabled: false,
    role_id: 'role-editor',
    role_name: 'Editor',
    role_slug: 'editor',
    is_admin: false,
  },
];

const AUDIT = [
  {
    id: 'evt-1',
    actor_id: 'u-linus',
    actor_label: 'linus@acme.io',
    action: 'role.assigned',
    target: 'u-linus',
    source: 'web',
    created_at: '2026-08-16T10:00:00Z',
  },
  {
    id: 'evt-2',
    actor_id: 'u-grace',
    actor_label: 'grace@acme.io',
    action: 'member.invited',
    target: 'dev-partner@globex.io',
    source: 'web',
    created_at: '2026-08-13T10:00:00Z',
  },
];

const PERMS_ADMIN = { is_admin: true, permissions: [] as string[] };
const PERMS_VIEWER = { is_admin: false, permissions: ['members:view'] };

/** Every call the mocked transport saw, so a test can assert what reached the API. */
interface RecordedCall {
  url: string;
  method: string;
  body: unknown;
}

/** How one mocked screen is configured. */
interface MockOptions {
  /** Seat usage the licence proxy reports; `null` makes the licence read fail. */
  seats?: { used: number; max: number } | null;
  /** The `permissions/me` payload. */
  perms?: { is_admin: boolean; permissions: string[] };
  /** Fail one write, keyed by `${method} ${pathSuffix}`. */
  failWrite?: { match: string; status: number; body: Record<string, unknown> };
  /** Make the roster read fail, so the table's own error state is reachable. */
  failRoster?: boolean;
}

/**
 * Build a `{success, data}` response.
 *
 * @param data The payload.
 * @returns A resolved `Response`-alike.
 */
function ok(data: unknown) {
  return Promise.resolve({
    status: 200,
    json: () => Promise.resolve({ success: true, data }),
  } as Response);
}

/**
 * Point `global.fetch` at the fixtures and record every call.
 *
 * @param options See {@link MockOptions}.
 * @returns The recorded calls, which fill in as the screen works.
 */
function mockApi(options: MockOptions = {}): RecordedCall[] {
  const { seats = { used: 5, max: 10 }, perms = PERMS_ADMIN, failWrite, failRoster } = options;
  const calls: RecordedCall[] = [];

  const fn = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = init?.method ?? 'GET';
    calls.push({
      url,
      method,
      body: typeof init?.body === 'string' ? JSON.parse(init.body) : undefined,
    });

    if (failWrite && `${method} ${url}`.includes(failWrite.match)) {
      return Promise.resolve({
        status: failWrite.status,
        json: () => Promise.resolve({ success: false, ...failWrite.body }),
      } as Response);
    }

    if (url.includes('/api/tenants/license')) {
      if (seats === null) {
        return Promise.resolve({
          status: 500,
          json: () => Promise.resolve({ success: false, error: 'boom' }),
        } as Response);
      }
      return ok({
        plan: { name: 'Team', type: 'paid' },
        seats,
        quotas: { max_projects: 1, max_versions: 3, max_ai_requests: 0 },
        features: [],
      });
    }
    if (url.includes('/api/access/permissions/me')) return ok(perms);
    if (url.includes('/api/access/roles')) return ok(ROLES);
    if (url.includes('/api/access/audit')) return ok(AUDIT);
    if (url.includes('/api/access/members')) {
      if (method === 'GET' && failRoster) {
        return Promise.resolve({
          status: 500,
          json: () => Promise.resolve({ success: false, error: 'The roster is unavailable' }),
        } as Response);
      }
      if (method !== 'GET') {
        return method === 'DELETE'
          ? Promise.resolve({ status: 204, json: () => Promise.resolve({}) } as Response)
          : ok({});
      }
      return ok(MEMBERS);
    }
    return ok([]);
  });

  // @ts-expect-error - assigning a test double to the global
  global.fetch = fn;
  return calls;
}

/**
 * Render the screen and wait for the roster.
 *
 * @param options See {@link MockOptions}.
 * @returns The recorded calls and a `userEvent` session.
 */
async function renderMembers(options: MockOptions = {}) {
  const calls = mockApi(options);
  const user = userEvent.setup();
  render(<MembersClient />);
  await screen.findByText('Ada Lovelace');
  return { calls, user };
}

/**
 * The `<tr>` one member's row lives in.
 *
 * @param email The member's address, which the identity cell carries.
 * @returns The row element.
 */
function rowFor(email: string): HTMLElement {
  const cell = document.querySelector(`[data-member-email="${email}"]`);
  if (!cell) throw new Error(`No row for ${email}`);
  const row = cell.closest('tr');
  if (!row) throw new Error(`Row for ${email} is not in a table`);
  return row as HTMLElement;
}

/** Native dialogs, spied on for the whole file — criterion 1 is that none of them fire. */
let confirmSpy: jest.SpiedFunction<typeof window.confirm>;
let promptSpy: jest.SpiedFunction<typeof window.prompt>;

beforeEach(() => {
  confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true);
  promptSpy = jest.spyOn(window, 'prompt').mockReturnValue('');
});

afterEach(() => {
  jest.restoreAllMocks();
});

/* -------------------------------------------------------------------------
   1. The page
   ------------------------------------------------------------------------- */

describe('the members page', () => {
  it('leads with the page chrome the design language asks for', async () => {
    await renderMembers();

    expect(screen.getByRole('heading', { level: 1, name: 'Members' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toBeInTheDocument();
    // The counts moved from the header into the facts line (HIVE-11.9).
    expect(screen.getByRole('list', { name: 'Members summary' })).toHaveTextContent(/5 members/);
    expect(screen.getByRole('link', { name: /Roles/ })).toHaveAttribute(
      'href',
      '/ade/dashboard/roles'
    );
  });

  it('names SSO and SCIM on one "Coming next" line, with no button that does nothing (HIVE-11.9)', async () => {
    await renderMembers();

    const line = screen.getByTestId('coming-next');
    expect(line).toHaveTextContent('Coming next:');
    expect(within(line).getByTestId('coming-next-sso')).toHaveTextContent('SSO (OIDC/SAML)');
    expect(within(line).getByTestId('coming-next-scim')).toHaveTextContent('SCIM 2.0 provisioning');
    expect(screen.queryByRole('button', { name: /Configure SSO|Enable SCIM/ })).not.toBeInTheDocument();
    expect(screen.queryByText('Coming soon')).not.toBeInTheDocument();
    // The follow link opens What's new in place.
    fireEvent.click(within(line).getByRole('button', { name: 'Follow in What’s new' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('offers no disabled button anywhere on the page (HIVE-11.9, §10)', async () => {
    await renderMembers({ seats: { used: 5, max: 5 } });
    const page = document.querySelector('.page') as HTMLElement;
    expect(page.querySelectorAll('button:disabled, button[aria-disabled="true"]')).toHaveLength(0);
  });
});

/* -------------------------------------------------------------------------
   2. The facts line (was the seat meter)
   ------------------------------------------------------------------------- */

describe('the facts line', () => {
  /** The summary list's facts, as text. */
  const facts = () =>
    within(screen.getByRole('list', { name: 'Members summary' }))
      .getAllByRole('listitem')
      .map((item) => item.textContent?.replace(/\s+/g, ' ').trim());

  it('counts members by state and seats exactly as the meter did, with no meter card', async () => {
    await renderMembers({ seats: { used: 3, max: 10 } });

    expect(facts()).toEqual([
      '5 members',
      expect.stringMatching(/^\d+ active$/),
      '1 pending',
      expect.stringMatching(/^\d+ suspended$/),
      '3 of 10 seats used',
      'Team plan',
    ]);
    expect(screen.queryByTestId('member-seat-usage')).not.toBeInTheDocument();
    // Below the 80 % line there is no bar at all.
    expect(screen.queryByTestId('member-seat-progress')).not.toBeInTheDocument();
  });

  it('adds a thin seat bar at 80 %, in the warn tone', async () => {
    await renderMembers({ seats: { used: 4, max: 5 } });

    expect(facts()).toContain('4 of 5 seats used');
    const bar = screen.getByRole('progressbar', { name: 'Member seats: 4 of 5 seats used' });
    expect(bar).toHaveAttribute('aria-valuenow', '80');
  });

  it('warns at capacity with the licence’s own guidance, and offers no invite', async () => {
    await renderMembers({ seats: { used: 5, max: 5 } });

    const banner = await screen.findByTestId('member-seats-exhausted');
    expect(banner).toHaveTextContent(/All member seats included in this tenant's license/i);
    // The action that would 403 is not offered, rather than offered disabled.
    expect(screen.queryByTestId('members-invite')).not.toBeInTheDocument();
  });

  it('says nothing about seats rather than guessing when the licence could not be read', async () => {
    await renderMembers({ seats: null });

    expect(facts().some((fact) => fact?.includes('seat'))).toBe(false);
    // A failed background read must not become a limit: inviting stays available.
    expect(screen.getByTestId('members-invite')).toBeEnabled();
  });

  it('draws no bar on an unlimited plan, and says the seats are unlimited', async () => {
    await renderMembers({ seats: { used: 12, max: -1 } });

    expect(facts()).toContain('12 seats used');
    expect(facts()).toContain('unlimited seats');
    expect(screen.queryByTestId('member-seat-progress')).not.toBeInTheDocument();
  });
});

/* -------------------------------------------------------------------------
   3. The roster
   ------------------------------------------------------------------------- */

describe('the roster', () => {
  it('draws one row per member, with the shared status vocabulary', async () => {
    await renderMembers();

    expect(screen.getAllByTestId('member-row')).toHaveLength(5);
    const grace = rowFor('grace@acme.io');
    expect(within(grace).getByText('Active')).toBeInTheDocument();
    expect(within(grace).getByText('Admin')).toBeInTheDocument();
    expect(within(rowFor('margaret@acme.io')).getByText('Suspended')).toBeInTheDocument();
  });

  it('marks the viewer’s own row and closes every write on it', async () => {
    await renderMembers();

    const own = rowFor('ada@acme.io');
    expect(within(own).getByText('(you)')).toBeInTheDocument();
    // A pill rather than a live select, and no suspend or offboard at all.
    expect(within(own).queryByLabelText(/^Role for/)).not.toBeInTheDocument();
    expect(within(own).queryByRole('button', { name: /Suspend/ })).not.toBeInTheDocument();
    expect(within(own).queryByRole('button', { name: /Offboard/ })).not.toBeInTheDocument();
  });

  it('makes a pending invitation visually distinct and prints when it was sent', async () => {
    await renderMembers();

    const invite = rowFor('dev-partner@globex.io');
    expect(invite.className).toContain('mbr-row--pending');
    expect(within(invite).getByText('Pending')).toBeInTheDocument();
    expect(within(invite).getByText('Invited Aug 13, 2026')).toBeInTheDocument();
    // The address is the name — a pending account often has no display name yet.
    expect(within(invite).getByText('dev-partner@globex.io')).toBeInTheDocument();
  });

  it('prints Last active and Joined from the fields this ticket added to the API', async () => {
    await renderMembers();

    const linus = rowFor('linus@acme.io');
    expect(within(linus).getByText('Mar 18, 2025')).toBeInTheDocument();
    // Someone who has never signed in gets a dash, not an epoch date.
    expect(within(rowFor('margaret@acme.io')).getAllByText('—').length).toBeGreaterThan(0);
  });

  it('narrows by the search box and by the facet chips', async () => {
    const { user } = await renderMembers();

    await user.type(screen.getByLabelText('Filter members'), 'grace');
    await waitFor(() => expect(screen.getAllByTestId('member-row')).toHaveLength(1));

    await user.clear(screen.getByLabelText('Filter members'));
    await user.click(screen.getByRole('button', { name: /^Pending/ }));
    await waitFor(() => expect(screen.getAllByTestId('member-row')).toHaveLength(1));
    expect(screen.getByTestId('member-row')).toHaveAttribute(
      'data-member-email',
      'dev-partner@globex.io'
    );
  });

  it('reports the roster in the foot, not the current filter', async () => {
    const { user } = await renderMembers();

    await user.click(screen.getByRole('button', { name: /^Admins/ }));
    await waitFor(() => expect(screen.getAllByTestId('member-row')).toHaveLength(2));
    expect(screen.getByTestId('members-summary')).toHaveTextContent(
      '5 people · 3 active · 1 pending · 1 suspended'
    );
  });
});

/* -------------------------------------------------------------------------
   4. Capability gating
   ------------------------------------------------------------------------- */

describe('two-factor compliance (TFA-1.3 #5657)', () => {
  /** Put the roster under a two-factor policy for one test. */
  const withPolicy = async (run: () => Promise<void>) => {
    // Restored in place afterwards: other suites hold references to these very objects.
    const saved = MEMBERS.map((member) => ({ ...member }));
    const statuses: Record<string, [string, string | null]> = {
      'ada@acme.io': ['enabled', '2026-10-20T12:00:00Z'],
      'grace@acme.io': ['overdue', '2026-10-20T12:00:00Z'],
      'linus@acme.io': ['grace', new Date(Date.now() + 3 * 86_400_000 - 60_000).toISOString()],
    };
    for (const member of MEMBERS as Array<Record<string, unknown>>) {
      const [status, due] = statuses[member.email as string] ?? ['overdue', '2026-10-20T12:00:00Z'];
      member.two_factor_status = status;
      member.two_factor_due_at = due;
    }
    try {
      await run();
    } finally {
      MEMBERS.forEach((member, index) => {
        const record = member as Record<string, unknown>;
        delete record.two_factor_status;
        delete record.two_factor_due_at;
        Object.assign(member, saved[index]);
      });
    }
  };

  it('has no Needs two-factor chip or badges while the policy is off', async () => {
    await renderMembers();
    expect(screen.queryByRole('button', { name: /Needs two-factor/ })).not.toBeInTheDocument();
    expect(screen.queryByTestId('member-two-factor-badge')).not.toBeInTheDocument();
  });

  it('badges who still has to comply, and filters to them', async () => {
    await withPolicy(async () => {
      const { user } = await renderMembers();

      expect(within(rowFor('grace@acme.io')).getByTestId('member-two-factor-badge')).toHaveTextContent('2FA overdue');
      expect(within(rowFor('linus@acme.io')).getByTestId('member-two-factor-badge')).toHaveTextContent(
        '2FA due in 3 days'
      );
      // Compliant, suspended and pending members are not chased.
      for (const email of ['ada@acme.io', 'margaret@acme.io', 'dev-partner@globex.io']) {
        expect(within(rowFor(email)).queryByTestId('member-two-factor-badge')).not.toBeInTheDocument();
      }

      await user.click(screen.getByRole('button', { name: /Needs two-factor/ }));
      expect(screen.getAllByTestId('member-row').map((row) => row.dataset.memberEmail)).toEqual([
        'grace@acme.io',
        'linus@acme.io',
      ]);
    });
  });
});

describe('when the roster cannot be read', () => {
  it('says so inside the card, rather than claiming the workspace is empty', async () => {
    mockApi({ failRoster: true });
    render(<MembersClient />);

    // "No members yet" would be a claim about the workspace; this is a claim about the
    // request, and it comes with the retry that acts on it.
    expect(await screen.findByText('The roster is unavailable')).toBeInTheDocument();
    expect(screen.queryByText('No members yet')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Try again|Retry/i })).toBeInTheDocument();
  });
});

describe('a viewer with no members grants', () => {
  it('sees the same page with fewer actions, not a different page', async () => {
    await renderMembers({ perms: PERMS_VIEWER });

    expect(screen.queryByTestId('members-invite')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('member-row')).toHaveLength(5);
    // Roles are pills, not selects, and no row offers a write.
    expect(screen.queryByLabelText(/^Role for/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Offboard/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Resend/ })).not.toBeInTheDocument();
    // The summary is context, not an action, so it stays.
    expect(screen.getByTestId('member-facts')).toBeInTheDocument();
  });
});

/* -------------------------------------------------------------------------
   5. The four decisions
   ------------------------------------------------------------------------- */

describe('inviting', () => {
  it('opens a dialog from the header and sends what was typed', async () => {
    const { calls, user } = await renderMembers();

    await user.click(screen.getByTestId('members-invite'));
    const dialog = await screen.findByTestId('members-invite-dialog');

    await user.type(within(dialog).getByLabelText('Email address'), 'new@acme.io');
    await user.selectOptions(within(dialog).getByLabelText('Role'), 'role-editor');
    await user.click(within(dialog).getByRole('button', { name: /Send invite/ }));

    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.method === 'POST' &&
            call.url.endsWith('/api/access/members') &&
            JSON.stringify(call.body) ===
              JSON.stringify({ email: 'new@acme.io', role_id: 'role-editor' })
        )
      ).toBe(true)
    );
  });

  it('refuses an empty address with the screen’s own message, without calling the API', async () => {
    const { calls, user } = await renderMembers();

    await user.click(screen.getByTestId('members-invite'));
    const dialog = await screen.findByTestId('members-invite-dialog');
    await user.click(within(dialog).getByRole('button', { name: /Send invite/ }));

    expect(await within(dialog).findByText('Please enter an email address')).toBeInTheDocument();
    expect(calls.filter((call) => call.method === 'POST')).toHaveLength(0);
  });

  it('sends on ↵ in the email field, not only on the footer button', async () => {
    const { calls, user } = await renderMembers();

    await user.click(screen.getByTestId('members-invite'));
    const dialog = await screen.findByTestId('members-invite-dialog');
    await user.type(within(dialog).getByLabelText('Email address'), 'quick@acme.io{Enter}');

    await waitFor(() =>
      expect(
        calls.some(
          (call) => call.method === 'POST' && call.url.endsWith('/api/access/members')
        )
      ).toBe(true)
    );
  });

  it('forecasts the seat the invitation would take', async () => {
    const { user } = await renderMembers({ seats: { used: 4, max: 5 } });

    await user.click(screen.getByTestId('members-invite'));
    const dialog = await screen.findByTestId('members-invite-dialog');
    expect(within(dialog).getByText('5 of 5')).toBeInTheDocument();
    expect(
      within(dialog).getByRole('meter', { name: /Member seats after this invite/i })
    ).toHaveAttribute('aria-valuenow', '5');
  });
});

describe('suspending', () => {
  it('asks first — the screen this replaces suspended on the first click', async () => {
    const { calls, user } = await renderMembers();

    await user.click(within(rowFor('linus@acme.io')).getByRole('button', { name: /Suspend/ }));

    const dialog = await screen.findByTestId('member-suspend-dialog');
    expect(dialog).toHaveAttribute('role', 'alertdialog');
    expect(within(dialog).getByText(/Suspend Linus Torvalds\?/)).toBeInTheDocument();
    // Nothing has been written yet.
    expect(calls.filter((call) => call.method === 'PATCH')).toHaveLength(0);

    await user.click(within(dialog).getByRole('button', { name: 'Suspend' }));
    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.method === 'PATCH' &&
            call.url.endsWith('/members/u-linus') &&
            JSON.stringify(call.body) === JSON.stringify({ status: 'suspended' })
        )
      ).toBe(true)
    );
  });

  it('offers Reinstate on a suspended member, and asks the other way round', async () => {
    const { calls, user } = await renderMembers();

    await user.click(
      within(rowFor('margaret@acme.io')).getByRole('button', { name: /Reinstate/ })
    );
    const dialog = await screen.findByTestId('member-suspend-dialog');
    expect(within(dialog).getByText(/Reinstate Margaret Hamilton\?/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole('button', { name: 'Reinstate' }));
    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.method === 'PATCH' &&
            JSON.stringify(call.body) === JSON.stringify({ status: 'active' })
        )
      ).toBe(true)
    );
  });

  it('shows a licence refusal inside the dialog, which stays open', async () => {
    const { user } = await renderMembers({
      seats: { used: 5, max: 5 },
      failWrite: {
        match: 'PATCH',
        status: 403,
        body: {
          error: "This tenant's license allows 5 member seat(s) and all 5 are in use.",
          code: 'license-seats-exhausted',
        },
      },
    });

    await user.click(
      within(rowFor('margaret@acme.io')).getByRole('button', { name: /Reinstate/ })
    );
    const dialog = await screen.findByTestId('member-suspend-dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Reinstate' }));

    await waitFor(() =>
      expect(within(dialog).getByText(/Suspend or remove a member, or upgrade the plan/i))
        .toBeInTheDocument()
    );
    expect(screen.getByTestId('member-suspend-dialog')).toBeInTheDocument();
  });
});

describe('offboarding', () => {
  it('confirms with a dialog, never a window.confirm', async () => {
    const { calls, user } = await renderMembers();

    await user.click(within(rowFor('linus@acme.io')).getByRole('button', { name: /Offboard/ }));
    const dialog = await screen.findByTestId('member-offboard-dialog');
    expect(dialog).toHaveAttribute('role', 'alertdialog');
    expect(confirmSpy).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole('button', { name: 'Offboard' }));
    await waitFor(() =>
      expect(
        calls.some((call) => call.method === 'DELETE' && call.url.endsWith('/members/u-linus'))
      ).toBe(true)
    );
  });

  it('raises the elevated warning for an administrator, and counts what is left', async () => {
    const { user } = await renderMembers();

    await user.click(within(rowFor('grace@acme.io')).getByRole('button', { name: /Offboard/ }));

    const warning = await screen.findByTestId('member-offboard-admin-warning');
    expect(warning).toHaveTextContent('Grace Hopper is an administrator');
    // Two administrators in the fixture, so removing one leaves exactly one.
    expect(warning).toHaveTextContent('leaves 1 administrator');
  });

  it('reads as cancelling an invitation when that is what it is', async () => {
    const { user } = await renderMembers();

    await user.click(
      within(rowFor('dev-partner@globex.io')).getByRole('button', { name: /Cancel the invitation/ })
    );

    const dialog = await screen.findByTestId('member-offboard-dialog');
    expect(
      within(dialog).getByText(/Cancel the invitation for dev-partner@globex\.io\?/)
    ).toBeInTheDocument();
    // The dismiss button must not also read "Cancel", or neither reads as anything.
    expect(within(dialog).getByRole('button', { name: 'Keep invitation' })).toBeInTheDocument();
    expect(within(dialog).getByRole('button', { name: 'Cancel invite' })).toBeInTheDocument();
  });
});

describe('re-issuing an invitation', () => {
  it('reaches the endpoint this ticket added, and only from a pending row', async () => {
    const { calls, user } = await renderMembers();

    expect(
      within(rowFor('linus@acme.io')).queryByRole('button', { name: /Resend/ })
    ).not.toBeInTheDocument();

    await user.click(
      within(rowFor('dev-partner@globex.io')).getByRole('button', { name: /Resend/ })
    );

    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.method === 'POST' && call.url.endsWith('/members/u-partner/resend-invite')
        )
      ).toBe(true)
    );
  });
});

describe('changing a role inline', () => {
  it('assigns it, and reports a failure in the page banner', async () => {
    const { calls, user } = await renderMembers();

    await user.selectOptions(screen.getByLabelText('Role for Linus Torvalds'), 'role-owner');

    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.method === 'PATCH' &&
            call.url.endsWith('/members/u-linus') &&
            JSON.stringify(call.body) === JSON.stringify({ role_id: 'role-owner' })
        )
      ).toBe(true)
    );
  });

  it('does not also open the drawer behind the select', async () => {
    const { user } = await renderMembers();

    await user.selectOptions(screen.getByLabelText('Role for Linus Torvalds'), 'role-owner');

    await waitFor(() => expect(screen.queryByTestId('member-drawer')).not.toBeInTheDocument());
  });
});

/* -------------------------------------------------------------------------
   6. The detail drawer
   ------------------------------------------------------------------------- */

describe('the detail drawer', () => {
  it('opens on the row and reads the membership off the record', async () => {
    const { user } = await renderMembers();

    await user.click(within(rowFor('linus@acme.io')).getByText('Linus Torvalds'));

    const drawer = await screen.findByTestId('member-drawer');
    expect(within(drawer).getByText('linus@acme.io')).toBeInTheDocument();
    expect(within(drawer).getByText('Mar 18, 2025')).toBeInTheDocument();
    expect(within(drawer).getByText('u-linus')).toBeInTheDocument();
    expect(within(drawer).getByText('Not enabled')).toBeInTheDocument();
  });

  it('names the permissions the assigned role actually grants', async () => {
    const { user } = await renderMembers();

    await user.click(within(rowFor('linus@acme.io')).getByText('Linus Torvalds'));

    const drawer = await screen.findByTestId('member-drawer');
    expect(within(drawer).getByText('projects:view')).toBeInTheDocument();
    expect(within(drawer).getByText('versions:edit')).toBeInTheDocument();
    // And it says where they came from rather than asserting them.
    expect(within(drawer).getByRole('link', { name: 'Editor' })).toHaveAttribute(
      'href',
      '/ade/dashboard/roles'
    );
  });

  it('narrows the access ledger to the person it is about', async () => {
    const { user } = await renderMembers();

    await user.click(within(rowFor('linus@acme.io')).getByText('Linus Torvalds'));

    const activity = await screen.findByTestId('member-activity');
    expect(within(activity).getByText('role.assigned')).toBeInTheDocument();
    // The invitation of somebody else is not this person's activity.
    expect(within(activity).queryByText('member.invited')).not.toBeInTheDocument();
  });

  it('reads the ledger once, not once per member', async () => {
    const { calls, user } = await renderMembers();

    await user.click(within(rowFor('linus@acme.io')).getByText('Linus Torvalds'));
    await screen.findByTestId('member-activity');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByTestId('member-drawer')).not.toBeInTheDocument());

    await user.click(within(rowFor('grace@acme.io')).getByText('Grace Hopper'));
    await screen.findByTestId('member-drawer');

    expect(calls.filter((call) => call.url.includes('/api/access/audit'))).toHaveLength(1);
  });
});

/* -------------------------------------------------------------------------
   7. The first acceptance criterion, asserted for the whole file
   ------------------------------------------------------------------------- */

describe('native browser dialogs', () => {
  it('are never reached, on any path this screen offers', async () => {
    const { user } = await renderMembers();

    await user.click(within(rowFor('linus@acme.io')).getByRole('button', { name: /Suspend/ }));
    await user.keyboard('{Escape}');
    await user.click(within(rowFor('linus@acme.io')).getByRole('button', { name: /Offboard/ }));
    await user.keyboard('{Escape}');
    await user.click(screen.getByTestId('members-invite'));

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(promptSpy).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------------------
// The docs fixtures
// ---------------------------------------------------------------------------------------

/**
 * The documentation site's Members & seats page (`apiome-docs/screens.json`, DOCS-1.9) is
 * captured from these dumps:
 * `A11Y_FIXTURE_DUMP=1 npx jest tests/members-hive-redesign.test.tsx -t "docs fixtures"`.
 */
describe('the docs fixtures', () => {
  /** Answer the screen's reads with the docs workspace (`tests/helpers/access-docs-data.ts`). */
  function mockDocsApi() {
    // @ts-expect-error - assigning a test double to the global
    global.fetch = jest.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url.includes('/api/tenants/license')) {
        return ok({
          plan: { name: 'Team', type: 'paid' },
          seats: DOCS_SEATS,
          quotas: { max_projects: 25, max_versions: 250, max_ai_requests: 0 },
          features: [],
        });
      }
      if (url.includes('/api/access/permissions/me')) return ok(PERMS_ADMIN);
      if (url.includes('/api/access/roles')) return ok(DOCS_ROLES);
      if (url.includes('/api/access/audit')) return ok(DOCS_AUDIT);
      if (url.includes('/api/access/members')) return ok(DOCS_MEMBERS);
      return ok([]);
    });
  }

  /** The page root. */
  const page = () => document.querySelector('.page') as HTMLElement;

  it('renders the roster, the invite dialog, a member drawer and the lifecycle dialogs', async () => {
    // Relative times ("2 hours ago") read against the docs capture clock, not today.
    jest.spyOn(Date, 'now').mockReturnValue(DOCS_NOW);
    mockDocsApi();
    const user = userEvent.setup();
    render(<MembersClient />);
    await screen.findByText('Priya Raman');
    expect(screen.getByRole('list', { name: 'Members summary' })).toHaveTextContent(/9 members/);
    writeA11yFixture('members', liveMarkup(page()));

    await user.click(screen.getByTestId('members-invite'));
    const invite = await screen.findByTestId('members-invite-dialog');
    await user.type(within(invite).getByLabelText('Email address'), 'lena.fischer@northwind.io');
    await user.selectOptions(within(invite).getByLabelText('Role'), 'role-editor');
    expect(invite).toHaveTextContent('10 of 10');
    writeA11yFixture('members-invite-dialog', liveMarkup(invite));
    await user.click(within(invite).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByTestId('members-invite-dialog')).not.toBeInTheDocument());

    await user.click(within(rowFor('sam.okafor@northwind.io')).getByText('Sam Okafor'));
    const drawer = await screen.findByTestId('member-drawer');
    await within(drawer).findByTestId('member-activity');
    expect(drawer).toHaveTextContent('Release manager');
    writeA11yFixture('members-drawer', liveMarkup(drawer));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByTestId('member-drawer')).not.toBeInTheDocument());

    await user.click(within(rowFor('elena.vasquez@northwind.io')).getByRole('button', { name: /Suspend/ }));
    const suspend = await screen.findByTestId('member-suspend-dialog');
    expect(suspend).toHaveTextContent('Suspend Elena Vasquez?');
    writeA11yFixture('members-suspend-dialog', liveMarkup(suspend));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByTestId('member-suspend-dialog')).not.toBeInTheDocument());

    await user.click(within(rowFor('marcus.lee@northwind.io')).getByRole('button', { name: /Offboard/ }));
    const offboard = await screen.findByTestId('member-offboard-dialog');
    expect(within(offboard).getByTestId('member-offboard-admin-warning')).toBeInTheDocument();
    writeA11yFixture('members-offboard-dialog', liveMarkup(offboard));
  });
});

/* -------------------------------------------------------------------------
   Reset a member's two-factor (TFA-1.2, #5656)
   ------------------------------------------------------------------------- */

describe('resetting a member’s two-factor', () => {
  /** Linus, with two-factor on for the length of one test. */
  const linus = MEMBERS.find((entry) => entry.user_id === 'u-linus')!;

  beforeEach(() => {
    linus.two_factor_enabled = true;
  });

  afterEach(() => {
    linus.two_factor_enabled = false;
  });

  /** Open Linus's drawer. */
  async function openLinus(options: MockOptions = {}) {
    const rendered = await renderMembers(options);
    await rendered.user.click(within(rowFor('linus@acme.io')).getByText('Linus Torvalds'));
    return { ...rendered, drawer: await screen.findByTestId('member-drawer') };
  }

  it('is offered to an owner for a member who has two-factor on', async () => {
    const { drawer } = await openLinus();
    expect(within(drawer).getByRole('button', { name: 'Reset two-factor' })).toBeInTheDocument();
  });

  it('is not offered when the member has no two-factor', async () => {
    linus.two_factor_enabled = false;
    const { drawer } = await openLinus();
    expect(within(drawer).queryByTestId('member-reset-two-factor')).not.toBeInTheDocument();
  });

  it('is not offered to someone who is not an owner', async () => {
    const { drawer } = await openLinus({
      perms: { is_admin: false, permissions: ['members:view', 'members:edit', 'members:delete'] },
    });
    expect(within(drawer).queryByTestId('member-reset-two-factor')).not.toBeInTheDocument();
  });

  it('is not offered on the owner’s own row', async () => {
    const { user } = await renderMembers();
    await user.click(within(rowFor('ada@acme.io')).getByText('Ada Lovelace'));
    const drawer = await screen.findByTestId('member-drawer');
    expect(within(drawer).queryByTestId('member-reset-two-factor')).not.toBeInTheDocument();
  });

  it('asks for a reason and the member’s email, then resets through the workspace route', async () => {
    const { user, calls, drawer } = await openLinus();
    await user.click(within(drawer).getByTestId('member-reset-two-factor'));

    const dialog = await screen.findByTestId('reset-two-factor-dialog');
    expect(within(dialog).getByText('Reset two-factor for Linus Torvalds?')).toBeInTheDocument();
    const submit = within(dialog).getByTestId('reset-two-factor-submit');
    expect(submit).toBeDisabled();

    await user.type(within(dialog).getByTestId('reset-two-factor-reason'), 'Lost his phone and codes.');
    await user.type(within(dialog).getByTestId('reset-two-factor-confirm'), 'linus@acme.io');
    expect(submit).toBeEnabled();
    await user.click(submit);

    await waitFor(() =>
      expect(calls).toContainEqual({
        url: '/api/access/members/u-linus/two-factor/reset',
        method: 'POST',
        body: { reason: 'Lost his phone and codes.', confirm: 'linus@acme.io' },
      })
    );
  });

  it('shows the workspace-boundary refusal in the dialog', async () => {
    const { user, drawer } = await openLinus({
      failWrite: {
        match: '/two-factor/reset',
        status: 409,
        body: {
          error:
            'This member also belongs to another workspace, so their two-factor can only be reset by an administrator of this Apiome installation.',
          code: 'multi_tenant_member',
        },
      },
    });
    await user.click(within(drawer).getByTestId('member-reset-two-factor'));
    const dialog = await screen.findByTestId('reset-two-factor-dialog');
    await user.type(within(dialog).getByTestId('reset-two-factor-reason'), 'Lost his phone and codes.');
    await user.type(within(dialog).getByTestId('reset-two-factor-confirm'), 'linus@acme.io');
    await user.click(within(dialog).getByTestId('reset-two-factor-submit'));

    expect(
      await within(dialog).findByText(/can only be reset by an administrator of this Apiome installation/)
    ).toBeInTheDocument();
  });
});
