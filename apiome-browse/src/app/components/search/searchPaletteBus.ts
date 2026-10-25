'use client';

/**
 * A tiny event bus so any component (the navbar, a keyboard shortcut, an empty state) can open
 * the search palette without threading state through the tree. The palette itself is mounted
 * once in `ClientLayout`.
 */

import { notifyStoredPrefChanged } from './useStoredPref';

const OPEN_EVENT = 'apiome-browse:open-search-palette';

/** Open the palette, optionally pre-filled with a query. */
export function openSearchPalette(initialQuery = ''): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(OPEN_EVENT, { detail: { query: initialQuery } }));
}

/** Subscribe to open requests; returns the unsubscribe. */
export function onOpenSearchPalette(handler: (query: string) => void): () => void {
  if (typeof window === 'undefined') return () => undefined;
  const listener = (event: Event) => {
    const detail = (event as CustomEvent<{ query?: string }>).detail;
    handler(detail?.query ?? '');
  };
  window.addEventListener(OPEN_EVENT, listener);
  return () => window.removeEventListener(OPEN_EVENT, listener);
}

/** Whether a key event happened inside something that takes typed input. */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

/** The key used for recent searches in localStorage (shared by the palette and the search page). */
export const RECENT_SEARCHES_KEY = 'apiome-browse-search-recent';
export const RECENT_SEARCHES_MAX = 8;

/** Read recent searches; never throws. */
export function readRecentSearches(): string[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(RECENT_SEARCHES_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

/** Remember a search at the top of the recent list; never throws. */
export function pushRecentSearch(query: string): void {
  const q = query.trim();
  if (typeof window === 'undefined' || !q) return;
  try {
    const prev = readRecentSearches().filter((x) => x.toLowerCase() !== q.toLowerCase());
    prev.unshift(q);
    window.localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(prev.slice(0, RECENT_SEARCHES_MAX)));
  } catch {
    /* storage unavailable */
  }
  notifyStoredPrefChanged();
}

/** Forget every recent search; never throws. */
export function clearRecentSearches(): void {
  try {
    window.localStorage.removeItem(RECENT_SEARCHES_KEY);
  } catch {
    /* storage unavailable */
  }
  notifyStoredPrefChanged();
}
