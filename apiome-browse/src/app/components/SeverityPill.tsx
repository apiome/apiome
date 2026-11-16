import {
  severityBadgeClasses,
  severityDotClasses,
} from '../../../lib/changelog/group';
import type { Severity } from '../../../lib/changelog/types';

/**
 * Small severity pill (dot + label) in the rounded-full status-pill style. Shared by the version
 * Changes tab and the project changelog page so both read the same severity vocabulary.
 *
 * @param severity - The change severity (unknown values render as docs-only).
 * @param label - The visible text (e.g. `Breaking` or `2 Breaking`).
 */
export function SeverityPill({ severity, label }: { severity: Severity | string; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${severityBadgeClasses(severity)}`}
    >
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${severityDotClasses(severity)}`}></span>
      {label}
    </span>
  );
}

/**
 * Dashed empty-state note used for the pending / initial / failed changelog states — a version
 * never renders as an empty section.
 *
 * @param text - The note.
 */
export function ChangesNote({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-dashed border-zinc-300 bg-white/40 p-10 text-center dark:border-zinc-700 dark:bg-zinc-900/40">
      <p className="text-sm text-zinc-500 dark:text-zinc-400">{text}</p>
    </div>
  );
}
