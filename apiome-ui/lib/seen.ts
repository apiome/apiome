/**
 * Per-device "I have seen this" and other on/off flags (HIVE-11.5, #5601).
 *
 * The quiet pass replaces standing explainers with a callout that shows once and then lives
 * one click away (`DismissibleCallout`), and folds stat strips into a facts line whose
 * expanded state is remembered (`FactsLine`). Both remember a single boolean **per device**,
 * in `localStorage`:
 *
 * - `hive.seen.<id>` — the reader dismissed the callout `<id>` (written as `'1'`).
 * - `hive.<page>.stats` — the reader expanded the stats on `<page>` (`'1'`) or collapsed
 *   them again (`'0'`).
 *
 * Every read and write is **read-through safe**: a private window, blocked site data or a
 * full quota makes storage throw, and these helpers then behave as if nothing was ever
 * stored — the callout shows again, the stats start collapsed — instead of crashing the
 * page. Nothing here is account state; clearing site data resets it, by design.
 */

/** Prefix of every "seen" key. */
export const SEEN_PREFIX = 'hive.seen.';

/**
 * The `localStorage` key a "seen" flag lives under.
 *
 * @param id The thing that was seen, e.g. `catalog-explainer`.
 * @returns `hive.seen.<id>`.
 */
export function seenKey(id: string): string {
  return `${SEEN_PREFIX}${id}`;
}

/**
 * The `localStorage` key a page's "stats expanded" flag lives under.
 *
 * @param page The page, e.g. `catalog`.
 * @returns `hive.<page>.stats`.
 */
export function statsKey(page: string): string {
  return `hive.${page}.stats`;
}

/**
 * Reads an on/off flag.
 *
 * @param key The full storage key.
 * @returns `true` for `'1'`, `false` for `'0'`, `undefined` when unset, unrecognised, or
 *   storage is unavailable.
 */
export function readFlag(key: string): boolean | undefined {
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === '1') return true;
    if (raw === '0') return false;
    return undefined;
  } catch {
    return undefined;
  }
}

/**
 * Writes an on/off flag. Never throws.
 *
 * @param key The full storage key.
 * @param on The value to remember.
 * @returns `true` when it was stored, `false` when storage refused it.
 */
export function writeFlag(key: string, on: boolean): boolean {
  try {
    window.localStorage.setItem(key, on ? '1' : '0');
    return true;
  } catch {
    return false;
  }
}

/**
 * Whether the reader has dismissed `id` on this device.
 *
 * @param id The thing that was seen.
 * @returns `true` only when a dismissal is stored and readable.
 */
export function hasSeen(id: string): boolean {
  return readFlag(seenKey(id)) === true;
}

/**
 * Remembers that the reader dismissed `id` on this device. Never throws.
 *
 * @param id The thing that was seen.
 * @returns `true` when it was stored.
 */
export function markSeen(id: string): boolean {
  return writeFlag(seenKey(id), true);
}

/**
 * Forgets a dismissal, so the thing shows again. Never throws.
 *
 * @param id The thing that was seen.
 */
export function clearSeen(id: string): void {
  try {
    window.localStorage.removeItem(seenKey(id));
  } catch {
    // Nothing stored that we could reach — nothing to forget.
  }
}
