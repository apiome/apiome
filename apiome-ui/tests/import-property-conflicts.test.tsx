/**
 * Import preview: property conflicts (#583).
 *
 * Rendered through the real `PreviewPanel` (Monaco stubbed): when the selected schemas use one
 * property name with different definitions, the Preview step warns before the import runs, names
 * each property and lists every definition with the schemas that use it. It follows the selection,
 * and it is a polite status region, not an interrupting alert.
 */

import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, it, jest } from '@jest/globals';

import { PreviewPanel } from '../src/app/components/ade/dashboard/PreviewPanel';
import { PropertyConflictsAlert } from '../src/app/components/ade/dashboard/PropertyConflictsAlert';
import type { PropertyConflict } from '../src/app/utils/property-conflict-detection';
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

const CONFLICTING = analysisOf({
  Customer: {
    type: 'object',
    properties: { id: { type: 'string', format: 'uuid' }, status: { type: 'string', enum: ['active', 'inactive'] } },
  },
  Transaction: {
    type: 'object',
    properties: { id: { type: 'integer', format: 'int64' }, status: { type: 'string', enum: ['pending', 'completed'] } },
  },
  Note: { type: 'object', properties: { text: { type: 'string' } } },
});

describe('import preview: property conflicts (#583)', () => {
  it('warns about each property defined differently, with every definition and its schemas', () => {
    render(<PreviewPanel analysis={CONFLICTING} />);
    const alert = screen.getByTestId('property-conflicts');
    expect(alert).toHaveAttribute('role', 'status');
    expect(within(alert).getByText('2 properties are defined differently in the selected schemas')).toBeInTheDocument();
    const status = within(alert).getByTestId('property-conflict-status');
    expect(status).toHaveTextContent('Customer: {"enum":["active","inactive"],"type":"string"}');
    expect(status).toHaveTextContent('Transaction: {"enum":["pending","completed"],"type":"string"}');
    expect(within(alert).getByTestId('property-conflict-id')).toHaveTextContent('{"format":"int64","type":"integer"}');
  });

  it('follows the selection: deselecting one side of every conflict clears the warning', () => {
    render(<PreviewPanel analysis={CONFLICTING} />);
    expect(screen.getByTestId('property-conflicts')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('schema-select-Transaction'));
    expect(screen.queryByTestId('property-conflicts')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('schema-select-Transaction'));
    expect(screen.getByTestId('property-conflicts')).toBeInTheDocument();
  });

  it('says nothing when every property is defined one way', () => {
    render(
      <PreviewPanel
        analysis={analysisOf({
          A: { type: 'object', properties: { id: { type: 'string' } } },
          B: { type: 'object', properties: { id: { type: 'string' } } },
        })}
      />
    );
    expect(screen.queryByTestId('property-conflicts')).not.toBeInTheDocument();
  });

  it('lists at most twenty properties and counts the rest', () => {
    const conflicts: PropertyConflict[] = Array.from({ length: 25 }, (_, i) => ({
      property: `p${i}`,
      definitions: [
        { schemas: ['A'], summary: '{"type":"string"}' },
        { schemas: ['B'], summary: '{"type":"integer"}' },
      ],
    }));
    render(<PropertyConflictsAlert conflicts={conflicts} />);
    expect(screen.getByText('25 properties are defined differently in the selected schemas')).toBeInTheDocument();
    expect(screen.getAllByTestId(/^property-conflict-p/)).toHaveLength(20);
    expect(screen.getByText('and 5 more.')).toBeInTheDocument();
  });

  it('uses the singular for one property', () => {
    render(
      <PropertyConflictsAlert
        conflicts={[{ property: 'x', definitions: [{ schemas: ['A'], summary: '1' }, { schemas: ['B'], summary: '2' }] }]}
      />
    );
    expect(screen.getByText('1 property is defined differently in the selected schemas')).toBeInTheDocument();
  });
});
