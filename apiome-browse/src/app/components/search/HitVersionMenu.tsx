'use client';

import Link from 'next/link';
import { useEffect, useId, useRef, useState } from 'react';
import type { VersionMenuEntry } from '../../../../lib/search/compare';

/**
 * The version chip on a search hit, opening a small menu of the project's other published
 * versions (BDX-2.6). Each entry lands on the same operation or schema anchor in that version when
 * the item exists there, and on the version page (marked *not in this version*) when it does not.
 *
 * The chip sits above the row's stretched link, so opening the menu never opens the hit.
 *
 * @param versionSlug The hit's own version, shown on the chip.
 * @param entries The other versions (see `versionMenuEntries`), newest first.
 */
export function HitVersionMenu({ versionSlug, entries }: { versionSlug: string; entries: readonly VersionMenuEntry[] }) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);
  const menuId = useId();

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
          {entries.map((entry) => (
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
        </span>
      )}
    </span>
  );
}
