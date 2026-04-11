'use client';

import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

const STORAGE_KEY = 'objectified:push-409';

export type PushConflictCurrentHead = {
  revisionId?: string;
  versionId?: string;
  shortMessage?: string | null;
  createdAt?: string | null;
};

export type PushConflictState = {
  projectId: string;
  message: string;
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
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PushConflictState;
    if (parsed?.projectId && typeof parsed.message === 'string') return parsed;
  } catch {
    /* ignore */
  }
  return null;
}

export function PushConflictBannerProvider({ children }: { children: ReactNode }) {
  const [conflict, setConflict] = useState<PushConflictState | null>(readConflictFromSession);

  const setPushConflictFrom409 = useCallback((state: PushConflictState) => {
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
