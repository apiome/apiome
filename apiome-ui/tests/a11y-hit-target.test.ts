/**
 * Pointer targets — HIVE-10.2 (#5338), `docs/mockups/DESIGN.md` §9 "44 px min touch targets in
 * comfortable density".
 *
 * Small controls keep their drawn size and gain an invisible hit area from `.hit-target`. This
 * suite pins the parts of that contract a Jest run can see: the token values per density, the
 * rule's shape (behind the real boxes, centred, never shrinking a control), and that every small
 * primitive the audit found opts in. Real hit-testing runs in the browser gate (`e2e/a11y/`).
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { parseBlock, parseDeclarations, readGlobalsCss, stripCssComments, topLevelRules } from './helpers/design-tokens';

const css = readGlobalsCss();
const rules = topLevelRules(css);
const ROOT = join(__dirname, '..');

/** The declarations of the first top-level rule whose prelude is exactly `prelude`. */
function rule(prelude: string): Map<string, string> {
  const found = rules.find((candidate) => candidate.prelude === prelude);
  if (!found) throw new Error(`globals.css has no top-level \`${prelude}\` rule`);
  return parseDeclarations(found.body);
}

/** Small primitives that must opt into `.hit-target`, with the file that draws each. */
const OPTED_IN: Array<[string, string]> = [
  ['Button (all sizes)', 'src/app/components/ui/Button.tsx'],
  ['Segmented option', 'src/app/components/ui/Segmented.tsx'],
  ['Checkbox', 'src/app/components/ui/Checkbox.tsx'],
  ['Radio', 'src/app/components/ui/RadioGroup.tsx'],
  ['Switch', 'src/app/components/ui/Switch.tsx'],
  ['Dialog close', 'src/app/components/ui/Dialog.tsx'],
  ['Drawer close', 'src/app/components/ui/Drawer.tsx'],
  ['DataTable filter chip', 'src/app/components/ui/DataTable.tsx'],
  ['Rail item', 'src/app/components/shell/railChrome.tsx'],
  ['Rail menu row', 'src/app/components/shell/railMenu.tsx'],
  ['Rail collapse handle', 'src/app/components/shell/AppShell.tsx'],
  ['Permission matrix toggle', 'src/app/components/ade/roles/PermissionMatrix.tsx'],
];

describe('--target-min (pointer target size per density)', () => {
  it('is 44 px (2.75rem) in comfortable density', () => {
    expect(parseBlock(css, ':root').get('--target-min')).toBe('2.75rem');
  });

  it('drops to the WCAG 2.2 AA floor of 24 px (1.5rem) in compact density', () => {
    expect(parseBlock(css, 'html[data-density="compact"]').get('--target-min')).toBe('1.5rem');
  });
});

describe('.hit-target', () => {
  const after = rule('.hit-target::after');

  it('draws a centred box at least --target-min on each side, never smaller than the control', () => {
    expect(after.get('content')).toBe("''");
    expect(after.get('position')).toBe('absolute');
    expect(after.get('width')).toBe('max(100%, var(--target-min))');
    expect(after.get('height')).toBe('max(100%, var(--target-min))');
    expect(after.get('transform')).toBe('translate(-50%, -50%)');
  });

  it('sits behind every real box, so a neighbour control always wins the click', () => {
    expect(after.get('z-index')).toBe('-1');
    expect(rule(':where(:has(> .hit-target))').get('isolation')).toBe('isolate');
  });

  it('makes unpositioned hosts `relative`, leaving an `absolute` / `fixed` / `sticky` host alone', () => {
    expect(rule('.hit-target:not(.absolute, .fixed, .sticky)').get('position')).toBe('relative');
    // Never a bare `.hit-target { position }`: unlayered, it would beat the close buttons' `absolute`.
    expect(rules.some((candidate) => candidate.prelude === '.hit-target')).toBe(false);
    expect(stripCssComments(css)).not.toMatch(/@layer\s+[^{]*\{/);
  });

  it.each(OPTED_IN)('%s opts in', (_name, file) => {
    expect(readFileSync(join(ROOT, file), 'utf8')).toMatch(/['"`\s]hit-target[\s'"`]/);
  });
});
