/**
 * The public catalog draws from the same Hive tokens as the Control Panel, but as a copy: the
 * two apps are built separately and share no stylesheet. This holds the copy against the
 * original — every colour, radius and shadow `src/app/globals.css` declares must equal the value
 * `apiome-ui/src/app/globals.css` declares for it, in the light palette and in the dark one.
 *
 * It skips when apiome-ui is not on disk (the Docker build copies only this app).
 */
import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const BROWSE_CSS = join(__dirname, '..', '..', 'src', 'app', 'globals.css');
const UI_CSS = join(__dirname, '..', '..', '..', 'apiome-ui', 'src', 'app', 'globals.css');

/** Custom properties declared in the first block whose prelude starts with `prelude`. */
function declarations(css: string, prelude: string): Map<string, string> {
  const start = css.indexOf(prelude);
  if (start < 0) throw new Error(`no \`${prelude}\` block`);
  const open = css.indexOf('{', start);
  let depth = 0;
  let end = open;
  for (; end < css.length; end += 1) {
    if (css[end] === '{') depth += 1;
    else if (css[end] === '}' && (depth -= 1) === 0) break;
  }
  const body = css.slice(open + 1, end).replace(/\/\*[\s\S]*?\*\//g, '');
  const found = new Map<string, string>();
  for (const match of body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
    found.set(match[1], match[2].trim().replace(/\s+/g, ' ').toLowerCase());
  }
  return found;
}

/** apiome-ui's name for one of this app's tokens. */
function uiName(token: string): string {
  if (token.startsWith('--radius-') || token.startsWith('--shadow-')) return token;
  if (token === '--overlay') return '--color-overlay';
  return `--color-${token.slice(2).replace(/^bg-/, '')}`;
}

const SHARED = /^--(bg-|fg|border|overlay|accent|ink|honey|ok|warn|danger|violet|orange|radius-|shadow-)/;

describe.skipIf(!existsSync(UI_CSS))('Hive tokens match apiome-ui', () => {
  const browse = readFileSync(BROWSE_CSS, 'utf8');
  const ui = existsSync(UI_CSS) ? readFileSync(UI_CSS, 'utf8') : '';

  it.each([
    ['light', ':root {', '@theme static {'],
    ['dark', 'html.dark {', 'html[data-theme="dark"],'],
  ])('in the %s palette', (_name, browsePrelude, uiPrelude) => {
    const mine = declarations(browse, browsePrelude);
    const theirs = declarations(ui, uiPrelude);
    const checked: string[] = [];
    const drift: string[] = [];
    for (const [token, value] of mine) {
      if (!SHARED.test(token) || value.startsWith('var(')) continue;
      let original = theirs.get(uiName(token));
      // apiome-ui routes a few roles through a brand token (`--color-honey: var(--color-brand-honey)`).
      const alias = original?.match(/^var\((--[a-z0-9-]+)\)$/);
      if (alias) original = theirs.get(alias[1]);
      checked.push(token);
      if (original !== value) drift.push(`${token}: ${value} ≠ apiome-ui ${original ?? '(not declared)'}`);
    }
    expect(drift).toEqual([]);
    // Guards the guard: a renamed block or prefix would otherwise compare nothing and pass.
    expect(checked.length).toBeGreaterThan(40);
  });

  it('states the dark palette identically for the OS preference and the explicit class', () => {
    const byClass = declarations(browse, 'html.dark {');
    const byMedia = declarations(browse, ':root:not(.light) {');
    expect([...byMedia.entries()]).toEqual([...byClass.entries()]);
  });
});
