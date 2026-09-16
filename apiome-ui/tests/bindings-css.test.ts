/**
 * The stylesheet half of the Repository binding panel (GNC-2.1, #4737).
 *
 * `version-binding-panel.test.tsx` renders the surface; jsdom compiles no stylesheet, so this
 * suite reads `globals.css` the way `notifications-css.test.ts` does and pins what the component
 * leans on:
 *
 *   1. **Every `bnd-` class the component spells is declared**, and the section declares no class
 *      the component does not spell — the pairing that rots first.
 *   2. **The skin is tokens only** — no hex, no `rgb()`, no Tailwind palette class.
 *   3. **Nothing is frozen in pixels** except hairlines and focus rings, so the density and
 *      font-size preferences reach the whole panel.
 *   4. **Text is legible**: `--fg-subtle` is never spent on a line meant to be read.
 *   5. **Nothing scrolls sideways**: a long `owner/repo @ branch · path` and a 71-character digest
 *      wrap rather than push the card out of the viewport.
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
const COMPONENT_FILES = ['src/app/components/ade/bindings/VersionBindingPanel.tsx'] as const;

/** The binding block, from its banner to the next one (or the end of file). */
const SECTION = (() => {
  const start = css.indexOf('Repository binding (GNC-2.1, #4737)');
  if (start < 0) throw new Error('globals.css has no repository-binding section');
  const bannerStart = css.lastIndexOf('/* =', start);
  const next = css.indexOf('/* =', start);
  return css.slice(bannerStart < 0 ? start : bannerStart, next < 0 ? css.length : next);
})();

/** The same block with its comments removed, so prose never satisfies an assertion. */
const SECTION_CODE = SECTION.replace(/\/\*[\s\S]*?\*\//g, '');

/** Every `bnd-` class the section declares. */
const DECLARED: readonly string[] = [
  ...new Set([...SECTION_CODE.matchAll(/\.(bnd[a-z0-9_-]*)/g)].map((match) => match[1])),
].sort();

/** Every `bnd-` class the component spells, read out of the source. */
const SPELLED: readonly string[] = (() => {
  const found = new Set<string>();
  for (const file of COMPONENT_FILES) {
    const source = fs.readFileSync(path.join(process.cwd(), file), 'utf8');
    for (const match of source.matchAll(/\b(bnd(?:-[a-z0-9_-]+)?)\b/g)) found.add(match[1]);
  }
  return [...found].sort();
})();

/** Every top-level rule inside the section, for the sweeps below. */
const SECTION_RULES: readonly CssRule[] = rules.filter((rule) => /^\.bnd/.test(rule.prelude.trim()));

/**
 * Look one of this ticket's rules up.
 *
 * @param prelude - The rule's selector.
 * @returns The rule.
 */
function bindingRule(prelude: string): CssRule {
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
  const value = parseDeclarations(bindingRule(prelude).body).get(property);
  if (value === undefined) throw new Error(`\`${prelude}\` declares no \`${property}\``);
  return value;
}

describe('the repository-binding section of globals.css', () => {
  it('declares exactly the classes the component spells', () => {
    expect(SPELLED.filter((name) => !DECLARED.includes(name))).toEqual([]);
    expect(DECLARED.filter((name) => !SPELLED.includes(name))).toEqual([]);
    expect(SPELLED.length).toBeGreaterThan(15);
  });

  it('claims no class of another ticket', () => {
    const foreign = [...SECTION_CODE.matchAll(/\.([a-z][a-z0-9_-]*)/g)]
      .map((match) => match[1])
      .filter((name) => !name.startsWith('bnd'));
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
      ['.bnd', 'gap'],
      ['.bnd', 'padding'],
      ['.bnd-toolbar', 'gap'],
      ['.bnd-card', 'padding'],
      ['.bnd-form__grid', 'gap'],
      ['.bnd-candidate', 'padding'],
      ['.bnd-list', 'gap'],
    ] as const) {
      expect(declaration(prelude, property)).toContain('var(--space-');
    }
  });

  it('sizes every glyph from the icon scale', () => {
    expect(declaration('.bnd-card__glyph', 'inline-size')).toBe('var(--icon-dense)');
    expect(declaration('.bnd-card__glyph', 'block-size')).toBe('var(--icon-dense)');
  });
});

describe('legibility', () => {
  /** Every rule that sets `color`, with what it sets it to. */
  const INKS = SECTION_RULES.flatMap((rule) => {
    const color = parseDeclarations(rule.body).get('color');
    return color ? [{ prelude: rule.prelude.replace(/\s+/g, ' ').trim(), color }] : [];
  });

  it('never spends --fg-subtle on a line meant to be read', () => {
    const readable = INKS.filter(
      (ink) => ink.color.includes('--fg-subtle') && !ink.prelude.includes('__glyph')
    );
    expect(readable).toEqual([]);
  });

  it('draws the binding in the full ink and its context one step down', () => {
    expect(declaration('.bnd-card__title', 'color')).toBe('var(--fg)');
    expect(declaration('.bnd-candidate__what', 'color')).toBe('var(--fg)');
    expect(declaration('.bnd-candidate__meta', 'color')).toBe('var(--fg-muted)');
    expect(declaration('.bnd-note', 'color')).toBe('var(--fg-muted)');
  });

  it('inks the one link --fg and underlines it rather than tinting it accent', () => {
    // HIVE-8.1: `--accent` measures under 4.5:1 on this surface in three themes.
    expect(declaration('.bnd-card__link', 'color')).toBe('var(--fg)');
    expect(
      declaration('.bnd-card__link:hover, .bnd-card__link:focus-visible', 'text-decoration')
    ).toBe('underline');
  });
});

describe('long names never push anything sideways', () => {
  it('gives every flex or grid holder of a name a zero minimum', () => {
    for (const prelude of [
      '.bnd',
      '.bnd-toolbar',
      '.bnd-card',
      '.bnd-card__head',
      '.bnd-card__title',
      '.bnd-facts',
      '.bnd-facts__row',
      '.bnd-form',
      '.bnd-form__grid',
      '.bnd-list',
      '.bnd-candidate',
      '.bnd-settled',
      '.bnd-settled__what',
    ]) {
      expect(declaration(prelude, 'min-inline-size')).toBe('0');
    }
  });

  it('breaks a long repository name, path or digest anywhere rather than overflowing', () => {
    for (const prelude of ['.bnd-card__title', '.bnd-facts__row dd', '.bnd-candidate__what', '.bnd-settled__what']) {
      expect(declaration(prelude, 'overflow-wrap')).toBe('anywhere');
    }
  });

  it('caps the two pickers at their container', () => {
    expect(declaration('.bnd-select', 'max-inline-size')).toBe('100%');
  });
});
