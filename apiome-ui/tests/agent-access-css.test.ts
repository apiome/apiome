/**
 * The stylesheet half of MCP → Agent access (AGX-3.4, #4540).
 *
 * `agent-access-ui.test.tsx` renders the surface; jsdom compiles no stylesheet, so this suite
 * reads `globals.css` the way `bindings-css.test.ts` does and pins what the components lean on:
 *
 *   1. **Every `agx-` class the components put in a `className` is declared**, and the section
 *      declares no class they do not use.
 *   2. **The skin is tokens only** — no hex, no `rgb()`, no Tailwind palette class.
 *   3. **Nothing is frozen in pixels** except hairlines and focus rings.
 *   4. **Text is legible**: `--fg-subtle` is never spent on a line meant to be read.
 *   5. **Nothing scrolls the page sideways**: tables scroll in their own wrapper and long names
 *      wrap.
 */

import * as fs from 'fs';
import * as path from 'path';

import {
  findUnfencedHex,
  parseDeclarations,
  readGlobalsCss,
  topLevelRules,
  type CssRule,
} from './helpers/design-tokens';

const css = readGlobalsCss();
const rules = topLevelRules(css);

/** The components that spell these classes. */
const COMPONENT_DIRS = [
  'src/app/components/ade/agentAccess',
  'src/app/ade/dashboard/mcp/agents',
] as const;

/** The section, from its banner to the next one (or the end of file). */
const SECTION = (() => {
  const start = css.indexOf('AGENT ACCESS  (AGX-3.4, #4540)');
  if (start < 0) throw new Error('globals.css has no agent-access section');
  const bannerStart = css.lastIndexOf('/* =', start);
  const next = css.indexOf('/* =', start);
  return css.slice(bannerStart < 0 ? start : bannerStart, next < 0 ? css.length : next);
})();

/** The section with its comments removed, so prose never satisfies an assertion. */
const SECTION_CODE = SECTION.replace(/\/\*[\s\S]*?\*\//g, '');

/** Every `agx-` class the section declares. */
const DECLARED: readonly string[] = [
  ...new Set([...SECTION_CODE.matchAll(/\.(agx[a-z0-9_-]*)/g)].map((match) => match[1])),
].sort();

/** Every `agx-` class the components put in a `className="…"`. */
const SPELLED: readonly string[] = (() => {
  const found = new Set<string>();
  for (const dir of COMPONENT_DIRS) {
    const abs = path.join(process.cwd(), dir);
    for (const file of fs.readdirSync(abs).filter((f) => f.endsWith('.tsx'))) {
      const source = fs.readFileSync(path.join(abs, file), 'utf8');
      for (const attr of source.matchAll(/className="([^"]*)"/g)) {
        for (const name of attr[1].split(/\s+/)) if (name.startsWith('agx-')) found.add(name);
      }
    }
  }
  return [...found].sort();
})();

/** Every top-level rule inside the section. */
const SECTION_RULES: readonly CssRule[] = rules.filter((rule) => /^\.agx/.test(rule.prelude.trim()));

/**
 * Read one declaration out of one of this section's rules.
 *
 * @param prelude - The rule's selector.
 * @param property - The property.
 * @returns Its value.
 */
function declaration(prelude: string, property: string): string {
  const rule = rules.find((candidate) => candidate.prelude.replace(/\s+/g, ' ').trim() === prelude);
  if (!rule) throw new Error(`globals.css declares no rule \`${prelude}\``);
  const value = parseDeclarations(rule.body).get(property);
  if (value === undefined) throw new Error(`\`${prelude}\` declares no \`${property}\``);
  return value;
}

describe('the agent-access section of globals.css', () => {
  it('declares exactly the classes the components use', () => {
    expect(SPELLED.filter((name) => !DECLARED.includes(name))).toEqual([]);
    expect(DECLARED.filter((name) => !SPELLED.includes(name))).toEqual([]);
    expect(SPELLED.length).toBeGreaterThan(25);
  });

  it('styles only its own classes (and the borrowed focus token)', () => {
    const foreign = [...SECTION_CODE.matchAll(/\.([a-z][a-z0-9_-]*)/g)]
      .map((match) => match[1])
      .filter((name) => !name.startsWith('agx'));
    expect([...new Set(foreign)]).toEqual([]);
  });

  it('names no colour — every hue resolves through the token layer', () => {
    for (const rule of SECTION_RULES) {
      for (const [, value] of parseDeclarations(rule.body)) {
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
});

describe('density and font-scale independence', () => {
  const PX_ALLOWED = /^(outline|outline-offset|box-shadow|border(-[a-z-]+)?)$/;

  it('states nothing in px but hairlines and focus rings', () => {
    for (const rule of SECTION_RULES) {
      for (const [property, value] of parseDeclarations(rule.body)) {
        const lengths = value.match(/(?<!\d)(\d*\.?\d+)px/g) ?? [];
        if (lengths.length === 0) continue;
        expect({ prelude: rule.prelude, property, lengths }).toEqual({
          prelude: rule.prelude,
          property,
          lengths: lengths.filter((length) => PX_ALLOWED.test(property) && /^[12]px$/.test(length)),
        });
      }
    }
  });

  it('measures every font size through the type scale', () => {
    for (const rule of SECTION_RULES) {
      const size = parseDeclarations(rule.body).get('font-size');
      if (size === undefined) continue;
      expect(size).toMatch(/^var\(--fs-/);
    }
  });

  it('spends spacing tokens for gaps', () => {
    for (const rule of SECTION_RULES) {
      const gap = parseDeclarations(rule.body).get('gap');
      if (gap === undefined) continue;
      expect(gap).toMatch(/^var\(--space-\d\)( var\(--space-\d\))?$/);
    }
  });
});

describe('legibility and overflow', () => {
  it('never spends --fg-subtle on text', () => {
    for (const rule of SECTION_RULES) {
      expect(parseDeclarations(rule.body).get('color') ?? '').not.toContain('--fg-subtle');
    }
  });

  it('quiet lines are --fg-muted, content is --fg', () => {
    expect(declaration('.agx-hint', 'color')).toBe('var(--fg-muted)');
    expect(declaration('.agx-section-title', 'color')).toBe('var(--fg)');
  });

  it('tables scroll inside their wrapper rather than the page', () => {
    expect(declaration('.agx-table-wrap', 'overflow-x')).toBe('auto');
    expect(declaration('.agx-table-wrap', 'min-inline-size')).toBe('0');
  });

  it('long tool names, operation keys and toolset names wrap', () => {
    for (const prelude of [
      '.agx-cell-mono',
      '.agx-checklist__name',
      '.agx-toolset-card__name',
      '.agx-key-identity__name',
      '.agx-section-title',
    ]) {
      expect(declaration(prelude, 'overflow-wrap')).toBe('anywhere');
    }
  });

  it('the allowlist picker is bounded so the dialog footer stays reachable', () => {
    expect(declaration('.agx-checklist__list', 'max-block-size')).toMatch(/rem$/);
    expect(declaration('.agx-checklist__list', 'overflow-y')).toBe('auto');
  });
});
