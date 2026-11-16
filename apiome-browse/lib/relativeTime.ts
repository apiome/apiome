/**
 * Short relative times for cards and headers ("just now", "5m ago", "3d ago", "2y ago").
 *
 * One implementation for every Browse surface, so a card, a project header and a search hit say
 * the same thing about the same timestamp.
 */

/**
 * Describe how long ago a timestamp was.
 *
 * @param value - An ISO string, a `Date`, or nothing.
 * @param now - The reference time in epoch milliseconds; injectable for tests.
 * @returns The short label, or `undefined` when the value is missing or not a valid date.
 */
export function relativeTime(
  value: string | Date | null | undefined,
  now: number = Date.now()
): string | undefined {
  if (!value) return undefined;
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return undefined;
  const seconds = Math.round((now - then) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.round(days / 30);
  if (months < 12) return `${months}mo ago`;
  return `${Math.round(months / 12)}y ago`;
}
