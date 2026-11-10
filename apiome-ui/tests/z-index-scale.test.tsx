/**
 * The stacking scale (SUX-1.1, apiome#6748).
 *
 * "What paints over what" used to be a contest of literals — `z-[9998]` for a dialog's
 * scrim, `z-[10000]` for a select, `z-[10050]` for a confirm, and a Designer header at
 * `z-[10100]` that therefore painted over every one of them. The scale replaces the
 * numbers with ten named steps. This suite pins the contract:
 *
 *   1. `globals.css` declares exactly the steps `lib/zLayers.ts` lists, in ascending order,
 *      with the values the roadmap fixes, plus one `z-<step>` utility per step.
 *   2. The page layer sits wholly below the overlay layer, so a scrim covers the header.
 *   3. No primitive under `components/ui/` writes a literal z-index, and no declaration in
 *      `globals.css` does either.
 *   4. The overlay primitives render on their step, so a select inside a dialog inside a
 *      drawer is above both, and a toast and an alert clear all three.
 *   5. `cn()` treats a step and a literal as the same property, so an override replaces the
 *      primitive's layer instead of fighting it in the cascade.
 *
 * That the browser really stacks this way — the scrim over the header, the listbox over
 * the dialog — is `e2e/hive-z-index-scale.spec.ts`; jsdom has no layout.
 */

import React from 'react';
import { readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogTitle,
} from '../src/app/components/ui/AlertDialog';
import { Dialog, DialogContent, DialogTitle } from '../src/app/components/ui/Dialog';
import { Drawer, DrawerContent, DrawerTitle } from '../src/app/components/ui/Drawer';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../src/app/components/ui/Select';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../src/app/components/ui/Tooltip';
import { cn } from '../lib/utils';
import { Z_LAYERS, zLayer } from '../lib/zLayers';
import {
  parseDeclarations,
  readGlobalsCss,
  readTokenLayer,
  resolveToken,
  resolveZIndex,
  stripCssComments,
  topLevelRules,
} from './helpers/design-tokens';
import { sourceFiles } from './helpers/source-files';

const css = readGlobalsCss();
const layer = readTokenLayer(css);

/** The values SUX-1.1 fixes for each step, lowest first. */
const EXPECTED_SCALE: Record<(typeof Z_LAYERS)[number], number> = {
  base: 0,
  raised: 10,
  sticky: 100,
  chrome: 200,
  floating: 300,
  overlay: 1000,
  modal: 1010,
  popover: 1020,
  toast: 1030,
  alert: 1040,
};

describe('the z-index tokens', () => {
  it('declares every step of the scale in `@theme static`, with the roadmap values', () => {
    for (const step of Z_LAYERS) {
      expect(resolveToken(`--z-${step}`, layer)).toBe(String(EXPECTED_SCALE[step]));
    }
  });

  it('lists the steps in strictly ascending order', () => {
    const values = Z_LAYERS.map((step) => Number(resolveToken(`--z-${step}`, layer)));
    expect([...values].sort((a, b) => a - b)).toEqual(values);
    expect(new Set(values).size).toBe(values.length);
  });

  it('declares no `--z-*` token the code-side list does not know about', () => {
    const declared = [...layer.theme.keys()].filter((name) => /^--z-[a-z]+$/.test(name));
    expect(declared).toEqual(Z_LAYERS.map((step) => `--z-${step}`));
  });

  it('keeps the whole page layer below the whole overlay layer', () => {
    expect(EXPECTED_SCALE.floating).toBeLessThan(EXPECTED_SCALE.overlay);
    expect(EXPECTED_SCALE.chrome).toBeLessThan(EXPECTED_SCALE.overlay);
  });

  it('puts popovers above modals, so a select inside a dialog is never hidden by it', () => {
    expect(EXPECTED_SCALE.popover).toBeGreaterThan(EXPECTED_SCALE.modal);
  });

  it.each(Z_LAYERS)('exposes `z-%s` as a utility that reads its token', (step) => {
    const source = stripCssComments(css);
    const utility = new RegExp(`@utility z-${step} \\{\\s*z-index: var\\(--z-${step}\\);\\s*\\}`);
    expect(source).toMatch(utility);
  });

  it('builds the inline-style expression from the same token name', () => {
    expect(zLayer('toast')).toBe('var(--z-toast)');
  });
});

describe('no literal z-index', () => {
  const UI_DIR = join(__dirname, '..', 'src', 'app', 'components', 'ui');

  /** A Tailwind z utility with a number in it (`z-50`, `z-[9999]`) or a numeric `zIndex`. */
  const LITERAL = /(?<![\w-])-?z-(\d|\[)|zIndex:\s*-?\d|z-index:\s*-?\d/;

  it('appears in any primitive under components/ui/', () => {
    const offenders = sourceFiles(UI_DIR)
      .flatMap((file) =>
        readFileSync(file, 'utf8')
          .split('\n')
          .map((line, index) => ({ file, line, index }))
      )
      .filter(({ line }) => LITERAL.test(line))
      .map(({ file, line, index }) => `${relative(UI_DIR, file)}:${index + 1}: ${line.trim()}`);

    expect(offenders).toEqual([]);
  });

  it('appears in any declaration in globals.css', () => {
    const offenders = topLevelRules(css)
      .filter((rule) => !rule.prelude.startsWith('@utility'))
      .map((rule) => ({ prelude: rule.prelude, value: parseDeclarations(rule.body).get('z-index') }))
      .filter(({ value }) => value !== undefined && !/var\(--z-[a-z]+\)/.test(value))
      .map(({ prelude, value }) => `${prelude} → ${value}`);

    expect(offenders).toEqual([]);
  });

  it('leaves every tokenised declaration resolvable to a number', () => {
    for (const rule of topLevelRules(css)) {
      const value = parseDeclarations(rule.body).get('z-index');
      if (value === undefined || rule.prelude.startsWith('@utility')) continue;
      expect(Number.isFinite(resolveZIndex(value, layer))).toBe(true);
    }
  });
});

describe('the overlay primitives', () => {
  /** The scrim Radix renders for a modal, found by the class every Hive scrim carries. */
  const scrims = () => Array.from(document.querySelectorAll('.hive-overlay'));

  it('puts a dialog scrim on `overlay` and its surface on `modal`', () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogTitle>Publish</DialogTitle>
        </DialogContent>
      </Dialog>
    );

    expect(scrims()).toHaveLength(1);
    expect(scrims()[0]).toHaveClass('z-overlay');
    expect(screen.getByRole('dialog', { name: 'Publish' })).toHaveClass('z-modal');
  });

  it('puts a drawer on the same two steps as a dialog', () => {
    render(
      <Drawer open>
        <DrawerContent>
          <DrawerTitle>Details</DrawerTitle>
        </DrawerContent>
      </Drawer>
    );

    expect(scrims()[0]).toHaveClass('z-overlay');
    expect(screen.getByRole('dialog', { name: 'Details' })).toHaveClass('z-modal');
  });

  it('puts an alert dialog, scrim and surface, on `alert`', () => {
    render(
      <AlertDialog open>
        <AlertDialogContent>
          <AlertDialogTitle>Delete project?</AlertDialogTitle>
          <AlertDialogDescription>This cannot be undone.</AlertDialogDescription>
        </AlertDialogContent>
      </AlertDialog>
    );

    expect(scrims()[0]).toHaveClass('z-alert');
    // The surface is centred by a fixed wrapper; the wrapper is what stacks.
    const surface = screen.getByRole('alertdialog', { name: 'Delete project?' });
    expect(surface.parentElement).toHaveClass('z-alert');
  });

  it('puts a select listbox on `popover`, above the dialog it opens from', () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogTitle>Edit</DialogTitle>
          <Select open value="a">
            <SelectTrigger aria-label="Domain">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="a">Alpha</SelectItem>
            </SelectContent>
          </Select>
        </DialogContent>
      </Dialog>
    );

    expect(screen.getByRole('listbox')).toHaveClass('z-popover');
  });

  it('puts a tooltip on `popover`', () => {
    render(
      <TooltipProvider>
        <Tooltip open>
          <TooltipTrigger>Help</TooltipTrigger>
          <TooltipContent>More about this</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );

    // Radix renders the text twice (visible, and once for assistive technology); the
    // visible copy is the one carrying the classes.
    const content = screen.getAllByText('More about this').find((node) => node.classList.contains('z-popover'));
    expect(content).toBeDefined();
  });

  it('puts the toaster on `toast` instead of sonner’s own 999999999', () => {
    const source = readFileSync(join(__dirname, '..', 'src', 'app', 'components', 'ui', 'Toaster.tsx'), 'utf8');
    expect(source).toContain("style={{ zIndex: zLayer('toast') }}");
  });
});

describe('cn() and the stacking utilities', () => {
  it('lets a caller’s literal replace a primitive’s step', () => {
    expect(cn('fixed z-modal', 'z-[20]')).toBe('fixed z-[20]');
  });

  it('lets a caller’s step replace a primitive’s literal, and another step', () => {
    expect(cn('z-50', 'z-popover')).toBe('z-popover');
    expect(cn('z-overlay', 'z-alert')).toBe('z-alert');
  });

  it('leaves unrelated utilities alone', () => {
    expect(cn('z-chrome', 'shrink-0')).toBe('z-chrome shrink-0');
  });
});
