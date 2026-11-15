/**
 * The `/ade` launcher (HIVE-4.5, #5299).
 *
 * The ticket is a re-skin, so the first thing this suite asserts is *inventory*: every line
 * of the mockup's "Keeps (1:1)" list is still on the page and still does what it did — the
 * build string that opens What's new, preferences, the account chip, sign out, the greeting
 * and headline, the ordered application grid, the resource rows and the footer.
 *
 * HIVE-12.6 (#5613) moved the build string from the top row to the footer, put a What's new
 * icon button in its place, and replaced the roadmap panel with "Recently shipped", read
 * from the What's new notes; both What's new controls carry the user menu's unread dot.
 *
 * On top of that, the four acceptance criteria that are statements about markup rather than
 * about looks: commercial cards come from entitlements and no product route is written down,
 * an unshipped card is genuinely non-interactive and says "(coming soon)", an external card
 * opens a new tab and says so, and the three overlay hosts this route alone is responsible
 * for are mounted. The fifth — "no rail renders on /ade" — is answered by the absence of
 * `AppShell` from the tree, which is asserted here as the absence of its navigation landmark.
 *
 * What the suite cannot answer is anything about how it *looks*: jsdom compiles no
 * stylesheet. `tests/launcher-css.test.ts` reads the stylesheet instead.
 */

import React from 'react';
import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

const mockSignOutEverywhere = jest.fn<Promise<void>, [string]>(async () => undefined);
const mockOpenPreferences = jest.fn<boolean, [string | undefined]>(() => true);
const mockOpenShortcutSheet = jest.fn<boolean, []>(() => true);

// A real anchor, so every card and row keeps its link semantics for axe and for the `href`
// assertions — with the navigation suppressed, which jsdom answers with a "Not implemented"
// console error rather than by navigating.
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} onClick={(event) => event.preventDefault()} {...rest}>
      {children}
    </a>
  ),
}));

/** The session the page renders against; a test may replace it before rendering. */
const sessionUser: { current: Record<string, unknown> | null } = {
  current: {
    name: 'Ada Lovelace',
    email: 'ada@example.test',
    current_tenant_id: 'tenant-1',
  },
};

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({
    data: sessionUser.current ? { user: sessionUser.current } : null,
    status: 'authenticated',
    update: jest.fn(),
  }),
  AuthSessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

jest.mock('@lib/auth/sign-out-client', () => ({
  signOutEverywhere: (callbackUrl: string) => mockSignOutEverywhere(callbackUrl),
}));

jest.mock('@/app/components/ade/preferences/preferencesDrawerBus', () => ({
  openPreferences: (tab?: string) => mockOpenPreferences(tab),
}));

jest.mock('@/app/components/shell/shortcutSheetBus', () => ({
  openShortcutSheet: () => mockOpenShortcutSheet(),
}));

jest.mock('rehype-raw', () => ({ __esModule: true, default: () => () => {} }));

// The three overlay hosts have their own suites (`preferences-drawer-host`,
// `command-palette-entry-points`, `shortcut-sheet`). Here the only question is whether this
// route — the one `/ade` route with no `AppShell` to host them — mounts all three.
jest.mock('@/app/components/ade/preferences/PreferencesDrawerHost', () => ({
  __esModule: true,
  default: () => <div data-testid="preferences-host" />,
}));
jest.mock('@/app/components/shell/CommandPaletteHost', () => ({
  __esModule: true,
  default: ({ currentTenantId }: { currentTenantId: string | null }) => (
    <div data-testid="palette-host" data-tenant={currentTenantId ?? ''} />
  ),
}));
jest.mock('@/app/components/shell/ShortcutsHost', () => ({
  __esModule: true,
  default: ({ currentTenantId }: { currentTenantId: string | null }) => (
    <div data-testid="shortcuts-host" data-tenant={currentTenantId ?? ''} />
  ),
}));

import AdeHome from '../src/app/components/ade/AdeHome';
import { APP_VERSION_BADGE } from '../lib/app-version';
import { WHATS_NEW_SEEN_STORAGE_KEY } from '../src/app/components/shell/whatsNewSeen';
import { CONTROL_PANEL_VISIT_STORAGE_KEY } from '../src/app/components/shell/controlPanelVisit';
import type { ExternalHomeCard } from '../lib/external-links';
import type { LauncherSummary } from '../lib/db/launcher-summary';
import { writeA11yFixture } from './helpers/a11y-fixture-dump';

/** A commercial card exactly as `getCommercialAccessForSession()` hands one over. */
const SUITE_CARD: ExternalHomeCard = {
  id: 'suite',
  name: 'Designer Suite',
  tagline: 'Design workspace',
  description: 'Schema design and API path modeling in one suite.',
  href: 'https://studio.example.test/',
  enabled: true,
  external: true,
  icon: 'Layers',
  accent: 'from-violet-500 to-fuchsia-600',
  glow: 'group-hover:shadow-fuchsia-500/20',
  tone: 'violet',
};

/** The always-listed, never-shipped card the built-in catalog contributes. */
const DEVELOPER_CARD: ExternalHomeCard = {
  ...SUITE_CARD,
  id: 'developer-suite',
  name: 'Developer Suite',
  tagline: 'Developer tools',
  description: 'SDKs, tooling, and developer workflows — coming soon.',
  href: '#',
  enabled: false,
  external: false,
  icon: 'Workflow',
};

/** A resolved hero summary. */
const SUMMARY: LauncherSummary = {
  workspace: { id: 'tenant-1', name: 'Acme Corp', role: 'owner', licenseName: 'Free' },
  projectCount: 3,
  publishedCount: 5,
  attentionCount: 2,
};

/**
 * Render the launcher.
 *
 * @param props Overrides for the page's props.
 * @returns The Testing Library result.
 */
function renderLauncher(props: Partial<React.ComponentProps<typeof AdeHome>> = {}) {
  return render(
    <AdeHome commercialHomeCards={[SUITE_CARD, DEVELOPER_CARD]} summary={SUMMARY} {...props} />
  );
}

beforeEach(() => {
  sessionUser.current = {
    name: 'Ada Lovelace',
    email: 'ada@example.test',
    current_tenant_id: 'tenant-1',
  };
  mockSignOutEverywhere.mockClear();
  mockOpenPreferences.mockClear();
  mockOpenShortcutSheet.mockClear();
  window.localStorage.clear();
  // `WhatsNewDialog` fetches the release notes on open, and `RecentlyShipped` on mount; jsdom
  // ships no `fetch`. Plain prose has no entries, so by default the card stays out of the way.
  mockNotes('Notes.');
});

/**
 * Serve `markdown` as `/WHATS_NEW.md` for the rest of the test.
 *
 * @param markdown The notes file's body.
 */
function mockNotes(markdown: string) {
  global.fetch = jest
    .fn()
    .mockResolvedValue({ ok: true, text: async () => markdown }) as unknown as typeof fetch;
}

/** Notes shaped like `public/WHATS_NEW.md`: four entries, so the card has one to leave out. */
const NOTES = [
  '# Apiome 11-2026 RC8',
  '',
  '## Features/Improvements',
  '',
  '- **Access audit** — an append-only ledger of who did what',
  '- Look and feel:',
  '  - **Lint posture** — catalog-wide findings and waivers',
  '- Design system route: every component, every theme',
  '- **Fourth entry** — not shown',
  '',
  '## Bug Fixes',
  '',
  '- **A fix** — never "shipped"',
].join('\n');

describe('launcher — the top row', () => {
  it('carries the brand, What’s new, preferences, the account and sign out', () => {
    renderLauncher();

    const top = screen.getByRole('banner');
    expect(screen.getByRole('link', { name: 'Apiome home' })).toHaveAttribute('href', '/ade');
    expect(within(top).getByTestId('launch-whats-new')).toHaveAccessibleName(/^What’s new/);
    // HIVE-12.6: the build string left the top row for the footer (DESIGN.md §5.1).
    expect(top).not.toHaveTextContent(APP_VERSION_BADGE);
    expect(screen.getByRole('button', { name: 'Preferences' })).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Account menu for Ada Lovelace' })
    ).toHaveAttribute('href', '/ade/dashboard/profile');
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('orders the top row’s actions What’s new, Preferences, account, Sign out', () => {
    renderLauncher();

    const actions = Array.from(screen.getByRole('banner').querySelectorAll('a, button'))
      .map((el) => el.getAttribute('data-testid') ?? el.getAttribute('aria-label'));
    expect(actions).toEqual([
      'Apiome home',
      'launch-whats-new',
      'Preferences',
      'Account menu for Ada Lovelace',
      'Sign out',
    ]);
  });

  it('opens What’s new from the top row, and marks the build read as it does', async () => {
    const user = userEvent.setup();
    renderLauncher();

    expect(window.localStorage.getItem(WHATS_NEW_SEEN_STORAGE_KEY)).toBeNull();
    await user.click(screen.getByTestId('launch-whats-new'));

    // The launcher's badge and the rail's user menu show the same notes for the same build,
    // so reading them here has to clear the rail's unread dot as well (HIVE-3.4).
    expect(window.localStorage.getItem(WHATS_NEW_SEEN_STORAGE_KEY)).toBe(APP_VERSION_BADGE);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('asks the preferences bus for the pane rather than routing anywhere', async () => {
    const user = userEvent.setup();
    renderLauncher();

    await user.click(screen.getByRole('button', { name: 'Preferences' }));
    expect(mockOpenPreferences).toHaveBeenCalled();
  });

  it('still names the account chip for a reader with no display name', () => {
    // A credentials account may never have had one. The chip says "Account"; the greeting
    // below says "there" — the two fallbacks the pre-Hive launcher used, in the same places.
    sessionUser.current = { current_tenant_id: 'tenant-1' };
    renderLauncher();

    const chip = screen.getByRole('link', { name: 'Account menu' });
    expect(chip).toHaveTextContent('Account');
    expect(screen.getByText(/Good (morning|afternoon|evening), there/)).toBeInTheDocument();
  });

  it('signs out everywhere, back to the front door', async () => {
    const user = userEvent.setup();
    renderLauncher();

    await user.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(mockSignOutEverywhere).toHaveBeenCalledWith('/login');
  });
});

describe('launcher — the hero', () => {
  it('greets the reader by their first name', () => {
    renderLauncher();
    expect(screen.getByText(/Good (morning|afternoon|evening), Ada/)).toBeInTheDocument();
  });

  it('sets the headline, with no eyebrow pill and no filler paragraph (HIVE-12.5)', () => {
    renderLauncher();

    const heading = screen.getByRole('heading', { level: 1 });
    expect(heading).toHaveTextContent('Your API');
    expect(heading).toHaveTextContent('specification workspace');
    expect(screen.queryByText('Apiome platform')).not.toBeInTheDocument();
    expect(screen.queryByText(/Govern projects and versions/)).not.toBeInTheDocument();
  });

  it('summarises the workspace and the counts, each linking into the app', () => {
    renderLauncher();

    const workspace = screen.getByRole('link', { name: /Acme Corp/ });
    expect(workspace).toHaveAttribute('href', '/ade/dashboard/tenants');
    // Role and plan are worded by the workspace switcher's own formatter, so the rail and
    // the launcher can never describe the same membership two different ways.
    expect(workspace).toHaveTextContent('Owner · Free');

    expect(screen.getByRole('link', { name: '3 projects' })).toHaveAttribute(
      'href',
      '/ade/dashboard/projects'
    );
    expect(screen.getByRole('link', { name: '5 published' })).toHaveAttribute(
      'href',
      '/ade/dashboard/published'
    );
    // HIVE-12.5: blocking lint findings, leading to where they are worked off.
    expect(screen.getByRole('link', { name: '2 need attention' })).toHaveAttribute(
      'href',
      '/ade/dashboard/lint-workspace'
    );
  });

  it('draws no attention chip when nothing needs attention', () => {
    renderLauncher({ summary: { ...SUMMARY, attentionCount: 0 } });
    expect(screen.queryByTestId('launch-chip-attention')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '3 projects' })).toBeInTheDocument();
  });

  it('draws no chips at all when the summary could not be resolved', () => {
    // Every source behind them fails soft, so "no chips" is a state the page has to survive.
    renderLauncher({ summary: undefined });
    expect(screen.queryByRole('link', { name: /projects$/ })).not.toBeInTheDocument();
  });

  it('drops the workspace chip, but keeps the counts, for a reader with no workspace', () => {
    renderLauncher({ summary: { ...SUMMARY, workspace: null } });

    expect(screen.queryByRole('link', { name: /Acme Corp/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '3 projects' })).toBeInTheDocument();
  });
});

describe('launcher — the application grid', () => {
  it('orders Control Panel, then the host’s cards, then the Browser', () => {
    renderLauncher();

    const ids = screen
      .getAllByTestId(/^launch-app-/)
      .map((node) => node.getAttribute('data-testid'));
    // The host's unshipped Developer Suite is not a tile: it is named on the Coming next line.
    expect(ids).toEqual(['launch-app-control-panel', 'launch-app-suite', 'launch-app-browser']);
  });

  it('renders commercial cards from entitlements alone', () => {
    // Nothing about the suite is written down in the page: withhold the cards and the slot
    // is empty, rather than showing a product the reader cannot reach.
    renderLauncher({ commercialHomeCards: [] });

    const ids = screen
      .getAllByTestId(/^launch-app-/)
      .map((node) => node.getAttribute('data-testid'));
    expect(ids).toEqual(['launch-app-control-panel', 'launch-app-browser']);
    expect(screen.queryByText('Designer Suite')).not.toBeInTheDocument();
  });

  it('takes the host card’s destination verbatim', () => {
    renderLauncher();
    expect(screen.getByTestId('launch-app-suite')).toHaveAttribute(
      'href',
      'https://studio.example.test/'
    );
  });

  it('opens an external card in a new tab, and says so before it is clicked', () => {
    renderLauncher();

    const browser = screen.getByTestId('launch-app-browser');
    expect(browser).toHaveAttribute('target', '_blank');
    // `noopener` keeps the new tab from reaching back through `window.opener`.
    expect(browser.getAttribute('rel')).toContain('noopener');
    expect(within(browser).getByText('Opens in a new tab')).toBeInTheDocument();
  });

  it('routes an internal card through the client router', () => {
    renderLauncher();
    expect(screen.getByTestId('launch-app-control-panel')).toHaveAttribute(
      'href',
      '/ade/dashboard'
    );
    expect(screen.getByTestId('launch-app-control-panel')).not.toHaveAttribute('target');
  });

  it('names an unshipped product on the Coming next line instead of drawing it (HIVE-12.5)', () => {
    renderLauncher();

    expect(screen.queryByTestId('launch-app-developer-suite')).not.toBeInTheDocument();
    const line = screen.getByTestId('coming-next');
    expect(line).toHaveTextContent('Coming next:');
    expect(
      within(line)
        .getAllByTestId(/^coming-next-(?!follow)/)
        .map((tag) => tag.textContent)
    ).toEqual(['Developer Suite', 'Community', 'Marketplace']);
    // Text, not controls: the only interactive thing on the line is the What's new link.
    expect(within(line).getAllByRole('button')).toHaveLength(1);
    expect(within(line).queryAllByRole('link')).toHaveLength(0);
  });

  it('emphasises the Control Panel tile, and only it', () => {
    renderLauncher();
    expect(screen.getByTestId('launch-app-control-panel')).toHaveClass('launch-card--primary');
    expect(screen.getByTestId('launch-app-browser')).not.toHaveClass('launch-card--primary');
    expect(screen.getByTestId('launch-app-suite')).not.toHaveClass('launch-card--primary');
  });

  it('says when the Control Panel was last opened on this device', async () => {
    window.localStorage.setItem(
      CONTROL_PANEL_VISIT_STORAGE_KEY,
      String(Date.now() - 2 * 60 * 60 * 1000)
    );
    renderLauncher();

    expect(await screen.findByText('Included · last opened 2 hours ago')).toBeInTheDocument();
  });

  it('says only “Included” when this device has no visit recorded', async () => {
    renderLauncher();
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByTestId('launch-card-foot-control-panel')).toHaveTextContent(/^Included$/);
  });

  it('tints each card from its tone rather than from a colour', () => {
    renderLauncher();

    expect(screen.getByTestId('launch-app-control-panel')).toHaveAttribute('data-tone', 'accent');
    expect(screen.getByTestId('launch-app-browser')).toHaveAttribute('data-tone', 'ok');
    expect(screen.getByTestId('launch-app-suite')).toHaveAttribute('data-tone', 'violet');
  });

  it('falls back to the commercial tone for a host that declared none', () => {
    renderLauncher({ commercialHomeCards: [{ ...SUITE_CARD, tone: undefined }] });
    expect(screen.getByTestId('launch-app-suite')).toHaveAttribute('data-tone', 'violet');
  });
});

describe('launcher — resources', () => {
  it('lists Help & docs, and nothing that cannot be opened', () => {
    renderLauncher();

    // HIVE-4.9 (#5303): the row points at the in-app Help & docs page, which carries the
    // YouTube channel as one card among the guides — it no longer leaves for the channel
    // itself, so nothing here opens a new tab.
    const help = screen.getByTestId('launch-resource-help');
    expect(help).toHaveAttribute('href', '/ade/dashboard/help');
    expect(help).not.toHaveAttribute('target');

    // HIVE-12.5: Community and Marketplace moved to the Coming next line. HIVE-12.6 added
    // the two rows the mockup draws: Video walkthroughs and Keyboard shortcuts.
    expect(screen.getAllByTestId(/^launch-resource-/).map((row) => row.dataset.testid)).toEqual([
      'launch-resource-help',
      'launch-resource-videos',
      'launch-resource-shortcuts',
    ]);
  });

  it('opens Video walkthroughs on YouTube in a new tab, and says so (HIVE-12.6)', () => {
    renderLauncher();

    const videos = screen.getByTestId('launch-resource-videos');
    expect(videos).toHaveAttribute('href', 'https://www.youtube.com/@apiomedev');
    expect(videos).toHaveAttribute('target', '_blank');
    expect(videos).toHaveAttribute('rel', 'noopener noreferrer');
    expect(videos).toHaveAccessibleName(/opens in a new tab/);
  });

  it('opens the shortcuts sheet from Keyboard shortcuts rather than navigating (HIVE-12.6)', async () => {
    const user = userEvent.setup();
    renderLauncher();

    const row = screen.getByTestId('launch-resource-shortcuts');
    expect(row.tagName).toBe('BUTTON');
    expect(row).toHaveTextContent('?');
    await user.click(row);
    expect(mockOpenShortcutSheet).toHaveBeenCalledTimes(1);
  });

  it('has no roadmap panel (HIVE-12.5)', () => {
    renderLauncher();

    expect(screen.queryByTestId('launch-resource-audit')).not.toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'On the roadmap' })).not.toBeInTheDocument();
  });
});

describe('launcher — recently shipped (HIVE-12.6)', () => {
  it('lists the three newest What’s new entries — title, one line, release', async () => {
    mockNotes(NOTES);
    renderLauncher();

    const card = await screen.findByRole('region', { name: 'Recently shipped' });
    expect(global.fetch).toHaveBeenCalledWith('/WHATS_NEW.md');
    const rows = within(card).getAllByRole('listitem');
    expect(rows.map((row) => row.querySelector('.launch-ship__title')?.textContent)).toEqual([
      'Access audit',
      'Lint posture',
      'Design system route',
    ]);
    expect(rows[0]).toHaveTextContent('An append-only ledger of who did what');
    expect(rows[0]).toHaveTextContent('11-2026 RC8');
    expect(card).not.toHaveTextContent('Fourth entry');
    expect(card).not.toHaveTextContent('A fix');
  });

  it('opens What’s new from All release notes, and marks the build read', async () => {
    mockNotes(NOTES);
    const user = userEvent.setup();
    renderLauncher();

    await user.click(await screen.findByRole('button', { name: 'All release notes' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(window.localStorage.getItem(WHATS_NEW_SEEN_STORAGE_KEY)).toBe(APP_VERSION_BADGE);
  });

  it('is omitted when the notes hold no entries, so Resources spans the row', async () => {
    renderLauncher();
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.queryByTestId('launch-recently-shipped')).not.toBeInTheDocument();
    const lower = screen.getByRole('region', { name: 'Resources' }).parentElement;
    expect(lower?.children).toHaveLength(1);
  });

  it('is omitted when the notes cannot be fetched', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;
    renderLauncher();
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.queryByTestId('launch-recently-shipped')).not.toBeInTheDocument();
  });

  it('writes no roadmap copy of its own', async () => {
    mockNotes(NOTES);
    renderLauncher();
    await screen.findByRole('region', { name: 'Recently shipped' });

    expect(screen.queryByText(/On the roadmap|Planned/)).not.toBeInTheDocument();
  });
});

describe('launcher — the What’s new unread dot (HIVE-12.6)', () => {
  it('marks both What’s new controls while this build’s notes are unread', async () => {
    renderLauncher();

    expect(await screen.findByTestId('launch-whats-new-unread')).toBeInTheDocument();
    expect(screen.getByTestId('launch-whats-new')).toHaveAccessibleName(
      'What’s new — 1 unread release note'
    );
    expect(screen.getByTestId('launch-build').querySelector('.launch-unread-dot')).not.toBeNull();
  });

  it('clears both dots once What’s new is opened', async () => {
    const user = userEvent.setup();
    renderLauncher();

    await screen.findByTestId('launch-whats-new-unread');
    await user.click(screen.getByTestId('launch-build'));

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.queryByTestId('launch-whats-new-unread')).not.toBeInTheDocument();
    expect(screen.getByTestId('launch-build').querySelector('.launch-unread-dot')).toBeNull();
    expect(window.localStorage.getItem(WHATS_NEW_SEEN_STORAGE_KEY)).toBe(APP_VERSION_BADGE);
  });

  it('draws no dot for a reader who has already read this build’s notes', async () => {
    window.localStorage.setItem(WHATS_NEW_SEEN_STORAGE_KEY, APP_VERSION_BADGE);
    renderLauncher();
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.queryByTestId('launch-whats-new-unread')).not.toBeInTheDocument();
    expect(screen.getByTestId('launch-whats-new')).toHaveAccessibleName('What’s new');
  });
});

describe('launcher — only what opens (HIVE-12.5)', () => {
  it('has no disabled or aria-disabled control anywhere on the page', () => {
    const { container } = renderLauncher();
    expect(container.querySelectorAll('[disabled], [aria-disabled="true"]')).toHaveLength(0);
  });

  it('tabs from the tiles to the Coming next link, then to Resources', async () => {
    const user = userEvent.setup();
    renderLauncher();

    // Start just before the grid: the last hero chip.
    screen.getByTestId('launch-chip-attention').focus();
    const order: (string | null)[] = [];
    for (let step = 0; step < 5; step += 1) {
      await user.tab();
      order.push(document.activeElement?.getAttribute('data-testid') ?? null);
    }
    expect(order).toEqual([
      'launch-app-control-panel',
      'launch-app-suite',
      'launch-app-browser',
      'coming-next-follow',
      'launch-resource-help',
    ]);
  });

  it('opens What’s new from the Coming next line, and marks the build read', async () => {
    const user = userEvent.setup();
    renderLauncher();

    await user.click(screen.getByRole('button', { name: 'Follow in What’s new' }));

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(window.localStorage.getItem(WHATS_NEW_SEEN_STORAGE_KEY)).not.toBeNull();
  });

  it('drops the Coming next line’s host tag when the host ships nothing unshipped', () => {
    renderLauncher({ commercialHomeCards: [SUITE_CARD] });
    expect(screen.queryByTestId('coming-next-developer-suite')).not.toBeInTheDocument();
    expect(screen.getByTestId('coming-next-community')).toBeInTheDocument();
  });
});

describe('launcher — the page frame', () => {
  it('prints the build and the copyright in the footer', () => {
    renderLauncher();

    const footer = screen.getByRole('contentinfo');
    expect(within(footer).getByText(APP_VERSION_BADGE)).toBeInTheDocument();
    // A button, still spelled the way the rail's user menu spells it (HIVE-3.4).
    expect(within(footer).getByRole('button', { name: /see what's new/ })).toHaveTextContent(
      APP_VERSION_BADGE
    );
    expect(within(footer).getByText('© 2021 – 2026 NobuData LLC')).toBeInTheDocument();
  });

  it('draws no rail — this is the route AppShell does not own', () => {
    renderLauncher();
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument();
  });

  it('mounts the three overlay hosts AppShell would otherwise provide', () => {
    renderLauncher();

    // Without these, `⌘,`, `⌘K` and `?` would do nothing on the first page a reader lands on.
    expect(screen.getByTestId('preferences-host')).toBeInTheDocument();
    expect(screen.getByTestId('palette-host')).toHaveAttribute('data-tenant', 'tenant-1');
    expect(screen.getByTestId('shortcuts-host')).toHaveAttribute('data-tenant', 'tenant-1');
  });
});

describe('launcher — accessibility', () => {
  it('has no axe violations', async () => {
    const { container } = renderLauncher();
    expect(await axe(container)).toHaveNoViolations();
  });

  it('has no axe violations with Recently shipped drawn', async () => {
    mockNotes(NOTES);
    const { container } = renderLauncher();
    await screen.findByRole('region', { name: 'Recently shipped' });
    expect(await axe(container)).toHaveNoViolations();
  });

  it('has no axe violations without a summary or a commercial card', async () => {
    const { container } = renderLauncher({ commercialHomeCards: [], summary: undefined });
    expect(await axe(container)).toHaveNoViolations();
  });
});

describe('launcher — the a11y gate fixture (HIVE-10.2)', () => {
  it('renders the launcher (and writes its fixture on request)', async () => {
    mockNotes(NOTES);
    const { container } = renderLauncher();
    await screen.findByRole('region', { name: 'Recently shipped' });
    writeA11yFixture('launcher', container.innerHTML);
  });
});
