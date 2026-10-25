'use client';

import { useCallback, useSyncExternalStore } from 'react';

/**
 * A localStorage-backed preference read through `useSyncExternalStore`, so the server render and
 * the first client render agree (both see the default) and the stored value arrives without a
 * set-state-in-effect. Writes notify every subscriber on this page.
 */

type Listener = () => void;
const listeners = new Set<Listener>();
const snapshots = new Map<string, { raw: string | null; value: unknown }>();

function notify() {
  for (const l of listeners) l();
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  const onStorage = () => listener();
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}

/** Read one key, parsing with `parse`; the result is cached per raw string so snapshots stay stable. */
function readKey<T>(key: string, parse: (raw: string | null) => T): T {
  let raw: string | null = null;
  try {
    raw = window.localStorage.getItem(key);
  } catch {
    raw = null;
  }
  const cached = snapshots.get(key);
  if (cached && cached.raw === raw) return cached.value as T;
  const value = parse(raw);
  snapshots.set(key, { raw, value });
  return value;
}

/**
 * @param key The storage key.
 * @param fallback The value before hydration and when storage is empty or unavailable.
 * @param parse How to read the stored string; defaults to JSON.
 * @param serialize How to write a value; defaults to JSON.
 */
export function useStoredPref<T>(
  key: string,
  fallback: T,
  parse: (raw: string) => T = (raw) => JSON.parse(raw) as T,
  serialize: (value: T) => string = (value) => JSON.stringify(value)
): [T, (next: T) => void] {
  const getSnapshot = useCallback(
    () =>
      readKey(key, (raw) => {
        if (raw == null) return fallback;
        try {
          return parse(raw);
        } catch {
          return fallback;
        }
      }),
    [key, fallback, parse]
  );
  const value = useSyncExternalStore(subscribe, getSnapshot, () => fallback);
  const set = useCallback(
    (next: T) => {
      try {
        window.localStorage.setItem(key, serialize(next));
      } catch {
        /* storage unavailable: the in-memory snapshot still updates below */
      }
      snapshots.set(key, { raw: (() => {
        try {
          return window.localStorage.getItem(key);
        } catch {
          return null;
        }
      })(), value: next });
      notify();
    },
    [key, serialize]
  );
  return [value, set];
}

/** Tell every `useStoredPref` on the page that a key changed outside the hook (e.g. a clear). */
export function notifyStoredPrefChanged(): void {
  notify();
}
