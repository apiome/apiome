/**
 * The stylesheet half of the merge request surfaces (COL-4.3, #4527).
 *
 * jsdom compiles no stylesheet, so — as `review-page-css.test.ts` does — this reads `globals.css`
 * and pins what the Merge requests tab, its dialogs and the merge request page lean on:
 *
 *   1. **Every `mrq-` class the components use is declared, and the section declares nothing else.**
 *   2. **The skin is tokens only**, reading only custom properties the stylesheet declares.
 *   3. **Nothing is frozen in pixels** beyond hairlines.
 *   4. **Nothing scrolls sideways**: holders of names, titles and paths have a zero minimum and
 *      those texts break anywhere.
 *   5. **Quiet text is `--fg-muted`**, never `--fg-subtle`; nothing fades.
 */

import * as fs from 'fs';
import * as path from 'path';

import { findUnfencedHex, parseDeclarations, readGlobalsCss, topLevelRules } from './helpers/design-tokens';

const css = readGlobalsCss();
const rules = topLevelRules(css);

/** The merge request block, from its banner to the next banner (or the end of the file). */
const SECTION = (() => {
  const start = css.indexOf('Merge requests — COL-4.3 (#4527)');
  if (start < 0) throw new Error('globals.css has no merge-request section');
  const bannerStart = css.lastIndexOf('/* =', start);
  const next = css.indexOf('/* =', start);
  return css.slice(bannerStart, next < 0 ? css.length : next);
})();

/** The same block with its comments removed. */
const SECTION_CODE = SECTION.replace(/\/\*[\s\S]*?\*\//g, '');

/** The merge request components, whose `className`s the section must cover. */
const COMPONENT_DIR = path.join(__dirname, '..', 'src', 'app', 'components', 'ade', 'merge-requests');

/** Every `mrq-` class the components name. */
function componentClasses(): string[] {
  const names = new Set<string>();
  for (const file of fs.readdirSync(COMPONENT_DIR)) {
    const source = fs.readFileSync(path.join(COMPONENT_DIR, file), 'utf8');
    for (const match of source.matchAll(/["'` ](mrq[a-z0-9_-]*)/g)) names.add(match[1]);
  }
  return [...names].sort();
}

/** Every `mrq-` class the section declares. */
function sectionClasses(): string[] {
  return [...new Set([...SECTION_CODE.matchAll(/\.(mrq[a-z0-9_-]*)/g)].map((match) => match[1]))].sort();
}

/**
 * One declaration of one rule.
 *
 * @param prelude - The rule's selector.
 * @param property - The property.
 * @returns Its value.
 */
function declaration(prelude: string, property: string): string | undefined {
  const rule = rules.find((candidate) => candidate.prelude.replace(/\s+/g, ' ').trim() === prelude);
  if (!rule) throw new Error(`globals.css declares no rule \`${prelude}\``);
  return parseDeclarations(rule.body).get(property);
}

describe('the merge-request section of globals.css', () => {
  it('declares every class the merge request components use, and nothing else', () => {
    expect(sectionClasses()).toEqual(componentClasses());
  });

  it('is token-only and reads only declared custom properties', () => {
    expect(findUnfencedHex(SECTION_CODE)).toEqual([]);
    expect(SECTION_CODE).not.toMatch(/rgba?\(|hsla?\(/);
    const used = new Set([...SECTION_CODE.matchAll(/var\(--([a-z0-9-]+)/g)].map((match) => match[1]));
    expect([...used].filter((name) => !css.includes(`--${name}:`))).toEqual([]);
  });

  it('freezes nothing in pixels beyond hairlines', () => {
    const pixels = [...SECTION_CODE.matchAll(/(-?\d*\.?\d+)px/g)].map((match) => Number(match[1]));
    expect(pixels.filter((value) => Math.abs(value) > 1)).toEqual([]);
  });

  it('never scrolls sideways on a long branch name, title or path', () => {
    for (const prelude of ['.mrq-panel', '.mrq-row', '.mrq-head', '.mrq-conflicts, .mrq-review']) {
      expect(declaration(prelude, 'min-inline-size')).toBe('0');
    }
    for (const prelude of ['.mrq-row__title', '.mrq-row__meta', '.mrq-description', '.mrq-blocker']) {
      expect(declaration(prelude, 'overflow-wrap')).toBe('anywhere');
    }
  });

  it('never uses --fg-subtle and never fades', () => {
    expect(SECTION_CODE).not.toContain('--fg-subtle');
    expect(SECTION_CODE).not.toMatch(/opacity\s*:/);
  });
});
