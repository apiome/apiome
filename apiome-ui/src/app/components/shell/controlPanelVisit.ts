'use client';

import * as React from 'react';

/**
 * When the reader last had the Control Panel open, on this device (HIVE-12.5, #5612).
 *
 * The launcher's Control Panel tile says "Included · last opened 2 hours ago"
 * (`docs/mockups/proposals/launcher-focused.html`, callout 2). Nothing recorded that before:
 * the only recents store, `hive.paletteRecents`, logs what was opened *through* ⌘K. So the
 * shell stamps the time whenever a Control Panel page mounts — every `/ade/**` route except
 * the launcher, which is exactly the set `AppShell` draws — and the launcher reads it.
 *
 * Same rules as the other `hive.*` stores: device-local, never sent anywhere, and silent on
 * every failure. A browser that refuses storage simply gets a tile that says "Included".
 */

/** Storage key; epoch milliseconds as a decimal string. */
export const CONTROL_PANEL_VISIT_STORAGE_KEY = 'hive.controlPanelOpenedAt';

/**
 * Remember that the Control Panel is open now.
 *
 * @param now Epoch milliseconds to record; a parameter so tests need no fake clock.
 */
export function recordControlPanelVisit(now: number = Date.now()): void {
  if (typeof window === 'undefined') return;

  try {
    window.localStorage.setItem(CONTROL_PANEL_VISIT_STORAGE_KEY, String(Math.floor(now)));
  } catch {
    /* Storage unavailable — the launcher shows no "last opened" time. */
  }
}

/**
 * Read when the Control Panel was last open.
 *
 * @returns Epoch milliseconds, or `null` when nothing is stored, the store cannot be read, or
 *          what is there is not a positive integer.
 */
export function readControlPanelVisit(): number | null {
  if (typeof window === 'undefined') return null;

  try {
    const raw = window.localStorage.getItem(CONTROL_PANEL_VISIT_STORAGE_KEY);
    if (raw === null || !/^\d+$/.test(raw)) return null;
    const at = Number(raw);
    return Number.isSafeInteger(at) && at > 0 ? at : null;
  } catch {
    return null;
  }
}

/**
 * When the Control Panel was last open, for a component to render (the launcher's tile).
 *
 * `null` on the first render, server and client alike — the server has no `localStorage`, and
 * the tile's plain "Included" is the right first paint — then the stored time, after mount.
 *
 * @returns Epoch milliseconds, or `null` before mount and when nothing usable is stored.
 */
export function useControlPanelVisit(): number | null {
  const [openedAt, setOpenedAt] = React.useState<number | null>(null);

  React.useEffect(() => {
    setOpenedAt(readControlPanelVisit());
  }, []);

  return openedAt;
}
