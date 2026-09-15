/**
 * The stylesheet half of the Project Discussion panel (COL-1.3, #4515).
 *
 * `project-discussion-panel.test.tsx` renders the panel and pins its behaviour; jsdom compiles no
 * stylesheet, so this suite reads `globals.css` the way `consumers-css.test.ts` does and pins what
 * the component leans on:
 *
 *   1. **The skin is tokens only** — no hex, no `rgb()`, no Tailwind palette class.
 *   2. **Nothing is frozen in pixels** beyond hairlines, so density and font scale reach the rows.
 *   3. **Nothing scrolls sideways**: every flex holder of a long name has a zero minimum, and
 *      names and excerpts break anywhere.
 *   4. **Text is legible**: the link is `--fg`, not `--accent`; quiet text is `--fg-muted`, never
 *      `--fg-subtle`; nothing fades.
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

/** The line the unlayered `p` base rule is declared on. */
const BASE_TYPE_RULE_LINE = (() => {
  const rule = rules.find((candidate) => candidate.prelude === 'p');
  if (!rule) throw new Error('globals.css no longer declares a bare `p` rule');
  return rule.line;
})();

/** Every top-level rule this ticket added, by prelude. */
const DISCUSSION_PRELUDES = [
  '.disc',
  '.disc-facets',
  '.disc-chip-glyph',
  '.disc-note',
  '.disc-state',
  '.disc-min-h',
  '.disc-list',
  '.disc-thread',
  '.disc-thread:last-child',
  '.disc-thread__head',
  '.disc-thread__link',
  '.disc-thread__link:hover .disc-thread__element,\n.disc-thread__link:focus-visible .disc-thread__element',
  '.disc-thread__element',
  '.disc-thread__glyph',
  '.disc-thread__version',
  '.disc-thread__excerpt',
  '.disc-thread__meta',
  '.disc-thread__unresolved',
  '.disc-more',
  '.disc-more__error',
  '.disc-more__count',
] as const;

/**
 * Collapse a prelude's whitespace so a multi-line selector list compares by content.
 *
 * @param prelude - The selector text.
 * @returns It with whitespace runs collapsed to one space.
 */
function normalize(prelude: string): string {
  return prelude.replace(/\s+/g, ' ').trim();
}

/**
 * Look one of this ticket's rules up.
 *
 * @param prelude - The rule's selector.
 * @returns The rule.
 */
function discussionRule(prelude: string): CssRule {
  const rule = rules.find((candidate) => normalize(candidate.prelude) === normalize(prelude));
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
  const value = parseDeclarations(discussionRule(prelude).body).get(property);
  if (value === undefined) throw new Error(`\`${prelude}\` declares no \`${property}\``);
  return value;
}

/** The discussion block, from its banner to the next banner (or the end of the file). */
const SECTION = (() => {
  const start = css.indexOf('PROJECT DISCUSSION  (COL-1.3, #4515)');
  if (start < 0) throw new Error('globals.css has no project-discussion section');
  const bannerStart = css.lastIndexOf('/* =', start);
  const next = css.indexOf('/* =', start);
  return css.slice(bannerStart < 0 ? start : bannerStart, next < 0 ? css.length : next);
})();

/** The same block with its comments removed. */
const SECTION_CODE = SECTION.replace(/\/\*[\s\S]*?\*\//g, '');

describe('the project-discussion section of globals.css', () => {
  it('declares every rule the panel references', () => {
    const missing = DISCUSSION_PRELUDES.filter(
      (prelude) => !rules.some((rule) => normalize(rule.prelude) === normalize(prelude))
    );
    expect(missing).toEqual([]);
  });

  it('declares only disc- classes, and each one the panel uses', () => {
    const classes = new Set([...SECTION_CODE.matchAll(/\.(disc[a-z0-9_-]*)/g)].map((match) => match[1]));
    expect([...classes].sort()).toEqual(
      [
        'disc',
        'disc-chip-glyph',
        'disc-facets',
        'disc-list',
        'disc-min-h',
        'disc-more',
        'disc-more__count',
        'disc-more__error',
        'disc-note',
        'disc-state',
        'disc-thread',
        'disc-thread__element',
        'disc-thread__excerpt',
        'disc-thread__glyph',
        'disc-thread__head',
        'disc-thread__link',
        'disc-thread__meta',
        'disc-thread__unresolved',
        'disc-thread__version',
      ].sort()
    );
  });

  it('sits after the unlayered p base rule it has to outrank', () => {
    // `.disc-note`, `.disc-thread__excerpt` and `.disc-thread__meta` are `p`s.
    for (const prelude of DISCUSSION_PRELUDES) {
      expect(discussionRule(prelude).line).toBeGreaterThan(BASE_TYPE_RULE_LINE);
    }
  });

  it('names no colour — every hue resolves through the token layer', () => {
    for (const prelude of DISCUSSION_PRELUDES) {
      for (const [, value] of parseDeclarations(discussionRule(prelude).body)) {
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
  it('states nothing in px but a hairline', () => {
    for (const prelude of DISCUSSION_PRELUDES) {
      for (const [property, value] of parseDeclarations(discussionRule(prelude).body)) {
        const offending = value.match(/(?<!\d)(\d*\.?\d+)px/g)?.filter((px) => px !== '1px') ?? [];
        expect({ prelude, property, offending }).toEqual({ prelude, property, offending: [] });
      }
    }
  });

  it('measures every font size through the type scale', () => {
    for (const prelude of DISCUSSION_PRELUDES) {
      const size = parseDeclarations(discussionRule(prelude).body).get('font-size');
      if (size === undefined) continue;
      expect(size).toMatch(/^var\(--fs-/);
    }
  });

  it('spends spacing tokens for gaps and padding', () => {
    for (const [prelude, property] of [
      ['.disc-facets', 'gap'],
      ['.disc-thread', 'padding'],
      ['.disc-thread__head', 'gap'],
      ['.disc-more', 'padding'],
    ] as const) {
      expect(declaration(prelude, property)).toContain('var(--space-');
    }
  });

  it('sizes glyphs from the shared icon metric', () => {
    for (const prelude of ['.disc-chip-glyph', '.disc-thread__glyph']) {
      expect(declaration(prelude, 'inline-size')).toBe('var(--icon-dense)');
      expect(declaration(prelude, 'block-size')).toBe('var(--icon-dense)');
    }
  });
});

describe('overflow', () => {
  it('gives every flex holder of a long name a zero minimum', () => {
    for (const prelude of [
      '.disc',
      '.disc-facets',
      '.disc-thread',
      '.disc-thread__head',
      '.disc-thread__link',
      '.disc-thread__element',
    ]) {
      expect(declaration(prelude, 'min-inline-size')).toBe('0');
    }
  });

  it('breaks a long element name or excerpt rather than widening its row', () => {
    expect(declaration('.disc-thread__element', 'overflow-wrap')).toBe('anywhere');
    expect(declaration('.disc-thread__excerpt', 'overflow-wrap')).toBe('anywhere');
  });

  it('wraps the toolbar groups, the row head, the meta line and the footer', () => {
    for (const prelude of ['.disc-facets', '.disc-thread__head', '.disc-thread__meta', '.disc-more']) {
      expect(declaration(prelude, 'flex-wrap')).toBe('wrap');
    }
  });
});

describe('ink', () => {
  it('inks the link with the strongest ink, never the accent', () => {
    expect(declaration('.disc-thread__link', 'color')).toBe('var(--fg)');
    expect(SECTION_CODE).not.toMatch(/var\(--accent\)/);
  });

  it('marks the link on hover and focus with an underline, not a colour', () => {
    const prelude =
      '.disc-thread__link:hover .disc-thread__element,\n.disc-thread__link:focus-visible .disc-thread__element';
    expect(declaration(prelude, 'text-decoration')).toBe('underline');
  });

  it('keeps quiet text at --fg-muted, never --fg-subtle or a tone', () => {
    expect(SECTION_CODE).not.toContain('--fg-subtle');
    expect(SECTION_CODE).not.toContain('--fg-faint');
    expect(SECTION_CODE).not.toMatch(/var\(--(?:ok|warn|danger|info)-fg\)/);
    for (const prelude of ['.disc-note', '.disc-thread__version', '.disc-thread__meta', '.disc-more__count']) {
      expect(declaration(prelude, 'color')).toBe('var(--fg-muted)');
    }
  });
});
