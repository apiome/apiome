/**
 * The motion pass — HIVE-10.3 (#5339), `docs/mockups/DESIGN.md` §3.4.
 *
 * "Durations: fast 120 (hover, toggles) · base 180 (menus, tabs) · slow 260 (dialogs, drawers,
 * rail collapse). Easing cubic-bezier(.2,.8,.2,1). Dialogs rise 8 px + fade; drawers slide from
 * the right; palette rises from 12 vh. Respect prefers-reduced-motion and the Reduce motion
 * preference."
 *
 * This suite holds every stylesheet and component to that:
 *
 *   1. **No animation exceeds 260 ms.** Every `transition` / `animation` duration is a `--dur-*`
 *      token or a literal no longer than `--dur-slow`; Tailwind `duration-*` steps likewise.
 *      The only exceptions are the continuous indicators and ornaments the mockups themselves
 *      draw as loops ({@link AMBIENT_LOOPS}) — a spinner cannot finish in 260 ms — and those must
 *      be `infinite` and must stop under reduced motion.
 *   2. **One easing.** Every timing function is `var(--ease-out)` (the §3.4 curve), except
 *      `linear` and `var(--ease-in-out)` inside an ambient loop.
 *   3. **Reduce motion is instant.** Both reduce blocks zero every duration and delay and run a
 *      loop once, so state changes are immediate and nothing keeps cycling.
 *   4. **No animation blocks interaction.** A closing dialog, drawer or scrim stops taking
 *      pointer events while it plays its exit.
 *   5. The overlay motions are the ones §3.4 names.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { MOTION_MS } from '../lib/motion';
import { parseBlock, readGlobalsCss, stripCssComments, topLevelRules } from './helpers/design-tokens';

const ROOT = join(__dirname, '..');
const SRC = join(ROOT, 'src');
const css = readGlobalsCss();
const rules = topLevelRules(css);

/** The longest a one-shot motion may run (`--dur-slow`). */
const MAX_MS = 260;

/**
 * Continuous loops the mockups draw themselves (`hive.css` §13–14 spinner, shimmer and stripes;
 * the floating ornaments of `auth/login.html` and `home/launcher.html`), with why each is a loop.
 * Every one is zeroed and run once by the reduce-motion blocks.
 */
const AMBIENT_LOOPS: Record<string, string> = {
  'hive-shimmer': 'skeleton shimmer while content loads (hive.css .skeleton)',
  'hive-stripes': 'striped progress bar for work in flight (hive.css .progress--striped)',
  'prm-spin': 'spinner glyph in the primitives import (hive.css .spinner)',
  'studio-chat-indeterminate-progress': 'indeterminate progress while the studio assistant works',
  'auth-chip-float': 'decorative float on the sign-in art (auth/login.html @keyframes float)',
  'launch-comb-float': 'decorative float on the launcher art (home/launcher.html @keyframes float)',
};

/** Every `.css` file under `src/`. */
function stylesheets(directory: string = SRC): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) return stylesheets(path);
    return entry.endsWith('.css') ? [path] : [];
  });
}

/** Every `.ts` / `.tsx` file under `src/`. */
function sources(directory: string = SRC): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry) ? [path] : [];
  });
}

/** One `transition` / `animation` declaration found in a stylesheet. */
interface MotionDeclaration {
  file: string;
  property: string;
  value: string;
}

/**
 * Every motion declaration in a stylesheet, comments removed, values whitespace-collapsed.
 *
 * @param file Absolute path.
 * @returns The declarations, `!important` and all.
 */
function motionDeclarations(file: string): MotionDeclaration[] {
  const source = stripCssComments(readFileSync(file, 'utf8'));
  const found: MotionDeclaration[] = [];
  const declaration = /(?<![-\w])(transition|animation)(-duration|-timing-function|-delay)?\s*:\s*([^;{}]+);/g;
  for (const match of source.matchAll(declaration)) {
    found.push({
      file: file.slice(ROOT.length + 1),
      property: match[1] + (match[2] ?? ''),
      value: match[3].replace(/\s+/g, ' ').trim(),
    });
  }
  return found;
}

const DECLARATIONS = stylesheets().flatMap(motionDeclarations);

/** Literal times in a value, in milliseconds. */
function literalTimes(value: string): number[] {
  return [...value.matchAll(/(?<![\w-])(\d*\.?\d+)(ms|s)\b/g)].map(([, n, unit]) => Number(n) * (unit === 's' ? 1000 : 1));
}

/** The ambient loop a declaration runs, if it runs one. */
function ambientLoop(value: string): string | undefined {
  return Object.keys(AMBIENT_LOOPS).find((name) => new RegExp(`(^|[\\s,])${name}(\\s|$)`).test(value));
}

describe('the §3.4 tokens', () => {
  const tokens = parseBlock(css, '@theme static');

  it('defines fast 120, base 180, slow 260 and the one easing curve', () => {
    expect(tokens.get('--dur-fast')).toBe(`${MOTION_MS.fast}ms`);
    expect(tokens.get('--dur-base')).toBe(`${MOTION_MS.base}ms`);
    expect(tokens.get('--dur-slow')).toBe(`${MOTION_MS.slow}ms`);
    expect(MOTION_MS.slow).toBe(MAX_MS);
    expect(tokens.get('--ease-out')).toBe('cubic-bezier(0.2, 0.8, 0.2, 1)');
  });

  it('puts an unadorned Tailwind `transition` utility on the same rhythm', () => {
    expect(tokens.get('--default-transition-duration')).toBe('var(--dur-fast)');
    expect(tokens.get('--default-transition-timing-function')).toBe('var(--ease-out)');
  });
});

describe('no animation exceeds 260 ms', () => {
  it('finds the declarations it is checking', () => {
    expect(DECLARATIONS.length).toBeGreaterThan(80);
  });

  it('keeps every one-shot duration at or under --dur-slow', () => {
    const over = DECLARATIONS.filter(
      (d) => !ambientLoop(d.value) && literalTimes(d.value).some((ms) => ms > MAX_MS),
    ).map((d) => `${d.file}: ${d.property}: ${d.value}`);
    expect(over).toEqual([]);
  });

  it('allows a longer cycle only to a named ambient loop, and only as a loop', () => {
    for (const d of DECLARATIONS.filter((candidate) => ambientLoop(candidate.value))) {
      expect(`${d.value}`).toMatch(/\binfinite\b/);
    }
    // Every allowed loop is still in use, so the list cannot outlive what it excuses.
    for (const name of Object.keys(AMBIENT_LOOPS)) {
      expect(DECLARATIONS.some((d) => ambientLoop(d.value) === name)).toBe(true);
    }
  });

  it('uses no Tailwind duration step longer than --dur-slow, and no raw delay', () => {
    const offenders: string[] = [];
    for (const file of sources()) {
      const text = readFileSync(file, 'utf8');
      for (const [step] of text.matchAll(/\bduration-(\d+)\b/g)) {
        if (Number(step.slice('duration-'.length)) > MAX_MS) offenders.push(`${file.slice(ROOT.length + 1)}: ${step}`);
      }
      for (const [step] of text.matchAll(/\bdelay-\d+\b/g)) offenders.push(`${file.slice(ROOT.length + 1)}: ${step}`);
    }
    expect(offenders).toEqual([]);
  });

  it('caps script-driven motion at MOTION_MS.slow', () => {
    const offenders: string[] = [];
    for (const file of sources()) {
      for (const [call, ms] of readFileSync(file, 'utf8').matchAll(/motionDuration\((\d+)\)/g)) {
        if (Number(ms) > MAX_MS) offenders.push(`${file.slice(ROOT.length + 1)}: ${call}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe('one easing', () => {
  it('times every transition and animation with var(--ease-out)', () => {
    const offenders = DECLARATIONS.filter((d) => {
      const loop = ambientLoop(d.value);
      const stray = d.value
        .replace(/var\(--ease-out\)/g, '')
        .match(/cubic-bezier\([^)]*\)|var\(--ease-in-out\)|\b(ease-in-out|ease-in|ease-out|ease|linear|step-start|step-end|steps\([^)]*\))\b/g);
      if (!stray) return false;
      // A loop may run `linear` (spinner, stripes) or the in-out curve (an ornament's float).
      return !(loop && stray.every((timing) => timing === 'linear' || timing === 'var(--ease-in-out)'));
    }).map((d) => `${d.file}: ${d.property}: ${d.value}`);
    expect(offenders).toEqual([]);
  });
});

describe('reduce motion is instant', () => {
  /** The declarations of a reduce block, by property. */
  const reduceBlock = (prelude: string): Map<string, string> => {
    const source = stripCssComments(css);
    const start = source.indexOf(prelude);
    expect(start).toBeGreaterThan(-1);
    const open = source.indexOf('{', start + prelude.length - 1);
    const close = source.indexOf('}', open);
    const body = source.slice(open + 1, close);
    return new Map([...body.matchAll(/([\w-]+)\s*:\s*([^;]+);/g)].map(([, name, value]) => [name, value.trim()]));
  };

  it.each([
    ['the preference', 'html[data-motion="reduce"] *,\nhtml[data-motion="reduce"] *::before,\nhtml[data-motion="reduce"] *::after {'],
    ['the operating system', '@media (prefers-reduced-motion: reduce) {\n  *,\n  *::before,\n  *::after {'],
  ])('zeroes every duration and delay and runs a loop once, for %s', (_name, prelude) => {
    const block = reduceBlock(prelude);
    expect(block.get('animation-duration')).toBe('0ms !important');
    expect(block.get('animation-delay')).toBe('0ms !important');
    expect(block.get('animation-iteration-count')).toBe('1 !important');
    expect(block.get('transition-duration')).toBe('0ms !important');
    expect(block.get('transition-delay')).toBe('0ms !important');
    expect(block.get('scroll-behavior')).toBe('auto !important');
  });
});

describe('the overlays §3.4 names', () => {
  /** A top-level rule's declarations. */
  const rule = (prelude: string): string => {
    const found = rules.find((candidate) => candidate.prelude === prelude);
    if (!found) throw new Error(`globals.css has no \`${prelude}\` rule`);
    return found.body.replace(/\s+/g, ' ');
  };

  /** A keyframes block's text. */
  const keyframes = (name: string): string => {
    const source = stripCssComments(css);
    const start = source.indexOf(`@keyframes ${name} {`);
    expect(start).toBeGreaterThan(-1);
    return source.slice(start, source.indexOf('\n}', start)).replace(/\s+/g, ' ');
  };

  it('raises a dialog 8 px as it fades in, at --dur-slow', () => {
    expect(rule('.hive-dialog[data-state="open"]')).toContain('hive-dialog-rise var(--dur-slow) var(--ease-out)');
    expect(keyframes('hive-dialog-rise')).toContain('opacity: 0; transform: translateY(0.5rem)');
  });

  it('slides a drawer in from the right, at --dur-slow', () => {
    expect(rule('.hive-drawer[data-state="open"]')).toContain('hive-drawer-in var(--dur-slow) var(--ease-out)');
    // A positive X offset is to the right of where the drawer comes to rest.
    expect(keyframes('hive-drawer-in')).toMatch(/from \{ opacity: 0; transform: translateX\(1\.5rem\)/);
  });

  it('raises the palette from 12 vh', () => {
    expect(rule('.palette')).toContain('top: 12vh');
    expect(rule('.palette')).toContain('palette-rise var(--dur-slow) var(--ease-out)');
  });

  it('fades the scrim, and leaves faster than it arrives', () => {
    expect(rule('.hive-overlay[data-state="open"]')).toContain('hive-overlay-in var(--dur-base) var(--ease-out)');
    expect(rule('.hive-overlay[data-state="closed"]')).toContain('hive-overlay-out var(--dur-fast) var(--ease-out)');
  });

  it.each(['.hive-dialog[data-state="closed"]', '.hive-drawer[data-state="closed"]', '.hive-overlay[data-state="closed"]'])(
    'lets clicks through %s while it plays its exit',
    (prelude) => {
      expect(rule(prelude)).toContain('pointer-events: none');
    },
  );

  it.each([
    ['Dialog overlay', 'src/app/components/ui/Dialog.tsx', "'hive-overlay "],
    ['Dialog surface', 'src/app/components/ui/Dialog.tsx', "'hive-dialog "],
    ['Drawer overlay', 'src/app/components/ui/Drawer.tsx', "'hive-overlay "],
    ['Drawer surface', 'src/app/components/ui/Drawer.tsx', "'hive-drawer "],
    ['AlertDialog overlay', 'src/app/components/ui/AlertDialog.tsx', "'hive-overlay "],
  ])('%s wears its motion class', (_name, file, needle) => {
    expect(readFileSync(join(ROOT, file), 'utf8')).toContain(needle);
  });
});
