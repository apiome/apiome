/**
 * What the command palette offers (HIVE-3.6, #5292).
 *
 * `commandPaletteModel.ts` is the half of the palette that has no DOM in it: which
 * destinations exist, which are gated and why, what `>` means, and where an action's deep
 * link points. Pinning those here — rather than only through a render — is what lets the
 * component suite be about behaviour and this one about the contract with
 * `lib/platform-nav.ts` and `openActions.ts`.
 *
 * Every expectation about *destinations* is derived from the navigation model rather than
 * written out, so a palette that stops reading the model fails here rather than silently
 * offering a stale list.
 */

import {
  COMMANDS_ONLY_PREFIX,
  PALETTE_ACTIONS,
  PALETTE_GROUP_HEADINGS,
  buildActionCommands,
  buildCommandGroups,
  buildFavoriteCommands,
  buildJumpCommands,
  buildRecentCommands,
  parseCommandQuery,
} from '../src/app/components/shell/commandPaletteModel';
import {
  OPEN_ACTION_IDS,
  OPEN_ACTION_PARAM,
  openActionHref,
} from '../src/app/components/shell/openActions';
import {
  PLATFORM_NAV_GROUPS,
  PLATFORM_OFF_RAIL_ITEMS,
  PLATFORM_USER_MENU_ITEMS,
  getPlatformNavGroups,
  platformNavGatedReason,
} from '../lib/platform-nav';
import { isFeatureReleased } from '../lib/feature-release';
import { PLATFORM_NAV_ICONS } from '../lib/platform-nav-icons';
import type { CommandPaletteRecent } from '../src/app/components/shell/commandPaletteRecents';
import type { PinnedProject } from '../lib/db/dashboard-home-model';

/** A session with a workspace. */
const TENANT = 't-1';

/** Every released first-party destination the model describes, flattened — rail, off-rail, account. */
const MODEL_ITEMS = [
  ...PLATFORM_NAV_GROUPS.flatMap((group) => group.items),
  ...PLATFORM_OFF_RAIL_ITEMS,
  ...PLATFORM_USER_MENU_ITEMS,
].filter((item) => isFeatureReleased(item.id));

/** Two recents, oldest last, as the store hands them over. */
const RECENTS: CommandPaletteRecent[] = [
  {
    id: 'proj-1',
    label: 'Payments API',
    href: '/ade/dashboard/projects/1',
    meta: 'v2.4.0 · draft',
    icon: 'file-json-2',
    at: 2,
  },
  { id: 'proj-2', label: 'Orders Service', href: '/ade/dashboard/projects/2', at: 1 },
];

describe('Jump to — the navigation model, and only it', () => {
  it('offers every destination the model describes, rail, off-rail and user menu alike', () => {
    const commands = buildJumpCommands(getPlatformNavGroups({ currentTenantId: TENANT }), TENANT);

    expect(commands.map((command) => command.label).sort()).toEqual(
      MODEL_ITEMS.map((item) => item.label).sort()
    );
    for (const command of commands) {
      expect(command.group).toBe('jump');
      expect(command.href).toBeTruthy();
    }
  });

  it('files each destination under the section it lives in, so the section is searchable', () => {
    const commands = buildJumpCommands(getPlatformNavGroups({ currentTenantId: TENANT }), TENANT);

    // A labelled group's items carry its heading; the unlabelled leading group reads "Home".
    const catalog = commands.find((command) => command.label === 'Catalog')!;
    expect(catalog.meta).toBe('Bring in');
    expect(catalog.keywords).toEqual(['Catalog', 'Bring in']);

    const home = commands.find((command) => command.label === 'Home')!;
    expect(home.meta).toBe('Home');

    // Account destinations are user-menu rows in the rail; in the palette they are just
    // destinations, because a reader typing "profile" does not know which menu owns it.
    const profile = commands.find((command) => command.label === 'Profile')!;
    expect(profile.meta).toBe('Account');
  });

  it('keeps the destinations that left the rail, under the section they belong with (HIVE-12.2)', () => {
    const commands = buildJumpCommands(getPlatformNavGroups({ currentTenantId: TENANT }), TENANT);
    const meta = (label: string) => commands.find((command) => command.label === label)?.meta;

    expect(meta('Tenants')).toBe('Workspace');
    expect(meta('Data browser')).toBe('Tools');
    expect(meta('Migrations')).toBe('Tools');
    expect(commands.find((command) => command.label === 'Tenants')?.href).toBe('/ade/dashboard/tenants');
    // Off-rail rows follow the rail rows and precede the account rows.
    const labels = commands.map((command) => command.label);
    expect(labels.indexOf('Tenants')).toBeGreaterThan(labels.indexOf('Schema registry'));
    expect(labels.indexOf('Migrations')).toBeLessThan(labels.indexOf('Profile'));
  });

  it('lists SDK settings at its Export studio tab once the feature is previewed', () => {
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'sdk-settings';
    try {
      const commands = buildJumpCommands(getPlatformNavGroups({ currentTenantId: TENANT }), TENANT);
      const sdk = commands.find((command) => command.label === 'SDK settings');
      expect(sdk).toMatchObject({ meta: 'Ship', href: '/ade/dashboard/export/studio?tab=sdk' });
    } finally {
      delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    }
  });

  it('never lists an off-rail destination twice when a host already put it in the rail', () => {
    const groups = getPlatformNavGroups({
      currentTenantId: TENANT,
      injected: [
        {
          group: 'workspace',
          item: { id: 'tenants', label: 'Tenants', href: '/ade/dashboard/tenants', icon: 'building-2' },
        },
      ],
    });
    const commands = buildJumpCommands(groups, TENANT);
    expect(commands.filter((command) => command.label === 'Tenants')).toHaveLength(1);
  });

  it('names an icon the shared resolver knows, for every row it draws', () => {
    const commands = [
      ...buildJumpCommands(getPlatformNavGroups({ currentTenantId: TENANT }), TENANT),
      ...buildActionCommands(TENANT),
      ...buildRecentCommands(RECENTS),
    ];

    for (const command of commands) {
      expect(PLATFORM_NAV_ICONS[command.icon]).toBeDefined();
    }
  });

  it('disables exactly the destinations the rail disables, in the rail\u2019s words', () => {
    const commands = buildJumpCommands(getPlatformNavGroups({ currentTenantId: null }), null);
    const gated = MODEL_ITEMS.filter((item) => item.requiresTenant);

    expect(gated.length).toBeGreaterThan(0);
    for (const item of gated) {
      const command = commands.find((entry) => entry.label === item.label)!;
      expect(command.disabled).toBe(true);
      expect(command.disabledReason).toBe(platformNavGatedReason(item.label));
      // The reason takes the meta line's place, so it is read rather than hidden in a title.
      expect(command.meta).toBe(command.disabledReason);
    }

    for (const item of MODEL_ITEMS.filter((entry) => !entry.requiresTenant)) {
      expect(commands.find((entry) => entry.label === item.label)!.disabled).toBe(false);
    }
  });

  it('carries a contributed commercial destination through, gating and all', () => {
    const groups = getPlatformNavGroups({
      currentTenantId: TENANT,
      injected: [
        {
          group: 'build',
          item: { id: 'suite', label: 'Designer', href: 'https://suite.example/x', icon: 'box' },
        },
      ],
    });

    const designer = buildJumpCommands(groups, TENANT).find(
      (command) => command.label === 'Designer'
    )!;
    expect(designer.href).toBe('https://suite.example/x');
    expect(designer.meta).toBe('Build');
  });
});

describe('Actions — what a reader can start from anywhere', () => {
  it('offers the four DESIGN.md §5.4 actions, each with somewhere to go or something to do', () => {
    const commands = buildActionCommands(TENANT);

    expect(commands.map((command) => command.label)).toEqual([
      'New project…',
      'Import a spec…',
      'Create API key…',
      'Change theme…',
    ]);
    for (const command of commands) {
      expect(command.group).toBe('action');
      // Exactly one of the two: a row that neither goes anywhere nor does anything is dead.
      expect(Boolean(command.href) !== Boolean(command.run)).toBe(true);
    }
  });

  it('deep-links to the page that owns each dialog, naming an action that page answers', () => {
    const withHrefs = PALETTE_ACTIONS.filter((action) => action.href);
    expect(withHrefs.length).toBe(3);

    for (const action of withHrefs) {
      const url = new URL(action.href!, 'https://apiome.test');
      const requested = url.searchParams.get(OPEN_ACTION_PARAM);
      expect(OPEN_ACTION_IDS).toContain(requested);
      expect(url.pathname.startsWith('/ade/dashboard/')).toBe(true);
    }
  });

  it('gates a workspace-scoped action exactly as the rail gates a destination', () => {
    const gated = buildActionCommands(null);
    const themes = gated.find((command) => command.label === 'Change theme…')!;

    expect(themes.disabled).toBe(false); // the theme is the reader's, not the workspace's
    for (const command of gated.filter((entry) => entry !== themes)) {
      expect(command.disabled).toBe(true);
      expect(command.disabledReason).toBe(platformNavGatedReason(command.label));
    }
  });
});

describe('Recent \u2014 this workspace\u2019s history', () => {
  it('draws what the store holds, in the order it hands it over', () => {
    const commands = buildRecentCommands(RECENTS);

    expect(commands.map((command) => command.label)).toEqual(['Payments API', 'Orders Service']);
    expect(commands[0].meta).toBe('v2.4.0 · draft');
    expect(commands[0].icon).toBe('file-json-2');
    // A recent with no icon of its own still draws something.
    expect(commands[1].icon).toBe('clock');
    expect(commands.every((command) => command.disabled)).toBe(false);
  });
});

describe('the groups, assembled', () => {
  it('puts history first, then destinations, then actions', () => {
    const groups = buildCommandGroups({
      navGroups: getPlatformNavGroups({ currentTenantId: TENANT }),
      recents: RECENTS,
      currentTenantId: TENANT,
    });

    expect(groups.map((group) => group.heading)).toEqual([
      PALETTE_GROUP_HEADINGS.recent,
      PALETTE_GROUP_HEADINGS.jump,
      PALETTE_GROUP_HEADINGS.action,
    ]);
  });

  it('omits a group with nothing in it rather than drawing an empty heading', () => {
    const groups = buildCommandGroups({
      navGroups: getPlatformNavGroups({ currentTenantId: TENANT }),
      currentTenantId: TENANT,
    });

    expect(groups.map((group) => group.id)).toEqual(['jump', 'action']);
  });

  it('shows commands only, not commands first, when the reader types >', () => {
    const groups = buildCommandGroups({
      navGroups: getPlatformNavGroups({ currentTenantId: TENANT }),
      recents: RECENTS,
      currentTenantId: TENANT,
      commandsOnly: true,
    });

    expect(groups.map((group) => group.id)).toEqual(['action']);
  });

  it('gives every row an id unique across the whole palette', () => {
    const ids = buildCommandGroups({
      navGroups: getPlatformNavGroups({ currentTenantId: TENANT }),
      recents: RECENTS,
      currentTenantId: TENANT,
    }).flatMap((group) => group.commands.map((command) => command.id));

    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe('Favorites — the reader\u2019s pinned projects (#542)', () => {
  const FAVORITES: PinnedProject[] = [
    { projectId: 'p-1', projectName: 'Payments API', versionLabel: 'v2.4.0', pinnedAt: '2026-10-21T10:00:00.000Z' },
    { projectId: 'p 2', projectName: 'Orders Service', versionLabel: null, pinnedAt: '2026-10-20T10:00:00.000Z' },
  ];

  it('opens each favorite on its versions, with a quiet "Favorite" meta line', () => {
    const commands = buildFavoriteCommands(FAVORITES);
    expect(commands.map((command) => [command.label, command.meta, command.href])).toEqual([
      ['Payments API', 'Favorite · v2.4.0', '/ade/dashboard/versions?projectId=p-1'],
      ['Orders Service', 'Favorite', '/ade/dashboard/versions?projectId=p%202'],
    ]);
    expect(commands.every((command) => command.group === 'favorite' && !command.disabled)).toBe(true);
    expect(commands[0].keywords).toEqual(expect.arrayContaining(['Payments API']));
  });

  it('draws with an icon the rail knows', () => {
    for (const command of buildFavoriteCommands(FAVORITES)) {
      expect(PLATFORM_NAV_ICONS[command.icon]).toBeDefined();
    }
  });

  it('leads the palette, headed "Favorites"', () => {
    const groups = buildCommandGroups({
      navGroups: getPlatformNavGroups({ currentTenantId: TENANT }),
      recents: RECENTS,
      favorites: FAVORITES,
      currentTenantId: TENANT,
    });
    expect(groups[0].id).toBe('favorite');
    expect(groups[0].heading).toBe(PALETTE_GROUP_HEADINGS.favorite);
    expect(PALETTE_GROUP_HEADINGS.favorite).toBe('Favorites');
  });

  it('does not repeat a favorite under Recent', () => {
    const groups = buildCommandGroups({
      navGroups: getPlatformNavGroups({ currentTenantId: TENANT }),
      recents: [
        { id: 'fav', label: 'Payments API', href: '/ade/dashboard/versions?projectId=p-1', at: 3 },
        ...RECENTS,
      ],
      favorites: FAVORITES,
      currentTenantId: TENANT,
    });
    const recent = groups.find((group) => group.id === 'recent');
    expect(recent?.commands.map((command) => command.label)).toEqual(['Payments API', 'Orders Service']);
    expect(recent?.commands.some((command) => command.href === '/ade/dashboard/versions?projectId=p-1')).toBe(false);
  });

  it('is left out when there are none, and in commands-only mode', () => {
    const navGroups = getPlatformNavGroups({ currentTenantId: TENANT });
    expect(buildCommandGroups({ navGroups, currentTenantId: TENANT }).some((g) => g.id === 'favorite')).toBe(false);
    expect(
      buildCommandGroups({ navGroups, favorites: FAVORITES, currentTenantId: TENANT, commandsOnly: true }).map(
        (group) => group.id
      )
    ).toEqual(['action']);
  });
});

describe('the query', () => {
  it.each([
    ['projects', false, 'projects'],
    ['  projects  ', false, 'projects'],
    ['', false, ''],
  ])('reads %j as a plain search', (raw, commandsOnly, search) => {
    expect(parseCommandQuery(raw)).toEqual({ commandsOnly, search });
  });

  it.each([
    [COMMANDS_ONLY_PREFIX, ''],
    ['>theme', 'theme'],
    ['> theme', 'theme'],
    ['  >  theme  ', 'theme'],
  ])('reads %j as commands only', (raw, search) => {
    expect(parseCommandQuery(raw)).toEqual({ commandsOnly: true, search });
  });

  it('leaves a bare prefix with nothing to filter by, so the commands stay visible', () => {
    // Were the `>` kept as the search term, every command would score zero against it and
    // the mode would reveal an empty list.
    expect(parseCommandQuery('>').search).toBe('');
  });
});

describe('openActionHref', () => {
  it('appends the request to a clean route', () => {
    expect(openActionHref('/ade/dashboard/projects', 'new-project')).toBe(
      '/ade/dashboard/projects?open=new-project'
    );
  });
});
