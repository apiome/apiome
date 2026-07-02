/**
 * Error indicator helpers for Import Execution Panel (#731).
 * Red for failures with details. Used by ImportExecutionPanel.
 */

export type LogLevel = 'info' | 'warn' | 'error';

export interface ImportEventLike {
  id: string;
  ts: number;
  level: LogLevel;
  code: string;
  message: string;
  context?: unknown;
}

/** Event codes that represent intentionally skipped items (#732). */
const SKIPPED_EVENT_CODES = new Set(['SKIP_PROPERTY', 'SKIP_CHILDREN']);

/** Whether this event represents an intentionally skipped item (gray indicator). */
export function isSkippedEvent(ev: ImportEventLike): boolean {
  return SKIPPED_EVENT_CODES.has(ev.code);
}

/** Filter events to error level only (for Failures section). */
export function getErrorEvents(events: ImportEventLike[]): ImportEventLike[] {
  return events.filter((ev) => ev.level === 'error');
}

/** Format event context for display (string as-is, object as JSON). */
export function formatEventContext(context: unknown): string {
  if (context == null) return '';
  return typeof context === 'string' ? context : JSON.stringify(context, null, 2);
}

/** Tailwind classes for Live Progress row (error = red, warn = amber, skipped = gray, info = default). Accepts event or level for backward compatibility. */
export function getLiveProgressRowClasses(evOrLevel: ImportEventLike | LogLevel): string {
  const ev: ImportEventLike = typeof evOrLevel === 'string'
    ? { id: '', ts: 0, level: evOrLevel, code: '', message: '' }
    : evOrLevel;
  const base = 'flex items-start gap-2 p-2 rounded border ';
  if (isSkippedEvent(ev)) return base + 'border-gray-200 dark:border-gray-600 bg-gray-100 dark:bg-gray-800/60';
  if (ev.level === 'error') return base + 'border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-950/30';
  if (ev.level === 'warn') return base + 'border-yellow-200 dark:border-yellow-800 bg-amber-50/50 dark:bg-amber-950/20';
  return base + 'border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40';
}

/** Tailwind classes for Import Log line (error = red, warn = amber, skipped = gray, info = default). Accepts event or level for backward compatibility. */
export function getImportLogLineClasses(evOrLevel: ImportEventLike | LogLevel): string {
  const ev: ImportEventLike = typeof evOrLevel === 'string'
    ? { id: '', ts: 0, level: evOrLevel, code: '', message: '' }
    : evOrLevel;
  const base = 'text-xs font-mono rounded px-2 py-1 -mx-2 ';
  if (isSkippedEvent(ev)) return base + 'bg-gray-100 dark:bg-gray-800/60 text-gray-500 dark:text-gray-400';
  if (ev.level === 'error') return base + 'bg-red-100 dark:bg-red-950/50 border-l-2 border-red-500 dark:border-red-500';
  if (ev.level === 'warn') return base + 'bg-amber-50 dark:bg-amber-950/30';
  return base.trim();
}

/** Whether the Failures section should be shown (has any error events). */
export function shouldShowFailuresSection(events: ImportEventLike[]): boolean {
  return getErrorEvents(events).length > 0;
}
