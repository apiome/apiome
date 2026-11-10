'use client';

import Link from 'next/link';
import Image from 'next/image';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import { useTheme, specThemes, SpecTheme, Theme } from './ThemeProvider';
import { DirectoryStatPills, type DirectoryStats } from './DirectoryStatPills';
import { openSearchPalette } from './search/searchPaletteBus';

export function Navbar({ stats }: { stats: DirectoryStats }) {
  const pathname = usePathname();
  const { theme, specTheme, setTheme, setSpecTheme } = useTheme();
  const [showSettings, setShowSettings] = useState(false);

  const navItems = [
    { href: '/', label: 'Discover', exact: true },
    { href: '/search', label: 'Search', exact: false },
    { href: '/mcp', label: 'MCP Catalog', exact: false },
  ];

  return (
    <nav className="sticky top-0 z-40 border-b border-border/80 bg-surface/85 backdrop-blur supports-[backdrop-filter]:bg-surface/70">
      <div aria-hidden="true" className="brand-hairline h-0.5 w-full" />
      <div className="mx-auto flex h-14 max-w-[1480px] items-center gap-3 px-4 sm:px-6 lg:gap-4 lg:px-8">
        {/* Left: Logo + Nav */}
        <div className="flex min-w-0 shrink-0 items-center gap-6 lg:gap-8">
          <Link href="/" className="flex items-center gap-2 shrink-0" aria-label="Apiome home">
            <div className="flex h-9 items-center justify-center relative">
              <Image
                src="/Apiome-02.png"
                alt=""
                width={108}
                height={36}
                className="object-contain dark:hidden h-9 w-auto"
                priority
              />
              <Image
                src="/Apiome-05.png"
                alt=""
                width={108}
                height={36}
                className="object-contain hidden dark:block h-9 w-auto"
                priority
              />
            </div>
          </Link>

          <div className="hidden items-center gap-1 md:flex">
            {navItems.map((item) => {
              const active = item.exact ? pathname === item.href : pathname?.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded-md px-3 py-1.5 text-base font-medium transition-colors ${
                    active
                      ? 'bg-accent-soft text-accent-fg'
                      : 'text-fg-muted hover:bg-subtle hover:text-fg'
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </div>
        </div>

        <DirectoryStatPills stats={stats} className="hidden min-w-0 flex-1 lg:flex" />

        {/* Right: Search trigger + Tutorials + Login + Settings */}
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {/* Search trigger (⌘K palette) */}
          <button
            type="button"
            onClick={() => openSearchPalette()}
            className="hidden h-9 w-72 items-center gap-2 rounded-md border border-border bg-subtle/80 px-3 text-base text-fg-muted transition-colors hover:border-accent/30 hover:bg-accent-soft lg:flex xl:w-80"
            aria-label="Search the catalog"
            aria-keyshortcuts="Meta+K Control+K /"
          >
            <svg className="h-4 w-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <span className="min-w-0 flex-1 truncate text-left text-sm">Search operations, schemas, projects…</span>
            <kbd className="rounded-xs border border-border-strong bg-surface px-1.5 text-2xs font-medium text-fg-muted">⌘K</kbd>
          </button>
          <button
            type="button"
            onClick={() => openSearchPalette()}
            className="flex h-8 w-8 items-center justify-center rounded-md text-fg-muted transition-colors hover:bg-subtle hover:text-fg lg:hidden"
            aria-label="Search the catalog"
          >
            <svg className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
          </button>

          {/* Tutorials */}
          <a
            href="https://www.youtube.com/@apiomedev/"
            target="_blank"
            rel="noopener noreferrer"
            className="hidden items-center gap-1.5 rounded-md px-2.5 py-1.5 text-base font-medium text-fg-muted transition-colors hover:bg-subtle hover:text-fg sm:flex"
            title="Watch Apiome tutorials on YouTube"
          >
            <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" />
            </svg>
            <span className="hidden md:inline">Tutorials</span>
          </a>

          {/* Login / Sign Up */}
          <a
            href="https://app.apiome.dev/"
            className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-base font-medium text-fg-on-accent transition-colors hover:bg-accent-hover focus-visible:outline-none"
          >
            <span className="hidden sm:inline">Sign in</span>
            <span className="sm:hidden">Sign in</span>
          </a>

          {/* Separator */}
          <div className="hidden h-5 w-px bg-inset sm:block"></div>

          {/* Settings */}
          <div className="relative">
            <button
              onClick={() => setShowSettings(!showSettings)}
              className="flex h-8 w-8 items-center justify-center rounded-md text-fg-muted transition-colors hover:bg-subtle hover:text-fg"
              aria-label="Settings"
              aria-expanded={showSettings}
              aria-haspopup="true"
            >
              <svg className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </button>

            {showSettings && (
              <>
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setShowSettings(false)}
                  aria-hidden="true"
                />
                <div className="animate-fade-in absolute right-0 top-full z-50 mt-2 w-72 rounded-lg border border-border bg-surface p-4 shadow-lg">
                  <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-fg-muted">
                    Appearance
                  </h3>

                  <div className="mb-4">
                    <label className="block text-2xs font-medium uppercase tracking-wider text-fg-muted">
                      App Theme
                    </label>
                    <div className="mt-2 flex gap-1">
                      {(['light', 'dark', 'system'] as Theme[]).map((t) => (
                        <button
                          key={t}
                          onClick={() => setTheme(t)}
                          className={`flex-1 rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                            theme === t
                              ? 'bg-accent text-fg-on-accent'
                              : 'bg-subtle text-fg-muted hover:bg-inset'
                          }`}
                        >
                          {t}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="block text-2xs font-medium uppercase tracking-wider text-fg-muted">
                      Code Theme
                    </label>
                    <div className="mt-2 grid grid-cols-2 gap-1">
                      {(Object.entries(specThemes) as [SpecTheme, typeof specThemes.default][]).map(
                        ([key, value]) => (
                          <button
                            key={key}
                            onClick={() => setSpecTheme(key)}
                            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                              specTheme === key
                                ? 'bg-accent text-fg-on-accent'
                                : 'bg-subtle text-fg-muted hover:bg-inset'
                            }`}
                          >
                            {value.name}
                          </button>
                        )
                      )}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
      <div className="border-t border-border/80 px-4 py-2 lg:hidden">
        <DirectoryStatPills stats={stats} />
      </div>
    </nav>
  );
}
