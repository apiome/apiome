/**
 * Static reader for the honey gate (HIVE-13.1, #5614).
 *
 * DESIGN.md §2 spends honey on brand ornament only — the mark, the new / starred / pinned /
 * preview markers, the first-run checklist, empty-state art, the theme grid, the active rail
 * marker and the HEAD node — and says it is *never a feature-flag or filter colour*. The
 * quiet pass found it had leaked anyway (a honey saved-search pill on MCP servers, an
 * always-on honey `gitlike` flag in Versions), because nothing stopped the next one.
 *
 * This module finds every honey reference in the package's source, so
 * `tests/hive-design-tokens.test.ts` can hold each one against an allow-list:
 *
 *   • in a `.ts` / `.tsx` / `.css` file, the unit is the **file** — a component either is one
 *     of the brand surfaces or it is not;
 *   • in `src/app/globals.css`, which hosts every screen's rules, the unit is the **top-level
 *     rule** (by prelude), so the stylesheet cannot become a loophole.
 *
 * Comments are ignored in both, so prose that names a token ("not the honey flag") never
 * counts as a use of it.
 */

import { readFileSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { stripCssComments, topLevelRules } from './design-tokens';
import { sourceFiles } from './source-files';

/** The package root (`apiome-ui/`). */
export const PACKAGE_ROOT = join(__dirname, '..', '..');

/** The directories whose source the gate reads, relative to {@link PACKAGE_ROOT}. */
export const HONEY_SOURCE_DIRS = ['src', 'lib'];

/** The stylesheet whose rules are gated one by one rather than as a file. */
export const GLOBALS_CSS = 'src/app/globals.css';

/** Source files the gate reads: TypeScript and stylesheets. */
const GATED_EXTENSIONS = /\.(ts|tsx|css)$/;

/**
 * One honey reference: a custom property (`--honey`, `--honey-soft`, `--color-honey-fg`,
 * `--brand-honey`, `--gradient-honey`) or a Tailwind utility built on one (`bg-honey`,
 * `text-honey-fg`, `border-honey`, …).
 *
 * The look-behind refuses a name glued to a word or a hyphen, so a BEM modifier class such as
 * `auth-icon--honey` or a `data-tone="honey"` value is not a token use — what it draws is
 * decided by the rule that styles it, and that rule is gated in its own right.
 */
const HONEY_USAGE =
  /(?<![\w-])(?:--(?:color-)?(?:brand-)?honey[\w-]*|--gradient-honey[\w-]*|(?:bg|text|border|ring|fill|stroke|outline|shadow|from|via|to|decoration|caret|accent)-honey[\w-]*)/g;

/**
 * Remove `/* … *\/` blocks and whole-line `//` comments from TypeScript or CSS source.
 *
 * Only whole-line `//` comments are stripped, so a URL inside a string survives.
 *
 * @param source File text.
 * @returns The text without comments.
 */
export function stripComments(source: string): string {
  return stripCssComments(source).replace(/^\s*\/\/.*$/gm, '');
}

/**
 * Every distinct honey reference in a piece of source, comments excluded.
 *
 * @param source File text, or a rule body.
 * @returns The distinct references, in first-seen order (empty when there are none).
 */
export function findHoneyUsages(source: string): string[] {
  return [...new Set(stripComments(source).match(HONEY_USAGE) ?? [])];
}

/**
 * The top-level rules of a stylesheet that spend honey.
 *
 * @param css Stylesheet source.
 * @returns Each offending rule's prelude (whitespace collapsed) mapped to its references.
 */
export function honeyRules(css: string): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const rule of topLevelRules(css)) {
    const usages = findHoneyUsages(rule.body);
    if (usages.length > 0) found.set(rule.prelude, usages);
  }
  return found;
}

/**
 * The package's source files that spend honey, other than {@link GLOBALS_CSS}.
 *
 * @param root Package root. Defaults to {@link PACKAGE_ROOT}.
 * @returns Each offending file's POSIX path relative to `root`, mapped to its references.
 */
export function honeyFiles(root: string = PACKAGE_ROOT): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const dir of HONEY_SOURCE_DIRS) {
    for (const path of sourceFiles(join(root, dir), GATED_EXTENSIONS)) {
      const rel = relative(root, path).split(sep).join('/');
      if (rel === GLOBALS_CSS) continue;
      const usages = findHoneyUsages(readFileSync(path, 'utf8'));
      if (usages.length > 0) found.set(rel, usages);
    }
  }
  return found;
}

/**
 * The entries of `found` that no allow-list names.
 *
 * @param found What the scan found — file paths or rule preludes, to their references.
 * @param allowLists One or more allow-lists, keyed the same way.
 * @returns `"<key>: <references>"` for every unlisted entry, ready for a readable `toEqual([])`.
 */
export function unlistedHoney(
  found: Map<string, string[]>,
  ...allowLists: Readonly<Record<string, string>>[]
): string[] {
  return [...found.entries()]
    .filter(([key]) => !allowLists.some((list) => key in list))
    .map(([key, usages]) => `${key}: ${usages.join(' ')}`);
}

/**
 * The allow-list entries the scan no longer finds — stale, and to be deleted.
 *
 * Holding this at `[]` is what makes the pending list a ratchet: an exception that has been
 * fixed has to leave the list in the same change, so the list can only shrink.
 *
 * @param found What the scan found.
 * @param allowList One allow-list.
 * @returns The keys of `allowList` that `found` does not contain.
 */
export function staleHoneyEntries(
  found: Map<string, string[]>,
  allowList: Readonly<Record<string, string>>
): string[] {
  return Object.keys(allowList).filter((key) => !found.has(key));
}
