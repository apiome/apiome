'use client';

import Image from 'next/image';
import Link from 'next/link';
import { Youtube } from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';

export function Footer() {
  const reduce = useReducedMotion();

  return (
    <footer className="relative border-t border-zinc-200/70 bg-white/60 backdrop-blur-sm dark:border-zinc-800/70 dark:bg-zinc-950/60">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 -top-px h-px bg-gradient-to-r from-transparent via-blue-500/40 to-transparent dark:via-blue-400/30"
      />
      <div className="container mx-auto px-4 py-14">
        <div className="grid gap-10 md:grid-cols-2 lg:grid-cols-3">
          <div>
            <div className="mb-4 flex items-center gap-3">
              <div className="relative flex h-10 w-auto items-center">
                <Image
                  src="/Apiome-02.png"
                  alt="Apiome Logo"
                  width={120}
                  height={40}
                  className="h-10 w-auto object-contain dark:hidden"
                />
                <Image
                  src="/Apiome-05.png"
                  alt="Apiome Logo"
                  width={120}
                  height={40}
                  className="hidden h-10 w-auto object-contain dark:block"
                />
              </div>
            </div>
            <p className="mb-2 font-display text-lg italic text-zinc-700 dark:text-zinc-200">
              Your data: Designed, Defined, Discovered.
            </p>
            <p className="text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
              Visual API & Database Design Platform. Build better APIs faster with intuitive, visual tools.
            </p>
            <div className="mt-5 flex gap-3">
              <motion.a
                href="https://www.youtube.com/@objectifieddev"
                target="_blank"
                rel="noopener noreferrer"
                whileHover={reduce ? undefined : { y: -2, scale: 1.05 }}
                whileTap={reduce ? undefined : { scale: 0.95 }}
                className="flex h-9 w-9 items-center justify-center rounded-lg bg-zinc-100/70 text-zinc-600 ring-1 ring-inset ring-zinc-200/70 transition-colors hover:bg-red-500/10 hover:text-red-600 dark:bg-zinc-900/70 dark:text-zinc-400 dark:ring-zinc-800/70 dark:hover:bg-red-500/20 dark:hover:text-red-400"
                aria-label="YouTube"
              >
                <Youtube className="h-5 w-5" />
              </motion.a>
            </div>
          </div>

          <div>
            <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-zinc-900 dark:text-zinc-50">
              Product
            </h3>
            <ul className="space-y-2.5 text-sm">
              <FooterLink href="https://app.apiome.app" external>
                Launch App
              </FooterLink>
              <FooterLink href="/features">Features</FooterLink>
              <FooterLink href="/screenshots">Screenshots</FooterLink>
              <FooterLink href="/mcp">MCP</FooterLink>
              <FooterLink href="/for-teams">For Teams</FooterLink>
              <FooterLink href="/pricing">Pricing</FooterLink>
              <FooterLink href="https://browse.apiome.app" external>
                Browse APIs
              </FooterLink>
            </ul>
          </div>

          <div>
            <h3 className="mb-4 text-sm font-semibold uppercase tracking-wider text-zinc-900 dark:text-zinc-50">
              Resources
            </h3>
            <ul className="space-y-2.5 text-sm">
              <FooterLink href="https://www.youtube.com/@objectifieddev" external>
                Tutorials
              </FooterLink>
            </ul>
          </div>
        </div>

        <div className="mt-12 border-t border-zinc-200/70 pt-8 dark:border-zinc-800/70">
          <p className="text-center text-sm text-zinc-500 dark:text-zinc-500">
            © 2021 – 2026 NobuData LLC
          </p>
        </div>
      </div>
    </footer>
  );
}

function FooterLink({
  href,
  external,
  children,
}: {
  href: string;
  external?: boolean;
  children: React.ReactNode;
}) {
  const className =
    'group relative inline-flex text-zinc-600 transition-colors hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50';
  const inner = (
    <span className="relative">
      {children}
      <span className="pointer-events-none absolute -bottom-0.5 left-0 h-px w-0 bg-gradient-to-r from-blue-500 to-indigo-500 transition-[width] duration-300 group-hover:w-full" />
    </span>
  );
  return (
    <li>
      {external ? (
        <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
          {inner}
        </a>
      ) : (
        <Link href={href} className={className}>
          {inner}
        </Link>
      )}
    </li>
  );
}
