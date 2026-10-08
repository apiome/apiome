/**
 * The Hive application shell (HIVE-3.1, #5287).
 *
 * The ticket's acceptance criteria are behavioural — one chrome, a collapse that persists,
 * a tooltip for every icon, a gated item that says why — so this suite drives the shell
 * the way a reader does: mount `AdeAppShell` over a mocked session, then click, type and
 * focus. Every expectation about *destinations* is derived from `lib/platform-nav.ts`
 * rather than written out, so a rail that stops rendering the model fails here.
 *
 * What is deliberately not asserted: how the collapsed rail *looks*. The width, the hidden
 * labels and the group hairlines are CSS keyed on `data-rail` and a media query — jsdom
 * applies no stylesheet, so those live in `tests/app-shell-css.test.ts` and the e2e suite.
 */

import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockUsePathname = jest.fn<string, []>();
const mockUseSession = jest.fn<{ data: unknown }, []>();
const mockCommercialAccess = jest.fn<Promise<{ navItems: unknown[] }>, []>();
const mockTenantContext = jest.fn<
  Promise<{
    tenants: { id: string; name: string; role?: string; licenseName?: string }[];
    adminTenantIds: string[];
    createTenant: { allowed: boolean; used: number; max: number } | null;
  }>,
  []
>();
const mockSignOut = jest.fn<Promise<void>, [string]>();

jest.mock('next/navigation', () => ({
  usePathname: () => mockUsePathname(),
  // The workspace switcher (HIVE-3.3) refreshes the server components after a switch.
  useRouter: () => ({ refresh: jest.fn(), push: jest.fn() }),
}));

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

jest.mock('@lib/auth/session-client', () => ({
  AuthSessionProvider: ({ children }: { children: unknown }) => children,
  signOut: jest.fn(),
  useAuthSession: () => mockUseSession(),
}));

jest.mock('@lib/db/commercial-access', () => ({
  getCommercialAccessForSession: () => mockCommercialAccess(),
}));

jest.mock('@lib/auth/tenant-membership-context', () => ({
  loadTenantMembershipContext: () => mockTenantContext(),
}));

jest.mock('@lib/auth/sign-out-client', () => ({
  signOutEverywhere: (callbackUrl: string) => mockSignOut(callbackUrl),
}));

jest.mock('@lib/auth/last-active-tenant-actions', () => ({
  persistLastActiveTenant: jest.fn(async () => undefined),
}));

// The create-workspace dialog is a server-action client of its own, covered by
// `create-tenant-dialog.test.tsx`; the shell only cares that the menu can open it.
jest.mock('@/app/components/ade/CreateTenantDialog', () => ({
  __esModule: true,
  default: ({ open }: { open: boolean }) =>
    open ? <div data-testid="create-tenant-dialog-stub" /> : null,
}));

// next-themes still owns the `.dark` class; stubbing only its hook keeps the real
// `ThemeProvider` — which the preferences pane the rail hosts asks for — in the test.
jest.mock('next-themes', () => ({
  useTheme: () => ({ setTheme: jest.fn() }),
}));

import AdeAppShell from '../src/app/components/shell/AdeAppShell';
import AppShell from '../src/app/components/shell/AppShell';
import RailSearchTrigger from '../src/app/components/shell/RailSearchTrigger';
import { isCommandPaletteMounted, openCommandPalette } from '../src/app/components/shell/commandPaletteBus';
import { openShortcutSheet } from '../src/app/components/shell/shortcutSheetBus';
import { ThemeProvider } from '../src/app/providers/ThemeProvider';
import { NAV_COLLAPSED_STORAGE_KEY } from '../src/app/components/shell/navGroupCollapse';
import { RAIL_ICON_BREAKPOINT_PX } from '../src/app/components/shell/useIconRail';
import {
  isPreferencesDrawerMounted,
  openPreferences,
} from '../src/app/components/ade/preferences/preferencesDrawerBus';
import { RAIL_SHORTCUT, formatShortcutKeys, matchesShortcutChord } from '../lib/shortcuts';
import {
  PLATFORM_NAV_GROUPS,
  PLATFORM_USER_MENU_ITEMS,
  getPlatformNavGroups,
  platformNavGatedReason,
  type PlatformNavItem,
} from '../lib/platform-nav';
import NotificationsClient from '../src/app/ade/dashboard/notifications/NotificationsClient';
import { NOTIFICATION_TYPES, type NotificationRow } from '../lib/notifications';
import { NOTIFICATION_PREFERENCE_KEYS } from '../lib/notification-preferences';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

/** Every rail destination the model describes, flattened. */
const MODEL_ITEMS: PlatformNavItem[] = PLATFORM_NAV_GROUPS.flatMap((group) => group.items);

/** The headings the model asks for, in model order. */
const GROUP_LABELS = PLATFORM_NAV_GROUPS.map((group) => group.label).filter(
  (label): label is string => Boolean(label)
);

/** A workspace-scoped destination, taken from the model rather than named. */
const GATED_ITEM = MODEL_ITEMS.find((item) => item.requiresTenant)!;

/** Viewport width the mocked `matchMedia` answers against. */
let viewportWidth = 1440;

/**
 * Install the `matchMedia` jsdom does not implement, answering the icon-rail query from
 * {@link viewportWidth} so a test can put the shell on a narrow screen.
 */
function mockMatchMedia(): void {
  window.matchMedia = ((query: string) => ({
    media: query,
    get matches() {
      const max = /max-width:\s*(\d+)px/.exec(query);
      return max ? viewportWidth <= Number(max[1]) : false;
    },
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    addListener: jest.fn(),
    removeListener: jest.fn(),
    dispatchEvent: jest.fn(),
    onchange: null,
  })) as unknown as typeof window.matchMedia;
}

/** Options for {@link renderShell}. */
interface RenderShellOptions {
  /** Route the shell believes it is on. */
  pathname?: string;
  /** Whether the session carries a workspace. */
  tenant?: boolean;
  /** What the shell frames; a placeholder line by default. */
  children?: React.ReactNode;
}

/**
 * Mount the shell over a mocked session and let its two loaders settle.
 *
 * @param options See {@link RenderShellOptions}.
 */
async function renderShell({
  pathname = '/ade/dashboard',
  tenant = true,
  children = 'page content',
}: RenderShellOptions = {}) {
  mockUsePathname.mockReturnValue(pathname);
  mockUseSession.mockReturnValue({
    data: {
      user: {
        user_id: 'u-1',
        name: 'Ada Lovelace',
        email: 'ada@example.com',
        ...(tenant ? { current_tenant_id: 't-1' } : {}),
      },
    },
  });

  // `ThemeProvider` is what `/ade/layout.tsx` puts above every route in the shell; the
  // preferences pane the rail hosts reads it.
  const view = render(
    <ThemeProvider>
      <AdeAppShell>{children}</AdeAppShell>
    </ThemeProvider>
  );
  // Both effects resolve immediately; flushing them here keeps every test free of the
  // "not wrapped in act(...)" warning the loaders would otherwise produce.
  await act(async () => {
    await Promise.resolve();
  });
  return view;
}

beforeEach(() => {
  mockUsePathname.mockReset();
  mockUseSession.mockReset();
  mockSignOut.mockReset();
  mockSignOut.mockResolvedValue(undefined);
  mockCommercialAccess.mockReset();
  mockCommercialAccess.mockResolvedValue({ navItems: [] });
  mockTenantContext.mockReset();
  mockTenantContext.mockResolvedValue({
    tenants: [{ id: 't-1', name: 'Acme Corp', role: 'owner', licenseName: 'Free' }],
    adminTenantIds: [],
    createTenant: { allowed: true, used: 1, max: 5 },
  });

  viewportWidth = 1440;
  mockMatchMedia();
  window.localStorage.clear();
  document.documentElement.removeAttribute('data-rail');
});

describe('AppShell — one chrome', () => {
  it('renders a single primary navigation, and the page beside it', async () => {
    await renderShell();

    expect(screen.getAllByRole('navigation', { name: 'Primary' })).toHaveLength(1);
    const main = document.getElementById('main-content');
    expect(main).not.toBeNull();
    expect(main).toHaveTextContent('page content');
    // Nothing is rendered above the page: the rail and the page are siblings in one grid.
    expect(main?.parentElement).toHaveClass('hive-shell');
  });

  it('starts with a skip link that reaches the page', async () => {
    await renderShell();

    const skip = screen.getByRole('link', { name: 'Skip to content' });
    expect(skip).toHaveAttribute('href', '#main-content');
    // Focusable, so following the link moves the caret into the page instead of leaving it
    // in the rail with every destination still ahead of it.
    expect(document.getElementById('main-content')).toHaveAttribute('tabindex', '-1');
    // First in the DOM, so it is the first thing Tab reaches.
    expect(skip.compareDocumentPosition(screen.getByTestId('app-rail'))).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
  });

  it('links the brand back to the app launcher and hosts the preferences pane', async () => {
    await renderShell();

    expect(screen.getByTestId('rail-brand')).toHaveAttribute('href', '/ade');
    expect(isPreferencesDrawerMounted()).toBe(true);
  });
});

describe('AppShell — navigation from the model', () => {
  it('renders every modelled destination once, with its href', async () => {
    await renderShell();

    const nav = screen.getByRole('navigation', { name: 'Primary' });
    for (const item of MODEL_ITEMS) {
      const row = within(nav).getByTestId(`rail-nav-${item.id}`);
      expect(row).toHaveTextContent(item.label);
      expect(row).toHaveAttribute('href', item.href);
    }
    expect(within(nav).getAllByRole('link')).toHaveLength(MODEL_ITEMS.length);
  });

  it('renders a heading for every labelled group, and none for the leading run', async () => {
    await renderShell();

    const nav = screen.getByRole('navigation', { name: 'Primary' });
    for (const label of GROUP_LABELS) {
      expect(within(nav).getByRole('button', { name: new RegExp(label, 'i') })).toBeInTheDocument();
    }
    expect(within(nav).getAllByRole('button')).toHaveLength(GROUP_LABELS.length);
  });

  it('keeps account destinations out of the rail — they belong to the user menu', async () => {
    await renderShell();

    const nav = screen.getByRole('navigation', { name: 'Primary' });
    for (const item of PLATFORM_USER_MENU_ITEMS) {
      expect(within(nav).queryByTestId(`rail-nav-${item.id}`)).not.toBeInTheDocument();
    }
  });

  it('marks the current page, and only it', async () => {
    await renderShell({ pathname: '/ade/dashboard/catalog' });

    const current = screen.getAllByRole('link').filter((link) => link.getAttribute('aria-current'));
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveAttribute('data-testid', 'rail-nav-catalog');
    // The raised white pill of DESIGN.md §5.2, spelled as its elevation token.
    expect(current[0].className).toContain('shadow-raised');
  });

  it('places a commercial destination the host contributes in its reserved slot', async () => {
    mockCommercialAccess.mockResolvedValue({
      navItems: [{ id: 'suite-designer', label: 'Designer', href: 'https://suite.example/x' }],
    });
    await renderShell();

    const contributed = await screen.findByTestId('rail-nav-suite-designer');
    expect(contributed).toHaveAttribute('href', 'https://suite.example/x');
    const build = document.getElementById('rail-group-build');
    expect(build).not.toBeNull();
    expect(build).toContainElement(contributed);
  });
});

describe('AppShell — workspace gating', () => {
  it('renders a gated destination as a non-interactive control that explains itself', async () => {
    await renderShell({ tenant: false });

    const row = screen.getByTestId(`rail-nav-${GATED_ITEM.id}`);
    expect(row.tagName).toBe('BUTTON');
    expect(row).toHaveAttribute('aria-disabled', 'true');
    expect(row).not.toHaveAttribute('href');

    const reasonId = row.getAttribute('aria-describedby');
    expect(reasonId).toBeTruthy();
    expect(document.getElementById(reasonId!)).toHaveTextContent(
      platformNavGatedReason(GATED_ITEM.label)
    );
  });

  it('gates exactly the destinations the model gates', async () => {
    await renderShell({ tenant: false });

    const expected = getPlatformNavGroups({})
      .flatMap((group) => group.items)
      .filter((item) => item.disabled)
      .map((item) => item.id);

    for (const item of MODEL_ITEMS) {
      const row = screen.getByTestId(`rail-nav-${item.id}`);
      expect(row.getAttribute('aria-disabled')).toBe(expected.includes(item.id) ? 'true' : null);
    }
  });

  it('leaves every destination reachable once a workspace is selected', async () => {
    await renderShell({ tenant: true });

    for (const item of MODEL_ITEMS) {
      expect(screen.getByTestId(`rail-nav-${item.id}`)).not.toHaveAttribute('aria-disabled');
    }
  });
});

describe('AppShell — collapsing the rail', () => {
  it('toggles with the handle, and says which way it will go', async () => {
    await renderShell();

    const handle = screen.getByTestId('rail-collapse');
    expect(handle).toHaveAccessibleName('Collapse sidebar');

    fireEvent.click(handle);

    expect(document.documentElement).toHaveAttribute('data-rail', 'collapsed');
    expect(window.localStorage.getItem('hive.rail')).toBe('collapsed');
    expect(screen.getByTestId('rail-collapse')).toHaveAccessibleName('Expand sidebar');

    fireEvent.click(screen.getByTestId('rail-collapse'));
    expect(document.documentElement).toHaveAttribute('data-rail', 'expanded');
  });

  it.each([
    ['⌘\\', { metaKey: true }],
    ['Ctrl+\\', { ctrlKey: true }],
  ])('toggles with %s', async (_name, modifiers) => {
    await renderShell();

    fireEvent.keyDown(window, { key: '\\', ...modifiers });
    expect(document.documentElement).toHaveAttribute('data-rail', 'collapsed');

    fireEvent.keyDown(window, { key: '\\', ...modifiers });
    expect(document.documentElement).toHaveAttribute('data-rail', 'expanded');
  });

  it('ignores a bare backslash, so typing one never moves the rail', async () => {
    await renderShell();

    fireEvent.keyDown(window, { key: '\\' });
    expect(document.documentElement).not.toHaveAttribute('data-rail', 'collapsed');
  });

  it('starts collapsed when that is the stored preference, across a remount', async () => {
    window.localStorage.setItem('hive.rail', 'collapsed');
    const { unmount } = await renderShell();

    expect(screen.getByTestId('rail-collapse')).toHaveAccessibleName('Expand sidebar');
    unmount();

    await renderShell({ pathname: '/ade/dashboard/members' });
    expect(screen.getByTestId('rail-collapse')).toHaveAccessibleName('Expand sidebar');
    expect(document.documentElement).toHaveAttribute('data-rail', 'collapsed');
  });

  it('stops listening for the shortcut once the shell unmounts', async () => {
    const { unmount } = await renderShell();
    // The provider persists the default on mount, so "unchanged" is the assertion — a
    // listener that outlived its shell would write `collapsed` here.
    expect(window.localStorage.getItem('hive.rail')).toBe('expanded');
    unmount();

    fireEvent.keyDown(window, { key: '\\', metaKey: true });
    expect(window.localStorage.getItem('hive.rail')).toBe('expanded');
    expect(document.documentElement).toHaveAttribute('data-rail', 'expanded');
  });
});

describe('AppShell — folding a nav group', () => {
  it('folds on click, announces the state, and remembers it', async () => {
    await renderShell();

    const toggle = screen.getByTestId('rail-group-toggle-build');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(document.getElementById('rail-group-build')).not.toBeVisible();
    expect(JSON.parse(window.localStorage.getItem(NAV_COLLAPSED_STORAGE_KEY)!)).toEqual(['build']);
  });

  it('restores a fold stored by an earlier visit', async () => {
    window.localStorage.setItem(NAV_COLLAPSED_STORAGE_KEY, JSON.stringify(['govern']));
    await renderShell();

    await waitFor(() =>
      expect(screen.getByTestId('rail-group-toggle-govern')).toHaveAttribute(
        'aria-expanded',
        'false'
      )
    );
    expect(screen.getByTestId('rail-group-toggle-build')).toHaveAttribute('aria-expanded', 'true');
  });

  it('unfolds every group in the icon rail, where no heading could undo the fold', async () => {
    window.localStorage.setItem(NAV_COLLAPSED_STORAGE_KEY, JSON.stringify(['build']));
    window.localStorage.setItem('hive.rail', 'collapsed');
    await renderShell();

    expect(document.getElementById('rail-group-build')).toBeVisible();
  });

  it('survives a stored value that is not a list of group ids', async () => {
    window.localStorage.setItem(NAV_COLLAPSED_STORAGE_KEY, '{"build":true}');
    await renderShell();

    expect(screen.getByTestId('rail-group-toggle-build')).toHaveAttribute('aria-expanded', 'true');
  });
});

describe('AppShell — the icon rail', () => {
  it('names every destination in a tooltip once the labels are gone', async () => {
    window.localStorage.setItem('hive.rail', 'collapsed');
    await renderShell();

    const home = screen.getByTestId('rail-nav-home');
    fireEvent.focus(home);

    expect(await screen.findByRole('tooltip')).toHaveTextContent('Home');
  });

  it('is forced below the responsive breakpoint, whatever the preference says', async () => {
    viewportWidth = RAIL_ICON_BREAKPOINT_PX - 1;
    await renderShell();

    fireEvent.focus(screen.getByTestId('rail-nav-home'));
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Home');
  });

  it('says nothing on hover while the labels are on screen', async () => {
    await renderShell();

    fireEvent.focus(screen.getByTestId('rail-nav-home'));
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('still explains a gated destination in the expanded rail', async () => {
    await renderShell({ tenant: false });

    fireEvent.focus(screen.getByTestId(`rail-nav-${GATED_ITEM.id}`));
    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      platformNavGatedReason(GATED_ITEM.label)
    );
  });
});

describe('AppShell — its regions', () => {
  it('mounts the workspace switcher in region 2, naming the active workspace', async () => {
    await renderShell();

    const workspace = await screen.findByTestId('rail-workspace');
    expect(workspace).toHaveTextContent('Acme Corp');
    expect(workspace).toHaveTextContent('Owner · Free');
    // A switcher now, not the interim link to the tenants page (HIVE-3.3, #5289).
    expect(workspace).toHaveAttribute('aria-haspopup', 'menu');
  });

  it('opens the switcher menu from the rail', async () => {
    await renderShell();

    fireEvent.click(await screen.findByTestId('rail-workspace'));

    expect(screen.getByRole('menu', { name: 'Your workspaces' })).toBeInTheDocument();
  });

  it('says so plainly when there is no workspace yet', async () => {
    await renderShell({ tenant: false });

    expect(screen.getByTestId('rail-workspace')).toHaveTextContent('No workspace');
  });

  it('keeps the workspace row usable when the membership call fails', async () => {
    mockTenantContext.mockRejectedValue(new Error('offline'));
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});

    await renderShell();

    await waitFor(() =>
      expect(screen.getByTestId('rail-workspace')).toHaveTextContent('No workspace')
    );
    consoleError.mockRestore();
  });

  it('names the signed-in user on the footer button that opens their menu', async () => {
    await renderShell();

    // The row itself is the menu trigger from HIVE-3.4 (#5290); the destinations it used
    // to be are inside it now, and `tests/rail-user-menu.test.tsx` drives them.
    const trigger = screen.getByTestId('rail-user');
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    expect(trigger).toHaveTextContent('Ada Lovelace');
    expect(trigger).toHaveTextContent('ada@example.com');

    fireEvent.click(trigger);
    expect(screen.getByTestId('user-menu-profile')).toHaveAttribute(
      'href',
      '/ade/dashboard/profile'
    );

    fireEvent.click(screen.getByTestId('user-menu-sign-out'));
    expect(mockSignOut).toHaveBeenCalledWith('/login');
  });

  it('offers help before preferences in the footer, as DESIGN.md §5.2 orders them', async () => {
    await renderShell();

    expect(screen.getByTestId('rail-help')).toHaveAttribute('href', '/ade/dashboard/help');
    expect(
      screen
        .getByTestId('rail-help')
        .compareDocumentPosition(screen.getByTestId('rail-preferences'))
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('opens the preferences pane from the footer', async () => {
    await renderShell();

    fireEvent.click(screen.getByTestId('rail-preferences'));

    expect(await screen.findByRole('dialog')).toHaveTextContent(/preferences/i);
  });

  it('offers the search trigger in region 3, above the navigation (HIVE-3.6)', async () => {
    await renderShell();

    const trigger = screen.getByTestId('rail-search');
    expect(trigger).toBeInTheDocument();
    // Region 3 sits between the workspace row and the nav groups (`DESIGN.md` §5.2).
    expect(screen.getByTestId('rail-workspace').compareDocumentPosition(trigger)).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING
    );
    expect(
      trigger.compareDocumentPosition(screen.getByRole('navigation', { name: 'Primary' }))
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it('hosts the command palette, so the trigger and ⌘K reach the same dialog', async () => {
    await renderShell();

    expect(isCommandPaletteMounted()).toBe(true);

    fireEvent.click(screen.getByTestId('rail-search'));

    expect(await screen.findByRole('dialog')).toHaveAccessibleName('Command palette');
  });

  it('draws no search trigger for a shell that hosts no palette', async () => {
    // What the admin console's rail needs: `foundations/shell.html` specifies it with no
    // ⌘K search at all, because it has no workspace scope to search within.
    mockUsePathname.mockReturnValue('/ade/dashboard');
    mockUseSession.mockReturnValue({ data: { user: { user_id: 'u-1', current_tenant_id: 't-1' } } });

    render(
      <ThemeProvider>
        <AppShell
          groups={getPlatformNavGroups({ currentTenantId: 't-1' })}
          pathname="/ade/dashboard"
          commandPalette={false}
          search={({ iconRail }) => <RailSearchTrigger iconRail={iconRail} />}
        >
          page content
        </AppShell>
      </ThemeProvider>
    );
    await act(async () => {
      await Promise.resolve();
    });

    expect(isCommandPaletteMounted()).toBe(false);
    expect(screen.queryByTestId('rail-search')).not.toBeInTheDocument();
  });
});

describe('AppShell — the shortcut is documented where readers look for it', () => {
  it('prints the chord the matcher actually accepts', () => {
    // Since HIVE-3.7 (#5293) the chip and the matcher are the *same* declaration, so this
    // asserts the declaration rather than that two hand-written lists agree.
    expect(formatShortcutKeys(RAIL_SHORTCUT)).toEqual(['⌘', '\\']);
    expect(RAIL_SHORTCUT.description).toMatch(/sidebar/i);
    expect(
      matchesShortcutChord(
        { key: '\\', metaKey: true, ctrlKey: false, altKey: false, shiftKey: false },
        RAIL_SHORTCUT.chord!
      )
    ).toBe(true);
  });
});

describe('AppShell — accessibility', () => {
  it('has no axe violations, expanded', async () => {
    const { container } = await renderShell();

    expect(await axe(container)).toHaveNoViolations();
  });

  it('has no axe violations with a gated rail', async () => {
    const { container } = await renderShell({ tenant: false });

    expect(await axe(container)).toHaveNoViolations();
  });

  it('has no axe violations in the icon rail', async () => {
    window.localStorage.setItem('hive.rail', 'collapsed');
    const { container } = await renderShell();

    expect(await axe(container)).toHaveNoViolations();
  });
});

describe('AppShell — the a11y gate fixture (HIVE-10.2)', () => {
  it('renders the shell (and writes its fixture on request)', async () => {
    const { container } = await renderShell();
    writeA11yFixture('shell', container.innerHTML);
  });
});

// ---------------------------------------------------------------------------------------
// The docs fixtures
// ---------------------------------------------------------------------------------------

/**
 * The documentation site's Preferences theme gallery and Notifications page
 * (`apiome-docs/screens.json`, DOCS-1.9) are captured from these dumps:
 * `A11Y_FIXTURE_DUMP=1 npx jest tests/app-shell.test.tsx -t "docs fixtures"`.
 *
 * The gallery needs a screen with every kind of ink on it — the rail, a page header, filter
 * chips, primary and secondary buttons, unread markers — so it is the shell framing the
 * notification centre, the same markup captured once per theme.
 */
describe('the docs fixtures', () => {
  const HOUR = 60 * 60 * 1000;

  /** A week of a reviewer's inbox at Northwind, newest first, relative to now. */
  function docsInbox(now: number): NotificationRow[] {
    const base = {
      tenant_id: 't-1',
      user_id: 'u-1',
      project_id: 'prj-payments',
      version_id: 'ver-payments-2-4-0',
    };
    const rows: Array<[string, NotificationRow['type'], string, Record<string, unknown>, number, boolean]> = [
      ['ntf-1', 'review_requested', 'Priya Raman', { project_name: 'Payments API', version_label: '2.4.0', review_id: 'rvw-24', round: 1 }, 1, false],
      ['ntf-2', 'mention', 'Marcus Lee', { project_name: 'Payments API', version_label: '2.4.0', thread_id: 'thr-7', excerpt: '@ada should refunds return 202 while the ledger settles?' }, 3, false],
      ['ntf-3', 'review_decision', 'Sam Okafor', { project_name: 'Orders Service', version_label: '1.9.0', review_id: 'rvw-19', decision: 'approve' }, 5, false],
      ['ntf-4', 'thread_resolved', 'Elena Vasquez', { project_name: 'Payments API', version_label: '2.3.1', thread_id: 'thr-5' }, 27, true],
      ['ntf-5', 'version_published', 'Priya Raman', { project_name: 'Orders Service', version_label: '1.8.2' }, 30, true],
      ['ntf-6', 'review_decision', 'Tomas Berg', { project_name: 'Customer Profiles', version_label: '0.7.0', review_id: 'rvw-7', decision: 'request_changes' }, 74, true],
    ];
    return rows.map(([id, type, actor, payload, hoursAgo, read]) => ({
      ...base,
      id,
      type,
      actor_id: `u-${actor.split(' ')[0].toLowerCase()}`,
      actor_name: actor,
      payload,
      read_at: read ? new Date(now - (hoursAgo - 1) * HOUR).toISOString() : null,
      created_at: new Date(now - hoursAgo * HOUR).toISOString(),
    }));
  }

  /**
   * Answer the notification routes from {@link docsInbox}; everything else is a 404.
   *
   * @param inbox The rows the inbox holds.
   */
  function installInbox(inbox: NotificationRow[]): void {
    const unread = inbox.filter((row) => row.read_at === null);
    const byType = Object.fromEntries(
      NOTIFICATION_TYPES.map((type) => [type, unread.filter((row) => row.type === type).length])
    );
    const reply = (body: unknown, status = 200) => ({
      ok: status < 300,
      status,
      json: async () => body,
    });
    global.fetch = jest.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : String(input);
      if (url.startsWith('/api/notifications/unread-count')) {
        return reply({ success: true, unread: { total: unread.length, by_type: byType } });
      }
      if (url.startsWith('/api/notifications')) {
        return reply({
          success: true,
          notifications: inbox,
          count: inbox.length,
          total: inbox.length,
          limit: 50,
          offset: 0,
        });
      }
      return reply({ success: false, error: 'not routed' }, 404);
    }) as unknown as typeof fetch;
  }

  it('renders the shell around the notification centre', async () => {
    const now = Date.now();
    installInbox(docsInbox(now));
    const { container } = await renderShell({
      pathname: '/ade/dashboard/notifications',
      children: <NotificationsClient now={now} />,
    });
    await screen.findByText('Marcus Lee mentioned you in a comment');
    await waitFor(() => expect(screen.getByTestId('rail-notifications-badge')).toHaveTextContent('3'));
    writeA11yFixture('preferences-theme-sample', container.innerHTML);
  });

  it('renders the bell menu open over a folded rail', async () => {
    const now = Date.now();
    installInbox(docsInbox(now));
    // Folded groups keep the rail inside a 900 px capture, so the footer — and the menu that
    // opens above it — are on screen.
    window.localStorage.setItem(
      NAV_COLLAPSED_STORAGE_KEY,
      JSON.stringify(PLATFORM_NAV_GROUPS.map((group) => group.id))
    );
    const { container } = await renderShell({
      pathname: '/ade/dashboard/notifications',
      children: <NotificationsClient now={now} />,
    });
    await screen.findByText('Marcus Lee mentioned you in a comment');
    fireEvent.click(screen.getByTestId('rail-notifications'));
    const menu = await screen.findByTestId('notifications-menu');
    await within(menu).findByText('Priya Raman requested your review');
    writeA11yFixture('notifications-menu', container.innerHTML);
    window.localStorage.removeItem(NAV_COLLAPSED_STORAGE_KEY);
  });

  /**
   * Mount the shell around the notification centre, open an overlay, and dump the whole body —
   * the overlays portal out of the shell's container.
   *
   * @param open Opens the overlay.
   * @param ready The overlay's test id, awaited before the dump.
   * @param name The fixture's file stem.
   */
  async function dumpOverlay(open: () => void, ready: string, name: string): Promise<void> {
    const now = Date.now();
    installInbox(docsInbox(now));
    await renderShell({
      pathname: '/ade/dashboard/notifications',
      children: <NotificationsClient now={now} />,
    });
    await screen.findByText('Marcus Lee mentioned you in a comment');
    act(() => {
      open();
    });
    await screen.findByTestId(ready);
    writeA11yFixture(name, document.body.innerHTML);
  }

  it('renders the preferences pane on its Account, Notifications and Shortcuts tabs', async () => {
    await dumpOverlay(() => openPreferences('account'), 'preferences-drawer', 'preferences-account');
    cleanup();

    // A reader who has muted publishes: the tab shows the switch off.
    window.localStorage.setItem(NOTIFICATION_PREFERENCE_KEYS.version_published, 'off');
    await dumpOverlay(
      () => openPreferences('notifications'),
      'preferences-notifications',
      'preferences-notifications'
    );
    cleanup();
    window.localStorage.removeItem(NOTIFICATION_PREFERENCE_KEYS.version_published);

    await dumpOverlay(() => openPreferences('shortcuts'), 'open-shortcut-sheet', 'preferences-shortcuts');
  });

  it('renders the keyboard shortcut sheet', async () => {
    await dumpOverlay(() => openShortcutSheet(), 'shortcut-sheet', 'shortcut-sheet');
  });

  it('renders the command palette', async () => {
    await dumpOverlay(() => openCommandPalette(), 'command-palette', 'help-command-palette');
  });
});
