/**
 * Browser-level helpers behind {@link ./useUnsavedChangesGuard} (SUX-2.6, apiome#6753).
 *
 * Kept apart from the hook so the two decisions that are easy to get wrong — *is this click a
 * same-tab, in-app navigation?* and *is the current history entry our own sentinel?* — are plain
 * functions that can be pinned by unit tests without rendering anything.
 *
 * ### Why a sentinel entry
 *
 * The App Router has no "before route change" event, and a `popstate` arrives *after* the
 * browser has already moved. To be able to ask before Back leaves a dirty screen, the guard
 * pushes a duplicate of the current entry (same URL, same Next.js state, plus
 * {@link UNSAVED_GUARD_HISTORY_KEY}). Back then lands on the original copy of the same page: the
 * guard swallows that `popstate` (nothing visible changed), asks, and either steps forward onto
 * the sentinel again (Cancel) or goes one more step back for real (Discard / Save).
 */

/** Key the guard adds to `history.state` to mark the sentinel entry it pushed. */
export const UNSAVED_GUARD_HISTORY_KEY = '__apiomeUnsavedGuard';

/** Attribute that opts one link out of the guard (`data-unsaved-guard="ignore"`). */
export const UNSAVED_GUARD_IGNORE_ATTRIBUTE = 'data-unsaved-guard';

/**
 * Find the in-app destination a click would navigate to, or `null` when the guard must let it be.
 *
 * Only a plain primary-button click on a same-origin `<a href>` that opens in this tab and leaves
 * the current path or query counts. Modifier clicks (new tab / window / download), `target`
 * other than `_self`, `download`, other origins, hash-only jumps, an event something else already
 * cancelled, and links marked {@link UNSAVED_GUARD_IGNORE_ATTRIBUTE}`="ignore"` are all left alone,
 * because none of them throw the current screen away.
 *
 * @param event The click, as seen by a capture-phase `document` listener.
 * @param location The current location (injectable for tests). Defaults to `window.location`.
 * @returns The destination as `pathname + search + hash` (ready for `router.push`), or `null`.
 */
export function inAppNavigationTarget(
  event: MouseEvent,
  location: Pick<Location, 'href' | 'origin' | 'pathname' | 'search'> = window.location
): string | null {
  if (event.defaultPrevented) return null;
  if (event.button !== 0) return null;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;

  const target = event.target;
  if (!(target instanceof Element)) return null;
  const anchor = target.closest('a[href]');
  if (!(anchor instanceof HTMLAnchorElement)) return null;
  if (anchor.getAttribute(UNSAVED_GUARD_IGNORE_ATTRIBUTE) === 'ignore') return null;
  if (anchor.hasAttribute('download')) return null;
  const linkTarget = anchor.getAttribute('target');
  if (linkTarget && linkTarget !== '_self') return null;

  let url: URL;
  try {
    url = new URL(anchor.getAttribute('href') ?? '', location.href);
  } catch {
    return null;
  }
  if (url.origin !== location.origin) return null;
  if (url.pathname === location.pathname && url.search === location.search) return null;
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * Whether a history state object is the sentinel the guard pushed.
 *
 * @param state Any `history.state` value.
 * @returns True when the entry carries {@link UNSAVED_GUARD_HISTORY_KEY}.
 */
export function isUnsavedGuardSentinel(state: unknown): boolean {
  return (
    typeof state === 'object' &&
    state !== null &&
    (state as Record<string, unknown>)[UNSAVED_GUARD_HISTORY_KEY] === true
  );
}

/**
 * Push the sentinel entry, unless the current entry already is one.
 *
 * The existing state is copied (Next.js keeps its router tree there), so a later traversal onto
 * either copy restores the same page.
 */
export function pushUnsavedGuardSentinel(): void {
  if (isUnsavedGuardSentinel(window.history.state)) return;
  const base =
    typeof window.history.state === 'object' && window.history.state !== null
      ? (window.history.state as Record<string, unknown>)
      : {};
  window.history.pushState(
    { ...base, [UNSAVED_GUARD_HISTORY_KEY]: true },
    '',
    window.location.href
  );
}

/**
 * Traverse history by `delta` while hiding the resulting `popstate` from every other listener.
 *
 * Used for the guard's own moves between the original entry and the sentinel, which show the
 * same page: the App Router and any scope listener must not treat them as a navigation.
 *
 * @param delta Passed to `history.go`.
 * @returns Resolves once the traversal's `popstate` has been swallowed (or after a short
 *   fallback, for an environment that never fires one).
 */
export function silentHistoryGo(delta: number): Promise<void> {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      window.removeEventListener('popstate', swallow, true);
      resolve();
    };
    const swallow = (event: PopStateEvent) => {
      event.stopImmediatePropagation();
      finish();
    };
    window.addEventListener('popstate', swallow, true);
    window.history.go(delta);
    window.setTimeout(finish, 500);
  });
}

/**
 * Drop the sentinel when it is the current entry, so a clean screen leaves no duplicate behind.
 *
 * @returns Resolves when the history is back on the original entry (immediately when there was
 *   no sentinel to remove).
 */
export function removeUnsavedGuardSentinel(): Promise<void> {
  if (!isUnsavedGuardSentinel(window.history.state)) return Promise.resolve();
  return silentHistoryGo(-1);
}
