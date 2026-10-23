import { getMainAppUrl, normalizeAppOrigin } from './app-urls';
import { getCommercialNavItems, type ExternalNavItem } from './external-links';
import { isFeatureReleased } from './feature-release';
import { getSuiteTriggerIsActive } from './suite-contract';
import { STUDIO_APP_ROUTES, UI_STUDIO_ROUTES } from './studio-routes';

export { getMainAppUrl, normalizeAppOrigin };

/** True when this Next.js app is the standalone studio surface. */
export function isStudioSurface(): boolean {
  return process.env.NEXT_PUBLIC_APP_SURFACE === 'studio';
}

/** @deprecated Prefer getMainAppUrl() — resolved at call time for correct env in tests and SSR. */
export const MAIN_APP_URL = getMainAppUrl();

export function mainAppPath(path: string): string {
  const suffix = path.startsWith('/') ? path : `/${path}`;
  return `${getMainAppUrl()}${suffix}`;
}

export function getPlatformCoreNavItems(): ExternalNavItem[] {
  const onStudio = isStudioSurface();
  return [
    {
      id: 'home',
      label: 'Home',
      href: onStudio ? mainAppPath('/ade') : '/ade',
      external: onStudio,
    },
    {
      id: 'control-panel',
      label: 'Control Panel',
      href: onStudio ? mainAppPath('/ade/dashboard') : '/ade/dashboard',
      external: onStudio,
    },
  ];
}

/** Commercial app tabs (Suite) — pass items filtered by license entitlements. */
export function getStudioCommercialNavItems(entitledFlags: Set<string>): ExternalNavItem[] {
  return getCommercialNavItems(entitledFlags);
}

export function getPlatformNavItems(commercialNavItems: ExternalNavItem[] = []): ExternalNavItem[] {
  return [...getPlatformCoreNavItems(), ...commercialNavItems];
}

/** Nav href comes from commercial product config (NEXT_PUBLIC_STUDIO_URL). */
export function resolvePlatformNavHref(item: ExternalNavItem): string {
  return item.href;
}

function isStudioAppPathActive(pathname: string): boolean {
  if (isStudioSurface()) {
    return (
      pathname === STUDIO_APP_ROUTES.root ||
      pathname === STUDIO_APP_ROUTES.editor ||
      pathname.startsWith(`${STUDIO_APP_ROUTES.editor}/`) ||
      pathname === STUDIO_APP_ROUTES.paths ||
      pathname.startsWith(`${STUDIO_APP_ROUTES.paths}/`) ||
      pathname === STUDIO_APP_ROUTES.code ||
      pathname.startsWith(`${STUDIO_APP_ROUTES.code}/`)
    );
  }
  return (
    pathname === UI_STUDIO_ROUTES.root ||
    pathname.startsWith(`${UI_STUDIO_ROUTES.root}/`)
  );
}

export function platformNavItemIsActive(item: ExternalNavItem, pathname: string | null): boolean {
  if (!pathname) return false;

  if (item.id === 'home') {
    return !isStudioSurface() && pathname === '/ade';
  }
  if (item.id === 'control-panel') {
    return !isStudioSurface() && pathname.startsWith('/ade/dashboard');
  }
  // Designer trigger: built-in studio routes, plus any contributed active check
  // from a commercial suite host (no product-specific paths live here).
  if (item.id === 'suite') {
    const contributed = getSuiteTriggerIsActive();
    return isStudioAppPathActive(pathname) || (contributed?.(pathname) ?? false);
  }

  if (item.external || item.href.startsWith('http://') || item.href.startsWith('https://')) {
    return false;
  }
  return (
    pathname === item.href ||
    (item.href !== '/ade' && pathname.startsWith(`${item.href}/`))
  );
}

export function platformProfilePath(): string {
  return isStudioSurface() ? mainAppPath('/ade/dashboard/profile') : '/ade/dashboard/profile';
}

/* ==========================================================================
   Hive navigation model (HIVE-3.2, #5288) — DESIGN.md §6
   --------------------------------------------------------------------------
   One declarative description of where a signed-in user can go, replacing the
   hard-coded array that used to live inside `DashboardSideNav.tsx` and the
   per-item `isActive` special cases beside it.

   Three rules hold this module together:

     1. **Data, not markup.** Every entry is plain, serialisable data — the
        icon is a Lucide *name*, resolved to a component by
        `lib/platform-nav-icons.ts`, so the model can be imported (and tested)
        without pulling a rendering library behind it.
     2. **One active-state resolver.** `isPlatformNavHrefActive()` owns every
        rule about which pathname belongs to which destination. A component
        asks; it never decides.
     3. **Nothing about a separate product.** Commercial suite destinations are
        *injected* by the host at runtime ({@link PlatformNavInjection}); this
        repository reserves the slot and never names a route it does not own.

   Grouping is by job-to-be-done (Build · Bring in · Ship · Govern ·
   Workspace), not by the internal org chart the old sidebar mirrored.
   ========================================================================== */

/** Ids of the rail's nav groups, in render order (DESIGN.md §6). */
export const PLATFORM_NAV_GROUP_IDS = [
  'home',
  'build',
  'bring-in',
  'ship',
  'govern',
  'workspace',
] as const;

/** One of {@link PLATFORM_NAV_GROUP_IDS}. */
export type PlatformNavGroupId = (typeof PLATFORM_NAV_GROUP_IDS)[number];

/**
 * How a destination decides whether the current pathname belongs to it.
 *
 * - `exact` — the pathname *is* the href. The default, and what every
 *   leaf-page entry uses.
 * - `subtree` — the href or anything below it (`/catalog`, `/catalog/42`).
 * - `projects` — the one irregular rule, kept verbatim from the pre-Hive
 *   sidebar: Projects also owns the *versions* subtree, because a version is
 *   reached by drilling into a project — but **not** the sunset timeline,
 *   which lives under `/versions/` yet is its own nav entry.
 */
export type PlatformNavMatch = 'exact' | 'subtree' | 'projects' | 'connectors';

/** A destination in the rail, a menu, or the command palette. */
export interface PlatformNavItem {
  /** Stable id — used as a React key, a test handle and a palette address. */
  id: string;
  /** Human label, in the sentence case DESIGN.md §10 asks for. */
  label: string;
  /** In-app route, or an absolute URL when {@link external} is set. */
  href: string;
  /** Lucide icon name; resolve with `resolvePlatformNavIcon()`. */
  icon: string;
  /** Maturity chip beside the label, e.g. `Preview`. */
  pill?: string;
  /** True when the destination is meaningless without a selected workspace. */
  requiresTenant?: boolean;
  /** Active-state rule; defaults to `exact`. */
  match?: PlatformNavMatch;
  /** True for destinations outside this application (a commercial host). */
  external?: boolean;
}

/** A labelled run of destinations. */
export interface PlatformNavGroup {
  id: PlatformNavGroupId;
  /** Group heading. Omitted for the leading, unlabelled group (Home). */
  label?: string;
  /**
   * True when the group starts folded for a reader who has never folded or unfolded a
   * group (HIVE-12.1). Once they have, their stored choice under `hive.navCollapsed` wins;
   * see `readCollapsedNavGroups()`. Only meaningful on a labelled group: an unlabelled one
   * has no heading to unfold it with.
   */
  defaultCollapsed?: boolean;
  items: PlatformNavItem[];
}

/** A destination with its gating decided for the current session. */
export interface ResolvedPlatformNavItem extends PlatformNavItem {
  /** True when the item must render non-interactive. */
  disabled: boolean;
  /** Why it is disabled — tooltip copy. Absent when the item is enabled. */
  disabledReason?: string;
}

/** A group whose destinations have had their gating decided. */
export interface ResolvedPlatformNavGroup extends Omit<PlatformNavGroup, 'items'> {
  items: ResolvedPlatformNavItem[];
}

/** A destination contributed at runtime, with the group it belongs in. */
export interface PlatformNavInjection {
  /** Which group the host wants the destination to appear in. */
  group: PlatformNavGroupId;
  /** The destination itself. */
  item: PlatformNavItem;
}

/** What {@link getPlatformNavGroups} needs to decide gating and injection. */
export interface PlatformNavOptions {
  /** `current_tenant_id` from the session; absent/empty means "no workspace". */
  currentTenantId?: string | null;
  /** Destinations contributed by a commercial suite host (entitlement-filtered). */
  injected?: readonly PlatformNavInjection[];
}

/* -------------------------------------------------------------------------
   Routes
   ------------------------------------------------------------------------- */

/** The dashboard root — "Home" in the rail. */
const DASHBOARD_HREF = '/ade/dashboard';

/** Version list. Owned by Projects for active-state purposes, never its own item. */
export const PLATFORM_NAV_VERSIONS_HREF = `${DASHBOARD_HREF}/versions`;

/** The one `/versions/` child that is *not* Projects: its own nav entry. */
export const PLATFORM_NAV_SUNSET_TIMELINE_HREF = `${PLATFORM_NAV_VERSIONS_HREF}/sunset-timeline`;

/**
 * Icon used for a contributed destination that names no icon of its own.
 *
 * Mirrors `resolveExternalLinkIcon`'s fallback so a commercial entry looks the
 * same in the rail as it does on the launcher grid.
 */
export const DEFAULT_PLATFORM_NAV_ICON = 'box';

/* -------------------------------------------------------------------------
   The model
   ------------------------------------------------------------------------- */

/**
 * Every first-party destination, grouped by job to be done (DESIGN.md §6).
 *
 * Deliberately absent, and not an oversight:
 *
 * - **Tenants, SDK settings and the Tools** (Data browser, Migrations) — they
 *   live off the rail, in the menus beside the things they configure; see
 *   {@link PLATFORM_OFF_RAIL_ITEMS} (HIVE-12.2).
 * - **`/ade/studio*`** — a commercial product in another repository. It
 *   arrives (or does not) through {@link PlatformNavOptions.injected}.
 * - **Profile / Linked accounts** — user-menu destinations, not rail items;
 *   see {@link PLATFORM_USER_MENU_ITEMS}.
 */
export const PLATFORM_NAV_GROUPS: readonly PlatformNavGroup[] = [
  {
    id: 'home',
    items: [
      { id: 'home', label: 'Home', href: DASHBOARD_HREF, icon: 'house' },
    ],
  },
  {
    id: 'build',
    label: 'Build',
    items: [
      {
        id: 'projects',
        label: 'Projects',
        href: `${DASHBOARD_HREF}/projects`,
        icon: 'folder-kanban',
        requiresTenant: true,
        match: 'projects',
      },
      {
        id: 'primitives',
        label: 'Primitives & types',
        href: `${DASHBOARD_HREF}/primitives`,
        icon: 'shapes',
        requiresTenant: true,
        match: 'subtree',
      },
    ],
  },
  {
    id: 'bring-in',
    label: 'Bring in',
    items: [
      {
        id: 'catalog',
        label: 'Catalog',
        href: `${DASHBOARD_HREF}/catalog`,
        icon: 'library',
        requiresTenant: true,
        match: 'subtree',
      },
      {
        id: 'repositories',
        label: 'Repositories',
        href: `${DASHBOARD_HREF}/repositories`,
        icon: 'git-branch',
        requiresTenant: true,
        match: 'subtree',
      },
      {
        // CDG-1.7: gateways and registries whose APIs sync into the catalog.
        id: 'connectors',
        label: 'Connectors',
        href: `${DASHBOARD_HREF}/connectors`,
        icon: 'plug',
        requiresTenant: true,
        match: 'connectors',
      },
      {
        id: 'mcp',
        label: 'MCP servers',
        href: `${DASHBOARD_HREF}/mcp`,
        icon: 'network',
        requiresTenant: true,
        // The MCP entry owns its capabilities/analytics/comparison sections,
        // which are reached from an in-page tab bar rather than their own items.
        match: 'subtree',
      },
    ],
  },
  {
    id: 'ship',
    label: 'Ship',
    items: [
      {
        id: 'published',
        label: 'Published',
        href: `${DASHBOARD_HREF}/published`,
        icon: 'globe',
        requiresTenant: true,
      },
      {
        id: 'sunset-timeline',
        label: 'Sunset timeline',
        href: PLATFORM_NAV_SUNSET_TIMELINE_HREF,
        icon: 'sunset',
        requiresTenant: true,
      },
      {
        id: 'export-studio',
        label: 'Export studio',
        href: `${DASHBOARD_HREF}/export/studio`,
        icon: 'package-open',
        requiresTenant: true,
      },
    ],
  },
  {
    id: 'govern',
    label: 'Govern',
    items: [
      {
        id: 'style-guides',
        label: 'Style guides',
        href: `${DASHBOARD_HREF}/style-guides`,
        icon: 'book-open-check',
        requiresTenant: true,
      },
      {
        id: 'lint-workspace',
        label: 'Lint posture',
        href: `${DASHBOARD_HREF}/lint-workspace`,
        icon: 'shield-check',
        pill: 'Preview',
        requiresTenant: true,
        match: 'subtree',
      },
      {
        // CDG-1.6: what connected gateways serve that the catalog does not describe.
        id: 'shadow-apis',
        label: 'Shadow APIs',
        href: `${DASHBOARD_HREF}/connectors/shadow`,
        icon: 'radar',
        requiresTenant: true,
      },
      {
        // CDG-3.4: what depends on what, and the blast radius of a change.
        id: 'dependency-graph',
        label: 'Dependency graph',
        href: `${DASHBOARD_HREF}/graph`,
        icon: 'network',
        requiresTenant: true,
      },
      {
        id: 'audit',
        label: 'Access audit',
        href: `${DASHBOARD_HREF}/audit`,
        icon: 'scroll-text',
        requiresTenant: true,
      },
    ],
  },
  {
    id: 'workspace',
    label: 'Workspace',
    // Admin chores rather than daily work: folded on first run so the rail fits a 900 px
    // tall window, its heading showing how many rows it holds (HIVE-12.1).
    defaultCollapsed: true,
    items: [
      {
        id: 'members',
        label: 'Members',
        href: `${DASHBOARD_HREF}/members`,
        icon: 'users',
        requiresTenant: true,
      },
      {
        id: 'roles',
        label: 'Roles',
        href: `${DASHBOARD_HREF}/roles`,
        icon: 'shield',
        requiresTenant: true,
      },
      {
        // CDG-2.4: the groups that own catalog entities and receive their findings.
        id: 'teams',
        label: 'Teams',
        href: `${DASHBOARD_HREF}/teams`,
        icon: 'users-round',
        requiresTenant: true,
        // A team page (`/teams/[slug]`) still lights the Teams entry.
        match: 'subtree',
      },
      {
        id: 'api-keys',
        label: 'API keys',
        href: `${DASHBOARD_HREF}/api-keys`,
        icon: 'key-round',
        requiresTenant: true,
      },
      {
        // CDG-4.5: registry defaults, serializer snippets and the tenant's schema subjects.
        id: 'schema-registry',
        label: 'Schema registry',
        href: `${DASHBOARD_HREF}/schema-registry`,
        icon: 'file-json-2',
        requiresTenant: true,
      },
    ],
  },
];

/**
 * Account destinations, which DESIGN.md §6 places in the rail footer's user
 * menu rather than in the nav groups.
 *
 * Neither is workspace-gated: a user with no workspace still has an identity.
 */
export const PLATFORM_USER_MENU_ITEMS: readonly PlatformNavItem[] = [
  { id: 'profile', label: 'Profile', href: `${DASHBOARD_HREF}/profile`, icon: 'circle-user' },
  {
    id: 'linked-accounts',
    label: 'Linked accounts',
    href: `${DASHBOARD_HREF}/linked-accounts`,
    icon: 'link',
  },
];

/** Where an off-rail destination is reached from, besides the command palette. */
export type PlatformOffRailHome = 'workspace-switcher' | 'user-menu' | 'export-studio-tab';

/** A destination that has a home outside the rail's groups (HIVE-12.2). */
export interface PlatformOffRailItem extends PlatformNavItem {
  /** The section the command palette lists it under — the rail group it belongs with. */
  section: string;
  /** The menu row or tab that reaches it. */
  home: PlatformOffRailHome;
}

/** The SDK & branding tab of Export studio — where `/ade/dashboard/sdk-settings` now lands. */
export const PLATFORM_NAV_SDK_SETTINGS_HREF = `${DASHBOARD_HREF}/export/studio?tab=sdk`;

/** The pre-HIVE-12.2 SDK settings route, kept as a redirect to {@link PLATFORM_NAV_SDK_SETTINGS_HREF}. */
export const PLATFORM_NAV_LEGACY_SDK_SETTINGS_HREF = `${DASHBOARD_HREF}/sdk-settings`;

/**
 * Destinations that left the rail, or never had a row in it (HIVE-12.2, #5609).
 *
 * `docs/mockups/proposals/rail-compact.html` callouts 2–4: each has a natural home next to the
 * thing it configures, which keeps the rail short enough to fit 900 px without hiding anything.
 *
 * - **Tenants** — the last row of the workspace switcher menu (“Manage workspaces…”), where
 *   switching already happens. Not tenant-gated: choosing a workspace is how you *stop* having
 *   none.
 * - **SDK settings** — the **SDK & branding** tab of Export studio; both decide how a version
 *   leaves the platform (SDK-3.4, #4494). Gated with its own feature id.
 * - **Data browser** and **Migrations** — the Tools, rows of the user menu beside Admin
 *   console. Like their routes, they need only a signed-in user.
 *
 * Every one stays in the command palette's **Jump to** (under {@link PlatformOffRailItem.section})
 * and in the active-state and lookup tables below, so a route, a `G`-jump or a gate that names
 * one of these ids resolves exactly as it did when it was a rail row.
 */
export const PLATFORM_OFF_RAIL_ITEMS: readonly PlatformOffRailItem[] = [
  {
    id: 'tenants',
    label: 'Tenants',
    href: `${DASHBOARD_HREF}/tenants`,
    icon: 'building-2',
    section: 'Workspace',
    home: 'workspace-switcher',
  },
  {
    id: 'sdk-settings',
    label: 'SDK settings',
    href: PLATFORM_NAV_SDK_SETTINGS_HREF,
    icon: 'package',
    requiresTenant: true,
    section: 'Ship',
    home: 'export-studio-tab',
  },
  {
    id: 'data-browser',
    label: 'Data browser',
    href: '/ade/database',
    icon: 'database',
    match: 'subtree',
    section: 'Tools',
    home: 'user-menu',
  },
  {
    id: 'migrations',
    label: 'Migrations',
    href: '/ade/migration',
    icon: 'git-compare-arrows',
    match: 'subtree',
    section: 'Tools',
    home: 'user-menu',
  },
];

/* -------------------------------------------------------------------------
   Active state — the single resolver
   ------------------------------------------------------------------------- */

/** Every modelled destination, flattened; the lookup table behind the resolver. */
const ALL_MODEL_ITEMS: readonly PlatformNavItem[] = [
  ...PLATFORM_NAV_GROUPS.flatMap((group) => group.items),
  ...PLATFORM_USER_MENU_ITEMS,
  ...PLATFORM_OFF_RAIL_ITEMS,
];

/** The shadow-API report, which lives under the Connectors path but is a Govern destination. */
const PLATFORM_NAV_SHADOW_APIS_HREF = `${DASHBOARD_HREF}/connectors/shadow`;

/** href → active-state rule, derived from the model so the two cannot drift. */
const MATCH_BY_HREF: ReadonlyMap<string, PlatformNavMatch> = new Map(
  ALL_MODEL_ITEMS.map((item) => [item.href, item.match ?? 'exact'])
);

/** True when `pathname` is `href` or a descendant route of it. */
function matchesSubtree(href: string, pathname: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * Does `pathname` belong to the destination at `href`?
 *
 * The rule comes from the model ({@link PlatformNavItem.match}); an href the
 * model does not know — a contributed commercial route, say — is matched
 * exactly, which is the conservative answer.
 *
 * @param href - Destination href, as it appears in the model.
 * @param pathname - Current `usePathname()` value; `null` before hydration.
 * @returns True when the destination should render as the current page.
 */
export function isPlatformNavHrefActive(href: string, pathname: string | null | undefined): boolean {
  if (!pathname) return false;

  switch (MATCH_BY_HREF.get(href) ?? 'exact') {
    case 'subtree':
      return matchesSubtree(href, pathname);
    case 'projects':
      // Projects owns itself plus the versions subtree — except the sunset
      // timeline, which is its own entry one group down.
      if (pathname === href) return true;
      if (pathname === PLATFORM_NAV_SUNSET_TIMELINE_HREF) return false;
      return matchesSubtree(PLATFORM_NAV_VERSIONS_HREF, pathname);
    case 'connectors':
      // Connectors owns its add and detail pages, but not the shadow-API report, which is its own
      // entry under Govern.
      if (pathname === PLATFORM_NAV_SHADOW_APIS_HREF || pathname.startsWith(`${PLATFORM_NAV_SHADOW_APIS_HREF}/`)) {
        return false;
      }
      return matchesSubtree(href, pathname);
    case 'exact':
    default:
      return pathname === href;
  }
}

/**
 * Convenience wrapper for callers that hold the item rather than its href.
 *
 * @param item - A modelled (or contributed) destination.
 * @param pathname - Current `usePathname()` value.
 * @returns True when the destination should render as the current page.
 */
export function isPlatformNavItemActive(
  item: Pick<PlatformNavItem, 'href' | 'match'>,
  pathname: string | null | undefined
): boolean {
  if (!pathname) return false;
  if (!MATCH_BY_HREF.has(item.href) && item.match) {
    // A contributed item carrying its own rule: honour it without the table.
    return item.match === 'subtree'
      ? matchesSubtree(item.href, pathname)
      : pathname === item.href;
  }
  return isPlatformNavHrefActive(item.href, pathname);
}

/* -------------------------------------------------------------------------
   Gating
   ------------------------------------------------------------------------- */

/**
 * Why a workspace-scoped destination is unavailable.
 *
 * One sentence, naming the destination, so the tooltip reads as an
 * explanation rather than a refusal (DESIGN.md §10).
 *
 * @param label - The destination's label.
 * @returns Tooltip copy for the disabled item.
 */
export function platformNavGatedReason(label: string): string {
  return `Select a workspace to use ${label}.`;
}

/**
 * Apply session gating to one released destination.
 *
 * Unreleased destinations (`lib/feature-release.ts`) never reach this: the
 * accessors below drop them, so they are absent rather than disabled.
 *
 * @param item - A modelled destination.
 * @param currentTenantId - `current_tenant_id` from the session, if any.
 * @returns The item with `disabled` and, when disabled, `disabledReason` set.
 */
function resolveItem(
  item: PlatformNavItem,
  currentTenantId: string | null | undefined
): ResolvedPlatformNavItem {
  const disabled = Boolean(item.requiresTenant) && !currentTenantId;
  return disabled
    ? { ...item, disabled, disabledReason: platformNavGatedReason(item.label) }
    : { ...item, disabled };
}

/**
 * The rail's groups for the current session.
 *
 * Contributed destinations are appended to the group their host asked for;
 * a contribution naming an unknown group is dropped rather than guessed at.
 * Unreleased destinations are left out. Groups that end up empty are omitted,
 * so a host can also contribute nothing.
 *
 * @param options - Session tenant and any runtime-injected destinations.
 * @returns Groups whose every item carries a resolved `disabled` flag.
 */
export function getPlatformNavGroups(
  options: PlatformNavOptions = {}
): ResolvedPlatformNavGroup[] {
  const { currentTenantId, injected = [] } = options;

  return PLATFORM_NAV_GROUPS.map((group) => {
    const contributed = injected
      .filter((injection) => injection.group === group.id)
      .map((injection) => injection.item);

    return {
      ...group,
      items: [...group.items, ...contributed]
        .filter((item) => isFeatureReleased(item.id))
        .map((item) => resolveItem(item, currentTenantId)),
    };
  }).filter((group) => group.items.length > 0);
}

/**
 * The user-menu destinations for the current session.
 *
 * @param options - Session tenant (neither entry is gated today; the argument
 *   keeps the two accessors symmetrical and the gate future-proof).
 * @returns Account destinations with a resolved `disabled` flag.
 */
export function getPlatformUserMenuItems(
  options: Pick<PlatformNavOptions, 'currentTenantId'> = {}
): ResolvedPlatformNavItem[] {
  return PLATFORM_USER_MENU_ITEMS.filter((item) => isFeatureReleased(item.id)).map((item) =>
    resolveItem(item, options.currentTenantId)
  );
}

/** An off-rail destination with its gating decided for the current session. */
export type ResolvedPlatformOffRailItem = ResolvedPlatformNavItem & Pick<PlatformOffRailItem, 'section' | 'home'>;

/**
 * The off-rail destinations for the current session (HIVE-12.2).
 *
 * Unreleased destinations are left out, exactly as {@link getPlatformNavGroups} leaves them
 * out of the rail; the rest carry the rail's `disabled` gating.
 *
 * @param options - Session tenant.
 * @param home - Keep only the destinations reached from this menu or tab; all when omitted.
 * @returns The destinations, in model order.
 */
export function getPlatformOffRailItems(
  options: Pick<PlatformNavOptions, 'currentTenantId'> = {},
  home?: PlatformOffRailHome
): ResolvedPlatformOffRailItem[] {
  return PLATFORM_OFF_RAIL_ITEMS.filter(
    (item) => (home === undefined || item.home === home) && isFeatureReleased(item.id)
  ).map((item) => ({ ...item, ...resolveItem(item, options.currentTenantId) }));
}

/**
 * The heading a destination sits under: its rail group's label, or an off-rail item's section.
 *
 * @param id - {@link PlatformNavItem.id} to place.
 * @returns The heading, or `undefined` for an unlabelled group (Home), a user-menu row or an
 *   unknown id.
 */
export function platformNavSectionLabel(id: string): string | undefined {
  const group = PLATFORM_NAV_GROUPS.find((candidate) => candidate.items.some((item) => item.id === id));
  if (group) return group.label;
  return PLATFORM_OFF_RAIL_ITEMS.find((item) => item.id === id)?.section;
}

/**
 * Look a destination up by id, across the rail groups, the user menu and the
 * off-rail destinations.
 *
 * @param id - {@link PlatformNavItem.id} to find.
 * @returns The destination, or `undefined` when nothing owns that id.
 */
export function findPlatformNavItem(id: string): PlatformNavItem | undefined {
  return ALL_MODEL_ITEMS.find((item) => item.id === id);
}

/**
 * Reserve rail slots for destinations a commercial host contributes.
 *
 * The host owns the label, the route and the entitlement decision; this
 * repository owns only *where* such a destination sits. Anything already
 * filtered out by `getCommercialNavItems()` never reaches here.
 *
 * @param items - Entitlement-filtered nav items from the commercial catalog.
 * @param group - Which group to place them in; DESIGN.md §6 puts suite
 *   destinations in Build, Bring in or Ship.
 * @returns Injections ready to pass as {@link PlatformNavOptions.injected}.
 */
export function toPlatformNavInjections(
  items: readonly { id: string; label: string; href: string; icon?: string; external?: boolean }[],
  group: PlatformNavGroupId = 'build'
): PlatformNavInjection[] {
  return items.map((item) => ({
    group,
    item: {
      id: item.id,
      label: item.label,
      href: item.href,
      icon: item.icon ?? DEFAULT_PLATFORM_NAV_ICON,
      external: item.external,
    },
  }));
}
