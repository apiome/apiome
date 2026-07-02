'use client';

import { useCallback, useState } from 'react';
import type { FormViewMode } from './FormNavigation';

/**
 * Persist a dialog's view mode preference in sessionStorage so power users
 * don't get bounced back to Guided every time they reopen a dialog.
 *
 * `storageKey` should be unique per dialog (e.g. 'class-edit-view-mode').
 *
 * This hook is meant to be used inside client-only components ("use client"),
 * so we can read sessionStorage eagerly in the lazy initializer without
 * causing a hydration mismatch with SSR.
 */
export function useFormViewMode(storageKey: string, initial: FormViewMode = 'guided') {
  const [mode, setModeState] = useState<FormViewMode>(() => {
    if (typeof window === 'undefined') return initial;
    try {
      const saved = window.sessionStorage.getItem(storageKey);
      if (saved === 'guided' || saved === 'advanced') return saved;
    } catch {
      /* sessionStorage may be unavailable; fall through to initial */
    }
    return initial;
  });

  const setMode = useCallback(
    (next: FormViewMode) => {
      setModeState(next);
      if (typeof window !== 'undefined') {
        try {
          window.sessionStorage.setItem(storageKey, next);
        } catch {
          /* ignore */
        }
      }
    },
    [storageKey],
  );

  return [mode, setMode] as const;
}
