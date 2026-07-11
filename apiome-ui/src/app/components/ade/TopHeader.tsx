// apiome-ui/src/app/components/ade/TopHeader.tsx
'use client';

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { signOut, useSession } from "next-auth/react";
import type { Session } from "next-auth";
import { usePathname } from 'next/navigation';
import { ChevronDown, Check, Shield } from 'lucide-react';
import WhatsNewDialog from './WhatsNewDialog';
import ThemeSelector from './ThemeSelector';
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
import type { ExternalNavItem } from '../../../../lib/external-links';
import { getTenantsAdministratedByUser, getTenantsForUser } from '../../../../lib/db/helper';

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

type TenantRow = { id: string; name: string };

type TenantAdminRow = { tenant_id: string; user_id: string };

export type TopHeaderTenantContext = {
  tenants: TenantRow[];
  adminTenantIds: Set<string>;
};

/** Serializable tenant context for server → client handoff (studio shell). */
export type SerializableTopHeaderTenantContext = {
  tenants: TenantRow[];
  adminTenantIds: string[];
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
};

async function loadDefaultTenantContext(userId: string): Promise<TopHeaderTenantContext> {
  const [tenantsJson, adminsJson] = await Promise.all([
    getTenantsForUser(userId),
    getTenantsAdministratedByUser(userId),
  ]);
  const tenants: TenantRow[] = JSON.parse(tenantsJson);
  const adminRows: TenantAdminRow[] = JSON.parse(adminsJson);
  const adminTenantIds = new Set(
    adminRows.filter((row) => row.user_id === userId).map((row) => row.tenant_id)
  );
  tenants.sort((a, b) => a.name.localeCompare(b.name));
  return { tenants, adminTenantIds };
}

type TopHeaderViewProps = Omit<TopHeaderProps, 'sessionBridge'> & TopHeaderSessionBridge;

function TopHeaderView({
  loadTenantContext = loadDefaultTenantContext,
  initialTenantContext,
  session,
  update,
}: TopHeaderViewProps) {
  const [open, setOpen] = useState(false);
  const [tenantMenuOpen, setTenantMenuOpen] = useState(false);
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
  const [commercialNavItems, setCommercialNavItems] = useState<ExternalNavItem[]>([]);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const tenantMenuRef = useRef<HTMLDivElement | null>(null);
  const pathname = usePathname();
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
      setOpen(false);
      setTenantMenuOpen(false);
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
        const { tenants, adminTenantIds: admins } = await loadTenantContext(currentUserId ?? '');
        setUserTenants(tenants);
        setAdminTenantIds(admins);
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
    return userTenants.filter((t) => t.name.toLowerCase().includes(q));
  }, [userTenants, tenantSearchQuery]);

  const handleSelectTenant = async (tenantId: string) => {
    if (tenantId === currentTenantId || isSwitchingTenant) return;
    setIsSwitchingTenant(true);
    try {
      await update({ current_tenant_id: tenantId });
      setTenantMenuOpen(false);
    } catch (error) {
      console.error('Failed to switch tenant:', error);
    } finally {
      setIsSwitchingTenant(false);
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
      <nav aria-label="Main navigation" className="min-w-0 flex-1 text-center">
        <ul
          className="m-0 inline-flex list-none items-center gap-2 p-0 text-[13px]"
        >
          {navItems.map((item) => {
            const href = resolvePlatformNavHref(item);
            const isActive = platformNavItemIsActive(item, pathname);
            const external = item.external || isExternalHref(href);

            return (
              <li key={item.id}>
                {item.enabled === false ? (
                  <span
                    className="cursor-not-allowed rounded-md px-2 py-1 text-[13px] text-slate-400 dark:text-slate-500"
                    title="Coming soon"
                  >
                    {item.label}
                  </span>
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
                      const isAdmin = adminTenantIds.has(t.id);
                      return (
                        <button
                          key={t.id}
                          type="button"
                          role="menuitem"
                          disabled={isSwitchingTenant || isCurrent}
                          onClick={() => handleSelectTenant(t.id)}
                          className={`flex w-full items-center gap-2 rounded px-3 py-2 text-left text-sm transition-colors ${
                            isCurrent
                              ? 'cursor-default bg-indigo-50 font-medium text-indigo-900 dark:bg-indigo-950/50 dark:text-indigo-100'
                              : 'cursor-pointer text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-700'
                          } ${isSwitchingTenant && !isCurrent ? 'opacity-50' : ''}`}
                        >
                          <span className="min-w-0 flex-1 truncate">{t.name}</span>
                          {isAdmin && (
                            <span
                              className="inline-flex shrink-0 items-center gap-0.5 rounded bg-amber-100/90 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900 dark:bg-amber-950/60 dark:text-amber-200"
                              title="You are an administrator of this tenant"
                            >
                              <Shield className="h-3.5 w-3.5" aria-hidden />
                              Admin
                            </span>
                          )}
                          {isCurrent && (
                            <Check className="h-4 w-4 shrink-0 text-indigo-600 dark:text-indigo-400" aria-hidden />
                          )}
                        </button>
                      );
                    })
                  )}
                </div>
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
              onClick={() => signOut({ callbackUrl: isStudioSurface() ? mainAppPath('/login') : undefined })}
              className="w-full text-left block px-3 py-2 hover:bg-red-100 dark:hover:bg-red-900/50 hover:text-red-700 dark:hover:text-red-300 rounded text-sm transition-colors text-gray-700 dark:text-gray-300"
              style={{ border: "none" }}
            >
              Sign out
            </button>
          </div>
        )}
        </div>
      </div>

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
