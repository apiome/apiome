'use client';

import Link from 'next/link';
import { useEffect, useId, useRef, useState } from 'react';
import type { VersionMenuEntry } from '../../../../lib/search/compare';

/** The versions a menu did not list with the page, and how to get them (DBP-1.27). */
export interface VersionMenuMore {
  /** How many of the project's versions the menu does not list. */
  count: number;
  /** Fetch the complete menu. Rejects when it cannot be loaded. */
  load: () => Promise<VersionMenuEntry[]>;
}

/**
 * The version chip on a search hit, opening a small menu of the project's other published
 * versions (BDX-2.6). Each entry lands on the same operation or schema anchor in that version when
 * the item exists there, and on the version page (marked *not in this version*) when it does not.
 *
 * The menu arrives with the project's newest versions. When the project has more, the menu ends
 * with **Show all versions**, which loads the rest in place (DBP-1.27).
 *
 * The chip sits above the row's stretched link, so opening the menu never opens the hit.
 *
 * @param versionSlug The hit's own version, shown on the chip.
 * @param entries The other versions (see `versionMenuEntries`), newest first.
 * @param more The versions not listed, when there are any.
 */
export function HitVersionMenu({
  versionSlug,
  entries,
  more,
}: {
  versionSlug: string;
  entries: readonly VersionMenuEntry[];
  more?: VersionMenuMore;
}) {
  const [open, setOpen] = useState(false);
  const [allEntries, setAllEntries] = useState<readonly VersionMenuEntry[] | null>(null);
  const [loadState, setLoadState] = useState<'idle' | 'loading' | 'failed'>('idle');
  const rootRef = useRef<HTMLSpanElement>(null);
  const menuId = useId();
  const shown = allEntries ?? entries;
  const canLoadMore = Boolean(more && more.count > 0) && !allEntries;

  // Close on a click outside the chip or on Escape.
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const loadAll = () => {
    if (!more || loadState === 'loading') return;
    setLoadState('loading');
    more
      .load()
      .then((loaded) => {
        setAllEntries(loaded);
        setLoadState('idle');
      })
      .catch(() => setLoadState('failed'));
  };

  return (
    <span ref={rootRef} className="relative z-10 inline-flex shrink-0">
      <button
        type="button"
        className="hit-version-chip"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        title="Switch to another published version"
        data-testid="hit-version-chip"
        onClick={() => setOpen((o) => !o)}
      >
        v{versionSlug}
        <svg className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24" aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <span id={menuId} role="menu" className="hit-version-menu" aria-label="Other published versions">
          <span className="hit-version-menu-heading block">Other versions</span>
          {shown.map((entry) => (
            <Link
              key={entry.versionSlug}
              href={entry.href}
              role="menuitem"
              className="hit-version-menu-item"
              onClick={() => setOpen(false)}
            >
              <span>v{entry.versionSlug}</span>
              {entry.missing && <span className="hit-version-menu-note">not in this version</span>}
            </Link>
          ))}
          {canLoadMore && (
            <button
              type="button"
              role="menuitem"
              className="hit-version-menu-item hit-version-menu-more"
              disabled={loadState === 'loading'}
              data-testid="hit-version-show-all"
              onClick={loadAll}
            >
              <span>{loadState === 'loading' ? 'Loading…' : 'Show all versions'}</span>
              <span className="hit-version-menu-note">
                {loadState === 'failed' ? 'could not load — try again' : `${more?.count} more`}
              </span>
            </button>
          )}
        </span>
      )}
    </span>
  );
}
