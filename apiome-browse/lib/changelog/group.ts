/**
 * Pure grouping/presentation helpers for stored publish changelogs (CTG-3.2, #4476).
 *
 * Framework-free so the Changes tab's logic is unit-testable: entries fold into severity
 * sections (breaking first), each holding pathGroup groups in input order; the label/badge
 * helpers keep the severity vocabulary and pill styling in one tested place.
 */

import type { ChangelogEntry, Severity } from './types';

/** One pathGroup's entries within a severity section, in input order. */
export interface PathGroupGroup {
  pathGroup: string;
  entries: ChangelogEntry[];
}

/** One severity's grouped entries. */
export interface SeveritySection {
  severity: Severity;
  groups: PathGroupGroup[];
  /** Total entries across the section's groups. */
  count: number;
}

/** Severity display order: worst first. */
const SEVERITY_ORDER: Severity[] = ['breaking', 'non-breaking', 'docs-only'];

const SEVERITY_LABELS: Record<Severity, string> = {
  breaking: 'Breaking',
  'non-breaking': 'Non-breaking',
  'docs-only': 'Docs-only',
};

/**
 * Rounded-pill color classes per severity (light + dark), matching the status-pill style used on
 * the version page: rose = breaking, amber = non-breaking, sky = docs-only.
 */
const SEVERITY_BADGE_CLASSES: Record<Severity, string> = {
  breaking: 'bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300',
  'non-breaking': 'bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300',
  'docs-only': 'bg-sky-50 text-sky-700 dark:bg-sky-500/10 dark:text-sky-300',
};

/** Dot color per severity, for the `h-1.5 w-1.5 rounded-full` marker inside a pill. */
const SEVERITY_DOT_CLASSES: Record<Severity, string> = {
  breaking: 'bg-rose-500',
  'non-breaking': 'bg-amber-500',
  'docs-only': 'bg-sky-500',
};

/** Coerce an unknown severity string to a known one (unknown values degrade to `docs-only`). */
function normalizeSeverity(severity: string): Severity {
  return (SEVERITY_ORDER as string[]).includes(severity) ? (severity as Severity) : 'docs-only';
}

/**
 * Fold changelog entries into ordered severity sections (breaking → non-breaking → docs-only),
 * each containing pathGroup groups that preserve the entries' input order. Severities outside
 * the known vocabulary fold into the docs-only section; empty sections are omitted.
 */
export function groupChangelogEntries(entries: ChangelogEntry[]): SeveritySection[] {
  const bySeverity = new Map<Severity, Map<string, ChangelogEntry[]>>();

  for (const entry of entries) {
    const severity = normalizeSeverity(entry.severity);
    let groups = bySeverity.get(severity);
    if (!groups) {
      groups = new Map();
      bySeverity.set(severity, groups);
    }
    const group = groups.get(entry.pathGroup);
    if (group) {
      group.push(entry);
    } else {
      groups.set(entry.pathGroup, [entry]);
    }
  }

  const sections: SeveritySection[] = [];
  for (const severity of SEVERITY_ORDER) {
    const groups = bySeverity.get(severity);
    if (!groups) continue;
    const groupList: PathGroupGroup[] = [];
    let count = 0;
    for (const [pathGroup, groupEntries] of groups) {
      groupList.push({ pathGroup, entries: groupEntries });
      count += groupEntries.length;
    }
    sections.push({ severity, groups: groupList, count });
  }
  return sections;
}

/** Human label for a severity ('Breaking' / 'Non-breaking' / 'Docs-only'). */
export function severityLabel(severity: string): string {
  return SEVERITY_LABELS[normalizeSeverity(severity)];
}

/** Pill color classes (light + dark) for a severity badge. */
export function severityBadgeClasses(severity: string): string {
  return SEVERITY_BADGE_CLASSES[normalizeSeverity(severity)];
}

/** Dot color class for the marker inside a severity pill. */
export function severityDotClasses(severity: string): string {
  return SEVERITY_DOT_CLASSES[normalizeSeverity(severity)];
}
