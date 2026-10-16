/**
 * The stylesheet half of `FactsLine` (HIVE-11.5, #5601).
 *
 * jsdom compiles no stylesheet, so this reads the `FACTS LINE` section of `globals.css` and
 * pins what the ticket asks of it: tokens only, no `px` type, a line no taller than 32 px in
 * comfortable density, wrapping rather than horizontal scroll, and tabular figures.
 */

import {
  contrastRatio,
  hexToRgb,
  parseDeclarations,
  readGlobalsCss,
  readThemeBlocks,
  readTokenLayer,
  resolveThemeToken,
  topLevelRules,
  type CssRule,
} from './helpers/design-tokens';

const css = readGlobalsCss();
const rules = topLevelRules(css);
const tokens = readTokenLayer(css);
const themes = readThemeBlocks(css);

/** Every rule the section introduces. */
const FACTS_RULES: CssRule[] = rules.filter((rule) => /\.facts(-line)?(__|\b)/.test(rule.prelude));

/**
 * The declarations of the one top-level rule with this prelude.
 *
 * @param prelude Exact prelude, whitespace-collapsed.
 * @returns Property to value.
 * @throws When the stylesheet has none, or more than one.
 */
function declarationsOf(prelude: string): Map<string, string> {
  const matches = rules.filter((rule) => rule.prelude === prelude);
  if (matches.length !== 1) {
    throw new Error(`globals.css has ${matches.length} \`${prelude}\` rules; expected exactly 1`);
  }
  return parseDeclarations(matches[0].body);
}

/**
 * A `rem` length in px at the default 16 px root.
 *
 * @param value E.g. `1.875rem`, possibly followed by a comment.
 * @returns The px value.
 */
function remToPx(value: string): number {
  const match = /([\d.]+)rem/.exec(value);
  if (!match) throw new Error(`Not a rem length: ${value}`);
  return Number(match[1]) * 16;
}

describe('facts line — tokens, not colours or pixels', () => {
  it('defines the section', () => {
    expect(FACTS_RULES.length).toBeGreaterThan(8);
  });

  it('paints every class from the token layer', () => {
    const paint = /^(color|background|background-color|border|border-(top|right|bottom|left)(-color)?|border-color|box-shadow|fill|stroke)$/;
    const offenders: string[] = [];
    for (const rule of FACTS_RULES) {
      for (const [property, value] of parseDeclarations(rule.body)) {
        if (!paint.test(property)) continue;
        if (/^(transparent|currentcolor|none|inherit|0)$/i.test(value.trim())) continue;
        if (!value.includes('var(--') || /#[0-9a-f]{3,8}\b/i.test(value)) {
          offenders.push(`${rule.prelude} { ${property}: ${value} }`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it('states no font size or height in px', () => {
    const offenders: string[] = [];
    for (const rule of FACTS_RULES) {
      for (const [property, value] of parseDeclarations(rule.body)) {
        if (!/^(font-size|line-height|height|min-height)$/.test(property)) continue;
        if (/\d+px/.test(value)) offenders.push(`${rule.prelude} { ${property}: ${value} }`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('sets numbers in tabular figures', () => {
    expect(declarationsOf('.facts').get('font-variant-numeric')).toBe('tabular-nums');
  });
});

describe('facts line — height and wrapping', () => {
  it('is the small-control height, ≤ 32 px in comfortable density', () => {
    expect(declarationsOf('.facts').get('min-height')).toBe('var(--control-h-sm)');
    const comfortable = resolveThemeToken('--control-h-sm', tokens);
    expect(remToPx(comfortable)).toBeLessThanOrEqual(32);
  });

  it('wraps the line and every fact rather than scrolling sideways', () => {
    expect(declarationsOf('.facts').get('flex-wrap')).toBe('wrap');
    expect(declarationsOf('.facts__list').get('flex-wrap')).toBe('wrap');
    expect(declarationsOf('.facts__item').get('min-width')).toBe('0');
  });

  it('hides the collapsed stats region despite any display rule', () => {
    expect(declarationsOf('.facts-line__stats[hidden]').get('display')).toBe('none');
  });
});

describe('facts line — contrast in every theme', () => {
  const themeIds = ['light', ...themes.keys()];

  it('keeps labels and muted asides at AA, and the dot above the 3:1 mark floor', () => {
    expect(declarationsOf('.facts').get('color')).toBe('var(--fg-muted)');
    expect(declarationsOf('.facts__item + .facts__item::before').get('background')).toBe('var(--fg-subtle)');
    expect(themeIds.length).toBeGreaterThanOrEqual(8);
    for (const id of themeIds) {
      const block = id === 'light' ? undefined : themes.get(id);
      const surface = hexToRgb(resolveThemeToken('--bg-canvas', tokens, block));
      const muted = contrastRatio(hexToRgb(resolveThemeToken('--fg-muted', tokens, block)), surface);
      const dot = contrastRatio(hexToRgb(resolveThemeToken('--fg-subtle', tokens, block)), surface);
      expect({ id, muted: muted >= 4.5, dot: dot >= 3 }).toEqual({ id, muted: true, dot: true });
    }
  });
});
