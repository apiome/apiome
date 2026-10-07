/**
 * The design system is a route, and it shows every primitive (HIVE-10.5, #5341).
 *
 * `/design-system` draws its specimens with the shipped components, so it cannot drift from
 * the app the way a static mockup can. It *can* fall behind: a new primitive lands in
 * `components/ui` and nobody adds a specimen. This suite is the CI check that stops that:
 *
 *   1. Every PascalCase value exported from a `components/ui/**\/*.tsx` module — a component —
 *      is drawn as JSX (`<Name`) somewhere under `src/app/design-system/`, or is listed in
 *      {@link GALLERY_EXEMPT} with the reason it cannot be drawn on its own.
 *   2. The exemption list stays honest: every entry still names an exported primitive, and
 *      none is also drawn (an exemption is for what cannot be drawn, not a to-do list).
 *   3. The contents list cannot point at nothing: every section in `galleries/sections.ts` is a
 *      real `id` in its gallery, and every gallery section is in the contents list.
 *
 * Exports are read with the TypeScript parser rather than by importing the modules, so a
 * type-only re-export (`export type { … }`) is not mistaken for a component.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import ts from 'typescript';

import {
  HIVE_GALLERY_SECTIONS,
  MCP_GALLERY_SECTION,
  PATTERN_GALLERIES,
  SUPPORTING_GALLERY_SECTIONS,
} from '../src/app/design-system/galleries/sections';

const ROOT = join(__dirname, '..');
const UI = join(ROOT, 'src', 'app', 'components', 'ui');
const DESIGN_SYSTEM = join(ROOT, 'src', 'app', 'design-system');
const GALLERIES = join(DESIGN_SYSTEM, 'galleries');

/**
 * Primitives that have no specimen of their own, and why. Each is either a part another
 * component draws for you, an alias, a global singleton, or a panel that fetches its own data
 * and so cannot appear on a data-free page.
 */
const GALLERY_EXEMPT: Readonly<Record<string, string>> = {
  // ---- parts drawn by their parent ------------------------------------------------------
  AlertDialog: 'Radix root behind ConfirmDialog / AlertDialog; drawn by the Confirms & prompts specimens.',
  AlertDialogPortal: 'Part of AlertDialogContent.',
  AlertDialogOverlay: 'Part of AlertDialogContent.',
  AlertDialogTrigger: 'The imperative dialogs open from useDialog(), not a trigger.',
  AlertDialogContent: 'Drawn by the Confirms & prompts specimens through dialogs/ConfirmDialog.',
  AlertDialogHeader: 'Drawn by the Confirms & prompts specimens through dialogs/ConfirmDialog.',
  AlertDialogFooter: 'Drawn by the Confirms & prompts specimens through dialogs/ConfirmDialog.',
  AlertDialogTitle: 'Drawn by the Confirms & prompts specimens through dialogs/ConfirmDialog.',
  AlertDialogDescription: 'Drawn by the Confirms & prompts specimens through dialogs/ConfirmDialog.',
  AlertDialogAction: 'Drawn by the Confirms & prompts specimens through dialogs/ConfirmDialog.',
  AlertDialogCancel: 'Drawn by the Confirms & prompts specimens through dialogs/ConfirmDialog.',
  DialogPortal: 'Part of DialogContent.',
  DialogOverlay: 'Part of DialogContent.',
  DialogClose: 'Part of DialogContent (its close button).',
  DrawerPortal: 'Part of DrawerContent.',
  DrawerOverlay: 'Part of DrawerContent.',
  SelectScrollUpButton: 'Part of SelectContent; appears only when the list overflows.',
  SelectScrollDownButton: 'Part of SelectContent; appears only when the list overflows.',
  DataTableBulkBar: 'Drawn by DataTable when rows are selected; see the Tables section.',
  DetailTabsTrigger: 'Drawn by DetailTabsList for each tab; see the MCP DetailTabs specimen.',
  EmptyStateArt: 'The hex art every EmptyState, ErrorState and GatedState draws.',
  ChartFrame: 'The accessible frame every MCP chart draws; see the MCP charts specimens.',
  // ---- aliases --------------------------------------------------------------------------
  CardBody: 'Alias of CardContent, kept for pre-Hive call sites.',
  // ---- global singletons ----------------------------------------------------------------
  Toaster: 'Mounted once by the root layout; the Legacy modal & toasts section raises every tone.',
  // ---- self-fetching panels -------------------------------------------------------------
  ShadowedNamesPanel: 'Fetches the tenant shadowing report itself; needs a session and data.',
  TrustDriftAlertsPanel: 'Fetches an endpoint’s drift report itself; needs a session and data.',
};

/**
 * Every `.tsx` file under a directory, recursively.
 *
 * @param directory Where to start.
 * @returns Absolute paths.
 */
function tsxFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) return tsxFiles(path);
    return entry.endsWith('.tsx') && !entry.endsWith('.test.tsx') ? [path] : [];
  });
}

/**
 * The PascalCase value exports of one module — its components. Type-only exports, ALL_CAPS
 * constants and default exports (which repeat a named export) are left out.
 *
 * @param path The module.
 * @returns The exported names.
 */
function componentExports(path: string): string[] {
  const file = ts.createSourceFile(path, readFileSync(path, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const names: string[] = [];
  const exported = (node: ts.Node) =>
    ts.canHaveModifiers(node) &&
    (ts.getModifiers(node) ?? []).some((m) => m.kind === ts.SyntaxKind.ExportKeyword);

  file.forEachChild((node) => {
    if (ts.isFunctionDeclaration(node) && exported(node) && node.name) names.push(node.name.text);
    if (ts.isClassDeclaration(node) && exported(node) && node.name) names.push(node.name.text);
    if (ts.isVariableStatement(node) && exported(node)) {
      for (const declaration of node.declarationList.declarations) {
        if (ts.isIdentifier(declaration.name)) names.push(declaration.name.text);
      }
    }
    if (
      ts.isExportDeclaration(node) &&
      !node.isTypeOnly &&
      !node.moduleSpecifier &&
      node.exportClause &&
      ts.isNamedExports(node.exportClause)
    ) {
      for (const element of node.exportClause.elements) {
        if (!element.isTypeOnly) names.push(element.name.text);
      }
    }
  });
  return names.filter((name) => /^[A-Z][a-z]/.test(name));
}

/** name → the module that exports it, for every primitive. */
const PRIMITIVES = new Map<string, string>();
for (const path of tsxFiles(UI)) {
  for (const name of componentExports(path)) PRIMITIVES.set(name, relative(ROOT, path));
}

/** Every gallery source, concatenated. */
const GALLERY_SOURCE = tsxFiles(DESIGN_SYSTEM)
  .map((path) => readFileSync(path, 'utf8'))
  .join('\n');

/**
 * Whether the gallery draws a component as JSX.
 *
 * @param name The component.
 * @returns `true` when `<Name` appears in a gallery source.
 */
function drawn(name: string): boolean {
  return new RegExp(`<${name}[\\s/>]`).test(GALLERY_SOURCE);
}

/**
 * The `id="…"` values of the `<Section>` elements in one gallery file.
 *
 * @param file The gallery file name under `galleries/`.
 * @returns The section ids, in source order.
 */
function sectionIds(file: string): string[] {
  const source = readFileSync(join(GALLERIES, file), 'utf8');
  return [...source.matchAll(/<Section\s+id="([^"]+)"/g)].map((match) => match[1]);
}

describe('every shipped primitive is in the /design-system gallery', () => {
  it('finds the primitives it is meant to check (the scan is not silently empty)', () => {
    expect(PRIMITIVES.size).toBeGreaterThan(80);
    expect(PRIMITIVES.has('Button')).toBe(true);
    expect(PRIMITIVES.has('GradeGlyph')).toBe(true);
    // A type-only re-export is not a component.
    expect(PRIMITIVES.has('ErrorStateVariant')).toBe(false);
  });

  it('draws every primitive, or says why it cannot', () => {
    const missing = [...PRIMITIVES]
      .filter(([name]) => !drawn(name) && !(name in GALLERY_EXEMPT))
      .map(([name, path]) => `${name} (${path}) — add a specimen to a gallery under src/app/design-system/galleries/`);
    expect(missing).toEqual([]);
  });

  it('keeps every exemption pointing at a real primitive', () => {
    const stale = Object.keys(GALLERY_EXEMPT).filter((name) => !PRIMITIVES.has(name));
    expect(stale).toEqual([]);
  });

  it('does not exempt what the gallery already draws', () => {
    const redundant = Object.keys(GALLERY_EXEMPT).filter(drawn);
    expect(redundant).toEqual([]);
  });

  it('gives every exemption a reason', () => {
    for (const reason of Object.values(GALLERY_EXEMPT)) expect(reason.trim().length).toBeGreaterThan(10);
  });
});

describe('the contents list matches the galleries', () => {
  it.each([
    ['HiveGallery.tsx', HIVE_GALLERY_SECTIONS],
    ['SupportingGallery.tsx', SUPPORTING_GALLERY_SECTIONS],
  ] as const)('lists every section of %s, in order', (file, sections) => {
    expect(sections.map((section) => section.id)).toEqual(sectionIds(file));
  });

  it('gives every section a unique anchor', () => {
    const ids = [...HIVE_GALLERY_SECTIONS, ...SUPPORTING_GALLERY_SECTIONS, MCP_GALLERY_SECTION].map(
      (section) => section.id
    );
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('links only to pattern galleries that exist', () => {
    for (const gallery of PATTERN_GALLERIES) {
      const directory = gallery.href.replace(/^\/design-system\//, '');
      expect(statSync(join(DESIGN_SYSTEM, directory, 'page.tsx')).isFile()).toBe(true);
    }
  });
});
