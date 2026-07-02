/**
 * Offline-fallback test for the catalog Source & Code viewer (MFI-25.4, #4089).
 *
 * Isolated in its own file because it mocks `@monaco-editor/react` to *fail to import* (the offline /
 * CDN-blocked case). The viewer's dynamic loader catches that and resolves to a `<pre>` fallback that
 * still prints the successfully-fetched raw source — the mockup's "Monaco failed to load" path.
 */

// Make importing the editor throw, so the dynamic loader's `.catch` branch takes over.
jest.mock('@monaco-editor/react', () => {
  throw new Error('offline: monaco unavailable');
});

import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { CatalogSourceViewer } from '../src/app/components/ade/dashboard/catalog/CatalogSourceViewer';
import type { CatalogSource } from '../src/app/utils/catalog-format-registry';

const SOURCE_HREF = '/api/catalog/item-1/source';
const FILE_SOURCE: CatalogSource = { kind: 'file', label: 'acme.proto', title: 'acme.proto' };
const RAW = 'syntax = "proto3";\nmessage Order { string id = 1; }';

describe('CatalogSourceViewer offline fallback (MFI-25.4)', () => {
  afterEach(() => jest.restoreAllMocks());

  it('renders the raw source in a <pre> when Monaco cannot be loaded', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      text: async () => RAW,
      json: async () => ({}),
    }) as unknown as typeof fetch;

    render(
      <CatalogSourceViewer
        sourceHref={SOURCE_HREF}
        sourceFormat="protobuf"
        resolvedSource={FILE_SOURCE}
        downloadable
        hasContent
        sourceUri={null}
        active
      />,
    );

    // The raw source was fetched fine; only the editor library failed → `<pre>` fallback.
    const fallback = await screen.findByTestId('catalog-detail-source-fallback');
    expect(fallback).toHaveTextContent('syntax = "proto3"');
    expect(fallback).toHaveTextContent(/could not be loaded/i);
  });
});
