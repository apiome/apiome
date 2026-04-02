// objectified-ui/src/app/components/ade/TopHeader.tsx
'use client';

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { signOut, useSession } from "next-auth/react";
import { usePathname } from 'next/navigation';
import WhatsNewDialog from './WhatsNewDialog';
import ThemeSelector from './ThemeSelector';
import { useTheme } from '../../providers/ThemeProvider';
import { useDarkMode } from '../../hooks/useDarkMode';
import { getTenantsForUser } from '../../../../lib/db/helper';
import packageJson from '../../../../package.json';

// Import version from package.json
const APP_VERSION = `03-2026-v${packageJson.version}`;

type NavItem = { label: string; href: string; enabled?: boolean; opensNewBrowser?: boolean };

const NAV_ITEMS: NavItem[] = [
  { label: "Home", href: "/ade" },
  { label: "Control Panel", href: "/ade/dashboard" },
  { label: "Designer", href: "/ade/studio" },
  // { label: "Database", href: "/ade/database", enabled: false },
  // { label: "Migration", href: "/ade/migration", enabled: false },
  // { label: "ETL", href: "/ade/etl", enabled: false },
  // { label: "Explorer", href: "/ade/database/explorer", enabled: false },
];

const TopHeader = () => {
  const [open, setOpen] = useState(false);
  const [showWhatsNew, setShowWhatsNew] = useState(false);
  const [showThemeSelector, setShowThemeSelector] = useState(false);
  const [currentTenantName, setCurrentTenantName] = useState<string>('');
  const menuRef = useRef<HTMLDivElement | null>(null);
  const { data: session } = useSession();
  const pathname = usePathname();
  const currentTenantId = (session?.user as any)?.current_tenant_id;
  const { currentTheme, isSystemTheme } = useTheme();
  const isDark = useDarkMode();

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
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, []);

  // Load current tenant name
  useEffect(() => {
    const loadTenantName = async () => {
      if (session && currentTenantId) {
        try {
          const userId = (session.user as any)?.user_id;
          const result = await getTenantsForUser(userId);
          const tenants = JSON.parse(result);
          const currentTenant = tenants.find((t: any) => t.id === currentTenantId);
          if (currentTenant) {
            setCurrentTenantName(currentTenant.name);
          }
        } catch (error) {
          console.error('Failed to load tenant name:', error);
        }
      }
    };
    loadTenantName();
  }, [session, currentTenantId]);


  return (
    <header
      className="relative z-[2000] flex h-12 items-center justify-between gap-3 border-b border-slate-200 bg-white/95 px-3 backdrop-blur-sm dark:border-slate-700 dark:bg-slate-900/95"
    >
      {/* Left: Logo */}
      <div className="flex h-10 items-center gap-2">
        <img
          src={isDark ? "/Objectified-05.png" : "/Objectified-02.png"}
          alt="Objectified Logo"
          className="h-full w-auto object-contain"
        />
        <button
          onClick={() => setShowWhatsNew(true)}
          className="cursor-pointer rounded-md border border-slate-300 px-2 py-1 text-[11px] font-medium tracking-[0.02em] text-slate-500 transition-colors hover:bg-slate-100 hover:text-indigo-600 dark:border-slate-600 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-indigo-400"
          title="View What's New"
        >
          v{APP_VERSION}
        </button>
      </div>

      {/* Center: Navigation */}
      <nav aria-label="Main navigation" className="flex-1 text-center">
        <ul
          className="m-0 inline-flex list-none items-center gap-2 p-0 text-[13px]"
        >
          {NAV_ITEMS.map((item) => {
            // Check if current path matches or is a subdirectory of this nav item
            // For exact matches, always activate
            // For subdirectory matches, only activate if the path continues with a slash
            const isActive = pathname === item.href ||
                            (item.href !== '/ade' && pathname?.startsWith(item.href + '/'));

            return (
              <li key={item.href}>
                {item.enabled === false ? (
                  <span
                    className="cursor-not-allowed rounded-md px-2 py-1 text-[13px] text-slate-400 dark:text-slate-500"
                    title="Coming soon"
                  >
                    {item.label}
                  </span>
                ) : (
                  <Link
                    href={item.href}
                    target={item.opensNewBrowser ? '_blank' : undefined}
                    rel={item.opensNewBrowser ? 'noopener noreferrer' : undefined}
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

      {/* Tenant Name Display */}
      {currentTenantName && (
        <div className="hidden items-center gap-2 rounded-lg border border-indigo-100 bg-gradient-to-r from-indigo-50 to-purple-50 px-3 py-1.5 dark:border-indigo-800/50 dark:from-indigo-900/20 dark:to-purple-900/20 md:flex">
          <div className="h-2 w-2 animate-pulse rounded-full bg-gradient-to-r from-indigo-500 to-purple-500" />
          <span className="text-sm font-medium text-indigo-700 dark:text-indigo-300">{currentTenantName}</span>
        </div>
      )}

      {/* Right: Profile / Selector */}
      <div ref={menuRef} className="relative">
        <button
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((s) => !s)}
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
            className="absolute right-0 z-[2001] mt-2 min-w-[240px] rounded-lg bg-white p-1 shadow-lg shadow-slate-900/15 dark:bg-slate-800 dark:shadow-gray-900/50"
          >
            <Link href="/ade/dashboard/profile" role="menuitem" className="block rounded px-3 py-2 text-sm text-gray-700 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white" style={{ textDecoration: "none" }} onClick={() => setOpen(false)}>
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
              onClick={() => signOut()}
              className="w-full text-left block px-3 py-2 hover:bg-red-100 dark:hover:bg-red-900/50 hover:text-red-700 dark:hover:text-red-300 rounded text-sm transition-colors text-gray-700 dark:text-gray-300"
              style={{ border: "none" }}
            >
              Sign out
            </button>
          </div>
        )}
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

export default TopHeader;
