/**
 * The stylesheet half of the notification centre (COL-3.2, #4522).
 *
 * `notifications-menu.test.tsx` and `notifications-page.test.tsx` render the two surfaces;
 * jsdom compiles no stylesheet, so this suite reads `globals.css` the way
 * `discussion-css.test.ts` does and pins what those components lean on:
 *
 *   1. **Every `ntf-` class a component spells is declared**, and the section declares no
 *      class no component spells — the pairing that rots first.
 *   2. **The skin is tokens only** — no hex, no `rgb()`, no Tailwind palette class.
 *   3. **Nothing is frozen in pixels** except hairlines and focus rings, so the density and
 *      font-size preferences reach every row.
 *   4. **Text is legible**: `--fg-subtle` is spent on glyphs and hairlines, never on a line
 *      meant to be read, because it measures 2.9–4.0:1 on `--bg-surface` across the nine
 *      themes.
 *   5. **Nothing scrolls sideways**: every holder of a project name has a zero minimum.
 *   6. **The section is bounded at the next banner**, so these assertions never become
 *      claims about a later ticket's rules.
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

/** The components that spell these classes. */
const COMPONENT_FILES = [
  'src/app/components/shell/NotificationsMenu.tsx',
  'src/app/components/ade/notifications/NotificationRowContent.tsx',
  'src/app/ade/dashboard/notifications/NotificationsClient.tsx',
] as const;

/** The notification-centre block, from its banner to the next one (or the end of file). */
const SECTION = (() => {
  const start = css.indexOf('NOTIFICATION CENTRE  (COL-3.2, #4522)');
  if (start < 0) throw new Error('globals.css has no notification-centre section');
  const bannerStart = css.lastIndexOf('/* =', start);
  const next = css.indexOf('/* =', start);
  return css.slice(bannerStart < 0 ? start : bannerStart, next < 0 ? css.length : next);
})();

/** The same block with its comments removed, so prose never satisfies an assertion. */
const SECTION_CODE = SECTION.replace(/\/\*[\s\S]*?\*\//g, '');

/** Every `ntf-` class the section declares. */
const DECLARED: readonly string[] = [
  ...new Set([...SECTION_CODE.matchAll(/\.(ntf[a-z0-9_-]*)/g)].map((match) => match[1])),
].sort();

/** Every `ntf-` class a component spells, read out of the source. */
const SPELLED: readonly string[] = (() => {
  const found = new Set<string>();
  for (const file of COMPONENT_FILES) {
    const source = fs.readFileSync(path.join(process.cwd(), file), 'utf8');
    for (const match of source.matchAll(/\b(ntf-[a-z0-9_-]+)/g)) found.add(match[1]);
  }
  return [...found].sort();
})();

/**
 * Look one of this ticket's rules up.
 *
 * @param prelude - The rule's selector.
 * @returns The rule.
 */
function notificationRule(prelude: string): CssRule {
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
  const value = parseDeclarations(notificationRule(prelude).body).get(property);
  if (value === undefined) throw new Error(`\`${prelude}\` declares no \`${property}\``);
  return value;
}

/** Every top-level rule inside the section, for the sweeps below. */
const SECTION_RULES: readonly CssRule[] = rules.filter(
  (rule) => /^\.(ntf|disc-thread--focused)/.test(rule.prelude.trim())
);

describe('the notification-centre section of globals.css', () => {
  it('declares exactly the classes the components spell', () => {
    // Both directions: a component reaching for a class nobody declared draws nothing, and
    // a declared class nobody spells is a rule that will be edited long after it stopped
    // being drawn.
    expect(SPELLED.filter((name) => !DECLARED.includes(name))).toEqual([]);
    expect(DECLARED.filter((name) => !SPELLED.includes(name))).toEqual([]);
    expect(SPELLED.length).toBeGreaterThan(20);
  });

  it('declares the one COL-1.3 rule it extends, and no other foreign class', () => {
    // The deep-linked thread is COL-1.3's row, tinted because a COL-3.2 notification named
    // it — so the rule belongs to this ticket rather than to the Discussion section.
    expect(SECTION_CODE).toContain('.disc-thread--focused');
    const foreign = [...SECTION_CODE.matchAll(/\.([a-z][a-z0-9_-]*)/g)]
      .map((match) => match[1])
      .filter((name) => !name.startsWith('ntf') && name !== 'disc-thread--focused');
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
          // 1–3px: a hairline, a focus ring, and the bar beside a quoted excerpt.
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
      ['.ntf-row', 'gap'],
      ['.ntf-row--page', 'padding'],
      ['.ntf-filters', 'gap'],
      ['.ntf-item', 'gap'],
      ['.ntf-empty', 'padding'],
    ] as const) {
      expect(declaration(prelude, property)).toContain('var(--space-');
    }
  });

  it('sizes the mark-read button from the control metric, not from a fixed square', () => {
    // A 30 px button beside 13 px text is only right at one density; the token moves both.
    expect(declaration('.ntf-item__mark', 'inline-size')).toBe('var(--control-h-sm)');
    expect(declaration('.ntf-item__mark', 'block-size')).toBe('var(--control-h-sm)');
  });

  it('sizes every glyph from the icon scale', () => {
    for (const prelude of ['.ntf-row__glyph svg', '.ntf-note__glyph', '.ntf-item__mark-glyph']) {
      expect(declaration(prelude, 'inline-size')).toBe('var(--icon-dense)');
      expect(declaration(prelude, 'block-size')).toBe('var(--icon-dense)');
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
    const readable = INKS.filter(
      (ink) => ink.color.includes('--fg-subtle') && !ink.prelude.includes('__glyph')
    );
    expect(readable).toEqual([]);
  });

  it('draws the sentence in the full ink and its context one step down', () => {
    expect(declaration('.ntf-row__sentence', 'color')).toBe('var(--fg)');
    expect(declaration('.ntf-row__context', 'color')).toBe('var(--fg-muted)');
    expect(declaration('.ntf-row__when', 'color')).toBe('var(--fg-muted)');
  });

  it('puts the badge’s own ink on the badge’s own fill', () => {
    // `--honey` with body ink over it is the contrast failure this pairing exists to avoid.
    for (const prelude of ['.ntf-badge', '.ntf-menu__count']) {
      expect(declaration(prelude, 'background')).toBe('var(--honey)');
      expect(declaration(prelude, 'color')).toBe('var(--honey-ink)');
    }
  });

  it('gives every interactive rule a visible focus ring', () => {
    for (const prelude of [
      '.ntf-menu__link:focus-visible',
      '.ntf-note__link:focus-visible',
      '.ntf-row--page:focus-visible',
      '.ntf-item__mark:focus-visible',
    ]) {
      expect(declaration(prelude, 'outline')).toContain('var(--focus-ring)');
    }
  });
});

describe('long names never push anything sideways', () => {
  it('gives every flex holder of a name a zero minimum', () => {
    for (const prelude of [
      '.ntf-row',
      '.ntf-row__body',
      '.ntf-row__sentence',
      '.ntf-row__context',
      '.ntf-row__excerpt',
      '.ntf-filters',
      '.ntf-item',
      '.ntf-list',
      '.ntf-group',
    ]) {
      expect(declaration(prelude, 'min-inline-size')).toBe('0');
    }
  });

  it('breaks a long project name or excerpt anywhere rather than overflowing', () => {
    for (const prelude of ['.ntf-row__sentence', '.ntf-row__context', '.ntf-row__excerpt']) {
      expect(declaration(prelude, 'overflow-wrap')).toBe('anywhere');
    }
  });

  it('caps the dropdown at the viewport, so a narrow window never scrolls sideways', () => {
    expect(declaration('.ntf-menu', 'max-inline-size')).toContain('100vw');
    expect(declaration('.ntf-menu__list', 'max-block-size')).toContain('vh');
  });
});
