/**
 * CatalogImportDialog — auto-detect confidence + paradigm + routing note (MFI-26.3, #4096).
 *
 * These tests cover the detect-step surface:
 *  1. After source input, the step shows "Auto-detected: <format>", the confidence, AND the paradigm
 *     ("· paradigm Graph"), plus a routing note whose destination matches the eventual
 *     routing_decision (catalog for GraphQL; Projects for the OpenAPI control).
 *  2. Ambiguous detection is surfaced: the close cluster is listed and the top pick is called out as
 *     an assumption.
 *
 * Detection is mocked via `/api/import/detect`; the registry (`/api/import/sources`) is served too.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { CatalogImportDialog } from '../src/app/components/ade/dashboard/catalog/CatalogImportDialog';
import type { ImportSourceDescriptor } from '../src/app/components/ade/dashboard/importSourceCatalog';

const SOURCES: ImportSourceDescriptor[] = [
  {
    key: 'graphql',
    label: 'GraphQL',
    description: 'Import a GraphQL schema from SDL or live endpoint introspection.',
    icon: 'waypoints',
    paradigm: 'graph',
    input_kinds: ['file', 'url', 'paste', 'discovery'],
    supports_live_discovery: true,
    formats: ['graphql'],
    available: true,
  },
];

/** Route the registry + a supplied detection response through one fetch mock. */
function mockFetch(detection: unknown): jest.Mock {
  return jest.fn((input: unknown) => {
    const url = typeof input === 'string' ? input : String(input);
    if (url.includes('/api/import/sources')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, sources: SOURCES }) });
    }
    if (url.includes('/api/import/detect')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(detection) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  }) as unknown as jest.Mock;
}

/** Drive Source → Detect by pasting content and detecting it. */
async function pasteAndDetect(text = 'type Query { hello: String }') {
  fireEvent.click(screen.getByTestId('catalog-import-source-paste'));
  fireEvent.change(screen.getByLabelText('Source content'), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: /detect pasted source/i }));
  await waitFor(() => expect(screen.getByText(/Auto-detected:/i)).toBeInTheDocument());
}

describe('CatalogImportDialog — detect confidence + paradigm + routing (MFI-26.3)', () => {
  afterEach(() => jest.restoreAllMocks());

  it('shows confidence and paradigm, and routes GraphQL to the catalog', async () => {
    global.fetch = mockFetch({
      matched: true,
      detected: { format: 'graphql', confidence: 0.95, reason: 'SDL type definitions', importable: true },
    }) as unknown as typeof fetch;

    render(<CatalogImportDialog open onClose={jest.fn()} />);
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()),
    );
    await pasteAndDetect();

    // Confidence + paradigm both shown.
    expect(screen.getByText(/95% confidence/i)).toBeInTheDocument();
    expect(screen.getByText(/paradigm Graph/i)).toBeInTheDocument();
    // Routing note matches the eventual routing_decision (catalog).
    expect(screen.getByText(/Routing decision → Catalog/i)).toBeInTheDocument();
    // No ambiguity notice for a confident single match.
    expect(screen.queryByTestId('detect-ambiguous')).not.toBeInTheDocument();
  });

  it('routes the OpenAPI control to Projects with a REST paradigm', async () => {
    global.fetch = mockFetch({
      matched: true,
      detected: { format: 'openapi-3.1', confidence: 0.99, reason: '`openapi: 3.1.0` marker', importable: true },
    }) as unknown as typeof fetch;

    render(<CatalogImportDialog open onClose={jest.fn()} />);
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()),
    );
    await pasteAndDetect('openapi: 3.1.0');

    expect(screen.getByText(/paradigm REST/i)).toBeInTheDocument();
    expect(screen.getByText(/Routing decision → Projects/i)).toBeInTheDocument();
  });

  it('surfaces ambiguous detection with the close cluster', async () => {
    global.fetch = mockFetch({
      matched: true,
      detected: { format: 'graphql', confidence: 0.55, reason: 'GraphQL SDL keyword', importable: true },
      ambiguous: true,
      ambiguous_candidates: [
        { format: 'graphql', confidence: 0.55, importable: true },
        { format: 'protobuf', confidence: 0.52, importable: true },
      ],
    }) as unknown as typeof fetch;

    render(<CatalogImportDialog open onClose={jest.fn()} />);
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()),
    );
    await pasteAndDetect();

    const notice = screen.getByTestId('detect-ambiguous');
    expect(notice).toBeInTheDocument();
    expect(screen.getByTestId('format-override-select')).toBeInTheDocument();
    // The selected format is named; the *other* candidate is listed (not the selected one twice).
    expect(notice).toHaveTextContent(/using GraphQL/i);
    expect(notice).toHaveTextContent(/Protobuf/i);
  });

  it('lets the user override an ambiguous format and updates routing', async () => {
    global.fetch = mockFetch({
      matched: true,
      detected: { format: 'graphql', confidence: 0.55, reason: 'GraphQL SDL keyword', importable: true },
      ambiguous: true,
      ambiguous_candidates: [
        { format: 'graphql', confidence: 0.55, importable: true },
        { format: 'protobuf', confidence: 0.52, importable: true },
      ],
    }) as unknown as typeof fetch;

    render(<CatalogImportDialog open onClose={jest.fn()} />);
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()),
    );
    await pasteAndDetect();

    expect(screen.getByText(/Routing decision → Catalog/i)).toBeInTheDocument();
    expect(screen.getByText(/paradigm Graph/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/import as format/i), { target: { value: 'protobuf' } });

    expect(screen.getByText(/Import format: Protobuf/i)).toBeInTheDocument();
    expect(screen.getByText(/paradigm RPC/i)).toBeInTheDocument();
    expect(screen.getByText(/Routing decision → Catalog/i)).toBeInTheDocument();
  });
});
