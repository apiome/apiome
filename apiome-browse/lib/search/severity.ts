/**
 * The `severity:` filter vocabulary of the catalog search (BDX-1.4).
 *
 * Classified changelog entries (CTG-3.2, `apiome.version_changelogs`) carry one of three stored
 * severities: `breaking`, `non-breaking`, `docs-only`. Visitors also think in the issue-tracker
 * words `warning` and `info`, so those (and a few spellings) resolve to the stored names. Anything
 * else resolves to null and is dropped — a typo never silently widens or empties the result set.
 *
 * Pure; shared by the query parser, the URL codec, the SQL builder and the rail.
 */

import type { Severity } from '../changelog/types';

/** The stored severities, worst first — the order the rail lists them in. */
export const CHANGE_SEVERITIES: readonly Severity[] = ['breaking', 'non-breaking', 'docs-only'];

/** Words a visitor may type after `severity:`, mapped to the stored severity. */
const SEVERITY_ALIASES: Readonly<Record<string, Severity>> = {
  breaking: 'breaking',
  break: 'breaking',
  major: 'breaking',
  error: 'breaking',
  nonbreaking: 'non-breaking',
  warning: 'non-breaking',
  warn: 'non-breaking',
  minor: 'non-breaking',
  docsonly: 'docs-only',
  docs: 'docs-only',
  doc: 'docs-only',
  info: 'docs-only',
  patch: 'docs-only',
};

/**
 * Resolve a `severity:` value or `severity=` URL token to a stored severity.
 *
 * @param raw The typed value (`breaking`, `warning`, `Docs-only`, …).
 * @returns The stored severity, or null when the value is not one the language knows.
 */
export function resolveChangeSeverity(raw: string | null | undefined): Severity | null {
  const key = (raw ?? '').trim().toLowerCase().replace(/[\s_-]+/g, '');
  return SEVERITY_ALIASES[key] ?? null;
}

/**
 * Rank bonus per severity for the `change` member: the gap between tiers (30) is larger than the
 * largest text score a change can add (25, see `sql.ts`), so within change hits severity always
 * orders first and text second.
 */
export const SEVERITY_RANK_BONUS: Readonly<Record<Severity, number>> = {
  breaking: 60,
  'non-breaking': 30,
  'docs-only': 0,
};
