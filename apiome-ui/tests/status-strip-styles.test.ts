/**
 * The stylesheet half of the `StatusStrip` primitive (HIVE-11.1, #5597).
 *
 * jsdom compiles no stylesheet, so `tests/status-strip.test.tsx` cannot pin how the strip
 * looks. This suite reads the `STATUS STRIP` section of `globals.css` the way
 * `hive-stepper-styles.test.ts` does and pins the promises the component leans on:
 *
 *   1. Every colour is a token (no raw hex), so the strip follows all nine themes.
 *   2. No font size, and no control height, is frozen in `px` — densities and font scales.
 *   3. An open chip's ink clears WCAG AA on its tint in every theme.
 *   4. The collapsed detail row really hides (`display: flex` would otherwise beat `[hidden]`).
 */

import {
  compositeOver,
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

/** WCAG AA for normal-size text — the chip label is `--fs-sm`. */
const WCAG_AA_NORMAL_TEXT_MIN = 4.5;

/** Every rule the section introduces. */
const STRIP_RULES: CssRule[] = rules.filter((rule) => /\.status-(strip|chip)/.test(rule.prelude));

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

describe('status strip — tokens, not colours or pixels', () => {
  it('defines the section', () => {
    expect(STRIP_RULES.length).toBeGreaterThan(10);
  });

  it('paints every class from the token layer', () => {
    const paint = /^(color|background|background-color|border|border-.*|box-shadow|fill|stroke)$/;
    const offenders: string[] = [];
    for (const rule of STRIP_RULES) {
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

  it('states no font size or control height in px', () => {
    const offenders: string[] = [];
    for (const rule of STRIP_RULES) {
      for (const [property, value] of parseDeclarations(rule.body)) {
        if (!/^(font-size|line-height|height|min-height)$/.test(property)) continue;
        if (/\d+px/.test(value)) offenders.push(`${rule.prelude} { ${property}: ${value} }`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('sizes the chip from the small-control token, so density reaches it', () => {
    expect(declarationsOf('.status-chip').get('min-height')).toBe('var(--control-h-sm)');
    expect(declarationsOf('.status-chip').get('font-size')).toBe('var(--fs-sm)');
  });
});

describe('status strip — open chips read in every theme', () => {
  const themeIds = ['light', ...themes.keys()];

  it('walks the base theme and every `html[data-theme]` block', () => {
    expect(themeIds).toEqual(expect.arrayContaining(['light', 'dark', 'high-contrast']));
    expect(themeIds.length).toBeGreaterThanOrEqual(8);
  });

  it.each(['ok', 'accent', 'warn', 'danger'])('draws an open %s chip as `-fg` on `-soft`', (tone) => {
    const open = declarationsOf(`.status-chip--${tone}.is-open`);
    expect(open.get('background')).toBe(`var(--${tone}-soft)`);
    expect(open.get('color')).toBe(`var(--${tone}-fg)`);

    for (const id of themeIds) {
      const block = id === 'light' ? undefined : themes.get(id);
      const surface = hexToRgb(resolveThemeToken('--bg-surface', tokens, block));
      const tint = compositeOver(resolveThemeToken(`--${tone}-soft`, tokens, block), surface);
      const ink = hexToRgb(resolveThemeToken(`--${tone}-fg`, tokens, block));
      expect({ id, ratio: contrastRatio(ink, tint) >= WCAG_AA_NORMAL_TEXT_MIN }).toEqual({
        id,
        ratio: true,
      });
    }
  });

  it('sets closed chips and detail copy in `--fg-muted`, which clears AA on the surface', () => {
    expect(declarationsOf('.status-chip').get('color')).toBe('var(--fg-muted)');
    expect(declarationsOf('.status-strip__detail').get('color')).toBe('var(--fg-muted)');
    expect(declarationsOf('.status-strip__caption').get('color')).toBe('var(--fg-muted)');
    for (const id of themeIds) {
      const block = id === 'light' ? undefined : themes.get(id);
      const ratio = contrastRatio(
        hexToRgb(resolveThemeToken('--fg-muted', tokens, block)),
        hexToRgb(resolveThemeToken('--bg-surface', tokens, block))
      );
      expect({ id, ok: ratio >= WCAG_AA_NORMAL_TEXT_MIN }).toEqual({ id, ok: true });
    }
  });
});

describe('status strip — layout', () => {
  it('hides the collapsed detail row despite its `display: flex`', () => {
    expect(declarationsOf('.status-strip__detail').get('display')).toBe('flex');
    expect(declarationsOf('.status-strip__detail[hidden]').get('display')).toBe('none');
  });

  it('wraps the row rather than scrolling the page sideways', () => {
    expect(declarationsOf('.status-strip__row').get('flex-wrap')).toBe('wrap');
    expect(declarationsOf('.status-strip__chips').get('flex-wrap')).toBe('wrap');
  });

  it('keeps the chip hairline beside the app-wide focus ring', () => {
    expect(declarationsOf('.status-chip:focus-visible').get('box-shadow')).toBe(
      'inset 0 0 0 1px var(--border), var(--shadow-focus)'
    );
  });
});
