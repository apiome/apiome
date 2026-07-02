'use client';

import Link from 'next/link';
import { Fragment } from 'react';

interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface BreadcrumbProps {
  items: BreadcrumbItem[];
}

export function Breadcrumb({ items }: BreadcrumbProps) {
  return (
    <nav className="flex items-center gap-2 text-[13px]" aria-label="Breadcrumb">
      <Link
        href="/"
        className="flex items-center text-zinc-500 transition-colors hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
        aria-label="Home"
      >
        <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"
          />
        </svg>
      </Link>
      {items.map((item, index) => (
        <Fragment key={index}>
          <span className="text-zinc-300 dark:text-zinc-700 font-light select-none" aria-hidden="true">
            /
          </span>
          {item.href ? (
            <Link
              href={item.href}
              className="max-w-[160px] truncate text-zinc-500 transition-colors hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-50"
              title={item.label}
            >
              {item.label}
            </Link>
          ) : (
            <span
              className="max-w-[240px] truncate font-medium text-zinc-900 dark:text-zinc-50"
              title={item.label}
              aria-current="page"
            >
              {item.label}
            </span>
          )}
        </Fragment>
      ))}
    </nav>
  );
}
