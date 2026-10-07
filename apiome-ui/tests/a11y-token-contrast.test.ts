/**
 * Token contrast gate — HIVE-10.2 (#5338), `docs/mockups/DESIGN.md` §9.
 *
 * "Themes are tested for 4.5:1 body / 3:1 large text", and High contrast holds body text to
 * AAA (7:1). This suite is the deterministic half of that promise: it resolves every
 * text-bearing token pair under every palette straight from `globals.css` and fails the build
 * the moment a theme regresses below its threshold. Rendered contrast (real compositing,
 * inherited backgrounds) stays the job of the Playwright axe gate in `e2e/a11y/`.
 *
 * Tokens are judged by the role DESIGN.md gives them:
 *
 *   - **text** tokens (`--fg`, `--fg-muted`, `--fg-subtle`, every `-fg` ink, `--ink-fg`,
 *     `--honey-ink`, `--fg-on-accent` on a danger button) must clear 4.5:1 — 7:1 in
 *     High contrast — on every surface they are placed on;
 *   - **mark** hues (`--accent`, `--ok`, `--danger`…: dots, bars, icons, the solid focus ring)
 *     must clear 3:1 (SC 1.4.11 non-text contrast, and large text);
 *   - `--fg-faint` is the disabled / decorative tier, which SC 1.4.3 exempts, and is not gated.
 *
 * A pair that cannot meet its threshold without breaking the design is recorded in
 * {@link DEVIATIONS} with a reason. The ledger is exact both ways: a new failure fails the
 * suite, and so does an entry that now passes (delete it — the ledger may only shrink).
 *
 * Mark hues are only gated at 3:1, so painting small body text with one (`text-warn`,
 * `color: var(--accent)`) can still fall under 4.5:1. Existing uses are counted in
 * {@link MARK_TEXT_BASELINE}; the count may only go down. New text uses the `-fg` ink.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import {
  compositeOver,
  contrastRatio,
  readGlobalsCss,
  readThemeBlocks,
  readTokenLayer,
  resolveThemeToken,
} from './helpers/design-tokens';
import { WCAG_AA_LARGE_TEXT_MIN, WCAG_AA_NORMAL_TEXT_MIN, type Rgb } from './helpers/tailwind-contrast';
import { themes } from '../src/app/config/themes';

/** WCAG 2.2 AAA minimum for normal-size text (SC 1.4.6), the High contrast promise. */
const WCAG_AAA_NORMAL_TEXT_MIN = 7;

/**
 * Head-room above each threshold. Browsers and axe composite translucent fills in floating
 * point and round differently from this suite, so a pair measured at exactly 4.50 here can
 * render at 4.49. The gate holds every pair a little above the line so it never passes a token
 * the rendered axe gate would fail.
 */
const MARGIN = 0.05;

const css = readGlobalsCss();
const layer = readTokenLayer(css);
const blocks = readThemeBlocks(css);

/** Every palette a user can see: each catalogue theme except `system`, which resolves to one. */
const PALETTES = themes.map((theme) => theme.id).filter((id) => id !== 'system');

/** Status families: a saturated mark, a `-soft` chip fill and a `-fg` ink. */
const FAMILIES = ['ok', 'warn', 'danger', 'info', 'violet', 'orange', 'rose', 'neutral', 'honey'];

/** Hues used as marks on a page (dots, bars, icons, focus ring). */
const MARKS = ['accent', 'ok', 'warn', 'danger', 'violet', 'orange', 'rose', 'neutral', 'honey'];

/** One checked pairing: `fg` painted over `bg`, which itself sits on the theme's card surface. */
export interface ContrastPair {
  /** Token name without `--color-`, e.g. `fg-muted`. */
  fg: string;
  /** Token name without `--color-`, e.g. `surface`. */
  bg: string;
  /** `text` (4.5:1, 7:1 in High contrast) or `mark` (3:1). */
  role: 'text' | 'mark';
  /**
   * What a translucent `bg` is composited over, without `--color-`. Defaults to `surface` (a
   * card); chips are also checked over `canvas`, `subtle` and `inset`, where tables, toolbars
   * and card footers put them.
   */
  over?: string;
}

/** One accepted shortfall, with the reason it cannot move. */
interface Deviation {
  palette: string;
  fg: string;
  bg: string;
  reason: string;
}

/**
 * The pair matrix. Each text tier is checked on the surfaces it is actually placed on.
 *
 * @returns Every pair the gate evaluates, per palette.
 */
export function contrastPairs(): ContrastPair[] {
  const pairs: ContrastPair[] = [];
  const text = (fg: string, bgs: string[]) => bgs.forEach((bg) => pairs.push({ fg, bg, role: 'text' }));
  const mark = (fg: string, bgs: string[]) => bgs.forEach((bg) => pairs.push({ fg, bg, role: 'mark' }));

  const pageSurfaces = ['canvas', 'surface', 'subtle', 'surface-muted', 'rail'];
  text('fg', [...pageSurfaces, 'inset', 'accent-soft']);
  text('fg-muted', [...pageSurfaces, 'inset', 'accent-soft']);
  text('fg-subtle', pageSurfaces);
  // Links and selected-row ink. `--accent` itself is a mark; link text uses `--accent-fg`.
  text('accent-fg', ['canvas', 'surface', 'accent-soft']);
  for (const family of FAMILIES) {
    text(`${family}-fg`, [`${family}-soft`, 'canvas', 'surface']);
    for (const over of ['canvas', 'subtle', 'inset']) pairs.push({ fg: `${family}-fg`, bg: `${family}-soft`, role: 'text', over });
  }
  // A deleted project card's amber recovery footer holds a danger-soft "Permanently delete".
  pairs.push({ fg: 'danger-fg', bg: 'danger-soft', role: 'text', over: 'warn-soft' });
  text('ink-fg', ['ink']);
  text('honey-ink', ['honey']);
  // The danger button's label; on accent / ok fills the same ink only ever paints icons.
  text('fg-on-accent', ['danger']);
  mark('fg-on-accent', ['accent', 'ok']);
  for (const hue of MARKS) mark(hue, ['canvas', 'surface']);
  return pairs;
}

/**
 * Accepted shortfalls. Keep each reason specific; a stale entry fails the suite.
 */
const DEVIATIONS: Deviation[] = [
  {
    palette: 'light',
    fg: 'honey',
    bg: 'canvas',
    reason: 'Brand honey is a fill behind --honey-ink (8.75:1), never a mark on a light page; darkening it would change the brand.',
  },
  {
    palette: 'light',
    fg: 'honey',
    bg: 'surface',
    reason: 'Brand honey is a fill behind --honey-ink (8.75:1), never a mark on a light page; darkening it would change the brand.',
  },
  {
    palette: 'whiteboard',
    fg: 'honey',
    bg: 'canvas',
    reason: 'Brand honey is a fill behind --honey-ink (8.75:1), never a mark on a light page; darkening it would change the brand.',
  },
  {
    palette: 'whiteboard',
    fg: 'honey',
    bg: 'surface',
    reason: 'Brand honey is a fill behind --honey-ink (8.75:1), never a mark on a light page; darkening it would change the brand.',
  },
];

const WHITE: Rgb = { r: 255, g: 255, b: 255 };

/**
 * A token under a palette, composited onto that palette's card surface.
 *
 * @param token Token name without `--color-`.
 * @param palette Palette id; `light` resolves against `:root` alone.
 * @param backdrop What the token is painted over (translucent tokens are composited).
 * @returns The opaque colour a reader sees.
 */
function paint(token: string, palette: string, backdrop?: Rgb): Rgb {
  const block = palette === 'light' ? undefined : blocks.get(palette);
  const surface = compositeOver(resolveThemeToken('--color-surface', layer, block), WHITE);
  return compositeOver(resolveThemeToken(`--color-${token}`, layer, block), backdrop ?? surface);
}

/**
 * The contrast of one pair under one palette.
 *
 * @param pair The pairing.
 * @param palette Palette id.
 * @returns The WCAG ratio.
 */
export function pairRatio(pair: ContrastPair, palette: string): number {
  const background = paint(pair.bg, palette, pair.over ? paint(pair.over, palette) : undefined);
  return contrastRatio(paint(pair.fg, palette, background), background);
}

/**
 * The threshold a pair must clear under a palette.
 *
 * @param pair The pairing.
 * @param palette Palette id.
 * @returns 7 for High contrast text, 4.5 for other text, 3 for marks — each plus {@link MARGIN}.
 */
export function thresholdFor(pair: ContrastPair, palette: string): number {
  if (pair.role === 'mark') return WCAG_AA_LARGE_TEXT_MIN + MARGIN;
  return (palette === 'high-contrast' ? WCAG_AAA_NORMAL_TEXT_MIN : WCAG_AA_NORMAL_TEXT_MIN) + MARGIN;
}

const key = (palette: string, fg: string, bg: string, over?: string) =>
  `${palette}: ${fg} on ${bg}${over ? ` over ${over}` : ''}`;

/** Every failing pair, as `palette: fg on bg (ratio < threshold)` keyed lines. */
function failures(): Map<string, string> {
  const found = new Map<string, string>();
  for (const palette of PALETTES) {
    for (const pair of contrastPairs()) {
      const ratio = pairRatio(pair, palette);
      const min = thresholdFor(pair, palette);
      if (ratio < min) {
        const id = key(palette, pair.fg, pair.bg, pair.over);
        found.set(id, `${id} (${ratio.toFixed(2)} < ${min})`);
      }
    }
  }
  return found;
}

describe('token contrast gate (HIVE-10.2)', () => {
  const failing = failures();
  const ledger = new Set(DEVIATIONS.map((d) => key(d.palette, d.fg, d.bg)));

  it('checks every palette in the theme catalogue', () => {
    expect(PALETTES).toEqual(
      expect.arrayContaining(['light', 'dark', 'high-contrast', 'blueprint', 'whiteboard', 'solarized', 'nord', 'darcula']),
    );
    expect(PALETTES).toHaveLength(8);
  });

  it('has no failing pair outside the deviation ledger', () => {
    const unexpected = [...failing.entries()].filter(([k]) => !ledger.has(k)).map(([, line]) => line);
    expect(unexpected).toEqual([]);
  });

  it('has no stale deviation (an entry that now passes must be deleted)', () => {
    const stale = [...ledger].filter((k) => !failing.has(k));
    expect(stale).toEqual([]);
  });

  it('gives every deviation a reason and never excuses text in High contrast', () => {
    for (const deviation of DEVIATIONS) {
      expect(deviation.reason.length).toBeGreaterThan(20);
      expect(deviation.palette).not.toBe('high-contrast');
    }
  });

  it.each(PALETTES)('%s holds body text at AA (AAA in High contrast) on the page and on cards', (palette) => {
    for (const bg of ['canvas', 'surface']) {
      const pair: ContrastPair = { fg: 'fg-muted', bg, role: 'text' };
      expect(pairRatio(pair, palette)).toBeGreaterThanOrEqual(thresholdFor(pair, palette));
    }
  });

  it('measures pairs the way a reader sees them (translucent chips composited)', () => {
    // dark --ok-soft is 14% green over the card; its ink must be judged on that mix, not on the raw rgba.
    const chip = pairRatio({ fg: 'ok-fg', bg: 'ok-soft', role: 'text' }, 'dark');
    expect(chip).toBeGreaterThan(WCAG_AA_NORMAL_TEXT_MIN);
    expect(chip).toBeLessThan(21);
  });
});

/**
 * Small-text uses of a mark hue when this gate landed (HIVE-10.2). The count must match
 * exactly: lower the number in the same change that moves a use to its `-fg` ink (so the
 * gain is locked in), and never raise it.
 */
const MARK_TEXT_BASELINE: Record<string, number> = {
  accent: 132,
  ok: 59,
  warn: 48,
  danger: 84,
  violet: 10,
  orange: 2,
  rose: 1,
  neutral: 1,
  honey: 2,
};

/**
 * Every source file under `src/` with one of the given extensions.
 *
 * @param directory Directory to walk.
 * @param extensions Extensions to keep, with the leading dot.
 * @returns Absolute paths.
 */
function sourceFiles(directory: string, extensions: string[]): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(directory)) {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) found.push(...sourceFiles(path, extensions));
    else if (extensions.some((extension) => entry.endsWith(extension))) found.push(path);
  }
  return found;
}

/**
 * How many times a mark hue paints text: `text-<hue>` utilities in TS/TSX plus
 * `color: var(--<hue>)` declarations in CSS.
 *
 * @param hue A {@link MARKS} entry.
 * @returns The use count across `src/`.
 */
export function markTextUses(hue: string): number {
  const root = join(__dirname, '..', 'src');
  const utility = new RegExp(`(^|[^a-z-])text-${hue}(/[0-9]+)?(?=[^a-z0-9-]|$)`, 'gm');
  const declaration = new RegExp(`(^|[;{\\s])color:\\s*var\\(--(color-)?${hue}\\)`, 'g');
  let count = 0;
  for (const file of sourceFiles(root, ['.ts', '.tsx'])) count += (readFileSync(file, 'utf8').match(utility) ?? []).length;
  for (const file of sourceFiles(root, ['.css'])) count += (readFileSync(file, 'utf8').match(declaration) ?? []).length;
  return count;
}

describe('mark hues as small text (ratchet)', () => {
  it.each(MARKS)('keeps %s text uses at the locked baseline', (hue) => {
    expect(markTextUses(hue)).toBe(MARK_TEXT_BASELINE[hue]);
  });
});
