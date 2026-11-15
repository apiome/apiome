/**
 * The in-tab channel that keeps every inbox reader in step (HIVE-12.3, #5610).
 *
 * {@link useNotifications} has two readers on screen at once — the rail bell and the
 * notification centre at `/ade/dashboard/notifications` — and each holds its own copy of the
 * unread tallies. Without this, marking a row read on the page clears *its* count while the
 * bell keeps the old one until its next minute-long poll, and the two surfaces disagree
 * about the one number the badge exists to show.
 *
 * A reader that writes (a mark-read whose POST succeeded) calls
 * {@link announceNotificationsRead}; every *other* subscribed reader re-reads. The writer is
 * skipped because it has already folded the endpoint's answer in, and a second read of the
 * same thing is a request for nothing.
 *
 * Module-level and in-tab only, the same shape as `shortcutSheetBus.ts`: a notification
 * marked read in another tab still reaches this one through the poll and the
 * `visibilitychange` read.
 */

/** A subscribed reader: its identity, and what to do when somebody else writes. */
type Listener = (source: symbol) => void;

/** Every mounted reader. */
const listeners = new Set<Listener>();

/**
 * Tell every other reader that the inbox changed.
 *
 * @param source The writer's token (from its own {@link subscribeNotificationsRead} call),
 *               so it is not told about its own write.
 */
export function announceNotificationsRead(source: symbol): void {
  for (const listener of [...listeners]) listener(source);
}

/**
 * Hear about writes made by other readers.
 *
 * @param token This reader's identity; writes announced with the same token are skipped.
 * @param onChange Called when a different reader announces a write.
 * @returns The unsubscribe function, for the effect's cleanup.
 */
export function subscribeNotificationsRead(token: symbol, onChange: () => void): () => void {
  const listener: Listener = (source) => {
    if (source !== token) onChange();
  };
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
