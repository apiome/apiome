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
  { label: "Browser", href: "https://browse.objectified.dev", opensNewBrowser: true },
  { label: "Database", href: "/ade/database", enabled: true },
  { label: "ETL", href: "/ade/etl", enabled: false },
  { label: "Explorer", href: "/ade/database/explorer", enabled: false },
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
      className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-700"
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        padding: "8px 12px",
        height: 48,
        position: "relative",
        zIndex: 2000,
      }}
    >
      {/* Left: Logo */}
      <div style={{ display: "flex", alignItems: "center", height: 40, gap: 8 }}>
        <img
          src={isDark ? "/Objectified-05.png" : "/Objectified-02.png"}
          alt="Objectified Logo"
          style={{ height: "100%", width: "auto", objectFit: "contain" }}
        />
        <button
          onClick={() => setShowWhatsNew(true)}
          className="text-xs text-gray-500 dark:text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 transition-colors cursor-pointer px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800"
          title="View What's New"
          style={{
            border: "1px solid currentColor",
            fontFamily: "monospace",
            fontWeight: 500
          }}
        >
          v{APP_VERSION}
        </button>
      </div>

      {/* Center: Navigation */}
      <nav aria-label="Main navigation" style={{ flex: 1, textAlign: "center" }}>
        <ul
          style={{
            listStyle: "none",
            margin: 0,
            padding: 0,
            display: "inline-flex",
            gap: 12,
            alignItems: "center",
            fontSize: 13,
          }}
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
                    className="text-gray-400 dark:text-gray-500 cursor-not-allowed"
                    style={{
                      padding: "4px 6px",
                      borderRadius: 6,
                      fontSize: 13,
                    }}
                    title="Coming soon"
                  >
                    {item.label}
                  </span>
                ) : (
                  <Link
                    href={item.href}
                    target={item.opensNewBrowser ? '_blank' : undefined}
                    rel={item.opensNewBrowser ? 'noopener noreferrer' : undefined}
                    className={`text-gray-800 dark:text-gray-200 hover:text-blue-600 dark:hover:text-blue-400 hover:bg-gray-100 dark:hover:bg-gray-500 transition-colors ${
                      isActive ? 'underline bg-gray-200 dark:bg-gray-600' : ''
                    }`}
                    style={{
                      padding: "4px 6px",
                      borderRadius: 6,
                      fontSize: 13,
                    }}
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
        <div className="flex items-center gap-2 px-3 py-1.5 bg-gradient-to-r from-indigo-50 to-purple-50 dark:from-indigo-900/20 dark:to-purple-900/20 rounded-lg border border-indigo-100 dark:border-indigo-800/50">
          <div className="w-2 h-2 rounded-full bg-gradient-to-r from-indigo-500 to-purple-500 animate-pulse" />
          <span className="text-sm font-medium text-indigo-700 dark:text-indigo-300">{currentTenantName}</span>
        </div>
      )}

      {/* Right: Profile / Selector */}
      <div ref={menuRef} style={{ position: "relative" }}>
        <button
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((s) => !s)}
          className="border border-gray-200 dark:border-gray-700 hover:bg-gray-100 dark:hover:bg-gray-800"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "4px 8px",
            borderRadius: 8,
            background: "transparent",
            cursor: "pointer",
          }}
        >
          <div
            className="w-7 h-7 rounded-full bg-indigo-600 flex items-center justify-center text-white text-xs font-medium"
            aria-hidden
          >
            {session?.user?.name ? String(session.user.name).slice(0, 1).toUpperCase() : '?'}
          </div>
          <span style={{ display: "none" /* hidden on small, shown via CSS if desired */ }}>
            {session?.user?.name}
          </span>
        </button>

        {open && (
          <div
            role="menu"
            aria-label="Profile menu"
            className="bg-white dark:bg-gray-800 shadow-lg dark:shadow-gray-900/50"
            style={{
              position: "absolute",
              right: 0,
              marginTop: 8,
              minWidth: 240,
              borderRadius: 8,
              padding: 4,
              zIndex: 2001,
            }}
          >
            <Link href="/ade/dashboard/profile" role="menuitem" className="block px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-900 dark:hover:text-white rounded text-sm transition-colors text-gray-700 dark:text-gray-300" style={{ textDecoration: "none" }} onClick={() => setOpen(false)}>
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
              style={{ border: "none", cursor: "pointer" }}
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
              style={{ border: "none", cursor: "pointer" }}
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
