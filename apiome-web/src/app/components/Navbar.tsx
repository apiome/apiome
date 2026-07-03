'use client';

import { links } from "@/lib/links";

import { useEffect, useState, useSyncExternalStore } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { usePathname } from 'next/navigation';
import { useTheme } from 'next-themes';
import { Sun, Moon, Menu, X } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Button } from './ui/Button';
import { cn } from '@/lib/utils';

const NAV_LINKS = [
  { href: '/features', label: 'Features' },
  { href: '/screenshots', label: 'Screenshots' },
  { href: '/mcp', label: 'MCP' },
  { href: '/for-teams', label: 'For Teams' },
  { href: '/pricing', label: 'Pricing' },
];

// SSR-safe client-only flag used to guard theme icon rendering without triggering
// hydration mismatches. Using useSyncExternalStore avoids calling setState in an effect.
const emptyUnsubscribe = () => () => {};
function useIsClient(): boolean {
  return useSyncExternalStore(
    emptyUnsubscribe,
    () => true,
    () => false,
  );
}

// Scroll subscription via useSyncExternalStore keeps setState out of effects.
function subscribeScroll(cb: () => void) {
  window.addEventListener('scroll', cb, { passive: true });
  return () => window.removeEventListener('scroll', cb);
}
function useScrolled(threshold = 8): boolean {
  return useSyncExternalStore(
    subscribeScroll,
    () => window.scrollY > threshold,
    () => false,
  );
}

export function Navbar() {
  const { resolvedTheme, setTheme } = useTheme();
  const pathname = usePathname();
  const isClient = useIsClient();
  const scrolled = useScrolled();
  const [mobileOpen, setMobileOpen] = useState(false);
  const reduce = useReducedMotion();

  // Lock body scroll when the mobile drawer is open. Touches an external system (DOM),
  // so setState-in-effect rule doesn't apply.
  useEffect(() => {
    if (mobileOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [mobileOpen]);

  const closeMobile = () => setMobileOpen(false);

  return (
    <>
      <nav
        className={cn(
          'sticky top-0 z-50 w-full border-b backdrop-blur-xl backdrop-saturate-150 transition-all duration-300',
          scrolled
            ? 'border-zinc-200/60 bg-white/70 shadow-[0_8px_30px_-12px_rgba(0,0,0,0.18)] dark:border-zinc-800/60 dark:bg-zinc-950/60 dark:shadow-[0_8px_30px_-12px_rgba(0,0,0,0.7)]'
            : 'border-white/40 bg-white/55 dark:border-white/10 dark:bg-zinc-950/45',
        )}
      >
        {/* Glass sheen: a bright hairline along the bottom edge */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-white/60 to-transparent dark:via-white/15"
        />
        <div className="container mx-auto px-4">
          <div
            className={cn(
              'flex items-center justify-between transition-[height] duration-300',
              scrolled ? 'h-14' : 'h-16',
            )}
          >
            <div className="flex items-center gap-2.5">
              <Link href="/" className="group flex items-center gap-3">
                <div className="relative flex h-10 w-auto items-center transition-transform duration-300 group-hover:scale-[1.03]">
                  <Image
                    src="/Apiome-02.png"
                    alt="Apiome Logo"
                    width={120}
                    height={40}
                    className="h-10 w-auto object-contain dark:hidden"
                    priority
                  />
                  <Image
                    src="/Apiome-05.png"
                    alt="Apiome Logo"
                    width={120}
                    height={40}
                    className="hidden h-10 w-auto object-contain dark:block"
                    priority
                  />
                </div>
              </Link>
              <span
                title="Release Candidate"
                className="inline-flex items-center rounded-full border border-amber-300/60 bg-amber-50/80 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-700 backdrop-blur dark:border-amber-700/50 dark:bg-amber-950/40 dark:text-amber-300"
              >
                RC
              </span>
            </div>

            <div className="flex items-center gap-1 sm:gap-2">
              <div className="hidden items-center gap-1 sm:flex">
                {NAV_LINKS.map((link) => {
                  const active = pathname === link.href;
                  return (
                    <Link
                      key={link.href}
                      href={link.href}
                      className={cn(
                        'relative rounded-lg px-3 py-2 text-sm font-medium transition-colors',
                        active
                          ? 'text-zinc-900 dark:text-zinc-50'
                          : 'text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50',
                      )}
                    >
                      {link.label}
                      {active && (
                        <motion.span
                          layoutId="nav-active-indicator"
                          className="absolute inset-x-2 bottom-1 h-[2px] rounded-full bg-gradient-to-r from-blue-600 to-indigo-600"
                          transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
                        />
                      )}
                    </Link>
                  );
                })}
              </div>

              <button
                onClick={() => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')}
                className="relative flex h-9 w-9 items-center justify-center rounded-lg text-zinc-600 transition-colors hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
                aria-label="Toggle theme"
                suppressHydrationWarning
              >
                <AnimatePresence mode="wait" initial={false}>
                  {isClient ? (
                    <motion.span
                      key={resolvedTheme ?? 'light'}
                      initial={reduce ? undefined : { opacity: 0, rotate: -90, scale: 0.7 }}
                      animate={reduce ? undefined : { opacity: 1, rotate: 0, scale: 1 }}
                      exit={reduce ? undefined : { opacity: 0, rotate: 90, scale: 0.7 }}
                      transition={{ duration: 0.25 }}
                      className="absolute"
                    >
                      {resolvedTheme === 'dark' ? <Moon className="h-5 w-5" /> : <Sun className="h-5 w-5" />}
                    </motion.span>
                  ) : (
                    <Sun className="h-5 w-5" />
                  )}
                </AnimatePresence>
              </button>

              <a
                href={links.app}
                target="_blank"
                rel="noopener noreferrer"
                className="hidden sm:inline-flex"
              >
                <Button size="sm">Launch App</Button>
              </a>

              <button
                onClick={() => setMobileOpen((v) => !v)}
                className="flex h-9 w-9 items-center justify-center rounded-lg text-zinc-700 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800 sm:hidden"
                aria-label="Toggle menu"
                aria-expanded={mobileOpen}
              >
                {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
              </button>
            </div>
          </div>
        </div>
      </nav>

      <AnimatePresence>
        {mobileOpen && (
          <>
            <motion.div
              className="fixed inset-0 z-40 bg-zinc-950/40 backdrop-blur-sm sm:hidden"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              onClick={() => setMobileOpen(false)}
              aria-hidden
            />
            <motion.div
              className="fixed inset-x-0 top-16 z-40 mx-4 overflow-hidden rounded-2xl border border-zinc-200/70 bg-white/95 p-2 shadow-2xl backdrop-blur-xl dark:border-zinc-800/70 dark:bg-zinc-950/95 sm:hidden"
              initial={{ opacity: 0, y: -12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.98 }}
              transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
            >
              <div className="flex flex-col p-2">
                {NAV_LINKS.map((link, i) => (
                  <motion.div
                    key={link.href}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.05 + i * 0.04 }}
                  >
                    <Link
                      href={link.href}
                      onClick={closeMobile}
                      className="block rounded-lg px-4 py-3 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-100 dark:text-zinc-200 dark:hover:bg-zinc-800"
                    >
                      {link.label}
                    </Link>
                  </motion.div>
                ))}
                <div className="mt-2 border-t border-zinc-200 pt-2 dark:border-zinc-800">
                  <a
                    href={links.app}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="block"
                    onClick={closeMobile}
                  >
                    <Button size="lg" className="w-full">
                      Launch App
                    </Button>
                  </a>
                </div>
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
