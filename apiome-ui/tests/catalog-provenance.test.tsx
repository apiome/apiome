/**
 * Inference provenance on the catalog detail — FMT-8.6 (#5467).
 *
 * Pins the pure vocabulary helpers (`utils/catalog-provenance`) and the two things the Overview
 * renders from them: the badge on an inferred / synthesized entity (never on a declared one) and the
 * Provenance filter that narrows every group to one class and states the inferred ratio.
 */

jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({ value }: { value?: string }) => <div data-testid="mock-monaco">{value}</div>,
}));

import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import {
  CatalogParsedGroups,
  type CatalogParsedGroup,
} from '../src/app/components/ade/dashboard/catalog/CatalogParsedModel';
import {
  countEntitiesByProvenance,
  hasNonDeclaredEntities,
  matchesProvenanceFilter,
  provenanceClassOf,
  provenanceDescription,
  provenanceRatioLine,
} from '../src/app/utils/catalog-provenance';

const MIXED: CatalogParsedGroup[] = [
  {
    title: 'Operations',
    entities: [
      { name: 'Create order', tag: 'POST', meta: '/orders', fields: [], provenance: 'declared' },
      { name: 'List orders', tag: 'GET', meta: '/orders', fields: [] },
    ],
  },
  {
    title: 'Types',
    entities: [
      {
        name: 'Order',
        tag: 'OBJECT',
        fields: [],
        provenance: 'inferred',
        provenanceEvidence: 'Schema inferred from the example request body of POST /orders.',
      },
      {
        name: 'Order_lines_item',
        tag: 'OBJECT',
        fields: [],
        provenance: 'synthesized',
        provenanceEvidence: 'Named by Apiome after the place it is written: Order.lines.',
      },
    ],
  },
];

const SUMMARY = { declared: 9, inferred: 13, synthesized: 2, total: 24, inferredRatio: 13 / 24 };

describe('catalog-provenance helpers', () => {
  it('reads an unstamped or unknown entity as declared', () => {
    expect(provenanceClassOf({})).toBe('declared');
    expect(provenanceClassOf({ provenance: 'observed' })).toBe('declared');
    expect(provenanceClassOf({ provenance: 'inferred' })).toBe('inferred');
    expect(provenanceClassOf({ provenance: 'synthesized' })).toBe('synthesized');
  });

  it('describes a class with the entity evidence appended', () => {
    expect(provenanceDescription({ provenance: 'inferred', provenanceEvidence: ' From the 200 example. ' })).toBe(
      'Apiome deduced this from an example or from code. From the 200 example.',
    );
    expect(provenanceDescription({})).toBe('The source states this.');
  });

  it('filters by class and passes everything for all', () => {
    expect(matchesProvenanceFilter({ provenance: 'inferred' }, 'all')).toBe(true);
    expect(matchesProvenanceFilter({ provenance: 'inferred' }, 'inferred')).toBe(true);
    expect(matchesProvenanceFilter({}, 'inferred')).toBe(false);
    expect(matchesProvenanceFilter({}, 'declared')).toBe(true);
  });

  it('counts entities per class', () => {
    expect(countEntitiesByProvenance(MIXED)).toEqual({ all: 4, declared: 2, inferred: 1, synthesized: 1 });
    expect(countEntitiesByProvenance(null)).toEqual({ all: 0, declared: 0, inferred: 0, synthesized: 0 });
    expect(hasNonDeclaredEntities(countEntitiesByProvenance(MIXED))).toBe(true);
    expect(hasNonDeclaredEntities(countEntitiesByProvenance([MIXED[0]]))).toBe(false);
  });

  it('states the inferred ratio, and nothing for a fully declared item', () => {
    expect(provenanceRatioLine(SUMMARY)).toBe(
      "54% of this item's constructs are inferred (13 of 24) · 2 synthesized",
    );
    expect(provenanceRatioLine({ ...SUMMARY, synthesized: 0 })).toBe(
      "54% of this item's constructs are inferred (13 of 24)",
    );
    expect(provenanceRatioLine({ declared: 5, inferred: 0, synthesized: 0, total: 5, inferredRatio: 0 })).toBeNull();
    expect(provenanceRatioLine(null)).toBeNull();
  });
});

describe('CatalogParsedGroups provenance', () => {
  it('badges inferred and synthesized entities only, with the evidence in the tooltip', () => {
    render(<CatalogParsedGroups parsed={MIXED} provenanceSummary={SUMMARY} />);
    const badges = screen.getAllByTestId('catalog-detail-parsed-provenance');
    expect(badges.map((b) => b.getAttribute('data-provenance'))).toEqual(['inferred', 'synthesized']);
    expect(badges[0]).toHaveTextContent('Inferred');
    expect(badges[0]).toHaveAttribute(
      'title',
      'Apiome deduced this from an example or from code. Schema inferred from the example request body of POST /orders.',
    );
  });

  it('narrows every group to one class from the Provenance filter', () => {
    render(<CatalogParsedGroups parsed={MIXED} provenanceSummary={SUMMARY} />);
    expect(screen.getByTestId('catalog-detail-provenance-ratio')).toHaveTextContent(
      "54% of this item's constructs are inferred (13 of 24) · 2 synthesized",
    );
    expect(screen.getByTestId('catalog-detail-provenance-option-inferred')).toHaveTextContent('Inferred 1');

    fireEvent.click(screen.getByTestId('catalog-detail-provenance-option-inferred'));
    const names = screen.getAllByTestId('catalog-detail-parsed-entity').map((e) => e.textContent);
    expect(names).toHaveLength(1);
    expect(names[0]).toContain('Order');

    const [operations] = screen.getAllByTestId('catalog-detail-parsed-group');
    expect(within(operations).getByTestId('catalog-detail-parsed-no-matches')).toHaveTextContent(
      'No inferred entities in this group.',
    );

    fireEvent.click(screen.getByTestId('catalog-detail-provenance-option-all'));
    expect(screen.getAllByTestId('catalog-detail-parsed-entity')).toHaveLength(4);
  });

  it('shows no filter for a fully declared item', () => {
    render(<CatalogParsedGroups parsed={[MIXED[0]]} />);
    expect(screen.queryByTestId('catalog-detail-provenance-filter')).toBeNull();
    expect(screen.queryByTestId('catalog-detail-parsed-provenance')).toBeNull();
  });
});
