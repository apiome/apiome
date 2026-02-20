'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { useTheme } from 'next-themes';
import { Sun, Moon } from 'lucide-react';
import { Button } from './ui/Button';

export function Navbar() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  return (
    <nav className="sticky top-0 z-50 border-b border-zinc-200 bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/80 dark:border-zinc-800 dark:bg-zinc-950/95 dark:supports-[backdrop-filter]:bg-zinc-950/80">
      <div className="container mx-auto px-4">
        <div className="flex h-16 items-center justify-between">
          {/* Logo */}
          <div className="flex items-center">
            <Link href="/" className="flex items-center gap-3">
              <div className="relative h-10 w-auto flex items-center">
                <Image
                  src="/Objectified-02.png"
                  alt="Objectified Logo"
                  width={120}
                  height={40}
                  className="h-10 w-auto object-contain dark:hidden"
                  priority
                />
                <Image
                  src="/Objectified-05.png"
                  alt="Objectified Logo"
                  width={120}
                  height={40}
                  className="hidden h-10 w-auto object-contain dark:block"
                  priority
                />
              </div>
            </Link>
          </div>

          {/* Navigation Links + Actions */}
          <div className="flex items-center gap-1 sm:gap-3">
            {/* Nav Links */}
            <Link
              href="/features"
              className="hidden rounded-lg px-3 py-2 text-sm font-medium text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-50 sm:inline-flex"
            >
              Features
            </Link>
            <Link
              href="/for-teams"
              className="hidden rounded-lg px-3 py-2 text-sm font-medium text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-50 sm:inline-flex"
            >
              For Teams
            </Link>
            <Link
              href="/pricing"
              className="hidden rounded-lg px-3 py-2 text-sm font-medium text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-50 sm:inline-flex"
            >
              Pricing
            </Link>

            {/* Theme Toggle */}
            <button
              onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
              className="relative flex h-9 w-9 items-center justify-center rounded-lg text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
              aria-label="Toggle theme"
              suppressHydrationWarning
            >
              {mounted ? (
                resolvedTheme === 'dark' ? (
                  <Moon className="h-5 w-5" />
                ) : (
                  <Sun className="h-5 w-5" />
                )
              ) : (
                <Sun className="h-5 w-5" />
              )}
            </button>

            {/* Launch App */}
            <a
              href="https://app.objectified.dev"
              target="_blank"
              rel="noopener noreferrer"
            >
              <Button size="sm">
                Launch App
              </Button>
            </a>
          </div>
        </div>
      </div>
    </nav>
  );
}
