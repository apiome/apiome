/**
 * The Radix Themes wrapper is gone (SUX-1.3, apiome/private-suite#2877, apiome#6750).
 *
 * Both layouts used to wrap the whole app in `@radix-ui/themes`' `<Theme>` and import its
 * 800 KB stylesheet, while no component of the package was ever rendered. The wrapper was not
 * inert: it declares its own `--space-1…9` on `.radix-themes`, and because a custom property
 * comes from the *nearest declaring ancestor*, every Hive element inherited Radix's ladder
 * (`--space-5/6/8` = 24/32/48 px) instead of Hive's (20/24/32 px), and the compact-density
 * swap on `<html>` never reached anything. It also lent the app `--space-7`, which Hive never
 * declares. This suite keeps it gone:
 *
 *   1. nothing under `src/` imports `@radix-ui/themes`, and the package — with the unused
 *      `@emotion/*` pair — is not a dependency;
 *   2. the stylesheet has no `.radix-themes` rule left, the bridge that undid the colour
 *      collisions included;
 *   3. every `var(--space-N)` the stylesheet spends is a step Hive declares, so a value can
 *      no longer silently resolve against a wrapper that is not there;
 *   4. the ladder and its density swap are the documented Hive values;
 *   5. `body` keeps `overflow-wrap: break-word`, the one inherited wrapper rule the app
 *      relied on.
 */

import { readFileSync } from 'node:fs';
import { join, relative } from 'node:path';

import { parseBlock, parseDeclarations, readGlobalsCss, stripCssComments, topLevelRules } from './helpers/design-tokens';
import { sourceFiles } from './helpers/source-files';

const ROOT = join(__dirname, '..');
const css = readGlobalsCss();

describe('the Radix Themes package', () => {
  it('is imported by nothing under src/', () => {
    const offenders = sourceFiles(join(ROOT, 'src'), /\.(ts|tsx|css)$/)
      .filter((file) => /['"]@radix-ui\/themes(\/[^'"]*)?['"]/.test(readFileSync(file, 'utf8')))
      .map((file) => relative(ROOT, file));
    expect(offenders).toEqual([]);
  });

  it.each(['@radix-ui/themes', '@emotion/react', '@emotion/styled'])('%s is not a dependency', (name) => {
    const manifest = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'));
    expect(manifest.dependencies ?? {}).not.toHaveProperty(name);
    expect(manifest.devDependencies ?? {}).not.toHaveProperty(name);
  });
});

describe('the stylesheet', () => {
  it('has no rule for the wrapper element', () => {
    expect(stripCssComments(css)).not.toMatch(/\.radix-themes\b/);
  });

  it('spends only spacing steps Hive declares', () => {
    const declared = new Set([...parseBlock(css, ':root').keys()].filter((name) => /^--space-\d+$/.test(name)));
    const spent = new Set([...stripCssComments(css).matchAll(/var\((--space-\d+)\)/g)].map((match) => match[1]));
    const undeclared = [...spent].filter((name) => !declared.has(name)).sort();
    expect(undeclared).toEqual([]);
  });

  it('declares no --space-7: it was only ever Radix’s 40 px, now spelled --space-10', () => {
    expect(parseBlock(css, ':root').has('--space-7')).toBe(false);
    expect(parseBlock(css, ':root').get('--space-10')).toBe('2.5rem');
  });
});

describe('the spacing ladder that now reaches the page', () => {
  const root = parseBlock(css, ':root');

  it.each([
    ['--space-5', '1.25rem'],
    ['--space-6', '1.5rem'],
    ['--space-8', '2rem'],
  ])('%s is %s (the documented Hive step, no longer Radix’s)', (name, value) => {
    expect(root.get(name)).toBe(value);
  });

  it('tightens --space-6 and --space-8 at compact density, on <html> where nothing overrides them', () => {
    const compact = parseBlock(css, 'html[data-density="compact"]');
    expect(compact.get('--space-6')).toBe('1.25rem');
    expect(compact.get('--space-8')).toBe('1.5rem');
  });
});

describe('the page’s base type', () => {
  const body = (() => {
    const rule = topLevelRules(css).find((candidate) => candidate.prelude === 'body');
    if (!rule) throw new Error('globals.css has no `body` rule');
    return parseDeclarations(rule.body);
  })();

  it('keeps long words wrapping, as the wrapper used to make them', () => {
    expect(body.get('overflow-wrap')).toBe('break-word');
  });

  it('sets the Hive face, leading and tracking the wrapper used to override', () => {
    expect(body.get('font-family')).toBe('var(--app-font-sans)');
    expect(body.get('line-height')).toBe('1.45');
    expect(body.get('letter-spacing')).toBe('0.002em');
  });
});
