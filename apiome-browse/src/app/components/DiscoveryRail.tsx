'use client';

import { ReactNode, useRef, useState, useEffect, useCallback } from 'react';
import Link from 'next/link';

interface DiscoveryRailProps {
  title: string;
  description?: string;
  seeAllHref?: string;
  seeAllLabel?: string;
  emptyMessage?: string;
  children: ReactNode;
  itemCount: number;
}

export function DiscoveryRail({
  title,
  description,
  seeAllHref,
  seeAllLabel = 'View all',
  emptyMessage = 'Nothing here yet.',
  children,
  itemCount,
}: DiscoveryRailProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const updateScroll = useCallback(() => {
    const el = trackRef.current;
    if (!el) return;
    setCanScrollLeft(el.scrollLeft > 8);
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 8);
  }, []);

  useEffect(() => {
    updateScroll();
    const el = trackRef.current;
    if (!el) return;
    const observer = new ResizeObserver(updateScroll);
    observer.observe(el);
    return () => observer.disconnect();
  }, [updateScroll, itemCount]);

  const scroll = (dir: 1 | -1) => {
    const el = trackRef.current;
    if (!el) return;
    const amount = Math.max(280, Math.floor(el.clientWidth * 0.85));
    el.scrollBy({ left: dir * amount, behavior: 'smooth' });
  };

  return (
    <section className="space-y-3">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-fg">{title}</h2>
          {description && (
            <p className="mt-0.5 text-sm text-fg-muted">{description}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          {itemCount > 0 && (
            <div className="hidden items-center gap-1 sm:flex">
              <button
                type="button"
                onClick={() => scroll(-1)}
                disabled={!canScrollLeft}
                aria-label={`Scroll ${title} left`}
                className="flex h-7 w-7 items-center justify-center rounded-md border border-border bg-surface text-fg-muted shadow-xs transition-opacity hover:bg-subtle disabled:opacity-40"
              >
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
                </svg>
              </button>
              <button
                type="button"
                onClick={() => scroll(1)}
                disabled={!canScrollRight}
                aria-label={`Scroll ${title} right`}
                className="flex h-7 w-7 items-center justify-center rounded-md border border-border bg-surface text-fg-muted shadow-xs transition-opacity hover:bg-subtle disabled:opacity-40"
              >
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                </svg>
              </button>
            </div>
          )}
          {seeAllHref && (
            <Link
              href={seeAllHref}
              className="text-xs font-medium text-accent-fg hover:text-accent-hover"
            >
              {seeAllLabel}
              <span aria-hidden="true"> &rarr;</span>
            </Link>
          )}
        </div>
      </div>

      {itemCount === 0 ? (
        <div className="rounded-lg border border-dashed border-border-strong bg-surface/40 p-6 text-center text-base text-fg-muted">
          {emptyMessage}
        </div>
      ) : (
        <div className="relative -mx-4 sm:mx-0">
          <div
            ref={trackRef}
            onScroll={updateScroll}
            className="flex snap-x snap-mandatory gap-3 overflow-x-auto scroll-smooth px-4 pb-2 sm:px-0 [&>*]:snap-start [scrollbar-width:thin]"
          >
            {children}
          </div>
        </div>
      )}
    </section>
  );
}
