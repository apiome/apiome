"use client";

import { useSyncExternalStore } from "react";

/**
 * Subscribes to a CSS media query without tripping the set-state-in-effect
 * lint rule. Returns `false` during SSR / first hydration, then the real match.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", cb);
      return () => mql.removeEventListener("change", cb);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}
