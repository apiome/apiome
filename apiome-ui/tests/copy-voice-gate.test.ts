/**
 * The content & voice gate (HIVE-10.4, #5340).
 *
 * DESIGN.md §10 — titles are nouns, buttons are verbs, descriptions answer "what is this
 * for?" in ≤ 14 words, errors say what happened **and** what to do — and §2's "Nothing
 * published yet", never "No records found". HIVE-10.4 brought every route into line; this
 * suite is what keeps it there:
 *
 *   1. **The rules themselves** (`lib/copy-voice.ts`) are pinned, including the edge cases a
 *      careless edit would break ("Failed to update version" does not name an action just
 *      because it contains "update").
 *   2. **The source** is read with the TypeScript parser, not a regex, so a multi-line
 *      `description={…}` is judged as surely as a one-line one:
 *        - every literal `title` / `description` on a feedback state or page header;
 *        - every `*_EMPTY_TITLE` / `*_EMPTY_DESC` copy constant;
 *        - every JSX text node, for "No records found"-class copy;
 *        - admin navigation titles;
 *        - and no component imports `toast` from `sonner` directly, which would bypass
 *          the voiced `toast.error` (`src/app/components/ui/toast.ts`).
 *
 * The runtime half — that `ErrorState`, `ErrorBanner`, `AlertDialog` and `toast.error`
 * really do add the next action — is `tests/copy-voice-surfaces.test.tsx`.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import ts from 'typescript';

import {
  DEFAULT_NEXT_ACTION,
  MAX_DESCRIPTION_WORDS,
  UNKNOWN_FAILURE,
  countWords,
  fitsDescription,
  isBannedPageTitle,
  isNoRecordsCopy,
  isOperationalFailure,
  namesNextAction,
  voiceFailure,
  withNextAction,
} from '../lib/copy-voice';

const ROOT = join(__dirname, '..');
const SRC = join(ROOT, 'src');

/** Components whose `title` / `description` props are §10 copy. */
const VOICED_COMPONENTS = new Set([
  'EmptyState',
  'ErrorState',
  'GatedState',
  'ErrorBanner',
  'PageHeader',
]);

/**
 * Directories that hold no user-facing screen copy: route handlers return API errors read
 * by code, not people.
 */
const SKIPPED_DIRECTORIES = new Set(['api']);

/** The only two modules allowed to import from `sonner`. */
const SONNER_ALLOWED = new Set([
  ['src', 'app', 'components', 'ui', 'Toaster.tsx'].join(sep),
  ['src', 'app', 'components', 'ui', 'toast.ts'].join(sep),
]);

/** Every `.ts` / `.tsx` source under `src/`, outside {@link SKIPPED_DIRECTORIES}. */
function sources(directory: string = SRC): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) {
      return SKIPPED_DIRECTORIES.has(entry) ? [] : sources(path);
    }
    return /\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry) ? [path] : [];
  });
}

/** One piece of copy found in the source, with where it was found. */
interface Copy {
  /** `path:line`, relative to the package. */
  where: string;
  /** The string itself. */
  text: string;
}

/** The parsed form of every source file, built once. */
const parsed = sources().map((path) => {
  const text = readFileSync(path, 'utf8');
  return {
    path,
    rel: relative(ROOT, path),
    text,
    file: ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX),
  };
});

/**
 * The literal string an expression evaluates to, when it is one.
 *
 * @param node A JSX attribute initializer or an expression.
 * @returns The string, or `null` for anything computed.
 */
function literalOf(node: ts.Node | undefined): string | null {
  if (!node) return null;
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
  if (ts.isJsxExpression(node)) return literalOf(node.expression);
  if (ts.isParenthesizedExpression(node)) return literalOf(node.expression);
  return null;
}

/**
 * Walk every node of every source file.
 *
 * @param visit Called with each node and its file's relative path and source file.
 */
function walk(visit: (node: ts.Node, rel: string, file: ts.SourceFile) => void): void {
  for (const { rel, file } of parsed) {
    const recurse = (node: ts.Node) => {
      visit(node, rel, file);
      ts.forEachChild(node, recurse);
    };
    recurse(file);
  }
}

/**
 * `path:line` for a node.
 *
 * @param rel The file's relative path.
 * @param file The source file.
 * @param node The node.
 * @returns A location a reader can open.
 */
function at(rel: string, file: ts.SourceFile, node: ts.Node): string {
  return `${rel}:${file.getLineAndCharacterOfPosition(node.getStart()).line + 1}`;
}

/** Every literal `prop` on a {@link VOICED_COMPONENTS} element. */
function voicedProp(prop: 'title' | 'description'): Copy[] {
  const found: Copy[] = [];
  walk((node, rel, file) => {
    if (!ts.isJsxOpeningElement(node) && !ts.isJsxSelfClosingElement(node)) return;
    if (!VOICED_COMPONENTS.has(node.tagName.getText(file))) return;
    for (const attribute of node.attributes.properties) {
      if (!ts.isJsxAttribute(attribute) || attribute.name.getText(file) !== prop) continue;
      const text = literalOf(attribute.initializer);
      if (text !== null) found.push({ where: at(rel, file, attribute), text });
    }
  });
  return found;
}

/** Every `const *_EMPTY_TITLE` / `*_EMPTY_DESC(RIPTION)` copy constant with a literal value. */
function emptyStateConstants(kind: 'TITLE' | 'DESC'): Copy[] {
  const name = kind === 'TITLE' ? /_EMPTY_TITLE$/ : /_EMPTY_DESC(RIPTION)?$/;
  const found: Copy[] = [];
  walk((node, rel, file) => {
    if (!ts.isVariableDeclaration(node) || !ts.isIdentifier(node.name)) return;
    if (!name.test(node.name.text)) return;
    const text = literalOf(node.initializer);
    if (text !== null) found.push({ where: at(rel, file, node), text });
  });
  return found;
}

/** Every non-blank JSX text node. */
function jsxText(): Copy[] {
  const found: Copy[] = [];
  walk((node, rel, file) => {
    if (!ts.isJsxText(node)) return;
    const text = node.text.replace(/\s+/g, ' ').trim();
    if (text) found.push({ where: at(rel, file, node), text });
  });
  return found;
}

/** Locations of every copy that fails `rule`, for a failure message that lists them all. */
function offenders(copies: Copy[], rule: (text: string) => boolean): string[] {
  return copies.filter(({ text }) => rule(text)).map(({ where, text }) => `${where}  “${text}”`);
}

// =========================================================================================
// 1. The rules
// =========================================================================================

describe('copy-voice rules (lib/copy-voice.ts)', () => {
  it('counts words the way a reader would', () => {
    expect(countWords('')).toBe(0);
    expect(countWords('   ')).toBe(0);
    expect(countWords(undefined)).toBe(0);
    expect(countWords(' Create  one from a template. ')).toBe(5);
  });

  it('holds descriptions to fourteen words', () => {
    expect(MAX_DESCRIPTION_WORDS).toBe(14);
    expect(fitsDescription('one two three four five six seven eight nine ten eleven twelve thirteen fourteen')).toBe(true);
    expect(fitsDescription('one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen')).toBe(false);
    expect(fitsDescription('a b c', 2)).toBe(false);
  });

  it.each([
    'No records found',
    'No records found.',
    'No results',
    'No data',
    'No data available',
    'No items to display',
    'No users found',
    'No templates were found',
    'Nothing found',
  ])('flags “%s” as "No records found"-class copy', (text) => {
    expect(isNoRecordsCopy(text)).toBe(true);
  });

  it.each([
    'No projects yet',
    'Nothing published yet — publish a version to see it here.',
    'Catalog item not found — go back to the catalog.',
    'No matching records',
    '',
  ])('accepts “%s”', (text) => {
    expect(isNoRecordsCopy(text)).toBe(false);
  });

  it.each(['Manage users', 'Configure SDKs', 'User Management', 'System Configuration'])(
    'rejects “%s” as a page title',
    (title) => {
      expect(isBannedPageTitle(title)).toBe(true);
    }
  );

  it.each(['Users', 'SDK settings', 'Projects', 'Tenant manager', '', undefined])(
    'accepts %p as a page title',
    (title) => {
      expect(isBannedPageTitle(title)).toBe(false);
    }
  );

  it('does not mistake the failed verb for advice', () => {
    expect(namesNextAction('Failed to update version')).toBe(false);
    expect(namesNextAction('Could not load branches')).toBe(false);
    expect(namesNextAction("Couldn't create tag.")).toBe(false);
    expect(namesNextAction('Could not sign out. Try again.')).toBe(true);
    expect(namesNextAction('Slug is taken — try acme-eu')).toBe(true);
    expect(namesNextAction('Name is required')).toBe(true);
    expect(namesNextAction('')).toBe(false);
    expect(namesNextAction(null)).toBe(false);
  });

  it('adds a next action only where one is missing', () => {
    expect(withNextAction('Could not load branches')).toBe('Could not load branches — try again.');
    expect(withNextAction('Failed to publish.')).toBe('Failed to publish — try again.');
    expect(withNextAction('Server error (500)!', 'reload the page.')).toBe(
      'Server error (500) — reload the page.'
    );
    expect(withNextAction('Could not sign out. Try again.')).toBe('Could not sign out. Try again.');
    expect(withNextAction('  Enter a valid URL.  ')).toBe('Enter a valid URL.');
  });

  it('tells an operational failure from a rule', () => {
    expect(isOperationalFailure('Failed to enable mock for v1.0.0.')).toBe(true);
    expect(isOperationalFailure("Couldn't reach the server")).toBe(true);
    expect(isOperationalFailure('Request failed (502)')).toBe(true);
    expect(isOperationalFailure('Unexpected error')).toBe(true);
    expect(isOperationalFailure('System primitives cannot be edited')).toBe(false);
    expect(isOperationalFailure('That name is taken')).toBe(false);
    expect(isOperationalFailure('')).toBe(false);
  });

  it('voices failures and leaves rules as written', () => {
    expect(voiceFailure('Failed to copy URL to clipboard.')).toBe(
      'Failed to copy URL to clipboard — try again.'
    );
    expect(voiceFailure(' That name is taken ')).toBe('That name is taken');
    expect(voiceFailure('Could not sign out. Try again.')).toBe('Could not sign out. Try again.');
    expect(voiceFailure('')).toBe(UNKNOWN_FAILURE);
    expect(voiceFailure(null)).toBe(UNKNOWN_FAILURE);
  });

  it('never returns a blank sentence', () => {
    expect(withNextAction('')).toBe(UNKNOWN_FAILURE);
    expect(withNextAction('   ')).toBe(UNKNOWN_FAILURE);
    expect(withNextAction(undefined)).toBe(UNKNOWN_FAILURE);
    expect(withNextAction('Broke', '   ')).toBe(`Broke — ${DEFAULT_NEXT_ACTION}`);
    expect(namesNextAction(UNKNOWN_FAILURE)).toBe(true);
  });
});

// =========================================================================================
// 2. The source
// =========================================================================================

describe('the source passes the §10 voice check', () => {
  it('finds the copy it is meant to judge (the scan is not silently empty)', () => {
    expect(parsed.length).toBeGreaterThan(100);
    expect(voicedProp('title').length).toBeGreaterThan(50);
    expect(voicedProp('description').length).toBeGreaterThan(50);
    expect(emptyStateConstants('TITLE').length).toBeGreaterThan(0);
  });

  it('keeps every literal state and page description to fourteen words', () => {
    const copies = [...voicedProp('description'), ...emptyStateConstants('DESC')];
    expect(offenders(copies, (text) => !fitsDescription(text))).toEqual([]);
  });

  it('titles no state or page "No records found", "Manage …" or "… Configuration"', () => {
    const copies = [...voicedProp('title'), ...emptyStateConstants('TITLE')];
    expect(offenders(copies, (text) => isNoRecordsCopy(text) || isBannedPageTitle(text))).toEqual(
      []
    );
  });

  it('draws no "No records found"-class copy anywhere in JSX', () => {
    expect(offenders(jsxText(), isNoRecordsCopy)).toEqual([]);
  });

  it('titles every admin navigation entry as a noun', () => {
    const sidebar = parsed.find(({ rel }) => rel.endsWith(join('admin', 'dashboard', 'AdminSidebar.tsx')));
    const overview = parsed.find(({ rel }) =>
      rel.endsWith(join('admin', 'dashboard', 'AdminDashboardClient.tsx'))
    );
    expect(sidebar).toBeDefined();
    expect(overview).toBeDefined();
    const titles: Copy[] = [];
    for (const source of [sidebar!, overview!]) {
      const recurse = (node: ts.Node) => {
        if (
          ts.isPropertyAssignment(node) &&
          node.name.getText(source.file) === 'title' &&
          literalOf(node.initializer) !== null
        ) {
          titles.push({ where: at(source.rel, source.file, node), text: literalOf(node.initializer)! });
        }
        ts.forEachChild(node, recurse);
      };
      recurse(source.file);
    }
    expect(titles.length).toBeGreaterThan(5);
    expect(offenders(titles, isBannedPageTitle)).toEqual([]);
  });

  it('raises every toast through the voiced wrapper, never sonner directly', () => {
    const direct = parsed
      .filter(({ rel }) => !SONNER_ALLOWED.has(rel))
      .filter(({ text }) => /from\s+['"]sonner['"]/.test(text))
      .map(({ rel }) => rel);
    expect(direct).toEqual([]);
  });
});
