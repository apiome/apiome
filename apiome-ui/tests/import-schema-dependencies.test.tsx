/**
 * Import preview: required dependencies follow the selection (#579).
 *
 * Rendered through the real `PreviewPanel` (Monaco stubbed):
 *
 *  1. **Selecting a schema selects what it references** — transitively, and the import options the
 *     wizard receives carry them; a polite status line says what was added and why.
 *  2. **A referenced schema cannot be deselected** — its checkbox is disabled with "Required by …",
 *     and stays selected; once its referrer is deselected it unlocks.
 *  3. **Select None / Select All still work** as bulk controls.
 */

import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, it, jest } from '@jest/globals';

import { PreviewPanel, type ImportOptions } from '../src/app/components/ade/dashboard/PreviewPanel';
import type { AnalysisResult } from '../src/app/utils/openapi-analyzer';

jest.mock('@monaco-editor/react', () => ({ __esModule: true, default: () => null }));

/** Order → Customer → Address, Order → LineItem; Note stands alone. */
const ANALYSIS = {
  document: {
    openapi: '3.1.0',
    info: { title: 'Shop', version: '1.0.0' },
    components: {
      schemas: {
        Order: {
          type: 'object',
          properties: {
            customer: { $ref: '#/components/schemas/Customer' },
            lines: { type: 'array', items: { $ref: '#/components/schemas/LineItem' } },
          },
        },
        Customer: { type: 'object', properties: { address: { $ref: '#/components/schemas/Address' } } },
        Address: { type: 'object', properties: { city: { type: 'string' } } },
        LineItem: { type: 'object', properties: { qty: { type: 'integer' } } },
        Note: { type: 'object', properties: { text: { type: 'string' } } },
      },
    },
  },
} as unknown as AnalysisResult;

/**
 * Render the panel, recording each set of import options it reports.
 *
 * @returns The recorder.
 */
function renderPanel() {
  const onImportOptionsChange = jest.fn<(options: ImportOptions) => void>();
  render(<PreviewPanel analysis={ANALYSIS} onImportOptionsChange={onImportOptionsChange} />);
  const lastSelection = () => {
    const calls = onImportOptionsChange.mock.calls;
    return new Set(calls[calls.length - 1][0].selectedSchemas);
  };
  return { lastSelection };
}

const box = (name: string) => screen.getByTestId(`schema-select-${name}`);
const isChecked = (name: string) => box(name).getAttribute('data-state') === 'checked';

describe('import preview: required dependencies (#579)', () => {
  it('locks every schema a selected schema references, and names the referrer', () => {
    renderPanel();
    // Everything starts selected, so every referenced schema is locked.
    expect(box('Customer')).toBeDisabled();
    expect(box('Customer')).toHaveAttribute('title', 'Required by Order');
    expect(box('Address')).toHaveAttribute('title', 'Required by Customer');
    expect(box('LineItem')).toBeDisabled();
    expect(screen.getByTestId('schema-required-by-Customer')).toHaveTextContent('Required by Order');
    // Nothing references Order or Note.
    expect(box('Order')).toBeEnabled();
    expect(box('Note')).toBeEnabled();
  });

  it('selecting a schema selects what it references, and says so', () => {
    const { lastSelection } = renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Select None' }));
    expect(lastSelection()).toEqual(new Set());

    fireEvent.click(box('Order'));
    for (const name of ['Order', 'Customer', 'Address', 'LineItem']) expect(isChecked(name)).toBe(true);
    expect(isChecked('Note')).toBe(false);
    expect(lastSelection()).toEqual(new Set(['Order', 'Customer', 'Address', 'LineItem']));
    const note = screen.getByRole('status');
    expect(within(note).getByText(/Also selected/)).toHaveTextContent(
      'Also selected Customer, Address and LineItem: Order references them.'
    );
  });

  it('a referenced schema stays selected until its referrer is deselected', () => {
    const { lastSelection } = renderPanel();
    // Disabled, so a click changes nothing.
    fireEvent.click(box('Customer'));
    expect(isChecked('Customer')).toBe(true);

    fireEvent.click(box('Order'));
    expect(isChecked('Order')).toBe(false);
    expect(box('Customer')).toBeEnabled();
    expect(box('LineItem')).toBeEnabled();
    // Address is still required by Customer.
    expect(box('Address')).toBeDisabled();

    fireEvent.click(box('Customer'));
    expect(isChecked('Customer')).toBe(false);
    expect(box('Address')).toBeEnabled();
    expect(lastSelection()).toEqual(new Set(['Address', 'LineItem', 'Note']));
  });

  it('Select All selects everything again and clears the note', () => {
    const { lastSelection } = renderPanel();
    fireEvent.click(screen.getByRole('button', { name: 'Select None' }));
    fireEvent.click(box('Order'));
    fireEvent.click(screen.getByRole('button', { name: 'Select All' }));
    expect(lastSelection()).toEqual(new Set(['Order', 'Customer', 'Address', 'LineItem', 'Note']));
    expect(screen.getByRole('status')).toHaveTextContent('');
  });
});
