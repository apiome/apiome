// objectified-ui/src/app/components/ade/TopHeader.tsx
'use client';

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { signOut, useSession } from "next-auth/react";
import Avatar from '@mui/material/Avatar';
import { usePathname } from 'next/navigation';
import WhatsNewDialog from './WhatsNewDialog';
import { getTenantsForUser } from '../../../../lib/db/helper';

// Import version from package.json
const APP_VERSION = '01-2026';

type NavItem = { label: string; href: string };

const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/ade/dashboard" },
  { label: "Studio", href: "/ade/studio" },
];

const TopHeader = () => {
  const [open, setOpen] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(false);
  const [showWhatsNew, setShowWhatsNew] = useState(false);
  const [currentTenantName, setCurrentTenantName] = useState<string>('');
  const menuRef = useRef<HTMLDivElement | null>(null);
  const { data: session } = useSession();
  const pathname = usePathname();
  const currentTenantId = (session?.user as any)?.current_tenant_id;

  useEffect(() => {
    function handleOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, []);

  useEffect(() => {
    // Detect dark mode
    const checkDarkMode = () => {
      const isDark = document.documentElement.classList.contains('dark') ||
                     window.matchMedia('(prefers-color-scheme: dark)').matches;
      setIsDarkMode(isDark);
    };

    checkDarkMode();

    // Listen for changes to dark mode
    const observer = new MutationObserver(checkDarkMode);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['class']
    });

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    mediaQuery.addEventListener('change', checkDarkMode);

    return () => {
      observer.disconnect();
      mediaQuery.removeEventListener('change', checkDarkMode);
    };
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
          src={isDarkMode ? "/Objectified-05.png" : "/Objectified-02.png"}
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
                <Link
                  href={item.href}
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
          <Avatar sx={{ width: 28, height: 28 }} />
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
              minWidth: 160,
              borderRadius: 8,
              padding: 4,
              zIndex: 2001,
            }}
          >
            <Link href="/ade/dashboard/profile" role="menuitem" className="block px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-900 dark:hover:text-white rounded text-sm transition-colors text-gray-700 dark:text-gray-300" style={{ textDecoration: "none" }} onClick={() => setOpen(false)}>
              View Profile
            </Link>
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
    </header>
  );
}

export default TopHeader;
