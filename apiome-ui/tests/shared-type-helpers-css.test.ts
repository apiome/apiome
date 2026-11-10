/**
 * The shared type helpers (SUX-1.10, apiome#6751).
 *
 * Every screen family in `globals.css` used to restate its own quiet line, caps label,
 * meta line and field label under its own prefix — `.prj-quiet`, `.cid-caps`, `.shd-meta`,
 * `.sr-label` and seventeen more, each with the same declarations. They are now four shared
 * classes: `.hive-quiet`, `.hive-meta`, `.hive-caps` and `.hive-label`.
 *
 * This suite pins three things:
 *
 *   1. **The four helpers say what the copies said**, in one place, after the unlayered
 *      `p` / `h1`–`h4` base rules they have to outrank.
 *   2. **The copies stay gone.** None of the 21 retired class names is declared or used, and
 *      no per-screen `-quiet` / `-meta` / `-caps` / `-label` rule may restate a helper's
 *      declarations. The eight that differ are listed by name so a new one fails here.
 *   3. **Quiet text clears AA** in all nine appearances on the plain surface.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';

import {
  compositeOver,
  contrastRatio,
  parseDeclarations,
  readGlobalsCss,
  readThemeBlocks,
  readTokenLayer,
  resolveThemeToken,
  topLevelRules,
  type CssRule,
  type Rgb,
} from './helpers/design-tokens';

const css = readGlobalsCss();
const rules = topLevelRules(css);
const tokens = readTokenLayer(css);

/** The light default, then every `html[data-theme]` block — the nine appearances. */
const APPEARANCES = [
  ['light', undefined] as const,
  ...[...readThemeBlocks(css).entries()].map(([id, block]) => [id, block] as const),
];

/** WCAG AA for normal-size text. */
const WCAG_AA_NORMAL_TEXT_MIN = 4.5;

/** Pure white, the last thing behind every surface. */
const PAPER: Rgb = { r: 255, g: 255, b: 255 };

/** What each helper declares, property by property. */
const HELPERS = {
  '.hive-quiet': { 'font-size': 'var(--fs-xs)', color: 'var(--fg-muted)' },
  '.hive-meta': {
    display: 'block',
    'font-size': 'var(--fs-2xs)',
    color: 'var(--fg-muted)',
    'overflow-wrap': 'anywhere',
  },
  '.hive-caps': {
    'font-size': 'var(--fs-2xs)',
    'font-weight': '600',
    'letter-spacing': 'var(--track-caps)',
    'text-transform': 'uppercase',
    color: 'var(--fg-muted)',
  },
  '.hive-label': { 'font-size': 'var(--fs-sm)', 'font-weight': '500', color: 'var(--fg)' },
} as const;

/** The per-screen copies this ticket retired, with the helper that replaced each. */
const RETIRED: Record<string, keyof typeof HELPERS> = {
  'launch-caps': '.hive-caps',
  'acct-caps': '.hive-caps',
  'tnt-caps': '.hive-caps',
  'mbr-caps': '.hive-caps',
  'akey-secret-label': '.hive-caps',
  'aud-caps': '.hive-caps',
  'lw-caps': '.hive-caps',
  'cid-caps': '.hive-caps',
  'repo-det-caps': '.hive-caps',
  'sg-quiet': '.hive-quiet',
  'prj-quiet': '.hive-quiet',
  'ver-quiet': '.hive-quiet',
  'vdlg-quiet': '.hive-quiet',
  'prm-quiet': '.hive-quiet',
  'cat-quiet': '.hive-quiet',
  'cid-quiet': '.hive-quiet',
  'repo-quiet': '.hive-quiet',
  'xstd-quiet': '.hive-quiet',
  'shd-meta': '.hive-meta',
  'cnx-meta': '.hive-meta',
  'sr-label': '.hive-label',
};

/**
 * The per-screen helpers that are *not* identical to a shared one, so they stay in their
 * own blocks for HIVE to resolve (SUX roadmap §4, SUX-1.10). Adding to this list needs a
 * reason: a rule that only restates a helper belongs on the helper.
 */
const NOT_IDENTICAL = [
  'aud-quiet', // `--fs-sm`, not `--fs-xs`
  'cid-meta', // a flex row, not a type step
  'lw-quiet', // adds `min-width: 0`
  'rail-label', // a display toggle for the collapsible rail
  'vdlg-caps', // inline-flex with a gap and 0.06em tracking
  'xdlv-quiet', // `--fs-sm`, not `--fs-xs`
  'xstd-axis-label', // an SVG `fill`, not a `color`
  'xstd-caps', // flex, `--fg` ink and 0.04em tracking
];

/**
 * The one top-level rule with a given prelude.
 *
 * @param prelude Selector text, exactly as written in the stylesheet.
 * @returns The rule.
 * @throws When the stylesheet has none or more than one.
 */
function ruleFor(prelude: string): CssRule {
  const found = rules.filter((rule) => rule.prelude === prelude);
  if (found.length !== 1) {
    throw new Error(`expected exactly one \`${prelude}\` rule in globals.css, found ${found.length}`);
  }
  return found[0];
}

/**
 * A rule body as a plain object, so two rules compare regardless of declaration order.
 *
 * @param rule The rule.
 * @returns Property to value.
 */
function declarationsOf(rule: CssRule): Record<string, string> {
  return Object.fromEntries(parseDeclarations(rule.body));
}

/**
 * The opaque colour a token resolves to in one appearance, flattened onto its backdrop.
 *
 * @param name The token.
 * @param appearance The theme block, or `undefined` for the light default.
 * @param backdrop What is painted behind it.
 * @returns The resulting opaque channels.
 */
function paint(name: string, appearance: unknown, backdrop: Rgb): Rgb {
  return compositeOver(resolveThemeToken(name, tokens, appearance as never), backdrop);
}

/**
 * Every tracked source file that can carry a class name: components, e2e specs and the
 * fixture dumps the docs screenshots are drawn from.
 *
 * @returns Paths relative to the apiome-ui workspace.
 */
function sourceFiles(): string[] {
  const listed = execFileSync('git', ['ls-files', 'src', 'e2e'], {
    cwd: join(__dirname, '..'),
    encoding: 'utf8',
  });
  return listed
    .split('\n')
    .filter((path) => /\.(tsx?|html)$/.test(path));
}

describe('the shared type helpers', () => {
  it.each(Object.entries(HELPERS))('declares %s exactly as the copies did', (prelude, expected) => {
    expect(declarationsOf(ruleFor(prelude))).toEqual(expected);
  });

  it('sits after the unlayered p and h1–h4 base rules it has to outrank', () => {
    const base = Math.max(ruleFor('p').line, ruleFor('h2').line, ruleFor('h1, h2, h3, h4').line);
    for (const prelude of Object.keys(HELPERS)) {
      expect({ prelude, after: ruleFor(prelude).line > base }).toEqual({ prelude, after: true });
    }
  });

  it('sits before every screen block, so a screen rule can still refine a helper', () => {
    // The first screen block that used a helper was the launcher; a later rule of equal
    // specificity (`.tnt-hist-row`'s font size, `.cnx-mono`'s wrapping) must keep winning.
    const firstScreen = ruleFor('.launch-eyebrow').line;
    for (const prelude of Object.keys(HELPERS)) {
      expect({ prelude, before: ruleFor(prelude).line < firstScreen }).toEqual({
        prelude,
        before: true,
      });
    }
  });
});

describe('the per-screen copies stay gone', () => {
  it('declares none of the retired classes', () => {
    const declared = Object.keys(RETIRED).filter((name) =>
      new RegExp(`(^|[\\s,>+~(])\\.${name}(?![\\w-])`).test(
        rules.map((rule) => rule.prelude).join('\n'),
      ),
    );
    expect(declared).toEqual([]);
  });

  it('uses none of the retired classes in a component, spec or fixture', () => {
    const pattern = new RegExp(`(?<![\\w-])(${Object.keys(RETIRED).join('|')})(?![\\w-])`);
    const root = join(__dirname, '..');
    const offenders = sourceFiles().filter((path) =>
      pattern.test(readFileSync(join(root, path), 'utf8')),
    );
    expect(offenders).toEqual([]);
  });

  it('lists every per-screen helper that is left, by name', () => {
    const left = rules
      .map((rule) => rule.prelude)
      .filter((prelude) => /^\.(?!hive-)[a-z0-9-]+-(quiet|meta|caps|label)$/.test(prelude))
      .map((prelude) => prelude.slice(1))
      .sort();
    expect(left).toEqual([...NOT_IDENTICAL].sort());
  });

  it('lets no per-screen helper restate a shared one', () => {
    const shared = Object.values(HELPERS).map((expected) => JSON.stringify(sorted(expected)));
    const restating = NOT_IDENTICAL.filter((name) =>
      shared.includes(JSON.stringify(sorted(declarationsOf(ruleFor(`.${name}`))))),
    );
    expect(restating).toEqual([]);
  });
});

describe('quiet text clears AA in every theme', () => {
  it.each(APPEARANCES)('in the %s appearance, on the plain surface', (_id, block) => {
    const ground = paint('--bg-surface', block, PAPER);
    for (const [prelude, expected] of Object.entries(HELPERS)) {
      const ink = paint(expected.color.slice(4, -1), block, PAPER);
      const ratio = contrastRatio(ink, ground);
      expect({ prelude, clears: ratio >= WCAG_AA_NORMAL_TEXT_MIN }).toEqual({
        prelude,
        clears: true,
      });
    }
  });
});

/**
 * An object with its keys in order, so two declaration sets serialise the same way.
 *
 * @param record Property to value.
 * @returns The same entries, key-sorted.
 */
function sorted(record: Record<string, string>): Record<string, string> {
  return Object.fromEntries(Object.entries(record).sort(([a], [b]) => a.localeCompare(b)));
}
