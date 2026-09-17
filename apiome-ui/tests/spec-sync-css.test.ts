/**
 * The stylesheet half of the Synchronization section (GNC-2.3, #4739).
 *
 * `version-sync-panel.test.tsx` renders the surface; jsdom compiles no stylesheet, so this suite
 * reads `globals.css` the way `bindings-css.test.ts` does and pins what the component leans on:
 *
 *   1. **Every `syn-` class the component spells is declared**, and the section declares no class
 *      the component does not spell — the pairing that rots first.
 *   2. **The skin is tokens only** — no hex, no `rgb()`, no Tailwind palette class.
 *   3. **Nothing is frozen in pixels** except hairlines and focus rings, so the density and
 *      font-size preferences reach the whole section.
 *   4. **Text is legible**: `--fg-subtle` is never spent on a line meant to be read.
 *   5. **Nothing scrolls sideways.** This is the section's own risk: it shows three JSON values
 *      side by side, and one long schema would push the panel out of the viewport unless every
 *      value wraps and scrolls inside its own column.
 *   6. **The section is bounded at the next banner**, so these assertions never become claims
 *      about a later ticket's rules.
 */

import * as fs from 'fs';
import * as path from 'path';

import {
  findUnfencedHex,
  parseDeclarations,
  readGlobalsCss,
  topLevelRules,
  type CssRule,
} from './helpers/design-tokens';

const css = readGlobalsCss();
const rules = topLevelRules(css);

/** The component that spells these classes. */
const COMPONENT_FILES = ['src/app/components/ade/bindings/VersionSyncPanel.tsx'] as const;

/** The synchronization block, from its banner to the next one (or the end of file). */
const SECTION = (() => {
  const start = css.indexOf('Three-way synchronization (GNC-2.3, #4739)');
  if (start < 0) throw new Error('globals.css has no three-way-synchronization section');
  const bannerStart = css.lastIndexOf('/* =', start);
  const next = css.indexOf('/* =', start);
  return css.slice(bannerStart < 0 ? start : bannerStart, next < 0 ? css.length : next);
})();

/** The same block with its comments removed, so prose never satisfies an assertion. */
const SECTION_CODE = SECTION.replace(/\/\*[\s\S]*?\*\//g, '');

/** Every `syn-` class the section declares. */
const DECLARED: readonly string[] = [
  ...new Set([...SECTION_CODE.matchAll(/\.(syn[a-z0-9_-]*)/g)].map((match) => match[1])),
].sort();

/** Every `syn-` class the component spells, read out of the source. */
const SPELLED: readonly string[] = (() => {
  const found = new Set<string>();
  for (const file of COMPONENT_FILES) {
    const source = fs.readFileSync(path.join(process.cwd(), file), 'utf8');
    for (const match of source.matchAll(/\b(syn(?:-[a-z0-9_-]+)?)\b/g)) found.add(match[1]);
  }
  return [...found].sort();
})();

/** Every top-level rule inside the section, for the sweeps below. */
const SECTION_RULES: readonly CssRule[] = rules.filter((rule) => /^\.syn/.test(rule.prelude.trim()));

/**
 * Look one of this ticket's rules up.
 *
 * @param prelude - The rule's selector.
 * @returns The rule.
 */
function syncRule(prelude: string): CssRule {
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
function declaration(prelude: string, property: string): string {
  const value = parseDeclarations(syncRule(prelude).body).get(property);
  if (value === undefined) throw new Error(`\`${prelude}\` declares no \`${property}\``);
  return value;
}

describe('the synchronization section of globals.css', () => {
  it('declares exactly the classes the component spells', () => {
    expect(SPELLED.filter((name) => !DECLARED.includes(name))).toEqual([]);
    expect(DECLARED.filter((name) => !SPELLED.includes(name))).toEqual([]);
    expect(SPELLED.length).toBeGreaterThan(15);
  });

  it('claims no class of another ticket', () => {
    const foreign = [...SECTION_CODE.matchAll(/\.([a-z][a-z0-9_-]*)/g)]
      .map((match) => match[1])
      .filter((name) => !name.startsWith('syn'));
    expect([...new Set(foreign)]).toEqual([]);
  });

  it('names no colour — every hue resolves through the token layer', () => {
    for (const rule of SECTION_RULES) {
      for (const [, value] of parseDeclarations(rule.body)) {
        expect(value).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
        expect(value).not.toMatch(/\b(?:rgb|rgba|hsl|hsla|oklch)\(/);
      }
    }
  });

  it('names no Tailwind palette class', () => {
    for (const banned of ['slate-', 'indigo-', 'emerald-', 'rose-1', 'amber-', 'gray-']) {
      expect(SECTION_CODE).not.toContain(banned);
    }
  });

  it('leaves the hex fence of the stylesheet intact', () => {
    expect(findUnfencedHex(css).map((entry) => `${entry.line}: ${entry.text}`)).toEqual([]);
  });

  it('never fades anything', () => {
    expect(SECTION_CODE).not.toMatch(/(?<!-)\bopacity\s*:/);
  });
});

describe('density and font-scale independence', () => {
  /** Where a pixel length is still the honest unit: hairlines and focus rings. */
  const PX_ALLOWED = /^(outline|outline-offset|box-shadow|border(-[a-z-]+)?|inline-size|block-size)$/;

  it('states nothing in px but hairlines and focus rings', () => {
    for (const rule of SECTION_RULES) {
      for (const [property, value] of parseDeclarations(rule.body)) {
        const lengths = value.match(/(?<!\d)(\d*\.?\d+)px/g) ?? [];
        if (lengths.length === 0) continue;
        expect({ prelude: rule.prelude, property, lengths }).toEqual({
          prelude: rule.prelude,
          property,
          lengths: lengths.filter((length) => PX_ALLOWED.test(property) && /^[123]px$/.test(length)),
        });
      }
    }
  });

  it('measures every font size through the type scale', () => {
    for (const rule of SECTION_RULES) {
      const size = parseDeclarations(rule.body).get('font-size');
      if (size === undefined) continue;
      expect(size).toMatch(/^var\(--fs-/);
    }
  });

  it('spends spacing tokens for gaps and padding', () => {
    for (const [prelude, property] of [
      ['.syn', 'gap'],
      ['.syn-head', 'gap'],
      ['.syn-card', 'padding'],
      ['.syn-list', 'gap'],
      ['.syn-sides', 'gap'],
      ['.syn-side', 'padding'],
      ['.syn-conflict', 'padding'],
      ['.syn-past', 'padding'],
    ] as const) {
      expect(declaration(prelude, property)).toContain('var(--space-');
    }
  });
});

describe('legibility', () => {
  /** Every rule that sets `color`, with what it sets it to. */
  const INKS = SECTION_RULES.flatMap((rule) => {
    const color = parseDeclarations(rule.body).get('color');
    return color ? [{ prelude: rule.prelude.replace(/\s+/g, ' ').trim(), color }] : [];
  });

  it('never spends --fg-subtle on a line meant to be read', () => {
    expect(INKS.filter((ink) => ink.color.includes('--fg-subtle'))).toEqual([]);
  });

  it('draws the merge and its three values in the full ink, and their labels one step down', () => {
    expect(declaration('.syn-card__what', 'color')).toBe('var(--fg)');
    expect(declaration('.syn-side__value', 'color')).toBe('var(--fg)');
    expect(declaration('.syn-conflict__pointer', 'color')).toBe('var(--fg)');
    expect(declaration('.syn-side__label', 'color')).toBe('var(--fg-muted)');
    expect(declaration('.syn-head__note', 'color')).toBe('var(--fg-muted)');
  });

  it('inks the source link --fg and underlines it rather than tinting it accent', () => {
    // HIVE-8.1: `--accent` measures under 4.5:1 on this surface in three themes.
    expect(declaration('.syn-conflict__link, .syn-conflict__where', 'color')).toBe('var(--fg)');
    expect(
      declaration('.syn-conflict__link:hover, .syn-conflict__link:focus-visible', 'text-decoration')
    ).toBe('underline');
  });
});

describe('three values never push the panel sideways', () => {
  it('gives every flex or grid holder of a value a zero minimum', () => {
    for (const prelude of [
      '.syn',
      '.syn-head',
      '.syn-card',
      '.syn-card__head',
      '.syn-card__what',
      '.syn-facts',
      '.syn-facts__row',
      '.syn-facts__value',
      '.syn-list',
      '.syn-change',
      '.syn-conflict',
      '.syn-conflict__head',
      '.syn-sides',
      '.syn-side',
      '.syn-side__value',
      '.syn-past',
    ]) {
      expect(declaration(prelude, 'min-inline-size')).toBe('0');
    }
  });

  it('breaks a long pointer, digest or value anywhere rather than overflowing', () => {
    for (const prelude of [
      '.syn-card__what',
      '.syn-facts__value',
      '.syn-change__group',
      '.syn-change__pointer',
      '.syn-conflict__pointer',
      '.syn-side__value',
      '.syn-past__what',
    ]) {
      expect(declaration(prelude, 'overflow-wrap')).toBe('anywhere');
    }
  });

  it('wraps and bounds a value rather than letting one schema fill the page', () => {
    // A `<pre>` would otherwise keep its source line breaks and scroll the whole panel.
    expect(declaration('.syn-side__value', 'white-space')).toBe('pre-wrap');
    expect(declaration('.syn-side__value', 'overflow')).toBe('auto');
    expect(declaration('.syn-side__value', 'max-block-size')).toMatch(/rem$/);
  });

  it('lays the three sides out as columns that collapse rather than shrink', () => {
    expect(declaration('.syn-sides', 'grid-template-columns')).toMatch(
      /repeat\(auto-fit, minmax\([\d.]+rem, 1fr\)\)/
    );
  });
});
