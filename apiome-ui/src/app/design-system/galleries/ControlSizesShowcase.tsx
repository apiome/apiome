'use client';

/**
 * The §Forms control-sizes specimen of the gallery (SUX-1.2, apiome#6749).
 *
 * One row per size step, each holding a `Button`, an `Input`, a `Select` trigger and a
 * `Segmented` of that size side by side. The row is the promise of the ticket made visible:
 * the four controls share an outer height and a baseline at `sm`, `md` and `lg`, at both
 * densities and every font scale. `e2e/hive-control-sizes.spec.ts` measures the rows in a
 * browser, and the docs screenshot `design-system-control-sizes` is taken of this block.
 */

import * as React from 'react';

import {
  Button,
  FormField,
  Input,
  Segmented,
  SegmentedItem,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
  type ButtonProps,
  type FieldSize,
  type SegmentedSize,
} from '@/app/components/ui';

import { Demo, SpecimenLabel } from './GallerySection';

/** One size step and the name each primitive gives it. */
interface SizeStep {
  /** The field size (`Input`, `Select`, `Textarea`, `FormField`). */
  field: FieldSize;
  /** The same step in `Button`'s vocabulary. */
  button: NonNullable<ButtonProps['size']>;
  /** The same step in `Segmented`'s vocabulary. */
  segmented: SegmentedSize;
  /** The caption above the row: the step and the metric it is bound to. */
  caption: string;
}

/** The three steps, smallest first. */
const STEPS: readonly SizeStep[] = [
  { field: 'sm', button: 'sm', segmented: 'sm', caption: 'sm · --control-h-sm' },
  { field: 'md', button: 'default', segmented: 'default', caption: 'md (default) · --control-h' },
  { field: 'lg', button: 'lg', segmented: 'lg', caption: 'lg · --control-h-lg' },
];

/**
 * One row of same-size controls.
 *
 * @param props The step to draw.
 * @returns The captioned row.
 */
function ControlSizeRow({ step }: { step: SizeStep }) {
  const [view, setView] = React.useState('cards');
  const id = `ds-size-${step.field}`;
  return (
    <div className="flex flex-col gap-1.5">
      <SpecimenLabel>{step.caption}</SpecimenLabel>
      <Demo>
        <div data-testid={`control-size-row-${step.field}`} className="flex flex-wrap items-center gap-2.5">
          <Button size={step.button} variant="outline">
            Button
          </Button>
          <Input size={step.field} aria-label={`Input, ${step.field}`} placeholder="Input" className="w-40" />
          <Select defaultValue="rest">
            <SelectTrigger size={step.field} aria-label={`Select, ${step.field}`} className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="rest">REST</SelectItem>
              <SelectItem value="graphql">GraphQL</SelectItem>
            </SelectContent>
          </Select>
          <Segmented size={step.segmented} value={view} onValueChange={setView} aria-label={`View, ${step.field}`}>
            <SegmentedItem value="cards">Cards</SegmentedItem>
            <SegmentedItem value="table">Table</SegmentedItem>
          </Segmented>
        </div>
      </Demo>
      <div className="grid max-w-xl gap-3 sm:grid-cols-2">
        <FormField size={step.field} label="Field label" htmlFor={`${id}-input`}>
          <Input id={`${id}-input`} placeholder="Takes the field's size" />
        </FormField>
        <FormField size={step.field} label="Notes" htmlFor={`${id}-notes`}>
          <Textarea id={`${id}-notes`} placeholder="Padding and text follow the size" />
        </FormField>
      </div>
    </div>
  );
}

/**
 * The control-sizes specimen: a row per size step.
 *
 * @returns The specimen block.
 */
export function ControlSizesShowcase() {
  return (
    <div data-testid="design-system-control-sizes" className="flex flex-col gap-4 border-t border-border pt-4">
      {STEPS.map((step) => (
        <ControlSizeRow key={step.field} step={step} />
      ))}
    </div>
  );
}
