// objectified-ui/src/app/components/ade/TopHeader.tsx
'use client';

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { signOut, useSession } from "next-auth/react";
import Avatar from '@mui/material/Avatar';
import { usePathname } from 'next/navigation';

type NavItem = { label: string; href: string };

const NAV_ITEMS: NavItem[] = [
  { label: "Home", href: "/ade" },
  { label: "Dashboard", href: "/ade/dashboard" },
  { label: "Studio", href: "/ade/studio" },
];

const TopHeader = () => {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const { data: session } = useSession();
  const pathname = usePathname();

  useEffect(() => {
    function handleOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, []);

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
      }}
    >
      {/* Left: Logo / App Title */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div
          aria-hidden
          style={{
            width: 28,
            height: 28,
            borderRadius: 6,
            background: "linear-gradient(135deg,#5b8def,#7b61ff)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "white",
            fontWeight: 700,
            fontSize: 12,
          }}
        >
          O
        </div>
        <div style={{ display: "flex", flexDirection: "column", lineHeight: 1 }}>
          <span className="font-bold text-gray-900 dark:text-gray-100" style={{ fontSize: 13 }}>Objectified</span>
          <small className="text-gray-500 dark:text-gray-400" style={{ fontSize: 11 }}>Admin</small>
        </div>
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
              zIndex: 50,
            }}
          >
            <Link href="/ade/dashboard/profile" role="menuitem" className="block px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-900 dark:hover:text-white rounded text-sm transition-colors text-gray-700 dark:text-gray-300" style={{ textDecoration: "none" }}>
              View Profile
            </Link>
            {/*<Link href="/ade/account" role="menuitem" className="block px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-gray-900 dark:hover:text-white rounded text-sm transition-colors text-gray-700 dark:text-gray-300" style={{ textDecoration: "none" }}>*/}
            {/*  Account*/}
            {/*</Link>*/}
            <div className="h-px bg-gray-200 dark:bg-gray-600 my-1" />
            <button
              onClick={() => signOut()}
              className="w-full text-left block px-3 py-2 hover:bg-red-100 dark:hover:bg-red-900/50 hover:text-red-700 dark:hover:text-red-300 rounded text-sm transition-colors text-gray-700 dark:text-gray-300"
              style={{ background: "transparent", border: "none", cursor: "pointer" }}
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}

export default TopHeader;
