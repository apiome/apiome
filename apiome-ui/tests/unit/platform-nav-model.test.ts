/**
 * The Hive navigation model (HIVE-3.2, #5288).
 *
 * These tests are the contract `lib/platform-nav.ts` owes every surface that
 * renders navigation — the sidebar today, the `AppShell` rail (HIVE-3.1), the
 * command palette (HIVE-3.6) — so the four acceptance criteria are pinned here
 * rather than in any one component:
 *
 *   1. the model *is* the navigation (shape, grouping, labels, icons);
 *   2. active-state resolution is unchanged from the pre-Hive sidebar, route by
 *      route, for every destination the model carries;
 *   3. workspace gating produces exactly the disabled set it produced before;
 *   4. no Tools route and no commercial-product route is hard-coded anywhere.
 */
import {
  DEFAULT_PLATFORM_NAV_ICON,
  PLATFORM_NAV_GROUPS,
  PLATFORM_NAV_GROUP_IDS,
  PLATFORM_NAV_LEGACY_SDK_SETTINGS_HREF,
  PLATFORM_NAV_SDK_SETTINGS_HREF,
  PLATFORM_NAV_SUNSET_TIMELINE_HREF,
  PLATFORM_NAV_VERSIONS_HREF,
  PLATFORM_OFF_RAIL_ITEMS,
  PLATFORM_USER_MENU_ITEMS,
  findPlatformNavItem,
  getPlatformNavGroups,
  getPlatformOffRailItems,
  getPlatformUserMenuItems,
  isPlatformNavHrefActive,
  isPlatformNavItemActive,
  platformNavGatedReason,
  platformNavSectionLabel,
  toPlatformNavInjections,
  type PlatformNavItem,
} from '../../lib/platform-nav';
import { PLATFORM_NAV_ICONS, resolvePlatformNavIcon } from '../../lib/platform-nav-icons';
import {
  UNRELEASED_FEATURE_IDS,
  isFeatureReleased,
  parsePreviewFeatures,
} from '../../lib/feature-release';

/** Every modelled destination — rail groups, the user menu and the off-rail destinations. */
const ALL_ITEMS: PlatformNavItem[] = [
  ...PLATFORM_NAV_GROUPS.flatMap((group) => group.items),
  ...PLATFORM_USER_MENU_ITEMS,
  ...PLATFORM_OFF_RAIL_ITEMS,
];

/** Look a destination up by id, failing loudly rather than returning undefined. */
function item(id: string): PlatformNavItem {
  const found = findPlatformNavItem(id);
  if (!found) throw new Error(`No nav item with id "${id}"`);
  return found;
}

const TENANT = 't-1';

describe('platform-nav model — shape', () => {
  it('groups destinations by job to be done, in DESIGN.md §6 order', () => {
    expect(PLATFORM_NAV_GROUPS.map((group) => group.id)).toEqual([
      'home',
      'build',
      'bring-in',
      'ship',
      'govern',
      'workspace',
    ]);
    expect(PLATFORM_NAV_GROUPS.map((group) => group.label)).toEqual([
      undefined,
      'Build',
      'Bring in',
      'Ship',
      'Govern',
      'Workspace',
    ]);
    // Every declared group id is actually used, and vice versa.
    expect([...PLATFORM_NAV_GROUP_IDS].sort()).toEqual(
      PLATFORM_NAV_GROUPS.map((group) => group.id).sort()
    );
  });

  it('carries every destination §6 lists, in its group', () => {
    const byGroup = Object.fromEntries(
      PLATFORM_NAV_GROUPS.map((group) => [group.id, group.items.map((navItem) => navItem.id)])
    );

    expect(byGroup).toEqual({
      home: ['home'],
      build: ['projects', 'primitives'],
      'bring-in': ['catalog', 'repositories', 'connectors', 'mcp'],
      ship: ['published', 'sunset-timeline', 'export-studio'],
      govern: ['style-guides', 'lint-workspace', 'shadow-apis', 'dependency-graph', 'audit'],
      workspace: ['members', 'roles', 'teams', 'api-keys', 'schema-registry'],
    });
    expect(PLATFORM_USER_MENU_ITEMS.map((navItem) => navItem.id)).toEqual([
      'profile',
      'linked-accounts',
    ]);
  });

  it('labels every destination the way the mockup does', () => {
    expect(ALL_ITEMS.map((navItem) => navItem.label)).toEqual([
      'Home',
      'Projects',
      'Primitives & types',
      'Catalog',
      'Repositories',
      'Connectors',
      'MCP servers',
      'Published',
      'Sunset timeline',
      'Export studio',
      'Style guides',
      'Lint posture',
      'Shadow APIs',
      'Dependency graph',
      'Access audit',
      'Members',
      'Roles',
      'Teams',
      'API keys',
      'Schema registry',
      'Profile',
      'Linked accounts',
      'Tenants',
      'SDK settings',
      'Data browser',
      'Migrations',
    ]);
  });

  it('gives ids and hrefs that are unique', () => {
    const ids = ALL_ITEMS.map((navItem) => navItem.id);
    const hrefs = ALL_ITEMS.map((navItem) => navItem.href);
    expect(new Set(ids).size).toBe(ids.length);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it('marks only Lint posture as a preview', () => {
    expect(ALL_ITEMS.filter((navItem) => navItem.pill).map((navItem) => [navItem.id, navItem.pill]))
      .toEqual([['lint-workspace', 'Preview']]);
  });

  it('names only icons the icon map can resolve', () => {
    for (const navItem of ALL_ITEMS) {
      expect(PLATFORM_NAV_ICONS[navItem.icon]).toBeDefined();
      expect(resolvePlatformNavIcon(navItem.icon)).toBe(PLATFORM_NAV_ICONS[navItem.icon]);
    }
  });

  it('falls back to the generic icon for a name it does not know', () => {
    expect(resolvePlatformNavIcon('no-such-glyph')).toBe(
      PLATFORM_NAV_ICONS[DEFAULT_PLATFORM_NAV_ICON]
    );
  });

  it('finds a destination by id, and reports an unknown id as undefined', () => {
    expect(item('catalog').href).toBe('/ade/dashboard/catalog');
    expect(findPlatformNavItem('nope')).toBeUndefined();
  });
});

describe('platform-nav model — nothing commercial is hard-coded', () => {
  /** The Tools routes, which HIVE-12.2 gave an off-rail home (the user menu). */
  const TOOLS = ['/ade/database', '/ade/migration'];

  it('contains no studio route, and the Tools only off the rail', () => {
    for (const navItem of ALL_ITEMS) {
      expect(navItem.href.startsWith('/ade/studio')).toBe(false);
    }
    const railHrefs = PLATFORM_NAV_GROUPS.flatMap((group) => group.items).map((navItem) => navItem.href);
    for (const prefix of TOOLS) {
      expect(railHrefs.some((href) => href.startsWith(prefix))).toBe(false);
    }
  });

  it('routes every rail and account destination through /ade/dashboard', () => {
    for (const navItem of ALL_ITEMS) {
      const isTool = TOOLS.some((prefix) => navItem.href.startsWith(prefix));
      expect(isTool || navItem.href.startsWith('/ade/dashboard')).toBe(true);
      expect(navItem.external).toBeUndefined();
    }
  });
});

describe('platform-nav model — active-state resolution', () => {
  /**
   * Every route the model can be asked about, and the one destination that owns
   * it. Transcribed from the pre-Hive `DashboardSideNav.isActive`, so a change
   * to the resolver that changes behaviour fails here.
   */
  const ROUTES: ReadonlyArray<[pathname: string, ownerId: string]> = [
    ['/ade/dashboard', 'home'],
    ['/ade/dashboard/projects', 'projects'],
    [PLATFORM_NAV_VERSIONS_HREF, 'projects'],
    [`${PLATFORM_NAV_VERSIONS_HREF}/v-1`, 'projects'],
    [PLATFORM_NAV_SUNSET_TIMELINE_HREF, 'sunset-timeline'],
    ['/ade/dashboard/primitives', 'primitives'],
    ['/ade/dashboard/primitives/p-1', 'primitives'],
    ['/ade/dashboard/catalog', 'catalog'],
    ['/ade/dashboard/catalog/c-1', 'catalog'],
    ['/ade/dashboard/repositories', 'repositories'],
    ['/ade/dashboard/repositories/new', 'repositories'],
    ['/ade/dashboard/repositories/r-1/preview', 'repositories'],
    ['/ade/dashboard/mcp', 'mcp'],
    ['/ade/dashboard/mcp/capabilities', 'mcp'],
    ['/ade/dashboard/mcp/e-1', 'mcp'],
    ['/ade/dashboard/published', 'published'],
    ['/ade/dashboard/export/studio', 'export-studio'],
    ['/ade/dashboard/style-guides', 'style-guides'],
    ['/ade/dashboard/lint-workspace', 'lint-workspace'],
    ['/ade/dashboard/lint-workspace/findings', 'lint-workspace'],
    ['/ade/dashboard/audit', 'audit'],
    ['/ade/dashboard/connectors', 'connectors'],
    ['/ade/dashboard/connectors/new', 'connectors'],
    ['/ade/dashboard/connectors/3f1c', 'connectors'],
    ['/ade/dashboard/connectors/shadow', 'shadow-apis'],
    ['/ade/dashboard/graph', 'dependency-graph'],
    ['/ade/dashboard/members', 'members'],
    ['/ade/dashboard/roles', 'roles'],
    ['/ade/dashboard/teams', 'teams'],
    ['/ade/dashboard/teams/payments', 'teams'],
    ['/ade/dashboard/api-keys', 'api-keys'],
    ['/ade/dashboard/schema-registry', 'schema-registry'],
    ['/ade/dashboard/tenants', 'tenants'],
    ['/ade/dashboard/profile', 'profile'],
    ['/ade/dashboard/linked-accounts', 'linked-accounts'],
    ['/ade/database', 'data-browser'],
    ['/ade/database/tables', 'data-browser'],
    ['/ade/migration', 'migrations'],
  ];

  it.each(ROUTES)('%s activates exactly one destination', (pathname, ownerId) => {
    const active = ALL_ITEMS.filter((navItem) => isPlatformNavItemActive(navItem, pathname));
    expect(active.map((navItem) => navItem.id)).toEqual([ownerId]);
    expect(isPlatformNavHrefActive(item(ownerId).href, pathname)).toBe(true);
  });

  it('keeps Projects and Sunset timeline from claiming each other', () => {
    expect(isPlatformNavHrefActive(item('projects').href, PLATFORM_NAV_SUNSET_TIMELINE_HREF)).toBe(
      false
    );
    expect(
      isPlatformNavHrefActive(item('sunset-timeline').href, `${PLATFORM_NAV_VERSIONS_HREF}/v-1`)
    ).toBe(false);
  });

  it('matches leaf destinations exactly, never by prefix', () => {
    // `published` has no children today; a lookalike route must not light it up.
    expect(isPlatformNavHrefActive(item('published').href, '/ade/dashboard/published/x')).toBe(
      false
    );
    // `/export` is a page of its own; only `/export/studio` is the nav entry.
    expect(isPlatformNavHrefActive(item('export-studio').href, '/ade/dashboard/export')).toBe(false);
    // Carried over verbatim from the pre-Hive sidebar: a style-guide detail page
    // highlights nothing. DESIGN.md §6 lists `/[guideId]` under Style guides, so
    // this is a candidate for the ticket that owns that page — but changing it
    // here would break "active-state rules preserved exactly".
    expect(isPlatformNavHrefActive(item('style-guides').href, '/ade/dashboard/style-guides/g-1')).toBe(
      false
    );
  });

  it('never matches a sibling route that merely shares a prefix', () => {
    expect(isPlatformNavHrefActive(item('catalog').href, '/ade/dashboard/catalog-archive')).toBe(
      false
    );
    expect(isPlatformNavHrefActive(item('mcp').href, '/ade/dashboard/mcpx')).toBe(false);
  });

  it('is inactive before hydration, when the pathname is not known yet', () => {
    expect(isPlatformNavHrefActive(item('home').href, null)).toBe(false);
    expect(isPlatformNavHrefActive(item('home').href, undefined)).toBe(false);
    expect(isPlatformNavItemActive(item('home'), null)).toBe(false);
  });

  it('matches an unmodelled href exactly unless it declares its own rule', () => {
    const contributed = { href: '/ade/dashboard/anything' };
    expect(isPlatformNavHrefActive(contributed.href, contributed.href)).toBe(true);
    expect(isPlatformNavHrefActive(contributed.href, `${contributed.href}/child`)).toBe(false);

    const subtree = { href: '/ade/dashboard/anything', match: 'subtree' as const };
    expect(isPlatformNavItemActive(subtree, `${subtree.href}/child`)).toBe(true);
  });
});

describe('platform-nav model — workspace gating', () => {
  /** Exactly the entries the pre-Hive sidebar greyed out with no tenant. */
  const GATED = [
    'projects',
    'primitives',
    'catalog',
    'repositories',
    'connectors',
    'mcp',
    'published',
    'sunset-timeline',
    'export-studio',
    'style-guides',
    'lint-workspace',
    'shadow-apis',
    'dependency-graph',
    'audit',
    'members',
    'roles',
    'teams',
    'api-keys',
    'schema-registry',
  ];

  it('disables exactly the workspace-scoped destinations when there is no tenant', () => {
    const disabled = getPlatformNavGroups({ currentTenantId: null })
      .flatMap((group) => group.items)
      .filter((navItem) => navItem.disabled)
      .map((navItem) => navItem.id);

    expect(disabled.sort()).toEqual(GATED.filter((id) => isFeatureReleased(id)).sort());
  });

  it('leaves Home, Tenants, the Tools and the account destinations reachable without a tenant', () => {
    const enabled = getPlatformNavGroups({ currentTenantId: undefined })
      .flatMap((group) => group.items)
      .filter((navItem) => !navItem.disabled)
      .map((navItem) => navItem.id);

    expect(enabled).toEqual(['home']);
    expect(
      getPlatformOffRailItems({ currentTenantId: undefined })
        .filter((navItem) => !navItem.disabled)
        .map((navItem) => navItem.id)
    ).toEqual(['tenants', 'data-browser', 'migrations']);
    expect(
      getPlatformUserMenuItems({ currentTenantId: undefined }).every((navItem) => !navItem.disabled)
    ).toBe(true);
  });

  it('enables everything released once a workspace is selected', () => {
    const groups = getPlatformNavGroups({ currentTenantId: TENANT });
    for (const group of groups) {
      for (const navItem of group.items) {
        if (!isFeatureReleased(navItem.id)) continue;
        expect(navItem.disabled).toBe(false);
        expect(navItem.disabledReason).toBeUndefined();
      }
    }
  });

  it('explains each gated destination by name', () => {
    const projects = getPlatformNavGroups({ currentTenantId: null })
      .flatMap((group) => group.items)
      .find((navItem) => navItem.id === 'projects');

    expect(projects?.disabledReason).toBe('Select a workspace to use Projects.');
    expect(platformNavGatedReason('Catalog')).toBe('Select a workspace to use Catalog.');
  });

  it('treats an empty tenant id as no tenant', () => {
    const projects = getPlatformNavGroups({ currentTenantId: '' })
      .flatMap((group) => group.items)
      .find((navItem) => navItem.id === 'projects');

    expect(projects?.disabled).toBe(true);
  });

  it('does not mutate the model when resolving', () => {
    getPlatformNavGroups({ currentTenantId: null });
    expect(
      PLATFORM_NAV_GROUPS.flatMap((group) => group.items).every(
        (navItem) => !('disabled' in navItem)
      )
    ).toBe(true);
  });
});

describe('platform-nav model — runtime injection', () => {
  const contributed = {
    id: 'suite-designer',
    label: 'Designer',
    href: 'https://suite.example.com/editor',
    external: true,
  };

  it('appends a contributed destination after the group it was addressed to', () => {
    const [injection] = toPlatformNavInjections([contributed], 'build');
    const build = getPlatformNavGroups({ currentTenantId: TENANT, injected: [injection] }).find(
      (group) => group.id === 'build'
    );

    expect(build?.items.map((navItem) => navItem.id)).toEqual(
      ['projects', 'primitives', 'suite-designer'].filter((id) => isFeatureReleased(id))
    );
    expect(build?.items.at(-1)).toMatchObject({
      href: contributed.href,
      external: true,
      icon: DEFAULT_PLATFORM_NAV_ICON,
      disabled: false,
    });
  });

  it('defaults contributions to Build and honours an explicit icon', () => {
    const [injection] = toPlatformNavInjections([{ ...contributed, icon: 'shapes' }]);
    expect(injection.group).toBe('build');
    expect(injection.item.icon).toBe('shapes');
  });

  it('places contributions in Bring in or Ship when the host asks', () => {
    const injected = [
      ...toPlatformNavInjections([contributed], 'bring-in'),
      ...toPlatformNavInjections([{ ...contributed, id: 'suite-paths' }], 'ship'),
    ];
    const groups = getPlatformNavGroups({ currentTenantId: TENANT, injected });

    expect(groups.find((group) => group.id === 'bring-in')?.items.at(-1)?.id).toBe('suite-designer');
    expect(groups.find((group) => group.id === 'ship')?.items.at(-1)?.id).toBe('suite-paths');
  });

  it('drops a contribution addressed to a group that does not exist', () => {
    const groups = getPlatformNavGroups({
      currentTenantId: TENANT,
      injected: [
        // A host built against a later model, naming a group this build lacks.
        { group: 'tools' as never, item: { ...contributed, icon: 'box' } },
      ],
    });

    expect(groups.flatMap((group) => group.items).map((navItem) => navItem.id)).not.toContain(
      'suite-designer'
    );
  });

  it('renders the first-party model unchanged when nothing is contributed', () => {
    expect(
      getPlatformNavGroups({ currentTenantId: TENANT }).flatMap((group) =>
        group.items.map((navItem) => navItem.id)
      )
    ).toEqual(
      PLATFORM_NAV_GROUPS.flatMap((group) => group.items.map((navItem) => navItem.id)).filter(
        (id) => isFeatureReleased(id)
      )
    );
  });
});

describe('platform-nav model — release gate (MVP focus on Catalog and Projects)', () => {
  const ORIGINAL = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;

  afterEach(() => {
    if (ORIGINAL === undefined) delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    else process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = ORIGINAL;
  });

  /** Modelled rail ids the session's rail leaves out — only the release gate drops any. */
  function hiddenWithTenant(): string[] {
    const shown = new Set(
      getPlatformNavGroups({ currentTenantId: TENANT })
        .flatMap((group) => group.items)
        .map((navItem) => navItem.id)
    );
    for (const navItem of getPlatformOffRailItems({ currentTenantId: TENANT })) shown.add(navItem.id);
    return [...PLATFORM_NAV_GROUPS.flatMap((group) => group.items), ...PLATFORM_OFF_RAIL_ITEMS]
      .map((navItem) => navItem.id)
      .filter((id) => !shown.has(id));
  }

  it('holds back exactly the unreleased features, and every one of them is a modelled destination', () => {
    delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    expect([...UNRELEASED_FEATURE_IDS].sort()).toEqual([
      'audit',
      'export-studio',
      'mcp',
      'primitives',
      'sdk-settings',
      'style-guides',
    ]);
    for (const id of UNRELEASED_FEATURE_IDS) expect(findPlatformNavItem(id)).toBeDefined();
    expect(hiddenWithTenant().sort()).toEqual([...UNRELEASED_FEATURE_IDS].sort());
  });

  it('keeps Catalog and Projects open', () => {
    delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    expect(isFeatureReleased('catalog')).toBe(true);
    expect(isFeatureReleased('projects')).toBe(true);
  });

  it('leaves an unreleased destination out rather than disabling it, with or without a workspace', () => {
    delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    for (const tenant of [TENANT, null]) {
      const ids = getPlatformNavGroups({ currentTenantId: tenant })
        .flatMap((group) => group.items)
        .map((navItem) => navItem.id);
      expect(ids).not.toContain('mcp');
    }
  });

  it('re-opens listed features, or all of them, through the preview override', () => {
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = ' mcp , audit ';
    expect(hiddenWithTenant().sort()).toEqual(['export-studio', 'primitives', 'sdk-settings', 'style-guides']);

    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'ALL';
    expect(hiddenWithTenant()).toEqual([]);
  });

  it('parses the override, dropping blanks', () => {
    expect(parsePreviewFeatures(undefined)).toEqual(new Set());
    expect(parsePreviewFeatures('  ')).toEqual(new Set());
    expect(parsePreviewFeatures('all')).toBe('all');
    expect(parsePreviewFeatures('mcp,,audit,')).toEqual(new Set(['mcp', 'audit']));
  });

  it('never gates an id it does not list, whatever the override says', () => {
    expect(isFeatureReleased('members', '')).toBe(true);
    expect(isFeatureReleased('some-commercial-item', null)).toBe(true);
  });
});

describe('platform-nav model — off-rail destinations (HIVE-12.2)', () => {
  const releasedRailCount = () =>
    getPlatformNavGroups({ currentTenantId: TENANT }).flatMap((group) => group.items).length;

  afterEach(() => {
    delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
  });

  it('leaves 15 released destinations in the rail, 20 with every feature previewed', () => {
    delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    expect(releasedRailCount()).toBe(15);
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'all';
    expect(releasedRailCount()).toBe(20);
  });

  it('takes Tenants and SDK settings out of the rail and gives every off-rail item a home', () => {
    const railIds = PLATFORM_NAV_GROUPS.flatMap((group) => group.items).map((navItem) => navItem.id);
    expect(railIds).not.toContain('tenants');
    expect(railIds).not.toContain('sdk-settings');
    expect(PLATFORM_OFF_RAIL_ITEMS.map((navItem) => [navItem.id, navItem.home, navItem.section])).toEqual([
      ['tenants', 'workspace-switcher', 'Workspace'],
      ['sdk-settings', 'export-studio-tab', 'Ship'],
      ['data-browser', 'user-menu', 'Tools'],
      ['migrations', 'user-menu', 'Tools'],
    ]);
  });

  it('points SDK settings at the Export studio tab, and keeps the old route as its redirect', () => {
    expect(item('sdk-settings').href).toBe(PLATFORM_NAV_SDK_SETTINGS_HREF);
    expect(PLATFORM_NAV_SDK_SETTINGS_HREF).toBe('/ade/dashboard/export/studio?tab=sdk');
    expect(PLATFORM_NAV_LEGACY_SDK_SETTINGS_HREF).toBe('/ade/dashboard/sdk-settings');
    // The tab's address is not a second owner of the Export studio route.
    expect(isPlatformNavItemActive(item('sdk-settings'), '/ade/dashboard/export/studio')).toBe(false);
    expect(isPlatformNavItemActive(item('export-studio'), '/ade/dashboard/export/studio')).toBe(true);
  });

  it('keeps Tenants and the Tools ungated and SDK settings workspace-scoped', () => {
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'all';
    const byId = new Map(
      getPlatformOffRailItems({ currentTenantId: null }).map((navItem) => [navItem.id, navItem])
    );
    expect(byId.get('tenants')?.disabled).toBe(false);
    expect(byId.get('data-browser')?.disabled).toBe(false);
    expect(byId.get('migrations')?.disabled).toBe(false);
    expect(byId.get('sdk-settings')).toMatchObject({
      disabled: true,
      disabledReason: platformNavGatedReason('SDK settings'),
    });
  });

  it('drops an unreleased off-rail destination and filters by home', () => {
    delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    expect(getPlatformOffRailItems({ currentTenantId: TENANT }).map((navItem) => navItem.id)).toEqual([
      'tenants',
      'data-browser',
      'migrations',
    ]);
    expect(getPlatformOffRailItems({}, 'user-menu').map((navItem) => navItem.label)).toEqual([
      'Data browser',
      'Migrations',
    ]);
    expect(getPlatformOffRailItems({}, 'workspace-switcher').map((navItem) => navItem.id)).toEqual([
      'tenants',
    ]);
  });

  it('names each destination\'s section — rail group or off-rail section', () => {
    expect(platformNavSectionLabel('catalog')).toBe('Bring in');
    expect(platformNavSectionLabel('sdk-settings')).toBe('Ship');
    expect(platformNavSectionLabel('tenants')).toBe('Workspace');
    expect(platformNavSectionLabel('data-browser')).toBe('Tools');
    expect(platformNavSectionLabel('home')).toBeUndefined();
    expect(platformNavSectionLabel('nope')).toBeUndefined();
  });

  it('resolves an icon for every off-rail destination', () => {
    for (const navItem of PLATFORM_OFF_RAIL_ITEMS) {
      expect(PLATFORM_NAV_ICONS[navItem.icon]).toBeDefined();
    }
  });
});
