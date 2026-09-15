/**
 * The stylesheet half of the review page (COL-2.2, #4518).
 *
 * `review-page.test.tsx` renders the page and pins its behaviour; jsdom compiles no stylesheet, so
 * this suite reads `globals.css` the way `discussion-css.test.ts` does and pins what the page leans
 * on:
 *
 *   1. **Every class the components use is declared, and the section declares nothing else.**
 *   2. **The skin is tokens only** — no hex, no `rgb()`, and every custom property it reads exists.
 *   3. **Nothing is frozen in pixels** beyond hairlines, so density and font scale reach the page.
 *   4. **Nothing scrolls sideways**: every flex or grid holder of a name, note or pointer has a zero
 *      minimum, those texts break anywhere, and the two columns stack on a narrow screen.
 *   5. **The decision bar stays in reach**: sticky at the foot of the scroll container.
 *   6. **Text is legible**: quiet text is `--fg-muted`, never `--fg-subtle`; nothing fades.
 *   7. **The section is bounded at the next banner**, so these assertions never become claims about
 *      a later ticket's rules.
 */

import * as fs from 'fs';
import * as path from 'path';

import { findUnfencedHex, parseDeclarations, readGlobalsCss, topLevelRules, type CssRule } from './helpers/design-tokens';

const css = readGlobalsCss();
const rules = topLevelRules(css);

/** The review block, from its banner to the next banner (or the end of the file). */
const SECTION = (() => {
  const start = css.indexOf('REVIEW PAGE  (COL-2.2, #4518)');
  if (start < 0) throw new Error('globals.css has no review-page section');
  const bannerStart = css.lastIndexOf('/* =', start);
  const next = css.indexOf('/* =', start);
  return css.slice(bannerStart < 0 ? start : bannerStart, next < 0 ? css.length : next);
})();

/** The same block with its comments removed. */
const SECTION_CODE = SECTION.replace(/\/\*[\s\S]*?\*\//g, '');

/** The review components, whose `className`s the section must cover. */
const COMPONENT_DIR = path.join(__dirname, '..', 'src', 'app', 'components', 'ade', 'reviews');

/**
 * Look one of this ticket's rules up.
 *
 * @param prelude - The rule's selector.
 * @returns The rule.
 */
function reviewRule(prelude: string): CssRule {
  const rule = rules.find((candidate) => candidate.prelude.replace(/\s+/g, ' ').trim() === prelude);
  if (!rule) throw new Error(`globals.css declares no rule \`${prelude}\``);
  return rule;
}

/**
 * Read one declaration out of one of this ticket's rules.
 *
 * @param prelude - The rule's selector.
 * @param property - The property.
 * @returns Its value.
 */
function declaration(prelude: string, property: string): string | undefined {
  return parseDeclarations(reviewRule(prelude).body).get(property);
}

/** Every `rvw-` class the review components name. */
function componentClasses(): string[] {
  const names = new Set<string>();
  for (const file of fs.readdirSync(COMPONENT_DIR)) {
    const source = fs.readFileSync(path.join(COMPONENT_DIR, file), 'utf8');
    for (const match of source.matchAll(/["'` ](rvw[a-z0-9_-]*)/g)) names.add(match[1]);
  }
  return [...names].sort();
}

/** Every `rvw-` class the section declares. */
function sectionClasses(): string[] {
  return [...new Set([...SECTION_CODE.matchAll(/\.(rvw[a-z0-9_-]*)/g)].map((match) => match[1]))].sort();
}

describe('the review-page section of globals.css', () => {
  it('declares every class the review components use, and nothing else', () => {
    expect(sectionClasses()).toEqual(componentClasses());
  });

  it('is bounded: the section holds no second banner', () => {
    expect(SECTION.match(/\/\* =/g)).toHaveLength(1);
  });

  it('is token-only: no hex, no rgb(), no bare named colour', () => {
    expect(findUnfencedHex(SECTION_CODE)).toEqual([]);
    expect(SECTION_CODE).not.toMatch(/rgba?\(|hsla?\(/);
    expect(SECTION_CODE).not.toMatch(/:\s*(white|black|red|green|blue|gray|grey)\s*;/);
  });

  it('reads only custom properties the stylesheet declares', () => {
    const used = new Set([...SECTION_CODE.matchAll(/var\(--([a-z0-9-]+)/g)].map((match) => match[1]));
    const missing = [...used].filter((name) => !css.includes(`--${name}:`));
    expect(missing).toEqual([]);
  });

  it('freezes nothing in pixels beyond hairlines', () => {
    const pixels = [...SECTION_CODE.matchAll(/(-?\d*\.?\d+)px/g)].map((match) => Number(match[1]));
    expect(pixels.filter((value) => Math.abs(value) > 1)).toEqual([]);
  });

  it('never uses --fg-subtle and never fades', () => {
    expect(SECTION_CODE).not.toContain('--fg-subtle');
    expect(SECTION_CODE).not.toMatch(/opacity\s*:/);
  });

  it('gives every flex and grid holder a zero minimum where long text lives', () => {
    for (const prelude of [
      '.rvw',
      '.rvw-main',
      '.rvw-aside',
      '.rvw-card',
      '.rvw-person',
      '.rvw-person__head',
      '.rvw-changes',
      '.rvw-changes__head',
      '.rvw-severity',
      '.rvw-group',
      '.rvw-change',
      '.rvw-spec',
      '.rvw-decision',
      '.rvw-decision__foot',
      '.rvw-decision__status',
    ]) {
      expect({ prelude, min: declaration(prelude, 'min-inline-size') }).toEqual({ prelude, min: '0' });
    }
  });

  it('breaks names, notes and pointers anywhere', () => {
    for (const prelude of [
      '.rvw-person__name',
      '.rvw-person__note',
      '.rvw-changes__compare',
      '.rvw-group__name',
      '.rvw-change__summary',
      '.rvw-change__pointer',
      '.rvw-decision__message',
      '.rvw-decision__quote',
    ]) {
      expect({ prelude, wrap: declaration(prelude, 'overflow-wrap') }).toEqual({ prelude, wrap: 'anywhere' });
    }
  });

  it('lays the aside beside the main column and stacks it on a narrow screen', () => {
    expect(declaration('.rvw', 'grid-template-columns')).toBe('minmax(0, 1fr) minmax(0, 21.25rem)');
    expect(SECTION_CODE).toMatch(/@media \(max-width: 68rem\)\s*\{\s*\.rvw\s*\{\s*grid-template-columns: minmax\(0, 1fr\);/);
  });

  it('keeps the decision bar sticky at the foot of the scroll container', () => {
    expect(declaration('.rvw-decision', 'position')).toBe('sticky');
    expect(declaration('.rvw-decision', 'inset-block-end')).toBe('var(--space-4)');
    expect(declaration('.rvw-decision', 'background')).toBe('var(--bg-surface)');
  });

  it('gives the spec viewer the definite box Monaco needs', () => {
    expect(declaration('.rvw-spec__viewer', 'block-size')).toBe('min(70vh, 48rem)');
  });
});
