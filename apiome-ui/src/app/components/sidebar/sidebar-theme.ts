'use client';

import { useCallback, useSyncExternalStore } from 'react';

export type SidebarDensity = 'compact' | 'standard' | 'comfortable';

const STORAGE_KEY = 'apiome.sidebar.density';
const CHANGE_EVENT = 'apiome:sidebar-density-change';

/**
 * Linear/Vercel-inspired sidebar design tokens. Three density modes:
 * compact (dense IDE-style), standard (default), comfortable (large touch targets).
 *
 * Tokens are returned as Tailwind class strings so consumers can compose them
 * with their own conditional classes without runtime style objects.
 */
export interface SidebarDensityTokens {
  /** Vertical padding for an interactive row (button, list item). */
  rowPaddingY: string;
  /** Horizontal padding for a row. */
  rowPaddingX: string;
  /** Body text inside rows. */
  rowText: string;
  /** Min height for header (icon + title). */
  headerHeight: string;
  /** Padding for section content area. */
  sectionPadding: string;
  /** Gap between stacked rows. */
  rowGap: string;
  /** Search/filter input padding. */
  inputPaddingY: string;
}

const TOKENS: Record<SidebarDensity, SidebarDensityTokens> = {
  compact: {
    rowPaddingY: 'py-1',
    rowPaddingX: 'px-2',
    rowText: 'text-xs',
    headerHeight: 'h-11',
    sectionPadding: 'px-2 py-2',
    rowGap: 'gap-0.5',
    inputPaddingY: 'py-1',
  },
  standard: {
    rowPaddingY: 'py-1.5',
    rowPaddingX: 'px-2.5',
    rowText: 'text-sm',
    headerHeight: 'h-12',
    sectionPadding: 'px-3 py-3',
    rowGap: 'gap-1',
    inputPaddingY: 'py-1.5',
  },
  comfortable: {
    rowPaddingY: 'py-2.5',
    rowPaddingX: 'px-3',
    rowText: 'text-sm',
    headerHeight: 'h-14',
    sectionPadding: 'px-3 py-3.5',
    rowGap: 'gap-1.5',
    inputPaddingY: 'py-2',
  },
};

export const DENSITY_LABELS: Record<SidebarDensity, string> = {
  compact: 'Compact',
  standard: 'Standard',
  comfortable: 'Comfortable',
};

export function getSidebarTokens(density: SidebarDensity): SidebarDensityTokens {
  return TOKENS[density] ?? TOKENS.standard;
}

function readDensity(): SidebarDensity {
  if (typeof window === 'undefined') return 'standard';
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    if (v === 'compact' || v === 'standard' || v === 'comfortable') return v;
  } catch {
    /* ignore */
  }
  return 'standard';
}

function subscribe(listener: () => void): () => void {
  const onStorage = (e: StorageEvent) => {
    if (e.key === STORAGE_KEY) listener();
  };
  window.addEventListener(CHANGE_EVENT, listener);
  window.addEventListener('storage', onStorage);
  return () => {
    window.removeEventListener(CHANGE_EVENT, listener);
    window.removeEventListener('storage', onStorage);
  };
}

/**
 * Read and subscribe to the user's sidebar density preference. Persists
 * across reloads via localStorage. Updates fire instantly across components
 * within the same tab via a custom event, and across tabs via the storage
 * event.
 *
 * Uses {@link useSyncExternalStore} so React reads from localStorage as if
 * it were an external store, avoiding the cascading-render pattern of
 * setState-inside-useEffect.
 */
export function useSidebarDensity(): [SidebarDensity, (next: SidebarDensity) => void] {
  const density = useSyncExternalStore<SidebarDensity>(
    subscribe,
    readDensity,
    () => 'standard'
  );

  const setDensity = useCallback((next: SidebarDensity) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);

  return [density, setDensity];
}

/**
 * Convenience hook returning the resolved density tokens.
 */
export function useSidebarTokens(): SidebarDensityTokens {
  const [density] = useSidebarDensity();
  return getSidebarTokens(density);
}

/**
 * Shared color palette for the Linear/Vercel-style sidebar. Centralizing
 * these strings keeps the three sidebars visually identical and makes
 * future theme adjustments a one-file change.
 */
export const sidebarTheme = {
  surface:
    'bg-surface',
  border:
    'border-border',
  borderSoft:
    'border-border/70',
  textPrimary:
    'text-fg',
  textSecondary:
    'text-fg-muted',
  textTertiary:
    'text-fg-subtle',
  hover:
    'hover:bg-subtle',
  rowSelected:
    'bg-accent-soft text-accent-fg',
  rowSelectedRing:
    'ring-1 ring-inset ring-accent/30',
  iconBadge:
    'bg-accent-soft ring-1 ring-accent/30 text-accent-fg',
  inputBase:
    'bg-surface border-border text-fg placeholder:text-fg-faint focus:border-accent focus:ring-2 focus:ring-accent/20 focus:outline-none',
  sectionLabel:
    'text-2xs font-semibold tracking-[0.08em] uppercase text-fg-subtle',
} as const;
