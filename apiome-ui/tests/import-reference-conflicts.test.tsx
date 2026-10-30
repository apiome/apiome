/**
 * Import preview: reference conflicts (#584).
 *
 * Rendered through the real `PreviewPanel` (Monaco stubbed): when a selected schema holds a `$ref`
 * that will not resolve after import — a target this document does not define, or an `http(s)` URL,
 * which Apiome does not fetch — the Preview step warns before the import runs, per schema. It follows
 * the selection, and it is a polite status region, not an interrupting alert.
 */

import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, it, jest } from '@jest/globals';

import { PreviewPanel } from '../src/app/components/ade/dashboard/PreviewPanel';
import { ReferenceConflictsAlert } from '../src/app/components/ade/dashboard/ReferenceConflictsAlert';
import type { AnalysisResult } from '../src/app/utils/openapi-analyzer';

jest.mock('@monaco-editor/react', () => ({ __esModule: true, default: () => null }));

/**
 * An analysis over `schemas`.
 *
 * @param schemas The document's schemas.
 * @returns The analysis the panel takes.
 */
function analysisOf(schemas: Record<string, unknown>): AnalysisResult {
  return {
    document: { openapi: '3.1.0', info: { title: 'Shop', version: '1.0.0' }, components: { schemas } },
  } as unknown as AnalysisResult;
}

const UNRESOLVED = analysisOf({
  Order: {
    type: 'object',
    properties: {
      customer: { $ref: '#/components/schemas/Customer' },
      money: { $ref: 'https://schemas.example.com/money.json' },
    },
  },
  Invoice: { type: 'object', properties: { tax: { $ref: '#/components/schemas/TaxRate' } } },
  Tag: { type: 'object', properties: { name: { type: 'string' } } },
});

describe('import preview: reference conflicts (#584)', () => {
  it('names each schema with the references that will not resolve', () => {
    render(<PreviewPanel analysis={UNRESOLVED} />);
    const alert = screen.getByTestId('reference-conflicts');
    expect(alert).toHaveAttribute('role', 'status');
    expect(within(alert).getByText('2 schemas have references that won’t resolve after import')).toBeInTheDocument();
    const order = within(alert).getByTestId('reference-conflict-Order');
    expect(order).toHaveTextContent('Not defined in this document: Customer');
    expect(order).toHaveTextContent('Not fetched: https://schemas.example.com/money.json');
    expect(within(alert).getByTestId('reference-conflict-Invoice')).toHaveTextContent(
      'Not defined in this document: TaxRate'
    );
    expect(within(alert).queryByTestId('reference-conflict-Tag')).not.toBeInTheDocument();
  });

  it('follows the selection', () => {
    render(<PreviewPanel analysis={UNRESOLVED} />);
    fireEvent.click(screen.getByTestId('schema-select-Invoice'));
    expect(screen.getByText('1 schema has references that won’t resolve after import')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('schema-select-Order'));
    expect(screen.queryByTestId('reference-conflicts')).not.toBeInTheDocument();
  });

  it('says nothing when every reference resolves', () => {
    render(
      <PreviewPanel
        analysis={analysisOf({
          Order: { type: 'object', properties: { tag: { $ref: '#/components/schemas/Tag' } } },
          Tag: { type: 'object', properties: { name: { type: 'string' } } },
        })}
      />
    );
    expect(screen.queryByTestId('reference-conflicts')).not.toBeInTheDocument();
  });

  it('leaves out unselected targets, which the selection rules already prevent', () => {
    const { container } = render(
      <ReferenceConflictsAlert conflicts={[{ schema: 'Invoice', broken: [], external: [], notSelected: ['Order'] }]} />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('lists at most twenty schemas and counts the rest', () => {
    const conflicts = Array.from({ length: 23 }, (_, i) => ({
      schema: `S${i}`,
      broken: ['Missing'],
      external: [],
      notSelected: [],
    }));
    render(<ReferenceConflictsAlert conflicts={conflicts} />);
    expect(screen.getAllByTestId(/^reference-conflict-S/)).toHaveLength(20);
    expect(screen.getByText('and 3 more.')).toBeInTheDocument();
  });
});
