/**
 * Compact relative time for branch status popover (#2726).
 */

export function formatShortRelativeTime(iso?: string | null): string {
  if (!iso?.trim()) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
  const diffSec = Math.round((d.getTime() - Date.now()) / 1000);
  const absSec = Math.abs(diffSec);
  if (absSec < 60) return rtf.format(diffSec, 'second');
  const diffMin = Math.round(diffSec / 60);
  const absMin = Math.abs(diffMin);
  if (absMin < 60) return rtf.format(diffMin, 'minute');
  const diffHr = Math.round(diffSec / 3600);
  const absHr = Math.abs(diffHr);
  if (absHr < 24) return rtf.format(diffHr, 'hour');
  const diffDay = Math.round(diffSec / 86400);
  return rtf.format(diffDay, 'day');
}
