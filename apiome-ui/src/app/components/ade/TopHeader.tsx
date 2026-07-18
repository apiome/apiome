// apiome-ui/src/app/components/ade/TopHeader.tsx
'use client';

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { signOut, useSession } from "next-auth/react";
import type { Session } from "next-auth";
import { usePathname, useRouter } from 'next/navigation';
import { ChevronDown, Check, Plus, Shield } from 'lucide-react';
import WhatsNewDialog from './WhatsNewDialog';
import ThemeSelector from './ThemeSelector';
import CreateTenantDialog, { type CreatedTenant } from './CreateTenantDialog';
import { useTheme } from '../../providers/ThemeProvider';
import { useDarkMode } from '../../hooks/useDarkMode';
import packageJson from '../../../../package.json';
import {
  getPlatformNavItems,
  isStudioSurface,
  mainAppPath,
  platformNavItemIsActive,
  platformProfilePath,
  resolvePlatformNavHref,
} from '../../../../lib/platform-nav';
import { getCommercialAccessForSession } from '../../../../lib/db/commercial-access';
import { resolveExternalLinkIcon } from '../../../../lib/external-links';
import type { ExternalNavItem, ExternalNavMenuItem } from '../../../../lib/external-links';
import { loadTenantMembershipContext } from '../../../../lib/auth/tenant-membership-context';
import { persistLastActiveTenant } from '../../../../lib/auth/last-active-tenant-actions';
import type {
  CreateTenantGate,
  TenantMembershipRow,
} from '../../../../lib/auth/tenant-membership-context-mapping';

/** Optional CI/build stamp (e.g. `2026.05.05-84a231c`). Otherwise badge uses semver from package.json. */
const APP_BUILD_LABEL = process.env.NEXT_PUBLIC_APP_BUILD_LABEL?.trim();
const APP_VERSION_BADGE =
  APP_BUILD_LABEL && APP_BUILD_LABEL.length > 0
    ? APP_BUILD_LABEL
    : `v${packageJson.version} RC`;

type NavItem = ReturnType<typeof getPlatformNavItems>[number];

function isExternalHref(href: string): boolean {
  return href.startsWith('http://') || href.startsWith('https://');
}

function isNavMenuItemActive(menuItem: ExternalNavMenuItem, pathname: string | null): boolean {
  if (!pathname) return false;
  if (menuItem.external || isExternalHref(menuItem.href)) return false;
  return (
    pathname === menuItem.href ||
    (menuItem.href !== '/' && pathname.startsWith(`${menuItem.href}/`))
  );
}

/**
 * One switcher row. Enrichment fields (role/status/license, OLO-6.1 #4218) are
 * optional so legacy contexts — e.g. the studio shell's prefetched name-only
 * rows — keep rendering with the pre-OLO-6.1 admin-badge fallback.
 */
type TenantRow = TenantMembershipRow;

export type TopHeaderTenantContext = {
  tenants: TenantRow[];
  adminTenantIds: Set<string>;
  /** Create-tenant cap gate (OLO-5.3); the entry is hidden when absent. */
  createTenant?: CreateTenantGate | null;
};

/** Serializable tenant context for server → client handoff (studio shell). */
export type SerializableTopHeaderTenantContext = {
  tenants: TenantRow[];
  adminTenantIds: string[];
  createTenant?: CreateTenantGate | null;
};

export type TopHeaderSessionBridge = {
  session: Session | null;
  update: ReturnType<typeof useSession>['update'];
};

export type TopHeaderProps = {
  loadTenantContext?: (userId: string) => Promise<TopHeaderTenantContext>;
  /** Server-prefetched tenants (studio) so the switcher renders on first paint. */
  initialTenantContext?: SerializableTopHeaderTenantContext;
  /** Pass session from the studio shell to avoid a duplicate next-auth module graph. */
  sessionBridge?: TopHeaderSessionBridge;
  /** Called after the session tenant is updated (studio project/version reload). */
  onTenantSelected?: (tenantId: string) => void;
};

/**
 * Default context loader: the enriched membership listing (OLO-6.2's
 * `GET /v1/tenants/me` via the `loadTenantMembershipContext` server action,
 * which resolves the acting user from the server session — so unlike the
 * injectable `loadTenantContext(userId)` contract, it needs no argument).
 */
async function loadDefaultTenantContext(): Promise<TopHeaderTenantContext> {
  const { tenants, adminTenantIds, createTenant } = await loadTenantMembershipContext();
  return { tenants, adminTenantIds: new Set(adminTenantIds), createTenant };
}

type TopHeaderViewProps = Omit<TopHeaderProps, 'sessionBridge'> & TopHeaderSessionBridge;

function TopHeaderView({
  loadTenantContext = loadDefaultTenantContext,
  initialTenantContext,
  onTenantSelected,
  session,
  update,
}: TopHeaderViewProps) {
  const [open, setOpen] = useState(false);
  const [tenantMenuOpen, setTenantMenuOpen] = useState(false);
  const [openNavMenuId, setOpenNavMenuId] = useState<string | null>(null);
  const [showWhatsNew, setShowWhatsNew] = useState(false);
  const [showThemeSelector, setShowThemeSelector] = useState(false);
  const [currentTenantName, setCurrentTenantName] = useState<string>(() => {
    const currentId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
    if (!currentId || !initialTenantContext) return '';
    return initialTenantContext.tenants.find((tenant) => tenant.id === currentId)?.name ?? '';
  });
  const [userTenants, setUserTenants] = useState<TenantRow[]>(
    () => initialTenantContext?.tenants ?? []
  );
  const [adminTenantIds, setAdminTenantIds] = useState<Set<string>>(
    () => new Set(initialTenantContext?.adminTenantIds ?? [])
  );
  const [isLoadingTenants, setIsLoadingTenants] = useState(
    () => Boolean(session?.user) && !initialTenantContext
  );
  const [isSwitchingTenant, setIsSwitchingTenant] = useState(false);
  const [tenantSearchQuery, setTenantSearchQuery] = useState('');
  const [createTenantGate, setCreateTenantGate] = useState<CreateTenantGate | null>(
    () => initialTenantContext?.createTenant ?? null
  );
  const [createTenantOpen, setCreateTenantOpen] = useState(false);
  const [commercialNavItems, setCommercialNavItems] = useState<ExternalNavItem[]>([]);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const tenantMenuRef = useRef<HTMLDivElement | null>(null);
  const navMenuRef = useRef<HTMLElement | null>(null);
  const pathname = usePathname();
  const router = useRouter();
  const currentTenantId = (session?.user as any)?.current_tenant_id;
  const currentUserId =
    (session?.user as { user_id?: string })?.user_id ??
    (session?.user as { id?: string })?.id;
  const { currentTheme, isSystemTheme } = useTheme();
  const isDark = useDarkMode();
  const navItems = getPlatformNavItems(commercialNavItems);
  const profileHref = platformProfilePath();

  // Get display name for current theme (shows effective theme when system is selected)
  const getThemeDisplayName = () => {
    if (isSystemTheme) {
      const prefersDark = typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches;
      return `System (${prefersDark ? 'Dark' : 'Light'})`;
    }
    return currentTheme.name;
  };

  useEffect(() => {
    function handleOutside(e: MouseEvent) {
      const t = e.target as Node;
      if (menuRef.current?.contains(t)) return;
      if (tenantMenuRef.current?.contains(t)) return;
      if (navMenuRef.current?.contains(t)) return;
      setOpen(false);
      setTenantMenuOpen(false);
      setOpenNavMenuId(null);
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, []);

  useEffect(() => {
    if (!session?.user) {
      setCommercialNavItems([]);
      return;
    }
    let cancelled = false;
    getCommercialAccessForSession()
      .then(({ navItems }) => {
        if (!cancelled) setCommercialNavItems(navItems);
      })
      .catch((error) => {
        console.error('Failed to load commercial nav entitlements:', error);
        if (!cancelled) setCommercialNavItems([]);
      });
    return () => {
      cancelled = true;
    };
  }, [session]);

  useEffect(() => {
    const loadTenants = async () => {
      if (!session?.user) {
        setUserTenants([]);
        setAdminTenantIds(new Set());
        setCurrentTenantName('');
        setIsLoadingTenants(false);
        return;
      }
      setIsLoadingTenants(true);
      try {
        const { tenants, adminTenantIds: admins, createTenant } = await loadTenantContext(
          currentUserId ?? ''
        );
        setUserTenants(tenants);
        setAdminTenantIds(admins);
        setCreateTenantGate(createTenant ?? null);
        if (currentTenantId) {
          const current = tenants.find((t) => t.id === currentTenantId);
          setCurrentTenantName(current?.name ?? '');
        } else {
          setCurrentTenantName('');
        }
      } catch (error) {
        console.error('Failed to load tenants:', error);
      } finally {
        setIsLoadingTenants(false);
      }
    };
    loadTenants();
  }, [session, currentUserId, currentTenantId, loadTenantContext]);

  useEffect(() => {
    if (!tenantMenuOpen) setTenantSearchQuery('');
  }, [tenantMenuOpen]);

  const filteredTenants = React.useMemo(() => {
    const q = tenantSearchQuery.trim().toLowerCase();
    if (!q) return userTenants;
    return userTenants.filter(
      (t) => t.name.toLowerCase().includes(q) || (t.slug ?? '').toLowerCase().includes(q)
    );
  }, [userTenants, tenantSearchQuery]);

  const handleSelectTenant = async (tenantId: string) => {
    if (tenantId === currentTenantId || isSwitchingTenant) return;
    setIsSwitchingTenant(true);
    try {
      await update({ current_tenant_id: tenantId });
      const selected = userTenants.find((t) => t.id === tenantId);
      if (selected) {
        setCurrentTenantName(selected.name);
      }
      // Durable last-active persistence (OLO-6.1) so the next login restores
      // this tenant via the OLO-3.3 routing rules. Best-effort — a cookie
      // write failure must not break the switch itself.
      persistLastActiveTenant(tenantId).catch((error) => {
        console.error('Failed to persist last-active tenant:', error);
      });
      onTenantSelected?.(tenantId);
      setTenantMenuOpen(false);
      // Re-render server components so tenant-scoped views pick up the new
      // tenant without a full page reload.
      router.refresh();
    } catch (error) {
      console.error('Failed to switch tenant:', error);
    } finally {
      setIsSwitchingTenant(false);
    }
  };

  /**
   * A tenant created from the header dialog becomes the active tenant
   * immediately: activate it in the session, persist last-active, and refresh
   * so the guard/side-nav render the new tenant's dashboard state.
   */
  const handleTenantCreated = async (tenant: CreatedTenant) => {
    setCreateTenantOpen(false);
    setUserTenants((current) =>
      current.some((t) => t.id === tenant.id)
        ? current
        : [...current, { id: tenant.id, name: tenant.name, slug: tenant.slug, role: 'owner' }]
    );
    // The new tenant consumed one slot of the cap.
    setCreateTenantGate((gate) =>
      gate ? { ...gate, used: gate.used + 1, allowed: gate.used + 1 < gate.max } : gate
    );
    try {
      await update({ current_tenant_id: tenant.id });
      setCurrentTenantName(tenant.name);
      persistLastActiveTenant(tenant.id).catch((error) => {
        console.error('Failed to persist last-active tenant:', error);
      });
      onTenantSelected?.(tenant.id);
      router.refresh();
    } catch (error) {
      // Non-fatal: the JWT callback re-derives the active tenant on the next
      // request, so the created tenant is still reachable from the switcher.
      console.error('Failed to activate created tenant:', error);
    }
  };


  const showTenantSwitcher =
    Boolean(session?.user) &&
    (userTenants.length > 0 || isLoadingTenants || Boolean(currentTenantId));

  return (
    <header
      className="relative z-[10048] flex h-12 shrink-0 items-center justify-between gap-3 border-b border-slate-200 bg-white/95 px-3 backdrop-blur-sm dark:border-slate-700 dark:bg-slate-900/95"
    >
      {/* Left: Logo */}
      <div className="flex h-10 items-center gap-2">
        <img
          src={isDark ? "/Apiome-05.png" : "/Apiome-02.png"}
          alt="Apiome Logo"
          className="h-full w-auto object-contain"
        />
        <button
          onClick={() => setShowWhatsNew(true)}
          className="cursor-pointer rounded-md border border-slate-300 px-2 py-1 text-[11px] font-medium tracking-[0.02em] text-slate-500 transition-colors hover:bg-slate-100 hover:text-indigo-600 dark:border-slate-600 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-indigo-400"
          title="View What's New"
        >
          {APP_VERSION_BADGE}
        </button>
      </div>

      {/* Center: Navigation */}
      <nav ref={navMenuRef} aria-label="Main navigation" className="min-w-0 flex-1 text-center">
        <ul
          className="m-0 inline-flex list-none items-center gap-2 p-0 text-[13px]"
        >
          {navItems.map((item) => {
            const href = resolvePlatformNavHref(item);
            const isActive = platformNavItemIsActive(item, pathname);
            const external = item.external || isExternalHref(href);
            const isDropdown = item.menuItems !== undefined;
            const navMenuOpen = openNavMenuId === item.id;

            return (
              <li key={item.id} className="relative">
                {item.enabled === false ? (
                  <span
                    className="inline-flex cursor-not-allowed items-center gap-1 rounded-md px-2 py-1 text-[13px] text-slate-400 dark:text-slate-500"
                    title="Coming soon"
                  >
                    {item.label}
                    {isDropdown && <ChevronDown className="h-3.5 w-3.5" aria-hidden />}
                  </span>
                ) : isDropdown && item.menuItems!.length > 0 ? (
                  <>
                    <button
                      type="button"
                      aria-haspopup="menu"
                      aria-expanded={navMenuOpen}
                      onClick={() => {
                        setOpen(false);
                        setTenantMenuOpen(false);
                        setOpenNavMenuId((current) => (current === item.id ? null : item.id));
                      }}
                      className={`inline-flex cursor-pointer items-center gap-1 rounded-md px-2 py-1 text-[13px] text-slate-700 transition-colors hover:bg-slate-100 hover:text-indigo-600 dark:text-slate-200 dark:hover:bg-slate-700 dark:hover:text-indigo-400 ${
                        isActive ? 'bg-slate-200/80 font-medium text-slate-900 dark:bg-slate-700 dark:text-white' : ''
                      }`}
                    >
                      {item.label}
                      <ChevronDown
                        className={`h-3.5 w-3.5 transition-transform ${navMenuOpen ? 'rotate-180' : ''}`}
                        aria-hidden
                      />
                    </button>
                    {navMenuOpen && (
                      <div
                        role="menu"
                        aria-label={`${item.label} menu`}
                        className="absolute left-1/2 z-[10050] mt-2 w-[420px] -translate-x-1/2 rounded-lg bg-white p-2 text-left shadow-lg shadow-slate-900/15 dark:bg-slate-800 dark:shadow-gray-900/50"
                      >
                        <div className="grid max-h-[min(70vh,26rem)] grid-cols-2 gap-1 overflow-y-auto overscroll-contain">
                          {item.menuItems!.map((menuItem) => {
                            const menuExternal = menuItem.external || isExternalHref(menuItem.href);
                            const menuActive = isNavMenuItemActive(menuItem, pathname);
                            const MenuIcon = menuItem.icon
                              ? resolveExternalLinkIcon(menuItem.icon)
                              : null;
                            const tileClassName = `flex items-start gap-2.5 rounded-md px-3 py-2.5 transition-colors ${
                              menuActive
                                ? 'bg-indigo-50 dark:bg-indigo-950/50'
                                : 'hover:bg-slate-100 dark:hover:bg-slate-700'
                            }`;
                            const tileBody = (
                              <>
                                {MenuIcon && (
                                  <MenuIcon
                                    className="mt-0.5 h-4 w-4 shrink-0 text-indigo-600 dark:text-indigo-400"
                                    aria-hidden
                                  />
                                )}
                                <span className="min-w-0">
                                  <span className="block truncate text-[13px] font-medium text-slate-900 dark:text-slate-100">
                                    {menuItem.label}
                                  </span>
                                  {menuItem.description && (
                                    <span className="block text-xs text-slate-500 dark:text-slate-400">
                                      {menuItem.description}
                                    </span>
                                  )}
                                </span>
                              </>
                            );
                            return menuExternal ? (
                              <a
                                key={menuItem.id}
                                role="menuitem"
                                href={menuItem.href}
                                target={menuItem.opensNewBrowser ? '_blank' : undefined}
                                rel={menuItem.opensNewBrowser ? 'noopener noreferrer' : undefined}
                                className={tileClassName}
                                style={{ textDecoration: 'none' }}
                                onClick={() => setOpenNavMenuId(null)}
                              >
                                {tileBody}
                              </a>
                            ) : (
                              <Link
                                key={menuItem.id}
                                role="menuitem"
                                href={menuItem.href}
                                aria-current={menuActive ? 'page' : undefined}
                                className={tileClassName}
                                style={{ textDecoration: 'none' }}
                                onClick={() => setOpenNavMenuId(null)}
                              >
                                {tileBody}
                              </Link>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </>
                ) : external ? (
                  <a
                    href={href}
                    target={item.opensNewBrowser ? '_blank' : undefined}
                    rel={item.opensNewBrowser ? 'noopener noreferrer' : undefined}
                    className="rounded-md px-2 py-1 text-[13px] text-slate-700 transition-colors hover:bg-slate-100 hover:text-indigo-600 dark:text-slate-200 dark:hover:bg-slate-700 dark:hover:text-indigo-400"
                  >
                    {item.label}
                  </a>
                ) : (
                  <Link
                    href={href}
                    target={item.opensNewBrowser ? '_blank' : undefined}
                    rel={item.opensNewBrowser ? 'noopener noreferrer' : undefined}
                    aria-current={isActive ? 'page' : undefined}
                    className={`rounded-md px-2 py-1 text-[13px] text-slate-700 transition-colors hover:bg-slate-100 hover:text-indigo-600 dark:text-slate-200 dark:hover:bg-slate-700 dark:hover:text-indigo-400 ${
                      isActive ? 'bg-slate-200/80 font-medium text-slate-900 dark:bg-slate-700 dark:text-white' : ''
                    }`}
                  >
                    {item.label}
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="flex shrink-0 items-center gap-2">
        {showTenantSwitcher && (
          <div ref={tenantMenuRef} className="relative">
            <button
              type="button"
              aria-haspopup="menu"
              aria-expanded={tenantMenuOpen}
              aria-label="Switch tenant"
              disabled={isSwitchingTenant || isLoadingTenants}
              onClick={() => {
                setOpen(false);
                setOpenNavMenuId(null);
                setTenantMenuOpen((s) => !s);
              }}
              className="flex cursor-pointer items-center gap-2 rounded-lg border border-indigo-100 bg-gradient-to-r from-indigo-50 to-purple-50 px-3 py-1.5 transition-colors hover:from-indigo-100 hover:to-purple-100 disabled:cursor-wait disabled:opacity-70 dark:border-indigo-800/50 dark:from-indigo-900/20 dark:to-purple-900/20 dark:hover:from-indigo-900/35 dark:hover:to-purple-900/35"
            >
              <div className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-gradient-to-r from-indigo-500 to-purple-500" />
              <span className="max-w-[200px] truncate text-sm font-medium text-indigo-700 dark:text-indigo-300">
                {isLoadingTenants
                  ? 'Loading tenants…'
                  : currentTenantName || 'Select tenant'}
              </span>
              <ChevronDown
                className={`h-4 w-4 shrink-0 text-indigo-600 transition-transform dark:text-indigo-400 ${tenantMenuOpen ? 'rotate-180' : ''}`}
                aria-hidden
              />
            </button>
            {tenantMenuOpen && !isLoadingTenants && (
              <div
                role="menu"
                aria-label="Your tenants"
                className="absolute right-0 z-[10050] mt-2 flex max-h-[min(70vh,24rem)] min-w-[260px] flex-col overflow-hidden rounded-lg bg-white shadow-lg shadow-slate-900/15 dark:bg-slate-800 dark:shadow-gray-900/50"
              >
                <div className="shrink-0 border-b border-gray-200 p-2 dark:border-gray-600">
                  <input
                    type="search"
                    autoComplete="off"
                    value={tenantSearchQuery}
                    onChange={(e) => setTenantSearchQuery(e.target.value)}
                    onKeyDown={(e) => e.stopPropagation()}
                    placeholder="Search tenants…"
                    aria-label="Filter tenants"
                    className="w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:placeholder:text-gray-500"
                  />
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-1">
                  {filteredTenants.length === 0 ? (
                    <div className="px-3 py-2 text-sm text-gray-500 dark:text-gray-400">No matching tenants</div>
                  ) : (
                    filteredTenants.map((t) => {
                      const isCurrent = t.id === currentTenantId;
                      const isSuspended = t.status === 'suspended';
                      return (
                        <button
                          key={t.id}
                          type="button"
                          role="menuitem"
                          disabled={isSwitchingTenant || isCurrent || isSuspended}
                          title={
                            isSuspended
                              ? 'Your membership in this tenant is suspended'
                              : undefined
                          }
                          onClick={() => handleSelectTenant(t.id)}
                          className={`flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm transition-colors ${
                            isCurrent
                              ? 'cursor-default bg-indigo-50 font-medium text-indigo-900 dark:bg-indigo-950/50 dark:text-indigo-100'
                              : isSuspended
                                ? 'cursor-not-allowed text-gray-400 dark:text-gray-500'
                                : 'cursor-pointer text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-700'
                          } ${isSwitchingTenant && !isCurrent ? 'opacity-50' : ''}`}
                        >
                          <span className="min-w-0 flex-1 truncate">{t.name}</span>
                          {isSuspended && (
                            <span className="inline-flex shrink-0 items-center rounded bg-gray-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:bg-gray-700 dark:text-gray-400">
                              Suspended
                            </span>
                          )}
                          <TenantRoleBadge role={t.role} isLegacyAdmin={adminTenantIds.has(t.id)} />
                          <TenantLicenseChip name={t.licenseName} type={t.licenseType} role={t.role} />
                          {isCurrent && (
                            <Check className="h-4 w-4 shrink-0 text-indigo-600 dark:text-indigo-400" aria-hidden />
                          )}
                        </button>
                      );
                    })
                  )}
                </div>
                {createTenantGate && (
                  <div className="shrink-0 border-t border-gray-200 p-1 dark:border-gray-600">
                    <button
                      type="button"
                      role="menuitem"
                      data-testid="create-tenant-entry"
                      disabled={!createTenantGate.allowed}
                      title={
                        createTenantGate.allowed
                          ? undefined
                          : `Tenant limit reached (${createTenantGate.used} of ${createTenantGate.max} used) — upgrade your plan to create more`
                      }
                      onClick={() => {
                        setTenantMenuOpen(false);
                        setCreateTenantOpen(true);
                      }}
                      className={`flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm transition-colors ${
                        createTenantGate.allowed
                          ? 'cursor-pointer text-indigo-700 hover:bg-indigo-50 dark:text-indigo-300 dark:hover:bg-indigo-950/40'
                          : 'cursor-not-allowed text-gray-400 dark:text-gray-500'
                      }`}
                    >
                      <Plus className="h-4 w-4 shrink-0" aria-hidden />
                      <span className="min-w-0 flex-1 truncate">Create tenant</span>
                      {!createTenantGate.allowed && (
                        <span className="shrink-0 text-[10px] font-medium text-gray-400 dark:text-gray-500">
                          {createTenantGate.used}/{createTenantGate.max}
                        </span>
                      )}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Profile menu */}
        <div ref={menuRef} className="relative">
        <button
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => {
            setTenantMenuOpen(false);
            setOpenNavMenuId(null);
            setOpen((s) => !s);
          }}
          className="flex cursor-pointer items-center gap-2 rounded-lg border border-slate-200 bg-transparent px-2 py-1 transition-colors hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
        >
          <div
            className="w-7 h-7 rounded-full bg-indigo-600 flex items-center justify-center text-white text-xs font-medium"
            aria-hidden
          >
            {session?.user?.name ? String(session.user.name).slice(0, 1).toUpperCase() : '?'}
          </div>
          <span className="hidden">
            {session?.user?.name}
          </span>
        </button>

        {open && (
          <div
            role="menu"
            aria-label="Profile menu"
            className="absolute right-0 z-[10050] mt-2 min-w-[240px] rounded-lg bg-white p-1 shadow-lg shadow-slate-900/15 dark:bg-slate-800 dark:shadow-gray-900/50"
          >
            <Link href={profileHref} role="menuitem" className="block rounded px-3 py-2 text-sm text-gray-700 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white" style={{ textDecoration: "none" }} onClick={() => setOpen(false)}>
              View Profile
            </Link>
            <div className="h-px bg-gray-200 dark:bg-gray-600 my-1" />
            {/* Theme Selector */}
            <button
              onClick={() => {
                setShowThemeSelector(true);
                setOpen(false);
              }}
              role="menuitem"
              className="w-full text-left flex items-center justify-between px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-900 dark:hover:text-white rounded text-sm transition-colors text-gray-700 dark:text-gray-300"
              style={{ border: "none" }}
            >
              <span className="flex items-center gap-2">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01" />
                </svg>
                Theme
              </span>
              <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400">
                {getThemeDisplayName()}
              </span>
            </button>
            <div className="h-px bg-gray-200 dark:bg-gray-600 my-1" />
            <button
              // Explicit landing so logout exits cleanly to the login page instead of
              // bouncing off the protected page's auth guard (OLO-3.4). The studio
              // shell has no /login route of its own, so it targets the main app's.
              onClick={() => signOut({ callbackUrl: isStudioSurface() ? mainAppPath('/login') : '/login' })}
              className="w-full text-left block px-3 py-2 hover:bg-red-100 dark:hover:bg-red-900/50 hover:text-red-700 dark:hover:text-red-300 rounded text-sm transition-colors text-gray-700 dark:text-gray-300"
              style={{ border: "none" }}
            >
              Sign out
            </button>
          </div>
        )}
        </div>
      </div>

      {/* Create Tenant Dialog (OLO-6.1) */}
      <CreateTenantDialog
        open={createTenantOpen}
        onOpenChange={setCreateTenantOpen}
        onCreated={handleTenantCreated}
      />

      {/* What's New Dialog */}
      <WhatsNewDialog
        isOpen={showWhatsNew}
        onClose={() => setShowWhatsNew(false)}
      />

      {/* Theme Selector Dialog */}
      <ThemeSelector
        isOpen={showThemeSelector}
        onClose={() => setShowThemeSelector(false)}
      />
    </header>
  );
}

/** Badge styling per built-in role slug; custom roles use the neutral style. */
const ROLE_BADGE_CLASSES: Record<string, string> = {
  owner: 'bg-amber-100/90 text-amber-900 dark:bg-amber-950/60 dark:text-amber-200',
  admin: 'bg-indigo-100/90 text-indigo-900 dark:bg-indigo-950/60 dark:text-indigo-200',
  editor: 'bg-emerald-100/90 text-emerald-900 dark:bg-emerald-950/60 dark:text-emerald-200',
  viewer: 'bg-slate-100 text-slate-600 dark:bg-slate-700/80 dark:text-slate-300',
};

const ROLE_BADGE_NEUTRAL_CLASS =
  'bg-slate-100 text-slate-600 dark:bg-slate-700/80 dark:text-slate-300';

/**
 * Per-tenant effective-role badge (OLO-6.1). With no `role` (legacy name-only
 * context, e.g. the studio's prefetched rows) it falls back to the pre-OLO-6.1
 * "Admin" shield driven by `isLegacyAdmin`, so older callers keep their badge.
 *
 * @param role Effective RBAC role slug from the enriched listing, if known.
 * @param isLegacyAdmin Legacy administrator flag for the fallback badge.
 */
function TenantRoleBadge({ role, isLegacyAdmin }: { role?: string; isLegacyAdmin: boolean }) {
  if (!role) {
    if (!isLegacyAdmin) return null;
    return (
      <span
        className="inline-flex shrink-0 items-center gap-0.5 rounded bg-amber-100/90 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900 dark:bg-amber-950/60 dark:text-amber-200"
        title="You are an administrator of this tenant"
      >
        <Shield className="h-3.5 w-3.5" aria-hidden />
        Admin
      </span>
    );
  }
  const showShield = role === 'owner' || role === 'admin';
  return (
    <span
      data-testid="tenant-role-badge"
      className={`inline-flex shrink-0 items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
        ROLE_BADGE_CLASSES[role] ?? ROLE_BADGE_NEUTRAL_CLASS
      }`}
      title={`Your role in this tenant: ${role}`}
    >
      {showShield && <Shield className="h-3.5 w-3.5" aria-hidden />}
      {role}
    </span>
  );
}

/** Chip styling per license billing type (V097: free/paid/sponsor). */
const LICENSE_CHIP_CLASSES: Record<string, string> = {
  free: 'text-slate-500 dark:text-slate-400',
  paid: 'text-indigo-600 dark:text-indigo-400',
  sponsor: 'text-purple-600 dark:text-purple-400',
};

/**
 * Per-tenant license tier chip (OLO-6.1). An unlicensed tenant (no V182 row)
 * renders as "Free" — the same fallback the OLO-5.3 enforcement applies.
 * Renders nothing for legacy rows with no enrichment at all (no `role`), so
 * name-only contexts don't show a misleading tier.
 *
 * @param name Plan display name from the enriched listing, if any.
 * @param type Plan billing type (`free`/`paid`/`sponsor`), if any.
 * @param role Enrichment marker: chips only render for enriched rows.
 */
function TenantLicenseChip({
  name,
  type,
  role,
}: {
  name?: string | null;
  type?: string | null;
  role?: string;
}) {
  if (!role) return null;
  const label = name || 'Free';
  const colorClass = LICENSE_CHIP_CLASSES[type ?? 'free'] ?? LICENSE_CHIP_CLASSES.free;
  return (
    <span
      data-testid="tenant-license-chip"
      className={`inline-flex shrink-0 items-center text-[11px] font-medium ${colorClass}`}
      title={
        name
          ? `License plan: ${name}`
          : 'No license attached — Free plan defaults apply'
      }
    >
      · {label}
    </span>
  );
}

function TopHeaderWithSession(props: TopHeaderProps) {
  const { data: session, update } = useSession();
  return <TopHeaderView {...props} session={session ?? null} update={update} />;
}

function TopHeader({ sessionBridge, ...props }: TopHeaderProps) {
  if (sessionBridge) {
    return <TopHeaderView {...props} session={sessionBridge.session} update={sessionBridge.update} />;
  }
  return <TopHeaderWithSession {...props} />;
}

export default TopHeader;
