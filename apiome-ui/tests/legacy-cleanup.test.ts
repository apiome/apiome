/**
 * What the Hive redesign replaced stays deleted (HIVE-10.6, #5342).
 *
 * The cleanup ticket removed the last of the pre-Hive scaffolding that the page epics left
 * behind on purpose, "kept for one release so nothing breaks mid-migration":
 *
 *   • the legacy custom-property aliases (`--text-muted`, `--surface`, `--focus-ring`, …) and
 *     the Tailwind utilities they generated (`bg-background`, `text-text-muted`, …);
 *   • `components/ade/dashboard/dashboardScreenClasses.ts`, the table class strings that
 *     `components/ui/DataTable` superseded;
 *   • the one-off MUI conversion scripts, `convert_mui.py` and `convert-mui-to-radix.js`;
 *   • the sidebar kit's unread palette keys and density tokens;
 *   • `dark:` utilities that re-applied a Hive token — tokens already swap per theme, so the
 *     variant can only ever repeat the token or quietly fight it.
 *
 * Every one of those is the cheap mistake to re-introduce and none of them would fail a
 * behavioural suite (an unknown `var()` resolves to nothing rather than throwing), so the
 * deletions are pinned here as a source-text scan. Comments are stripped before matching:
 * the files that replaced the old code explain the change by name.
 */

import { existsSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { readGlobalsCss, readTokenLayer } from './helpers/design-tokens';
import { sourceFiles } from './helpers/source-files';
import { getSidebarTokens, sidebarTheme } from '../src/app/components/sidebar/sidebar-theme';

const APP_ROOT = join(__dirname, '..');

/** Files the ticket deleted, relative to the package root. */
const RETIRED_FILES: readonly string[] = [
  'src/app/components/ade/dashboard/dashboardScreenClasses.ts',
  'convert_mui.py',
  'convert-mui-to-radix.js',
];

/** Pre-Hive custom properties that no longer exist; a `var()` of one resolves to nothing. */
const RETIRED_PROPERTIES: readonly string[] = [
  'background',
  'foreground',
  'surface',
  'surface-muted',
  'border-subtle',
  'focus-ring',
  'text-muted',
  'shadow-subtle',
  'control-height',
];

/** Tailwind colour names the retired `--color-*` aliases generated. */
const RETIRED_UTILITY_COLOURS: readonly string[] = [
  'background',
  'foreground',
  'surface-muted',
  'border-subtle',
  'text-muted',
];

/** Utility prefixes that take a colour, for the two utility scans below. */
const COLOUR_UTILITY_PREFIXES =
  'bg|text|border|border-[trblxy]|ring|ring-offset|divide|outline|fill|stroke|from|via|to|placeholder|decoration|caret|accent|shadow';

/**
 * Remove block and line comments, so prose that names a retired thing is not an offence.
 *
 * `//` is only treated as a comment opener after whitespace or at a line start, so a URL
 * inside a string (`https://…`) survives.
 *
 * @param text Source text of a `.ts`, `.tsx` or `.css` file.
 * @returns The same text with its comments blanked out.
 */
function stripComments(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/[^\n]*/g, '$1');
}

/**
 * Package-relative paths of the files whose comment-free text matches a pattern.
 *
 * @param files Absolute paths to scan.
 * @param pattern What must not appear.
 * @returns The offending files, relative to the package root, so a failure names them.
 */
function offendersOf(files: readonly string[], pattern: RegExp): string[] {
  return files
    .filter((file) => pattern.test(stripComments(readFileSync(file, 'utf8'))))
    .map((file) => relative(APP_ROOT, file));
}

/** Application source: TypeScript and stylesheets under `src` and `lib`. */
const APP_SOURCES = ['src', 'lib'].flatMap((dir) =>
  sourceFiles(join(APP_ROOT, dir), /\.(ts|tsx|css)$/)
);

/** Everything that could import a module back: application source, unit and e2e suites. */
const IMPORTING_SOURCES = ['src', 'lib', 'tests', 'e2e'].flatMap((dir) =>
  sourceFiles(join(APP_ROOT, dir))
);

describe('legacy cleanup (HIVE-10.6, #5342)', () => {
  it('finds the files to check', () => {
    // Guards the guard: a walker that returned nothing would make every case below vacuous.
    expect(APP_SOURCES.length).toBeGreaterThan(500);
    expect(IMPORTING_SOURCES.length).toBeGreaterThan(APP_SOURCES.length);
  });

  it.each(RETIRED_FILES)('%s no longer exists', (file) => {
    expect(existsSync(join(APP_ROOT, file))).toBe(false);
  });

  it('imports dashboardScreenClasses from nowhere', () => {
    expect(offendersOf(IMPORTING_SOURCES, /from\s+['"][^'"]*\/dashboardScreenClasses['"]/)).toEqual(
      []
    );
  });

  it.each(RETIRED_PROPERTIES)('reads var(--%s) nowhere in the application', (name) => {
    expect(offendersOf(APP_SOURCES, new RegExp(`var\\(\\s*--${name}\\s*[,)]`))).toEqual([]);
  });

  it.each(RETIRED_UTILITY_COLOURS)('uses no *-%s colour utility', (colour) => {
    const utility = new RegExp(
      `(?:^|[\\s'"\`:])(?:${COLOUR_UTILITY_PREFIXES})-${colour}(?:/\\d+)?(?![\\w-])`
    );
    expect(offendersOf(APP_SOURCES, utility)).toEqual([]);
  });

  it('puts no dark: variant on a Hive token utility', () => {
    // The token names come from `@theme` itself, so a token added later is covered too.
    const tokens = [...readTokenLayer(readGlobalsCss()).theme.keys()]
      .filter((name) => name.startsWith('--color-'))
      .map((name) => name.slice('--color-'.length))
      // Longest first, so `fg-muted` is tried before `fg`.
      .sort((a, b) => b.length - a.length);
    expect(tokens).toEqual(expect.arrayContaining(['canvas', 'surface', 'fg', 'fg-muted', 'accent']));

    const duplicate = new RegExp(
      `dark:(?:[\\w-]+:)*(?:${COLOUR_UTILITY_PREFIXES})-(?:${tokens.join('|')})(?:/\\d+)?(?![\\w-])`
    );
    expect(offendersOf(APP_SOURCES, duplicate)).toEqual([]);
  });
});

describe('the sidebar kit carries no dead parts (HIVE-10.6, #5342)', () => {
  /** The three sidebars that still compose the kit, until the deferred Tools redesign. */
  const consumers = APP_SOURCES.filter((file) => /\.tsx?$/.test(file))
    .map((file) => stripComments(readFileSync(file, 'utf8')))
    .join('\n');

  it.each(Object.keys(sidebarTheme))('sidebarTheme.%s is read by a component', (key) => {
    expect(consumers).toMatch(new RegExp(`sidebarTheme\\.${key}\\b`));
  });

  it.each(Object.keys(getSidebarTokens('standard')))('density token %s is read by a component', (key) => {
    expect(consumers).toMatch(new RegExp(`tokens\\.${key}\\b`));
  });
});
