/**
 * The stylesheet half of the review status surfaces (COL-2.4, #4520).
 *
 * jsdom compiles no stylesheet, so `review-status-surfaces.test.tsx` cannot see what the pill
 * actually looks like. This suite reads `globals.css` the way `review-page-css.test.ts` does and
 * pins what the pill leans on:
 *
 *   1. **Every class the two components use is declared, and the section declares nothing else.**
 *   2. **The skin is tokens only** — no hex, no `rgb()`, no bare named colour.
 *   3. **Nothing is frozen in pixels** beyond the focus hairline, so density and font scale reach
 *      the pill.
 *   4. **Nothing scrolls sideways**: both holders carry a zero minimum, and the dialog's link
 *      breaks anywhere.
 *   5. **The pill is reachable**: it is a link, so it keeps the app's focus ring, and it is not
 *      underlined into looking like body copy.
 *   6. **The section is bounded at the next banner**, so these assertions never become claims
 *      about a later ticket's rules.
 */

import * as fs from 'fs';
import * as path from 'path';

import { findUnfencedHex, parseDeclarations, readGlobalsCss, topLevelRules, type CssRule } from './helpers/design-tokens';

const css = readGlobalsCss();
const rules = topLevelRules(css);

/** This ticket's block, from its banner to the next banner (or the end of the file). */
const SECTION = (() => {
  const start = css.indexOf('REVIEW STATUS SURFACES  (COL-2.4, #4520)');
  if (start < 0) throw new Error('globals.css has no review-status section');
  const bannerStart = css.lastIndexOf('/* =', start);
  const next = css.indexOf('/* =', start);
  return css.slice(bannerStart < 0 ? start : bannerStart, next < 0 ? css.length : next);
})();

/** The same block with its comments removed. */
const SECTION_CODE = SECTION.replace(/\/\*[\s\S]*?\*\//g, '');

/** The components whose `className`s the section must cover. */
const COMPONENT_DIR = path.join(__dirname, '..', 'src', 'app', 'components', 'ade', 'reviews');

/**
 * Look one of this ticket's rules up.
 *
 * @param prelude - The rule's selector.
 * @returns The rule.
 */
function statusRule(prelude: string): CssRule {
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
  return parseDeclarations(statusRule(prelude).body).get(property);
}

/** Every `rvs-` class the review components name. */
function componentClasses(): string[] {
  const names = new Set<string>();
  for (const file of fs.readdirSync(COMPONENT_DIR)) {
    const source = fs.readFileSync(path.join(COMPONENT_DIR, file), 'utf8');
    for (const match of source.matchAll(/["'` ](rvs[a-z0-9_-]*)/g)) names.add(match[1]);
  }
  return [...names].sort();
}

/** Every `rvs-` class the section declares. */
function sectionClasses(): string[] {
  return [...new Set([...SECTION_CODE.matchAll(/\.(rvs[a-z0-9_-]*)/g)].map((match) => match[1]))].sort();
}

describe('the review-status section of globals.css', () => {
  it('declares every class the pill and the panel use, and nothing else', () => {
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

  it('freezes nothing in pixels beyond hairlines and the focus ring', () => {
    const pixels = [...SECTION_CODE.matchAll(/(-?\d*\.?\d+)px/g)].map((match) => Number(match[1]));
    expect(pixels.filter((value) => Math.abs(value) > 2)).toEqual([]);
  });

  it('never uses --fg-subtle and never fades', () => {
    expect(SECTION_CODE).not.toContain('--fg-subtle');
    expect(SECTION_CODE).not.toMatch(/opacity\s*:/);
  });

  it('gives both holders a zero minimum, so a pill never widens a table cell', () => {
    for (const prelude of ['.rvs-pill', '.rvs-link']) {
      expect({ prelude, min: declaration(prelude, 'min-inline-size') }).toEqual({ prelude, min: '0' });
    }
  });

  it('breaks the dialog link anywhere', () => {
    expect(declaration('.rvs-link', 'overflow-wrap')).toBe('anywhere');
  });

  it('keeps the pill a badge rather than underlined body copy', () => {
    expect(declaration('.rvs-pill', 'text-decoration')).toBe('none');
    expect(declaration('.rvs-pill', 'color')).toBe('inherit');
  });

  it('keeps both links reachable by keyboard', () => {
    for (const prelude of ['.rvs-pill:focus-visible', '.rvs-link:focus-visible']) {
      expect({ prelude, outline: declaration(prelude, 'outline') }).toEqual({
        prelude,
        outline: '2px solid var(--focus-ring)',
      });
    }
  });
});
