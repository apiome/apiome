// objectified-ui/src/app/components/ade/TopHeader.tsx
'use client';

import React, { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { signOut, useSession } from "next-auth/react";
import Avatar from '@mui/material/Avatar';
import { useRouter, usePathname } from 'next/navigation';

type NavItem = { label: string; href: string };

const NAV_ITEMS: NavItem[] = [
  { label: "Home", href: "/ade" },
  { label: "Dashboard", href: "/ade/dashboard" },
  { label: "Studio", href: "/ade/studio" },
];

export default function TopHeader() {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const { data: session, status, update } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  React.useEffect(() => {
    if (session) {
      console.log('Session:', session, 'status:', status, 'update:', update);
    }

    if (session === null) {
      router.push('/login');
    }
  }, [session]);

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
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        padding: "8px 12px",
        borderBottom: "1px solid rgba(0,0,0,0.06)",
        background: "var(--geist-background, #fff)",
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
          <span style={{ fontWeight: 700, color: 'black', fontSize: 13 }}>Objectified</span>
          <small style={{ color: "rgba(0,0,0,0.5)", fontSize: 11 }}>Admin</small>
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
          {NAV_ITEMS.map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                className={`text-gray-800 hover:text-blue-600 transition-colors ${pathname === item.href ? 'underline' : ''}`}
                style={{
                  padding: "4px 6px",
                  borderRadius: 6,
                  transition: "background 0.12s",
                  fontSize: 13,
                  backgroundColor: pathname === item.href ? 'rgba(0,0,0,0.1)' : 'transparent',
                }}
              >
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      {/* Right: Profile / Selector */}
      <div ref={menuRef} style={{ position: "relative" }}>
        <button
          aria-haspopup="menu"
          aria-expanded={open}
          onClick={() => setOpen((s) => !s)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "4px 8px",
            borderRadius: 8,
            border: "1px solid rgba(0,0,0,0.06)",
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
            style={{
              position: "absolute",
              right: 0,
              marginTop: 8,
              minWidth: 160,
              background: "white",
              boxShadow: "0 6px 18px rgba(0,0,0,0.08)",
              borderRadius: 8,
              padding: 4,
              zIndex: 50,
            }}
            className={'dark:text-black dark:bg-gray-800'}
          >
            <Link href="/ade/profile" role="menuitem" className="block px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-white rounded text-sm transition-colors text-black dark:text-black" style={{ textDecoration: "none" }}>
              View Profile
            </Link>
            <Link href="/ade/account" role="menuitem" className="block px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-700 hover:text-white rounded text-sm transition-colors text-black dark:text-black" style={{ textDecoration: "none" }}>
              Account
            </Link>
            <div style={{ height: 1, background: "rgba(0,0,0,0.45)", margin: "4px 0" }} className="dark:bg-gray-600" />
            <Link href="/ade/account" role="menuitem"
                  onClick={() => signOut()}
                  className="block px-3 py-2 hover:bg-red-100 dark:hover:bg-red-700 hover:text-white rounded text-sm transition-colors text-black dark:text-black" style={{ textDecoration: "none" }}>
              Sign out
            </Link>
          </div>
        )}
      </div>
    </header>
  );
}
