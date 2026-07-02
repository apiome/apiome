'use client';

import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { FEATURE_GITLIKE } from '@lib/feature-flags';

const STORAGE_KEY = 'apiome:push-409';

export type PushConflictCurrentHead = {
  revisionId?: string;
  versionId?: string;
  shortMessage?: string | null;
  createdAt?: string | null;
};

export type PushConflictState = {
  projectId: string;
  message?: string;
  currentHeadRevisionId?: string;
  currentHead?: PushConflictCurrentHead | null;
};

type PushConflictBannerContextValue = {
  conflict: PushConflictState | null;
  setPushConflictFrom409: (state: PushConflictState) => void;
  clearPushConflict: () => void;
};

const PushConflictBannerContext = createContext<PushConflictBannerContextValue | undefined>(
  undefined
);

function readConflictFromSession(): PushConflictState | null {
  if (typeof window === 'undefined') return null;
  /* When git-like is disabled, ignore any persisted 409 state from a previous
     session so the banner never re-surfaces. We also clear it from storage
     defensively. */
  if (!FEATURE_GITLIKE) {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    return null;
  }
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed === 'object' &&
      typeof (parsed as Record<string, unknown>).projectId === 'string'
    ) {
      return parsed as PushConflictState;
    }
  } catch {
    /* ignore */
  }
  return null;
}

export function PushConflictBannerProvider({ children }: { children: ReactNode }) {
  const [conflict, setConflict] = useState<PushConflictState | null>(readConflictFromSession);

  const setPushConflictFrom409 = useCallback((state: PushConflictState) => {
    /* No-op when git-like is disabled — push/pull is gone, so 409s shouldn't
       surface as banners. The provider must stay mounted because consumers
       (StudioHeader, dashboard versions page) still call usePushConflictBanner(). */
    if (!FEATURE_GITLIKE) return;
    setConflict(state);
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      /* ignore */
    }
  }, []);

  const clearPushConflict = useCallback(() => {
    setConflict(null);
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const value = useMemo(
    () => ({ conflict, setPushConflictFrom409, clearPushConflict }),
    [conflict, setPushConflictFrom409, clearPushConflict]
  );

  return (
    <PushConflictBannerContext.Provider value={value}>{children}</PushConflictBannerContext.Provider>
  );
}

export function usePushConflictBanner(): PushConflictBannerContextValue {
  const ctx = useContext(PushConflictBannerContext);
  if (!ctx) {
    throw new Error('usePushConflictBanner must be used within PushConflictBannerProvider');
  }
  return ctx;
}
