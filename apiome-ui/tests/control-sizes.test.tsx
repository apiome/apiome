/**
 * Field size parity (SUX-1.2, apiome#6749).
 *
 * `Button` came in 30 / 36 / 42 px; `Input`, `Select` and `Textarea` only in 36 px, and a
 * `Segmented` stood 34 px beside a 36 px button. This suite holds the fix down on computed
 * classes — the browser half (`e2e/hive-control-sizes.spec.ts`) measures the boxes:
 *
 *   1. each field size binds the matching `--control-h*` metric and takes the button's
 *      padding, text size and radius at that step;
 *   2. a field with no `size` renders exactly as before (`md`);
 *   3. `FormField` hands its size to the control inside it, however deeply nested, and
 *      scales its label to `text-xs` at `sm`;
 *   4. a `Segmented` of each size, track inset included, is as tall as the metric.
 */

import React from 'react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  Button,
  DEFAULT_FIELD_SIZE,
  FIELD_LABEL_SIZE_CLASS,
  FormField,
  Input,
  Segmented,
  SegmentedItem,
  Select,
  SelectTrigger,
  SelectValue,
  Textarea,
  fieldSizeVariants,
  segmentedTrackClass,
  textareaSizeVariants,
  type FieldSize,
} from '../src/app/components/ui';

/** Every class on an element, as a set — order is meaningless, membership is not. */
function classesOf(element: Element): Set<string> {
  return new Set(element.className.split(/\s+/).filter(Boolean));
}

/** The metric each field size is bound to. */
const HEIGHT: Record<FieldSize, string> = {
  sm: 'h-[var(--control-h-sm)]',
  md: 'h-[var(--control-h)]',
  lg: 'h-[var(--control-h-lg)]',
};

/** The button size that shares each field size's step. */
const BUTTON_SIZE = { sm: 'sm', md: 'default', lg: 'lg' } as const;

/** The classes of one family a button and a field must agree on: padding-x, text size, radius. */
function stepClasses(classes: Set<string>): { px: string[]; text: string[]; radius: string[] } {
  const all = [...classes];
  return {
    px: all.filter((c) => /^px-/.test(c)),
    text: all.filter((c) => /^text-(xs|sm|base|lg)$/.test(c)),
    radius: all.filter((c) => /^rounded-(sm|md|lg)$/.test(c)),
  };
}

/** Render a select trigger, which Radix only draws inside a root. */
function renderTrigger(props: React.ComponentProps<typeof SelectTrigger> = {}) {
  render(
    <Select>
      <SelectTrigger aria-label="kind" {...props}>
        <SelectValue placeholder="Pick" />
      </SelectTrigger>
    </Select>
  );
  return screen.getByRole('combobox', { name: 'kind' });
}

describe('Input, Select trigger and Textarea sizes', () => {
  it.each<FieldSize>(['sm', 'md', 'lg'])('binds the %s input and trigger to its metric', (size) => {
    render(<Input aria-label="name" size={size} />);
    expect(classesOf(screen.getByLabelText('name'))).toContain(HEIGHT[size]);
    expect(classesOf(renderTrigger({ size }))).toContain(HEIGHT[size]);
  });

  it.each<FieldSize>(['sm', 'md', 'lg'])(
    'gives a %s field the same padding, text size and radius as the button of that step',
    (size) => {
      render(
        <>
          <Button size={BUTTON_SIZE[size]}>Go</Button>
          <Input aria-label="name" size={size} />
        </>
      );
      const button = stepClasses(classesOf(screen.getByRole('button', { name: 'Go' })));
      const input = stepClasses(classesOf(screen.getByLabelText('name')));
      expect(input).toEqual(button);
      // And exactly one of each survived `cn()`: no stale `px-3` beside an `px-2.5`.
      expect(input.px).toHaveLength(1);
      expect(input.text).toHaveLength(1);
      expect(input.radius).toHaveLength(1);
    }
  );

  it('leaves an unsized field exactly as it was', () => {
    render(
      <>
        <Input aria-label="plain" />
        <Textarea aria-label="notes" />
      </>
    );
    const input = classesOf(screen.getByLabelText('plain'));
    expect(input).toContain('h-[var(--control-h)]');
    expect(input).toContain('px-3');
    expect(input).toContain('text-sm');
    expect(input).toContain('rounded-md');
    const trigger = classesOf(renderTrigger());
    expect(trigger).toContain('h-[var(--control-h)]');
    const textarea = classesOf(screen.getByLabelText('notes'));
    expect(textarea).toContain('py-2.5');
    expect(textarea).toContain('min-h-24');
    expect(DEFAULT_FIELD_SIZE).toBe('md');
  });

  it('steps the textarea padding and text but keeps its growing height', () => {
    render(
      <>
        <Textarea aria-label="small" size="sm" />
        <Textarea aria-label="large" size="lg" />
      </>
    );
    const small = classesOf(screen.getByLabelText('small'));
    expect(small).toContain('text-xs');
    expect(small).toContain('rounded-sm');
    expect(small).toContain('px-2.5');
    expect(small).toContain('py-1.5');
    expect(small).toContain('min-h-24');
    expect(small).not.toContain('py-2.5');
    const large = classesOf(screen.getByLabelText('large'));
    expect(large).toContain('text-base');
    expect(large).toContain('px-4');
    expect(large).toContain('min-h-24');
    expect(textareaSizeVariants({ size: 'md' })).toContain('py-2.5');
  });

  it("lets a caller's own height win over the size", () => {
    render(<Input aria-label="tall" size="sm" className="h-12" />);
    const classes = classesOf(screen.getByLabelText('tall'));
    expect(classes).toContain('h-12');
    expect(classes).not.toContain('h-[var(--control-h-sm)]');
  });

  it('does not forward the size to the DOM as the native character-width attribute', () => {
    render(<Input aria-label="name" size="lg" />);
    expect(screen.getByLabelText('name')).not.toHaveAttribute('size');
  });

  it('exposes the single-line variants for a hand-built field', () => {
    expect(fieldSizeVariants({ size: 'sm' })).toContain('h-[var(--control-h-sm)]');
    expect(fieldSizeVariants()).toContain('h-[var(--control-h)]');
  });
});

describe('FormField size', () => {
  it('hands its size to an input, a nested select trigger and a textarea', () => {
    render(
      <>
        <FormField size="sm" label="Name" htmlFor="f-name">
          <Input id="f-name" />
        </FormField>
        <FormField size="lg" label="Kind">
          <Select>
            <SelectTrigger aria-label="kind">
              <SelectValue placeholder="Pick" />
            </SelectTrigger>
          </Select>
        </FormField>
        <FormField size="sm" label="Notes" htmlFor="f-notes">
          <div>
            <Textarea id="f-notes" />
          </div>
        </FormField>
      </>
    );
    expect(classesOf(screen.getByLabelText('Name'))).toContain(HEIGHT.sm);
    expect(classesOf(screen.getByRole('combobox', { name: 'kind' }))).toContain(HEIGHT.lg);
    expect(classesOf(screen.getByLabelText('Notes'))).toContain('text-xs');
  });

  it("keeps a control's own size over the field's", () => {
    render(
      <FormField size="sm" label="Name" htmlFor="f-name">
        <Input id="f-name" size="lg" />
      </FormField>
    );
    expect(classesOf(screen.getByLabelText('Name'))).toContain(HEIGHT.lg);
  });

  it.each<[FieldSize, string]>([
    ['sm', 'text-xs'],
    ['md', 'text-sm'],
    ['lg', 'text-sm'],
  ])('draws the %s label in %s', (size, text) => {
    render(
      <FormField size={size} label="Label" htmlFor="f">
        <Input id="f" />
      </FormField>
    );
    const label = screen.getByText('Label');
    expect(classesOf(label)).toContain(text);
    expect(FIELD_LABEL_SIZE_CLASS[size]).toBe(text);
  });

  it('defaults to md, so existing fields and labels are unchanged', () => {
    render(
      <FormField label="Label" htmlFor="f">
        <Input id="f" />
      </FormField>
    );
    expect(classesOf(screen.getByText('Label'))).toContain('text-sm');
    expect(classesOf(screen.getByLabelText('Label'))).toContain(HEIGHT.md);
  });

  it('lets a nested field inherit the outer size', () => {
    render(
      <FormField size="sm" label="Group">
        <FormField label="Inner" htmlFor="f-inner">
          <Input id="f-inner" />
        </FormField>
      </FormField>
    );
    expect(classesOf(screen.getByText('Inner'))).toContain('text-xs');
    expect(classesOf(screen.getByLabelText('Inner'))).toContain(HEIGHT.sm);
  });
});

describe('Segmented height equals the control metric', () => {
  const css = readFileSync(join(__dirname, '..', 'src', 'app', 'globals.css'), 'utf8');

  /**
   * The rem values of the three control metrics in the first block that declares them.
   *
   * @param block The CSS text to read from.
   * @returns `--control-h`, `-sm` and `-lg` in rem.
   */
  function metrics(block: string): Record<'md' | 'sm' | 'lg', number> {
    const read = (name: string) => {
      const match = new RegExp(`${name}:\\s*([\\d.]+)rem`).exec(block);
      if (!match) throw new Error(`${name} not found`);
      return Number(match[1]);
    };
    return { md: read('--control-h'), sm: read('--control-h-sm'), lg: read('--control-h-lg') };
  }

  /**
   * The rem height an option class computes to, given the metrics.
   *
   * @param cls An `h-[calc(var(--control-h…)-Nrem)]` class.
   * @param m The metrics.
   * @returns The option height in rem.
   */
  function optionHeight(cls: string, m: Record<'md' | 'sm' | 'lg', number>): number {
    const match = /^h-\[calc\(var\(--control-h(-sm|-lg)?\)-([\d.]+)rem\)\]$/.exec(cls);
    if (!match) throw new Error(`unexpected option height class ${cls}`);
    const base = match[1] === '-sm' ? m.sm : match[1] === '-lg' ? m.lg : m.md;
    return base - Number(match[2]);
  }

  /** The track inset, from `p-0.75` (Tailwind's 0.25rem spacing unit × 0.75, top and bottom). */
  const TRACK_INSET_REM = 2 * 0.75 * 0.25;

  it('keeps the track inset this suite assumes', () => {
    expect(segmentedTrackClass.split(/\s+/)).toContain('p-0.75');
  });

  const comfortable = metrics(css);
  const compactStart = css.indexOf('--control-h: 2rem');
  const compact = metrics(css.slice(compactStart - 1));

  it.each<['sm' | 'default' | 'lg', 'sm' | 'md' | 'lg']>([
    ['sm', 'sm'],
    ['default', 'md'],
    ['lg', 'lg'],
  ])('makes a %s group as tall as the %s control at both densities', (size, metric) => {
    render(
      <Segmented aria-label="View" size={size} defaultValue="a">
        <SegmentedItem value="a">A</SegmentedItem>
      </Segmented>
    );
    const heightClass = [...classesOf(screen.getByRole('radio', { name: 'A' }))].find((c) =>
      c.startsWith('h-[')
    );
    expect(heightClass).toBeDefined();
    for (const m of [comfortable, compact]) {
      expect(optionHeight(heightClass!, m) + TRACK_INSET_REM).toBeCloseTo(m[metric], 5);
    }
  });

  it('reads both density blocks', () => {
    expect(comfortable).toEqual({ md: 2.25, sm: 1.875, lg: 2.625 });
    expect(compact).toEqual({ md: 2, sm: 1.625, lg: 2.375 });
  });
});
