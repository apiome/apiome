'use client';

import Image from 'next/image';
import Link from 'next/link';
import { Twitter, Linkedin, Youtube } from 'lucide-react';

export function Footer() {
  const currentYear = new Date().getFullYear();

  return (
    <footer className="border-t border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
      <div className="container mx-auto px-4 py-12">
        <div className="grid gap-8 md:grid-cols-2 lg:grid-cols-3">
          {/* Brand */}
          <div>
            <div className="mb-4 flex items-center gap-3">
              <div className="relative h-10 w-auto flex items-center">
                <Image
                  src="/Objectified-02.png"
                  alt="Objectified Logo"
                  width={120}
                  height={40}
                  className="h-10 w-auto object-contain dark:hidden"
                />
                <Image
                  src="/Objectified-05.png"
                  alt="Objectified Logo"
                  width={120}
                  height={40}
                  className="hidden h-10 w-auto object-contain dark:block"
                />
              </div>
            </div>
            <p className="mb-2 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
              Your data: Designed, Defined, Discovered.
            </p>
            <p className="text-sm text-zinc-600 dark:text-zinc-400">
              Visual API & Database Design Platform. Build better APIs faster with our intuitive tools.
            </p>
            <div className="mt-4 flex gap-3">
              {/* GitHub - Coming Soon
              <a
                href="https://github.com/objectified"
                target="_blank"
                rel="noopener noreferrer"
                className="flex h-9 w-9 items-center justify-center rounded-lg text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
                aria-label="GitHub"
              >
                <Github className="h-5 w-5" />
              </a>
              */}
              {/*<a*/}
              {/*  href="https://twitter.com/objectifieddev"*/}
              {/*  target="_blank"*/}
              {/*  rel="noopener noreferrer"*/}
              {/*  className="flex h-9 w-9 items-center justify-center rounded-lg text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"*/}
              {/*  aria-label="Twitter"*/}
              {/*>*/}
              {/*  <Twitter className="h-5 w-5" />*/}
              {/*</a>*/}
              <a
                href="https://www.youtube.com/@objectifieddev"
                target="_blank"
                rel="noopener noreferrer"
                className="flex h-9 w-9 items-center justify-center rounded-lg text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
                aria-label="YouTube"
              >
                <Youtube className="h-5 w-5" />
              </a>
              {/*<a*/}
              {/*  href="https://linkedin.com/company/objectified"*/}
              {/*  target="_blank"*/}
              {/*  rel="noopener noreferrer"*/}
              {/*  className="flex h-9 w-9 items-center justify-center rounded-lg text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"*/}
              {/*  aria-label="LinkedIn"*/}
              {/*>*/}
              {/*  <Linkedin className="h-5 w-5" />*/}
              {/*</a>*/}
            </div>
          </div>

          {/* Product */}
          <div>
            <h3 className="mb-4 text-sm font-semibold text-zinc-900 dark:text-zinc-50">
              Product
            </h3>
            <ul className="space-y-2 text-sm">
              <li>
                <a
                  href="https://app.objectified.dev"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
                >
                  Launch App
                </a>
              </li>
              <li>
                <Link
                  href="/features"
                  className="text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
                >
                  Features
                </Link>
              </li>
              <li>
                <Link
                  href="/for-teams"
                  className="text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
                >
                  For Teams
                </Link>
              </li>
              <li>
                <Link
                  href="/pricing"
                  className="text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
                >
                  Pricing
                </Link>
              </li>
              <li>
                <a
                  href="https://browse.objectified.dev"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
                >
                  Browse APIs
                </a>
              </li>
            </ul>
          </div>

          {/* Resources */}
          <div>
            <h3 className="mb-4 text-sm font-semibold text-zinc-900 dark:text-zinc-50">
              Resources
            </h3>
            <ul className="space-y-2 text-sm">
              <li>
                <a
                  href="https://www.youtube.com/@objectifieddev"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
                >
                  Tutorials
                </a>
              </li>
              {/* GitHub - Coming Soon
              <li>
                <a
                  href="https://github.com/objectified"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
                >
                  GitHub
                </a>
              </li>
              */}
              {/* Community - Coming Soon
              <li>
                <a
                  href="https://discord.gg/objectified"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
                >
                  Community
                </a>
              </li>
              */}
            </ul>
          </div>
        </div>

        <div className="mt-12 border-t border-zinc-200 pt-8 dark:border-zinc-800">
          <p className="text-center text-sm text-zinc-600 dark:text-zinc-400">
            © 2018 - {currentYear} NobuData, LLC. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
}
