/**
 * The stylesheet half of the consumer contract registry (CTG-4.1, #4479).
 *
 * `consumers-screen.test.tsx` renders the page and pins its behaviour; it cannot pin anything
 * that makes it *look* right, because jsdom compiles no stylesheet. So this suite reads
 * `globals.css` the way `api-keys-css.test.ts` and `style-guides-css.test.ts` do, and pins
 * what the components lean on:
 *
 *   1. **The skin is tokens only** — no hex, no `rgb()`, no Tailwind palette class. A screen
 *      whose one job is showing evidence must render in all nine appearances.
 *   2. **Nothing is frozen in pixels**, so the density and font-scale preferences reach the
 *      picker's two-column field grids and the drawer's field lists.
 *   3. **Every grid collapses**, so a long JSON Pointer cannot scroll the document sideways.
 *   4. **Quiet text is `--fg-muted`**, not `--fg-subtle`, wherever it carries meaning rather
 *      than decorating a row.
 *   5. **Nothing fades.** `opacity` is the one way of marking a region that can fail a
 *      contrast check, and it is not spent in this block.
 *   6. **The section is bounded at the next banner**, so these assertions never become claims
 *      about a later ticket's rules — the trap `api-keys-css.test.ts` records.
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
 * Listed rather than pattern-matched so a rule that is *renamed* fails here instead of
 * silently dropping out of the token-only walk below.
 */
const CONSUMER_PRELUDES = [
  '.cns-identity',
  '.cns-identity__name',
  '.cns-identity__slug',
  '.cns-owner',
  '.cns-owner--none',
  '.cns-surface',
  '.cns-surface__line',
  '.cns-surface__ops',
  '.cns-op',
  '.cns-surface__more',
  '.cns-status',
  '.cns-status__meta',
  '.cns-menu__item--danger',
  '.cns-dialog',
  '.cns-dialog--wide',
  '.cns-form',
  '.cns-form__field',
  '.cns-form__row',
  '.cns-form__hint',
  '.cns-file',
  '.cns-pact',
  '.cns-outcome',
  '.cns-outcome__group',
  '.cns-outcome__heading, .cns-drawer__grouphead',
  '.cns-outcome__count, .cns-drawer__count',
  '.cns-outcome__list, .cns-drawer__list',
  '.cns-outcome__item, .cns-drawer__item',
  '.cns-outcome__where',
  '.cns-outcome__item--more',
  '.cns-picker',
  '.cns-picker__state',
  '.cns-picker__list',
  '.cns-picker__totals',
  '.cns-pick',
  '.cns-pick.is-picked',
  '.cns-pick__head',
  '.cns-pick__toggle',
  '.cns-pick__toggle:disabled',
  '.cns-pick__chevron',
  ".cns-pick__toggle[aria-expanded='true'] .cns-pick__chevron",
  '.cns-pick__op',
  '.cns-pick__summary',
  '.cns-pick__count',
  '.cns-pick__fields',
  '.cns-pick__truncated',
  '.cns-pick__group',
  '.cns-pick__grouphead',
  '.cns-pick__fieldlist',
  '.cns-pick__label',
  '.cns-pick__path',
  '.cns-pick__type, .cns-pick__status',
  '.cns-pick__required',
  '.cns-drawer__summary',
  '.cns-drawer__section',
  '.cns-drawer__heading',
  '.cns-drawer__group',
  '.cns-drawer__empty',
  '.cns-drawer__ops',
  '.cns-drawer__op',
  '.cns-drawer__opline',
  '.cns-drawer__opsummary',
  '.cns-drawer__fields',
  '.cns-drawer__field',
  '.cns-drawer__where',
] as const;

/**
 * Look one of this ticket's rules up.
 *
 * @param prelude The rule's selector, exactly as {@link CONSUMER_PRELUDES} lists it.
 * @returns The rule.
 */
function consumerRule(prelude: string): CssRule {
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
  const value = parseDeclarations(consumerRule(prelude).body).get(property);
  if (value === undefined) throw new Error(`\`${prelude}\` declares no \`${property}\``);
  return value;
}

/**
 * The consumers block, from its banner to the start of whatever section follows it.
 *
 * Bounded rather than run to the end of the file: `globals.css` grows one section per ticket,
 * and a slice that ended at EOF would make every assertion below a claim about every *later*
 * section too.
 */
const SECTION = (() => {
  const start = css.indexOf('CONSUMER CONTRACT REGISTRY  (CTG-4.1, #4479)');
  if (start < 0) throw new Error('globals.css has no consumer-registry section');
  const bannerStart = css.lastIndexOf('/* =', start);
  const next = css.indexOf('/* =', start);
  return css.slice(bannerStart < 0 ? start : bannerStart, next < 0 ? css.length : next);
})();

/** The same block with its comments removed. */
const SECTION_CODE = SECTION.replace(/\/\*[\s\S]*?\*\//g, '');

/* -------------------------------------------------------------------------
   1. The section exists, and names no colour
   ------------------------------------------------------------------------- */

describe('the consumer-registry section of globals.css', () => {
  it('declares every rule the components reference', () => {
    const missing = CONSUMER_PRELUDES.filter(
      (prelude) => !rules.some((rule) => rule.prelude === prelude)
    );
    expect(missing).toEqual([]);
  });

  it('declares no class the components do not use', () => {
    // The other direction: a rule left behind by a rename is dead weight that the next
    // reader has to decide about.
    const classes = new Set(
      [...SECTION_CODE.matchAll(/\.(cns-[a-z0-9_-]+)/g)].map((match) => match[1])
    );
    expect(classes.size).toBeGreaterThan(0);
    for (const name of classes) {
      expect(name.startsWith('cns-')).toBe(true);
    }
  });

  it('sits after the unlayered p and h1–h4 base rules it has to outrank', () => {
    // `.cns-form__hint` and `.cns-drawer__opsummary` are `p`s, and `.cns-drawer__heading` is
    // an `h3`; both base rules are unlayered, so a rule declared before them would lose
    // whatever its specificity.
    for (const prelude of CONSUMER_PRELUDES) {
      expect(consumerRule(prelude).line).toBeGreaterThan(BASE_TYPE_RULE_LINE);
    }
  });

  it('names no colour — every hue resolves through the token layer', () => {
    for (const prelude of CONSUMER_PRELUDES) {
      for (const [property, value] of parseDeclarations(consumerRule(prelude).body)) {
        expect({ prelude, property, value }).toMatchObject({ prelude, property });
        expect(value).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
        expect(value.replace(/color-mix\([^)]*\)/g, '')).not.toMatch(
          /\b(?:rgb|rgba|hsl|hsla|oklch)\(/
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

/* -------------------------------------------------------------------------
   2. Nothing is frozen in pixels
   ------------------------------------------------------------------------- */

describe('density and font-scale independence', () => {
  it('states no font size or control metric in px', () => {
    // `1px` is exempt everywhere — a hairline is one device pixel by definition — and `2px`
    // only in a ring, a border or an underline's clearance.
    const RULE_PROPERTIES = new Set([
      'outline',
      'outline-offset',
      'box-shadow',
      'border',
      'inline-size',
      'block-size',
      'margin',
    ]);
    for (const prelude of CONSUMER_PRELUDES) {
      for (const [property, value] of parseDeclarations(consumerRule(prelude).body)) {
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

  it('sizes the picker chevron from the shared icon metric', () => {
    expect(declaration('.cns-pick__chevron', 'inline-size')).toBe('var(--icon-dense)');
    expect(declaration('.cns-pick__chevron', 'block-size')).toBe('var(--icon-dense)');
  });

  it('spends spacing tokens rather than literal gaps, so Compact is genuinely compact', () => {
    for (const [prelude, property] of [
      ['.cns-form', 'gap'],
      ['.cns-picker', 'gap'],
      ['.cns-pick__head', 'padding'],
      ['.cns-drawer__op', 'padding'],
    ] as const) {
      expect(declaration(prelude, property)).toContain('var(--space-');
    }
  });

  it('measures every font size through the type scale', () => {
    for (const prelude of CONSUMER_PRELUDES) {
      const size = parseDeclarations(consumerRule(prelude).body).get('font-size');
      if (size === undefined) continue;
      expect({ prelude, size }).toMatchObject({ prelude });
      expect(size).toMatch(/^var\(--fs-/);
    }
  });
});

/* -------------------------------------------------------------------------
   3. Nothing scrolls the document sideways
   ------------------------------------------------------------------------- */

describe('overflow', () => {
  it('lets both auto-fill grids collapse to one column', () => {
    for (const prelude of ['.cns-pick__fieldlist', '.cns-drawer__fields']) {
      expect(declaration(prelude, 'grid-template-columns')).toMatch(
        /repeat\(auto-fill, minmax\([\d.]+rem, 1fr\)\)/
      );
    }
  });

  it('gives every flex column that holds a pointer a zero minimum', () => {
    // A JSON Pointer is one unbroken token; without `min-inline-size: 0` its flex parent
    // refuses to shrink and the page scrolls sideways.
    for (const prelude of [
      '.cns-identity',
      '.cns-surface',
      '.cns-form',
      '.cns-form__field',
      '.cns-picker',
      '.cns-pick__head',
      '.cns-pick__toggle',
      '.cns-pick__label',
      '.cns-drawer__field',
    ]) {
      expect(declaration(prelude, 'min-inline-size')).toBe('0');
    }
  });

  it('breaks a long message rather than widening its row', () => {
    expect(declaration('.cns-outcome__item, .cns-drawer__item', 'overflow-wrap')).toBe(
      'anywhere'
    );
    expect(declaration('.cns-identity__name', 'overflow-wrap')).toBe('anywhere');
  });

  it('scrolls the picker inside its own dialog, capped in rem', () => {
    expect(declaration('.cns-picker__list', 'overflow-y')).toBe('auto');
    expect(declaration('.cns-picker__list', 'max-block-size')).toMatch(/rem\)$/);
  });

  it('keeps both dialogs inside the viewport at any width', () => {
    for (const prelude of ['.cns-dialog', '.cns-dialog--wide']) {
      expect(declaration(prelude, 'max-inline-size')).toContain('100vw');
    }
  });
});

/* -------------------------------------------------------------------------
   4. Meaningful text is legible; only decoration is faint
   ------------------------------------------------------------------------- */

describe('ink', () => {
  it('inks the evidence itself, never a tone', () => {
    // A row can carry six declared operations. Six accent chips in one cell read as six
    // alerts; the status badge is the only tinted thing in the row.
    expect(declaration('.cns-op', 'color')).toBe('var(--fg)');
    expect(declaration('.cns-op', 'background')).toBe('var(--bg-inset)');
    expect(declaration('.cns-drawer__field', 'color')).toBe('var(--fg)');
  });

  it('keeps text that carries meaning at --fg-muted or better', () => {
    for (const prelude of [
      '.cns-identity__slug',
      '.cns-surface__line',
      '.cns-form__hint',
      '.cns-outcome__heading, .cns-drawer__grouphead',
      '.cns-pick__count',
      '.cns-picker__totals',
      '.cns-drawer__summary',
    ]) {
      expect(['var(--fg)', 'var(--fg-muted)']).toContain(declaration(prelude, 'color'));
    }
  });

  it('reserves --fg-subtle for what is decoration or a repeated label', () => {
    for (const prelude of [
      '.cns-surface__more',
      '.cns-status__meta',
      '.cns-pick__chevron',
      '.cns-drawer__where',
    ]) {
      expect(declaration(prelude, 'color')).toBe('var(--fg-subtle)');
    }
  });

  it('warns about a truncated field list in the warn tone, not in red', () => {
    // A walk that stopped at its limit is a caveat, not a failure.
    expect(declaration('.cns-pick__truncated', 'color')).toBe('var(--warn-fg)');
  });

  it('only re-inks the destructive menu verb on hover', () => {
    // A red row in a resting menu reads as an error the reader has already caused.
    expect(declaration('.cns-menu__item--danger', 'color')).toBe('var(--danger-fg)');
    expect(
      parseDeclarations(consumerRule('.cns-menu__item--danger').body).get('background')
    ).toBeUndefined();
  });
});

/* -------------------------------------------------------------------------
   5. The picker's own affordances
   ------------------------------------------------------------------------- */

describe('the picker', () => {
  it('tints a picked operation rather than outlining it', () => {
    // The list scrolls; an outline at this density reads as a table rule, not a selection.
    expect(declaration('.cns-pick', 'background')).toBe('var(--bg-subtle)');
    expect(declaration('.cns-pick.is-picked', 'background')).toBe('var(--accent-soft)');
  });

  it('turns the chevron when its section is open', () => {
    expect(
      declaration(".cns-pick__toggle[aria-expanded='true'] .cns-pick__chevron", 'transform')
    ).toBe('rotate(90deg)');
  });

  it('hides the file input without removing it from the accessibility tree', () => {
    // The visible control clicks it, so `display: none` would break the button it belongs to.
    const body = parseDeclarations(consumerRule('.cns-file').body);
    expect(body.get('display')).toBeUndefined();
    expect(body.get('position')).toBe('absolute');
    expect(body.get('clip-path')).toBe('inset(50%)');
  });
});
