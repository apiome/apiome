/**
 * Hive design-token layer — `src/app/globals.css` (HIVE-1.1, #5274).
 *
 * The redesign's premise is that colour, radius, elevation, motion and layout have exactly
 * one definition, in `@theme`, and that every later ticket only ever *swaps* those tokens
 * (HIVE-1.2 per theme, HIVE-1.3 per density) or *reads* them (Epics 2+). This suite locks
 * the four properties that premise rests on:
 *
 *   1. every token the design authority (`docs/mockups/DESIGN.md` §3.1) and the ticket's
 *      scope list name is declared and resolves to a literal — no dangling `var()`;
 *   2. the pre-Hive variable names stay retired (HIVE-10.6, #5342): the migration is over,
 *      so `--text-muted`, `--surface`, … are declared nowhere and a stray read of one fails
 *      here rather than silently resolving to nothing;
 *   3. the layering contract holds — `@theme static`, and no name declared in both
 *      `@theme` and the unlayered `:root` block (either mistake silently pins a token and
 *      breaks the per-theme swaps in `hive-theme-blocks.test.ts` without erroring);
 *   4. raw hex appears only inside a documented `hex-allow-start` / `hex-allow-end` fence;
 *   5. honey is spent only where DESIGN.md §2 spends it (HIVE-13.1, #5614): every honey
 *      token or utility outside `globals.css` sits in an allow-listed file, and every
 *      `globals.css` rule that spends one is an allow-listed rule.
 *
 * A fifth group used to pin the Radix Themes `<Theme>` props on both layouts; SUX-1.3 (#2877)
 * removed the wrapper, and `tests/radix-themes-removed.test.ts` now guards its absence.
 */

import {
  contrastRatio,
  designDocColorTokens,
  findUnfencedHex,
  hexToRgb,
  readGlobalsCss,
  readTokenLayer,
  resolveToken,
  topLevelRules,
  type TokenLayer,
} from './helpers/design-tokens';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  findHoneyUsages,
  honeyFiles,
  honeyRules,
  staleHoneyEntries,
  unlistedHoney,
} from './helpers/honey-gate';
import { WCAG_AA_LARGE_TEXT_MIN, WCAG_AA_NORMAL_TEXT_MIN } from './helpers/tailwind-contrast';

const css = readGlobalsCss();
const layer: TokenLayer = readTokenLayer(css);

/** Semantic families that each carry a base, a `-soft` fill and a `-fg` ink. */
const SEMANTIC_FAMILIES = ['ok', 'warn', 'danger', 'violet', 'orange', 'rose', 'neutral'];

/**
 * The Tailwind-facing tokens the ticket's scope list enumerates, by group.
 *
 * These are the names utilities are generated from (`bg-canvas`, `rounded-lg`,
 * `shadow-raised`, `ease-out`), so they must live in `@theme`, not in `:root`.
 */
const THEME_TOKEN_GROUPS: Record<string, string[]> = {
  surfaces: ['--color-canvas', '--color-rail', '--color-surface', '--color-subtle', '--color-inset', '--color-overlay'],
  ink: ['--color-fg', '--color-fg-muted', '--color-fg-subtle', '--color-fg-faint'],
  lines: ['--color-border', '--color-border-strong'],
  accent: [
    '--color-ink',
    '--color-accent',
    '--color-accent-soft',
    '--color-accent-fg',
    '--color-honey',
    '--color-honey-soft',
    '--color-honey-fg',
  ],
  semantic: SEMANTIC_FAMILIES.flatMap((family) => [
    `--color-${family}`,
    `--color-${family}-soft`,
    `--color-${family}-fg`,
  ]),
  radii: ['--radius-xs', '--radius-sm', '--radius-md', '--radius-lg', '--radius-xl'],
  shadows: ['--shadow-xs', '--shadow-sm', '--shadow-md', '--shadow-lg', '--shadow-raised'],
  motion: ['--ease-out', '--ease-in-out', '--dur-fast', '--dur-base', '--dur-slow'],
  layout: ['--rail-w', '--page-max'],
};

/**
 * Pre-Hive variable names, retired by HIVE-10.6 (#5342), and the Hive token that replaced
 * each one. The values document the migration for anyone reading an old branch.
 */
const RETIRED_ALIASES: Record<string, string> = {
  '--background': '--bg-canvas',
  '--foreground': '--fg',
  '--surface': '--bg-surface',
  '--surface-muted': '--bg-subtle',
  '--border-subtle': '--border',
  '--focus-ring': '--accent',
  '--text-muted': '--fg-muted',
  '--shadow-subtle': '--shadow-xs',
  '--control-height': '--control-h',
};

/**
 * The Tailwind colour utilities the pre-Hive names generated (`bg-background`,
 * `text-text-muted`, …), retired with them. `--color-surface` is not on the list: it is a
 * Hive token in its own right.
 */
const RETIRED_UTILITY_TOKENS = [
  '--color-background',
  '--color-foreground',
  '--color-surface-muted',
  '--color-border-subtle',
  '--color-text-muted',
];

describe('design authority — DESIGN.md §3.1 tokens', () => {
  const documented = designDocColorTokens();

  it('lists the colour families the Hive palette is built from', () => {
    // Guards the parser itself: a §3.1 rewrite that silently stopped matching would make
    // every assertion below vacuous.
    expect(documented).toEqual(expect.arrayContaining(['--bg-canvas', '--fg-muted', '--ink-fg', '--accent-soft']));
    expect(documented.length).toBeGreaterThanOrEqual(30);
  });

  it.each(designDocColorTokens())('%s resolves to a literal at :root', (token) => {
    expect(resolveToken(token, layer)).toMatch(/^(#|rgba?\(|color-mix\()/);
  });
});

describe('@theme token layer — ticket scope list', () => {
  it.each(Object.entries(THEME_TOKEN_GROUPS))('declares every %s token in @theme', (_group, tokens) => {
    const missing = tokens.filter((token) => !layer.theme.has(token));
    expect(missing).toEqual([]);
  });

  it.each(Object.values(THEME_TOKEN_GROUPS).flat())('%s resolves without a dangling var()', (token) => {
    expect(() => resolveToken(token, layer)).not.toThrow();
  });

  it('uses @theme static so no token is tree-shaken out of :root', () => {
    // Plain `@theme` drops variables no utility references — which, in a token layer landed
    // ahead of the components that consume it, is nearly all of them.
    expect(css).toContain('@theme static {');
    expect(css).not.toMatch(/@theme\s+(inline\s+)?\{/);
  });

  it('carries the Hive radius scale rather than Tailwind defaults', () => {
    expect(resolveToken('--radius-xs', layer)).toBe('4px');
    expect(resolveToken('--radius-sm', layer)).toBe('6px');
    expect(resolveToken('--radius-md', layer)).toBe('10px');
    expect(resolveToken('--radius-lg', layer)).toBe('14px');
    expect(resolveToken('--radius-xl', layer)).toBe('20px');
  });

  it('carries the DESIGN.md §3.4 motion durations and easing', () => {
    expect(resolveToken('--dur-fast', layer)).toBe('120ms');
    expect(resolveToken('--dur-base', layer)).toBe('180ms');
    expect(resolveToken('--dur-slow', layer)).toBe('260ms');
    expect(resolveToken('--ease-out', layer)).toBe('cubic-bezier(0.2, 0.8, 0.2, 1)');
  });

  it('carries the DESIGN.md §5.2 rail and page-width constants', () => {
    // The rail is chrome wrapped around type, so HIVE-1.6 (#5279) restated its two widths
    // in `rem` — 16.5rem is §5.2's 264px on a default 16px root, and it follows the
    // font-size preference from there. The page cap stays `px`: it is measured against the
    // viewport, and a cap that grew with the scale would force horizontal scroll.
    expect(resolveToken('--rail-w', layer)).toBe('16.5rem');
    expect(resolveToken('--rail-w-collapsed', layer)).toBe('4rem');
    expect(resolveToken('--page-max', layer)).toBe('2400px');
  });
});

describe('layering contract', () => {
  it('never declares a @theme token again in the unlayered :root block', () => {
    // `:root` is unlayered and `@theme` lands in `@layer theme`, so a duplicate name would
    // pin the token to its `:root` value and silently defeat the HIVE-1.2 theme swap.
    const shadowed = [...layer.root.keys()].filter((name) => layer.theme.has(name));
    expect(shadowed).toEqual([]);
  });

  it('drops the ad-hoc --radius-md that used to override the Tailwind radius scale', () => {
    expect(layer.root.has('--radius-md')).toBe(false);
  });

  it('routes every :root alias at a token instead of restating a value', () => {
    const literals = [...layer.root.entries()].filter(
      ([name, value]) =>
        // Type, spacing and control metrics are defined here outright; colour never is.
        // `--gradient-*` (HIVE-2.2) is not an exception to that: a gradient is a picture
        // rather than a colour, and the case below proves every stop inside one is a
        // token reference. `--hex-clip` (HIVE-2.5) is a silhouette — six points, no
        // colour — shared so the avatar hexagon and the empty-state art cannot drift.
        !/^--(app-|font-|fs-|lh-|track-|space-|control-|row-h|page-pad|card-pad|nav-item-h|target-min|table-|r-full|gradient-|hex-clip)/.test(name) &&
        !value.startsWith('var('),
    );
    expect(literals).toEqual([]);
  });

  it('builds every gradient out of tokens, so a theme swap reaches it', () => {
    const gradients = [...layer.root.entries()].filter(([name]) => name.startsWith('--gradient-'));
    expect(gradients.length).toBeGreaterThan(0);
    for (const [name, value] of gradients) {
      // Whatever is left after the geometry, the `var()`s and a `color-mix()` white point
      // must contain no colour of its own — no hex, no `rgb()`, no named hue.
      const stops = value
        // Token references, the two function wrappers, the geometry, and the achromatic
        // end-points a mix is allowed to lighten towards.
        .replace(/var\(--[a-z0-9-]+\)/g, '')
        .replace(/linear-gradient\(|color-mix\(in srgb|\)/g, '')
        .replace(/-?\d+(?:\.\d+)?(?:deg|%)/g, '')
        .replace(/\b(?:white|black|transparent)\b/g, '')
        .replace(/[\s,]/g, '');
      expect([name, stops]).toEqual([name, '']);
    }
  });
});

describe('legacy aliases — retired (HIVE-10.6, #5342)', () => {
  it.each(Object.keys(RETIRED_ALIASES))('%s is no longer declared at :root', (alias) => {
    expect(layer.root.has(alias)).toBe(false);
  });

  it.each(Object.entries(RETIRED_ALIASES))('%s has a Hive replacement, %s, that resolves', (_alias, token) => {
    expect(layer.root.has(token) || layer.theme.has(token)).toBe(true);
  });

  it.each(Object.keys(RETIRED_ALIASES))('nothing in the stylesheet reads var(%s)', (alias) => {
    expect(css).not.toMatch(new RegExp(`var\\(${alias}[,)]`));
  });

  it.each(RETIRED_UTILITY_TOKENS)('%s is no longer a @theme utility token', (utility) => {
    expect(layer.theme.has(utility)).toBe(false);
  });

  it('keeps --font-inter, which the capability and Mermaid graphs read directly', () => {
    expect(layer.root.get('--font-inter')).toBe('var(--app-font-sans)');
  });
});

describe('sibling-app content scanning', () => {
  it.each(['@source "../";', '@source "../../lib";'])('still declares %s', (directive) => {
    // Sibling apps (private-suite Studio/designer) import this stylesheet; without these,
    // Tailwind roots auto-detection at the consumer and never emits apiome-ui's classes.
    expect(css).toContain(directive);
  });
});

describe('raw-hex allow-list', () => {
  it('finds no hex literal outside a documented fence', () => {
    expect(findUnfencedHex(css).map((hit) => `${hit.line}: ${hit.text}`)).toEqual([]);
  });

  it('documents the allow-list next to the token layer', () => {
    expect(css).toContain('RAW HEX ALLOW-LIST');
    for (const permitted of ['brand', '.fmt--*', '.method--*']) {
      expect(css).toContain(permitted);
    }
  });

  it('balances every fence it opens', () => {
    const opened = css.match(/hex-allow-start/g) ?? [];
    const closed = css.match(/hex-allow-end/g) ?? [];
    expect(opened).toHaveLength(closed.length);
  });

  it('labels every fence with the reason it exists', () => {
    for (const [, label] of css.matchAll(/hex-allow-start:?(.*)/g)) {
      expect(label.trim().replace(/\*\/$/, '').trim().length).toBeGreaterThan(0);
    }
  });
});

describe('light-palette legibility (WCAG 2.2 AA)', () => {
  /**
   * Resolve a token and parse it as an opaque colour.
   *
   * @param token Custom-property name.
   * @returns The token's sRGB channels.
   */
  const colorOf = (token: string) => hexToRgb(resolveToken(token, layer));

  it.each([
    ['--fg', '--bg-canvas'],
    ['--fg', '--bg-surface'],
    ['--fg', '--bg-subtle'],
    ['--fg-muted', '--bg-surface'],
    ['--accent-fg', '--accent-soft'],
    ['--ok-fg', '--ok-soft'],
    ['--warn-fg', '--warn-soft'],
    ['--danger-fg', '--danger-soft'],
    ['--ink-fg', '--ink'],
  ])('%s on %s clears AA for body text', (ink, surface) => {
    expect(contrastRatio(colorOf(ink), colorOf(surface))).toBeGreaterThanOrEqual(WCAG_AA_NORMAL_TEXT_MIN);
  });

  it.each([
    ['--fg-subtle', '--bg-surface'],
    ['--accent', '--bg-surface'],
  ])('%s on %s clears AA for large text and non-text marks', (ink, surface) => {
    expect(contrastRatio(colorOf(ink), colorOf(surface))).toBeGreaterThanOrEqual(WCAG_AA_LARGE_TEXT_MIN);
  });
});

// ---------------------------------------------------------------------------------------
// Honey gate (HIVE-13.1, #5614)
// ---------------------------------------------------------------------------------------

/**
 * Files outside `globals.css` that may spend honey because they *are* one of DESIGN.md §2's
 * brand roles. The value is the role, so the reason sits next to the exception.
 *
 * The mark (`BrandMark`) and the Preferences theme grid are §2 roles too, but they draw with
 * fenced brand hex and theme swatches rather than the honey tokens, so they have no entry:
 * an entry the scan no longer finds fails the stale check below.
 */
const HONEY_BRAND_FILES: Record<string, string> = {
  'src/app/components/ui/statusVocabulary.ts':
    'the honey tone of Badge[data-status=new|starred|pinned|preview] and the shared tone vocabulary',
  'src/app/components/ade/launcher/HoneycombOrnament.tsx': 'empty-state / launcher honeycomb art',
  'src/app/components/ui/Card.tsx': '`Card variant="honey"` — the first-run checklist wash',
  'src/app/components/ui/Avatar.tsx': 'the brand avatar gradient (the mark’s hexagon)',
  'src/app/components/shell/UserMenu.tsx': 'the unread “new” dot on the user menu',
};

/**
 * Files that spend honey outside a §2 role today. Introduced allow-listed, per the quiet pass
 * roadmap (step 6): the list may only shrink — fix one, delete its line.
 */
const HONEY_PENDING_FILES: Record<string, string> = {
  'src/app/components/ui/Button.tsx': '`Button variant="honey"` — a filled honey button outside the Dark-theme primary',
  'src/app/components/ui/Alert.tsx': '`Alert variant="honey"` — a honey callout tone',
  'src/app/components/ui/metrics/metricTiers.ts': 'the honey metric mark tone',
};

/** `globals.css` rules that define the honey tokens: the token layer and the theme blocks. */
const HONEY_TOKEN_RULES: Record<string, string> = {
  '@theme static': 'declares --color-honey*',
  ':root': 'aliases --honey* and builds --gradient-honey',
  'html[data-theme="dark"], html.dark:not([data-theme])': 'theme swap',
  'html[data-theme="high-contrast"]': 'theme swap',
  'html[data-theme="blueprint"]': 'theme swap',
  'html[data-theme="solarized"]': 'theme swap',
  'html[data-theme="nord"]': 'theme swap',
  'html[data-theme="darcula"]': 'theme swap',
};

/** `globals.css` rules that spend honey in one of DESIGN.md §2's brand roles. */
const HONEY_BRAND_RULES: Record<string, string> = {
  '.rail-dot': 'the rail’s 6 px “Preview” dot',
  '.rail .rail-item[aria-current="page"]::before': 'the active rail marker',
  '.rail .rail-item[aria-current="page"] > svg': 'the active rail marker',
  '.rail .brand-lockup > :first-child': 'the mark — the bee’s honey hexagon',
  '.hive-empty-art': 'empty-state art',
  '.glow-honey::before': 'the auth / launcher brand canvas',
  '.auth-center::before': 'the auth / launcher brand canvas',
  '.page-header[data-mood="hero"]': 'the Home hero band',
  '.launch-unread-dot': 'a “new” marker',
  '.ntf-row__dot': 'a “new” (unread) marker',
  '.lw-view-chip__pinned': 'a “pinned” marker',
  '.prm-default > svg': 'a “starred” marker (the default namespace’s ★)',
  '.home-checklist__mark': 'the first-run checklist',
  '.home-hex__cell': 'the first-run checklist',
  '.home-hex__cell[data-on="true"]': 'the first-run checklist',
  '.home-step--next': 'the first-run checklist',
  '.home-step--next .home-step__mark': 'the first-run checklist',
  '.vt__row--head': 'the HEAD node on the Versions timeline',
  '.vt__node--head': 'the HEAD node on the Versions timeline',
};

/**
 * `globals.css` rules that spend honey outside a §2 role today — allow-listed when the gate
 * was introduced, and only allowed to shrink.
 */
const HONEY_PENDING_RULES: Record<string, string> = {
  '.auth-eyebrow': 'honey eyebrow type on auth pages',
  '.auth-icon--honey': 'honey subject glyph on onboarding steps',
  '.launch-tone[data-tone="honey"]': 'honey launcher tile tone',
  '.home-tone[data-tone="honey"]': 'honey Home tile tone',
  '.help-card[data-tone="honey"]': 'honey help-card tone',
  '.tnt-icon-tile[data-tone="honey"]': 'honey tenant icon tile tone',
  '.rol-dot': 'honey “unsaved” dot on Roles',
  ".lw-facet-dot[data-tone='honey']": 'honey facet dot on the lint workspace',
  '.ver-tag': 'honey version tag chip',
  '.vdlg-chip[data-tone="honey"]': 'honey version-dialog chip tone',
  '.vdlg-node__dot[data-tone="honey"]': 'honey version-dialog node tone',
  '.vdlg-node__tip[data-tone="honey"]': 'honey version-dialog node tone',
  '.vdlg-node__tag': 'honey version-dialog tag',
  '.repo-new-proposal': 'honey proposal frame on New repository',
  '.repo-new-proposal__title > svg': 'honey proposal glyph on New repository',
  '.disc-thread--focused': 'honey focus wash on a discussion thread',
};

describe('honey gate — DESIGN.md §2 (HIVE-13.1, #5614)', () => {
  const files = honeyFiles();
  const rules = honeyRules(css);

  it('finds honey only in allow-listed files', () => {
    expect(unlistedHoney(files, HONEY_BRAND_FILES, HONEY_PENDING_FILES)).toEqual([]);
  });

  it('finds honey only in allow-listed globals.css rules', () => {
    expect(unlistedHoney(rules, HONEY_TOKEN_RULES, HONEY_BRAND_RULES, HONEY_PENDING_RULES)).toEqual([]);
  });

  it.each([
    ['brand files', HONEY_BRAND_FILES, 'files'],
    ['pending files', HONEY_PENDING_FILES, 'files'],
    ['token rules', HONEY_TOKEN_RULES, 'rules'],
    ['brand rules', HONEY_BRAND_RULES, 'rules'],
    ['pending rules', HONEY_PENDING_RULES, 'rules'],
  ] as const)('carries no stale %s entry, so the allow-list can only shrink', (_name, list, kind) => {
    expect(staleHoneyEntries(kind === 'files' ? files : rules, list)).toEqual([]);
  });

  it('keeps honey off the two surfaces the quiet pass took it from', () => {
    expect(files.has('src/app/components/ade/dashboard/mcp/McpSavedSearchesPanel.tsx')).toBe(false);
    expect(files.has('src/app/components/ade/versions/GitlikeFlag.tsx')).toBe(false);
    expect([...rules.keys()].filter((prelude) => /^\.(ver-flag|chip)\b/.test(prelude))).toEqual([]);
  });

  describe('negative cases — the gate catches a new honey use', () => {
    it('reads tokens and utilities, and ignores comments and BEM modifiers', () => {
      expect(findHoneyUsages('<span className="rounded-full bg-honey text-honey-fg" />')).toEqual([
        'bg-honey',
        'text-honey-fg',
      ]);
      expect(findHoneyUsages('.x { color: var(--honey-fg); box-shadow: 0 0 0 1px var(--color-honey); }')).toEqual([
        '--honey-fg',
        '--color-honey',
      ]);
      expect(findHoneyUsages('/* not the honey flag: var(--honey) */\n// bg-honey\n<i className="auth-icon--honey" />')).toEqual(
        []
      );
    });

    it('fails a globals.css rule that starts spending honey', () => {
      const leaked = `${css}\n.mcp-saved-chip { background: var(--honey-soft); }\n`;
      expect(unlistedHoney(honeyRules(leaked), HONEY_TOKEN_RULES, HONEY_BRAND_RULES, HONEY_PENDING_RULES)).toEqual([
        '.mcp-saved-chip: --honey-soft',
      ]);
    });

    it('fails a component file that starts spending honey', () => {
      const root = mkdtempSync(join(tmpdir(), 'honey-gate-'));
      try {
        mkdirSync(join(root, 'src', 'app', 'ade'), { recursive: true });
        mkdirSync(join(root, 'lib'), { recursive: true });
        writeFileSync(join(root, 'src', 'app', 'ade', 'Leak.tsx'), 'export const Leak = () => <b className="bg-honey" />;\n');
        writeFileSync(join(root, 'src', 'app', 'ade', 'Quiet.tsx'), 'export const Quiet = () => <b className="chip" />;\n');
        expect(unlistedHoney(honeyFiles(root), HONEY_BRAND_FILES, HONEY_PENDING_FILES)).toEqual([
          'src/app/ade/Leak.tsx: bg-honey',
        ]);
      } finally {
        rmSync(root, { recursive: true, force: true });
      }
    });
  });
});

describe('neutral filter chip (HIVE-13.1, #5614)', () => {
  const chipRules = new Map(topLevelRules(css).map((rule) => [rule.prelude, rule.body]));

  it('rests as a hairline in --fg-muted and fills with ink when pressed', () => {
    expect(chipRules.get('.chip')).toContain('color: var(--fg-muted)');
    expect(chipRules.get('.chip')).toContain('box-shadow: inset 0 0 0 1px var(--border-strong)');
    expect(chipRules.get('.chip[aria-pressed="true"]')).toContain('background: var(--ink)');
    expect(chipRules.get('.chip[aria-pressed="true"]')).toContain('color: var(--ink-fg)');
  });

  it('sizes from the control and icon metrics rather than px', () => {
    expect(chipRules.get('.chip')).toContain('block-size: var(--control-h-sm)');
    expect(chipRules.get('.chip > svg')).toContain('inline-size: var(--icon-button)');
    expect(chipRules.get('.chip')).toContain('padding-inline: var(--space-3)');
    expect(chipRules.get('.chip')).toContain('font-size: var(--fs-xs)');
  });
});
