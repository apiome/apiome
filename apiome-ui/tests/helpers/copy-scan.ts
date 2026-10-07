/**
 * Source scanner for the HIVE-10.4 copy gate (#5340, `docs/mockups/DESIGN.md` §10).
 *
 * The gate needs to read the *copy* in `src/` — the strings a reader sees — without running the
 * app. This module walks every `.ts` / `.tsx` file with the TypeScript compiler API and returns
 * three kinds of text, each with where it was found:
 *
 * - **state copy** — the `title` / `description` / `message` of the four state primitives
 *   (`EmptyState`, `GatedState`, `ErrorState`, `ErrorBanner`, `LoadingState`) and of
 *   `PageHeader`, with string constants resolved through the same file or one import hop;
 * - **literals** — every user-facing string literal (and the fixed head of a template), skipping
 *   imports, object keys, type positions, `className`-style attributes and `console.*` calls;
 * - **JSX text** — text written directly between tags, with the tags it sits inside.
 *
 * It reports; the rules live in `tests/copy-voice.test.ts`.
 */

import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import ts from 'typescript';

/** `apiome-ui/`. */
export const UI_ROOT = join(__dirname, '..', '..');
/** `apiome-ui/src/`. */
export const SRC_ROOT = join(UI_ROOT, 'src');

/** The components whose props are state copy, and which props. */
export const STATE_COMPONENTS: Readonly<Record<string, readonly string[]>> = {
  EmptyState: ['title', 'description'],
  GatedState: ['title', 'description'],
  ErrorState: ['title', 'description'],
  ErrorBanner: ['title', 'description'],
  LoadingState: ['message'],
  PageHeader: ['title', 'description'],
  DataTable: ['errorTitle', 'loadingLabel'],
};

/** Attributes whose string values are never prose. */
const NON_PROSE_ATTRIBUTES = new Set([
  'className',
  'class',
  'id',
  'href',
  'src',
  'key',
  'type',
  'role',
  'name',
  'htmlFor',
  'data-testid',
  'testId',
  'variant',
  'size',
  'tone',
  'value',
  'defaultValue',
  'method',
  'target',
  'rel',
  'autoComplete',
  'inputMode',
  'side',
  'align',
]);

/** Where a piece of copy was found. */
export interface CopyLocation {
  /** Path relative to `apiome-ui/`. */
  file: string;
  /** 1-based line. */
  line: number;
}

/** A state primitive's prop, resolved to text. */
export interface StateCopy extends CopyLocation {
  component: string;
  prop: string;
  text: string;
}

/** A state primitive call site, with the props it passes. */
export interface StateSite extends CopyLocation {
  component: string;
  props: readonly string[];
}

/** A string literal, or the fixed head of a template. */
export interface LiteralCopy extends CopyLocation {
  text: string;
  /** The template's literal head only (there were substitutions after it). */
  partial: boolean;
  /**
   * `title` when the literal is assigned to a `title` / `heading` property or to a constant whose
   * name ends in `TITLE` / `HEADING` — copy that states what happened, held to the title rules.
   */
  role: 'title' | 'text';
}

/** Text between JSX tags. */
export interface JsxTextCopy extends CopyLocation {
  text: string;
  /** Tag names of the enclosing JSX elements, innermost first. */
  ancestors: readonly string[];
}

/** Everything the scan found. */
export interface CopyScan {
  stateCopy: StateCopy[];
  stateSites: StateSite[];
  literals: LiteralCopy[];
  jsxText: JsxTextCopy[];
}

/**
 * Every source file under `src/`, generated code excluded.
 *
 * @param directory Directory to walk.
 * @returns Absolute paths.
 */
export function sourceFiles(directory: string = SRC_ROOT): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) return entry === 'generated' ? [] : sourceFiles(path);
    return /\.tsx?$/.test(entry) && !/\.d\.ts$/.test(entry) ? [path] : [];
  });
}

const parsed = new Map<string, ts.SourceFile>();

/** Parse a file once. */
function parse(file: string): ts.SourceFile {
  let source = parsed.get(file);
  if (!source) {
    source = ts.createSourceFile(file, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    parsed.set(file, source);
  }
  return source;
}

/** The tag name of a JSX element, as written (`EmptyState`, `ui.EmptyState` → `EmptyState`). */
function tagName(node: ts.JsxOpeningLikeElement): string {
  const text = node.tagName.getText();
  return text.includes('.') ? text.slice(text.lastIndexOf('.') + 1) : text;
}

/** Resolve an import specifier to a file, for `@/`, `@lib/` and relative paths. */
function resolveImport(fromFile: string, specifier: string): string | undefined {
  let base: string;
  if (specifier.startsWith('@/')) base = join(SRC_ROOT, specifier.slice(2));
  else if (specifier.startsWith('@lib/')) base = join(UI_ROOT, 'lib', specifier.slice(5));
  else if (specifier.startsWith('.')) base = resolve(dirname(fromFile), specifier);
  else return undefined;
  for (const candidate of [base, `${base}.ts`, `${base}.tsx`, join(base, 'index.ts'), join(base, 'index.tsx')]) {
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
  }
  return undefined;
}

/** A top-level `const NAME = 'text'` (or template without substitutions) in a file. */
function constString(file: string, name: string): string | undefined {
  const source = parse(file);
  for (const statement of source.statements) {
    if (!ts.isVariableStatement(statement)) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name) || declaration.name.text !== name || !declaration.initializer) continue;
      const init = declaration.initializer;
      if (ts.isStringLiteral(init) || ts.isNoSubstitutionTemplateLiteral(init)) return init.text;
    }
  }
  return undefined;
}

/** Where an identifier imported into `file` comes from. */
function importedFrom(file: string, name: string): string | undefined {
  for (const statement of parse(file).statements) {
    if (!ts.isImportDeclaration(statement) || !statement.importClause?.namedBindings) continue;
    const bindings = statement.importClause.namedBindings;
    if (!ts.isNamedImports(bindings)) continue;
    const match = bindings.elements.find((element) => element.name.text === name);
    if (!match) continue;
    const target = resolveImport(file, (statement.moduleSpecifier as ts.StringLiteral).text);
    if (target) return constString(target, match.propertyName?.text ?? name) !== undefined ? target : undefined;
  }
  return undefined;
}

/**
 * The fixed texts an expression can evaluate to: a literal, both branches of a conditional, or a
 * string constant in this file or one import away. Anything computed returns nothing.
 */
function resolveTexts(file: string, expression: ts.Expression): string[] {
  if (ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) return [expression.text];
  if (ts.isParenthesizedExpression(expression)) return resolveTexts(file, expression.expression);
  if (ts.isConditionalExpression(expression)) {
    return [...resolveTexts(file, expression.whenTrue), ...resolveTexts(file, expression.whenFalse)];
  }
  if (ts.isBinaryExpression(expression) && expression.operatorToken.kind === ts.SyntaxKind.QuestionQuestionToken) {
    return resolveTexts(file, expression.right);
  }
  if (ts.isIdentifier(expression)) {
    const local = constString(file, expression.text);
    if (local !== undefined) return [local];
    const origin = importedFrom(file, expression.text);
    const imported = origin ? constString(origin, expression.text) : undefined;
    return imported !== undefined ? [imported] : [];
  }
  return [];
}

/** Whether a string literal node is copy a reader can see. */
function isProseLiteral(node: ts.StringLiteral | ts.NoSubstitutionTemplateLiteral | ts.TemplateHead): boolean {
  let parent: ts.Node = node.parent;
  if (ts.isTemplateExpression(parent)) parent = parent.parent;
  if (ts.isImportDeclaration(parent) || ts.isExportDeclaration(parent) || ts.isExternalModuleReference(parent)) return false;
  if (ts.isLiteralTypeNode(parent) || ts.isImportTypeNode(parent)) return false;
  if ((ts.isPropertyAssignment(parent) || ts.isPropertySignature(parent)) && parent.name === node) return false;
  if (ts.isElementAccessExpression(parent) && parent.argumentExpression === node) return false;
  if (ts.isCaseClause(parent)) return false;
  if (ts.isBinaryExpression(parent) && [ts.SyntaxKind.EqualsEqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken, ts.SyntaxKind.EqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsToken].includes(parent.operatorToken.kind)) return false;
  // A JSX attribute that is not prose (`className="…"`), directly or through `{…}`.
  let attribute: ts.Node | undefined = parent;
  if (ts.isJsxExpression(attribute)) attribute = attribute.parent;
  if (attribute && ts.isJsxAttribute(attribute) && NON_PROSE_ATTRIBUTES.has(attribute.name.getText())) return false;
  // Arguments of console.*, cn()/clsx() class builders, and require().
  for (let up: ts.Node | undefined = node.parent; up && !ts.isSourceFile(up); up = up.parent) {
    if (ts.isCallExpression(up)) {
      const callee = up.expression.getText();
      if (/^console\./.test(callee) || /^(cn|clsx|cva|twMerge|require)$/.test(callee)) return false;
    }
    if (ts.isFunctionLike(up) || ts.isBlock(up)) break;
  }
  return true;
}

/** Whether a literal is assigned as a title (property `title`/`heading`, or a `*_TITLE` const). */
function literalRole(node: ts.Node): 'title' | 'text' {
  let parent = node.parent;
  while (parent && (ts.isConditionalExpression(parent) || ts.isParenthesizedExpression(parent) || ts.isAsExpression(parent))) {
    parent = parent.parent;
  }
  if (parent && ts.isPropertyAssignment(parent) && /^(title|heading)$/i.test(parent.name.getText())) return 'title';
  if (parent && ts.isVariableDeclaration(parent) && /(TITLE|HEADING)$/.test(parent.name.getText())) return 'title';
  if (parent && (ts.isBindingElement(parent) || ts.isParameter(parent)) && /(title|heading)$/i.test(parent.name.getText())) {
    return 'title';
  }
  if (parent && ts.isJsxAttribute(parent) && /^(title|heading)$/.test(parent.name.getText())) return 'title';
  if (parent && ts.isJsxExpression(parent) && parent.parent && ts.isJsxAttribute(parent.parent) && /^(title|heading)$/.test(parent.parent.name.getText())) {
    return 'title';
  }
  return 'text';
}

/** The JSX tags enclosing a node, innermost first. */
function enclosingTags(node: ts.Node): string[] {
  const tags: string[] = [];
  for (let up: ts.Node | undefined = node.parent; up; up = up.parent) {
    if (ts.isJsxElement(up)) tags.push(tagName(up.openingElement));
  }
  return tags;
}

let cache: CopyScan | undefined;

/**
 * Scan every source file under `src/`.
 *
 * @returns The state copy, state call sites, literals and JSX text found. Cached per process.
 */
export function scanCopy(): CopyScan {
  if (cache) return cache;
  const scan: CopyScan = { stateCopy: [], stateSites: [], literals: [], jsxText: [] };

  for (const file of sourceFiles()) {
    const source = parse(file);
    const at = (node: ts.Node): CopyLocation => ({
      file: relative(UI_ROOT, file),
      line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
    });

    const visit = (node: ts.Node): void => {
      if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
        const component = tagName(node);
        const props = STATE_COMPONENTS[component];
        if (props) {
          const passed: string[] = [];
          for (const attribute of node.attributes.properties) {
            if (!ts.isJsxAttribute(attribute)) continue;
            const prop = attribute.name.getText();
            passed.push(prop);
            if (!props.includes(prop) || !attribute.initializer) continue;
            const value = ts.isStringLiteral(attribute.initializer)
              ? [attribute.initializer.text]
              : attribute.initializer.expression
                ? resolveTexts(file, attribute.initializer.expression)
                : [];
            for (const text of value) scan.stateCopy.push({ ...at(attribute), component, prop, text });
          }
          scan.stateSites.push({ ...at(node), component, props: passed });
        }
      }
      if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) && isProseLiteral(node)) {
        scan.literals.push({ ...at(node), text: node.text, partial: false, role: literalRole(node) });
      }
      if (ts.isTemplateHead(node) && isProseLiteral(node)) {
        scan.literals.push({ ...at(node), text: node.text, partial: true, role: literalRole(node.parent) });
      }
      if (ts.isJsxText(node)) {
        const text = node.text.replace(/\s+/g, ' ').trim();
        if (text) scan.jsxText.push({ ...at(node), text, ancestors: enclosingTags(node) });
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }

  cache = scan;
  return scan;
}
