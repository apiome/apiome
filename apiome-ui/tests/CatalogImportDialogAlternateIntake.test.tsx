/**
 * CatalogImportDialog — alternate intake source cards (MFI-26.5, #4098).
 *
 * A format's own way in (live introspection, reflection, a registry crawl) appears as a source card
 * only when the registry declares it **and** the wizard has a panel for its kind. The panel registry
 * is empty in the product today; this suite registers a stand-in `introspection` panel so the
 * data-driven path can be driven end to end:
 *
 *  1. today's registry (live discovery flags, no `alternate_intake`) → only the base tiles;
 *  2. a declared intake whose kind has a panel → a card labelled from the registry, which opens that
 *     panel in place of the base intake panels;
 *  3. a declared kind with no panel, or an unavailable source → no card.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, it, jest, afterEach } from '@jest/globals';

import type { ImportSourceDescriptor } from '../src/app/components/ade/dashboard/importSourceCatalog';
import type { CatalogAlternateIntakePanelProps } from '../src/app/components/ade/dashboard/catalog/catalogAlternateIntakePanels';

jest.mock('../src/app/components/ade/dashboard/catalog/catalogAlternateIntakePanels', () => {
  /** Stand-in panel: proves the dialog hands it the chosen format's descriptor. */
  function IntrospectionPanel({ source }: CatalogAlternateIntakePanelProps) {
    return <div data-testid="introspection-panel">Introspect {source.label}</div>;
  }
  return {
    CATALOG_ALTERNATE_INTAKE_PANELS: { introspection: IntrospectionPanel },
    CATALOG_ALTERNATE_INTAKE_KINDS: new Set(['introspection']),
  };
});

// Imported after the mock so the dialog sees the stand-in registry.
import { CatalogImportDialog } from '../src/app/components/ade/dashboard/catalog/CatalogImportDialog';

const GRAPHQL: ImportSourceDescriptor = {
  key: 'graphql',
  label: 'GraphQL',
  description: 'Import a GraphQL schema from SDL or live endpoint introspection.',
  icon: 'waypoints',
  paradigm: 'graph',
  input_kinds: ['file', 'url', 'paste', 'discovery'],
  supports_live_discovery: true,
  formats: ['graphql'],
  available: true,
};

const INTROSPECTION = {
  kind: 'introspection',
  label: 'Live introspection',
  description: 'Read the schema from a running endpoint',
  icon: 'radar',
};

/** Serve the given registry; every other request fails quietly. */
function serve(sources: ImportSourceDescriptor[]) {
  global.fetch = jest.fn((input: unknown) => {
    const url = typeof input === 'string' ? input : String(input);
    if (url.includes('/api/import/sources')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, sources }) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  }) as unknown as typeof fetch;
}

async function renderWith(sources: ImportSourceDescriptor[]) {
  serve(sources);
  render(<CatalogImportDialog open onClose={jest.fn()} />);
  await waitFor(() =>
    expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()),
  );
}

describe('CatalogImportDialog — alternate intake (MFI-26.5)', () => {
  afterEach(() => jest.restoreAllMocks());

  it('shows only the base intake cards when no format declares an alternate intake', async () => {
    await renderWith([GRAPHQL]);
    await waitFor(() => expect(screen.getByTestId('catalog-import-source-git')).toBeInTheDocument());
    expect(screen.queryByTestId('catalog-import-source-alternate-graphql')).not.toBeInTheDocument();
    expect(screen.queryByText('Live introspection')).not.toBeInTheDocument();
  });

  it('adds a registry-labelled card that opens the registered panel', async () => {
    await renderWith([{ ...GRAPHQL, alternate_intake: INTROSPECTION }]);
    const card = await screen.findByTestId('catalog-import-source-alternate-graphql');
    expect(card).toHaveTextContent('Live introspection');
    expect(card).toHaveTextContent('Read the schema from a running endpoint');

    // File Upload is the default intake; choosing the alternate card replaces its panel.
    expect(screen.getByText('Drop a source file here, or browse.')).toBeInTheDocument();
    fireEvent.click(card);
    expect(screen.getByTestId('introspection-panel')).toHaveTextContent('Introspect GraphQL');
    expect(screen.queryByText('Drop a source file here, or browse.')).not.toBeInTheDocument();

    // Choosing a base method again puts its panel back.
    fireEvent.click(screen.getByTestId('catalog-import-source-paste'));
    expect(screen.queryByTestId('introspection-panel')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Source content')).toBeInTheDocument();
  });

  it('draws no card for a declared kind without a panel', async () => {
    await renderWith([{ ...GRAPHQL, alternate_intake: { ...INTROSPECTION, kind: 'reflection' } }]);
    await waitFor(() => expect(screen.getByTestId('catalog-import-source-git')).toBeInTheDocument());
    expect(screen.queryByTestId('catalog-import-source-alternate-graphql')).not.toBeInTheDocument();
  });

  it('draws no card for an unavailable source', async () => {
    await renderWith([{ ...GRAPHQL, available: false, alternate_intake: INTROSPECTION }]);
    await waitFor(() => expect(screen.getByTestId('catalog-import-source-git')).toBeInTheDocument());
    expect(screen.queryByTestId('catalog-import-source-alternate-graphql')).not.toBeInTheDocument();
  });
});
