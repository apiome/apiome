/**
 * The stylesheet half of Ship → SDK settings (SDK-3.4, #4494).
 *
 * `sdk-settings-screen.test.tsx` renders the page and pins its behaviour; it cannot pin anything
 * that makes it *look* right, because jsdom compiles no stylesheet. So this suite reads
 * `globals.css` the way `consumers-css.test.ts` and `style-guides-css.test.ts` do, and pins what
 * the components lean on:
 *
 *   1. **The skin is tokens only** — no hex, no `rgb()`, no Tailwind palette class, so the screen
 *      renders in all nine appearances.
 *   2. **Nothing is frozen in pixels**, so the density and font-scale preferences reach the form's
 *      fields and the preview's rows.
 *   3. **The long values scroll inside themselves.** A package name and a licence header are both
 *      unbroken strings a user pastes in; without `min-inline-size: 0` and an overflow rule they
 *      would push the document sideways.
 *   4. **Nothing fades.** `opacity` is the one way of marking a region that can fail a contrast
 *      check, and it is not spent in this block.
 *   5. **The section is bounded at the next banner**, so these assertions never become claims
 *      about a later ticket's rules.
 */

import {
  findUnfencedHex,
  parseDeclarations,
  readGlobalsCss,
  topLevelRules,
  type CssRule,
} from './helpers/design-tokens';

const css = readGlobalsCss();
const rules = topLevelRules(css);

/** The line the unlayered `p` base rule is declared on, found rather than assumed. */
const BASE_TYPE_RULE_LINE = (() => {
  const rule = rules.find((candidate) => candidate.prelude === 'p');
  if (!rule) throw new Error('globals.css no longer declares a bare `p` rule');
  return rule.line;
})();

/**
 * Every top-level rule this ticket added, by prelude.
 *
 * Listed rather than pattern-matched so a rule that is *renamed* fails here instead of silently
 * dropping out of the token-only walk below.
 */
const SDK_PRELUDES = [
  '.sdks-notice',
  '.sdks-problems',
  '.sdks-scope',
  '.sdks-scope__label',
  '.sdks-scope__select',
  '.sdks-scope__hint',
  '.sdks-card',
  '.sdks-card__header',
  '.sdks-card__text',
  '.sdks-card__title',
  '.sdks-card__desc',
  '.sdks-fingerprint',
  '.sdks-body',
  '.sdks-field',
  '.sdks-field__head',
  '.sdks-field__label',
  '.sdks-field__inherit',
  '.sdks-field__box',
  '.sdks-field__control',
  '.sdks-field__hint',
  '.sdks-footer',
  '.sdks-footer__state',
  '.sdks-footer__spinner',
  '.sdks-preview',
  '.sdks-preview__list',
  '.sdks-preview__row',
  '.sdks-preview__term',
  '.sdks-preview__glyph',
  '.sdks-preview__value',
  '.sdks-preview__value--block',
] as const;

/**
 * Look one of this ticket's rules up.
 *
 * @param prelude The rule's selector, exactly as {@link SDK_PRELUDES} lists it.
 * @returns The rule.
 */
function sdkRule(prelude: string): CssRule {
  const rule = rules.find((candidate) => candidate.prelude === prelude);
  if (!rule) throw new Error(`globals.css declares no rule \`${prelude}\``);
  return rule;
}

/**
 * Read one declaration out of one of this ticket's rules.
 *
 * @param prelude The rule's selector.
 * @param property The property to read.
 * @returns Its value, whitespace-collapsed.
 */
function declaration(prelude: string, property: string): string {
  const value = parseDeclarations(sdkRule(prelude).body).get(property);
  if (value === undefined) throw new Error(`\`${prelude}\` declares no \`${property}\``);
  return value;
}

/**
 * The SDK-settings block, from its banner to the start of whatever section follows it.
 *
 * Bounded rather than run to the end of the file: `globals.css` grows one section per ticket, and
 * a slice that ended at EOF would make every assertion below a claim about every *later* section
 * too.
 */
const SECTION = (() => {
  const start = css.indexOf('SDK GENERATION SETTINGS  (SDK-3.4, #4494)');
  if (start < 0) throw new Error('globals.css has no SDK-settings section');
  const bannerStart = css.lastIndexOf('/* =', start);
  const next = css.indexOf('/* =', start);
  return css.slice(bannerStart < 0 ? start : bannerStart, next < 0 ? css.length : next);
})();

/** The same block with its comments removed. */
const SECTION_CODE = SECTION.replace(/\/\*[\s\S]*?\*\//g, '');

describe('the SDK-settings section of globals.css', () => {
  it('declares every rule the components reference', () => {
    const missing = SDK_PRELUDES.filter(
      (prelude) => !rules.some((rule) => rule.prelude === prelude),
    );
    expect(missing).toEqual([]);
  });

  it('declares no class outside its own prefix', () => {
    const classes = new Set(
      [...SECTION_CODE.matchAll(/\.([a-z][a-z0-9_-]*)/g)].map((match) => match[1]),
    );
    expect(classes.size).toBeGreaterThan(0);
    for (const name of classes) {
      expect(name.startsWith('sdks-')).toBe(true);
    }
  });

  it('sits after the unlayered p and h1–h4 base rules it has to outrank', () => {
    // `.sdks-card__desc`, `.sdks-field__hint` and `.sdks-scope__hint` are `p`s and
    // `.sdks-card__title` is an `h2`; both base rules are unlayered, so a rule declared before
    // them would lose whatever its specificity.
    for (const prelude of SDK_PRELUDES) {
      expect(sdkRule(prelude).line).toBeGreaterThan(BASE_TYPE_RULE_LINE);
    }
  });

  it('names no colour — every hue resolves through the token layer', () => {
    for (const prelude of SDK_PRELUDES) {
      for (const [property, value] of parseDeclarations(sdkRule(prelude).body)) {
        expect({ prelude, property, value }).toMatchObject({ prelude, property });
        expect(value).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
        expect(value.replace(/color-mix\([^)]*\)/g, '')).not.toMatch(
          /\b(?:rgb|rgba|hsl|hsla|oklch)\(/,
        );
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
  it('states no font size or control metric in px', () => {
    const RULE_PROPERTIES = new Set([
      'outline',
      'outline-offset',
      'box-shadow',
      'border',
      'inline-size',
      'block-size',
      'margin',
    ]);
    for (const prelude of SDK_PRELUDES) {
      for (const [property, value] of parseDeclarations(sdkRule(prelude).body)) {
        const allowed = RULE_PROPERTIES.has(property) ? ['1px', '2px'] : ['1px'];
        const offending = value
          .match(/(?<!\d)(\d*\.?\d+)px/g)
          ?.filter((px) => !allowed.includes(px));
        expect({ prelude, property, offending: offending ?? [] }).toMatchObject({
          prelude,
          property,
          offending: [],
        });
      }
    }
  });

  it('sizes both glyph-scale boxes from the shared icon metric', () => {
    for (const prelude of ['.sdks-field__box', '.sdks-footer__spinner', '.sdks-preview__glyph']) {
      expect(declaration(prelude, 'inline-size')).toBe('var(--icon-dense)');
      expect(declaration(prelude, 'block-size')).toBe('var(--icon-dense)');
    }
  });

  it('spends spacing tokens rather than literal gaps, so Compact is genuinely compact', () => {
    for (const [prelude, property] of [
      ['.sdks-body', 'gap'],
      ['.sdks-field', 'gap'],
      ['.sdks-footer', 'gap'],
      ['.sdks-preview__list', 'gap'],
    ] as const) {
      expect(declaration(prelude, property)).toContain('var(--space-');
    }
  });

  it('states every font size as a scale token', () => {
    for (const prelude of SDK_PRELUDES) {
      const size = parseDeclarations(sdkRule(prelude).body).get('font-size');
      if (size === undefined) continue;
      expect(size).toMatch(/^var\(--fs-/);
    }
  });
});

describe('a long value cannot scroll the document sideways', () => {
  it('lets the flex and grid children shrink', () => {
    for (const prelude of [
      '.sdks-card__text',
      '.sdks-field',
      '.sdks-preview__term',
      '.sdks-preview__value',
    ]) {
      expect(declaration(prelude, 'min-inline-size')).toBe('0');
    }
  });

  it('scrolls an over-wide resolved value inside its own cell', () => {
    expect(declaration('.sdks-preview__value', 'overflow-x')).toBe('auto');
  });

  it('wraps a multi-line licence header rather than letting one word set the width', () => {
    expect(declaration('.sdks-preview__value--block', 'white-space')).toBe('pre-wrap');
    expect(declaration('.sdks-preview__value--block', 'overflow-wrap')).toBe('anywhere');
  });

  it('lets the field header wrap when the Inherit label will not fit beside the label', () => {
    expect(declaration('.sdks-field__head', 'flex-wrap')).toBe('wrap');
    expect(declaration('.sdks-footer', 'flex-wrap')).toBe('wrap');
  });

  it('collapses the preview to one column on a narrow viewport, in rem', () => {
    expect(SECTION_CODE).toMatch(/@media \(max-inline-size: [\d.]+rem\)/);
    expect(SECTION_CODE).not.toMatch(/@media \([^)]*\d+px\)/);
  });
});
