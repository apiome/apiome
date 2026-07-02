/**
 * Render/interaction tests for the catalog Source & Code viewer (MFI-25.4, #4089).
 *
 * The viewer must fetch the raw source lazily on first activation, render it read-only in Monaco with
 * the correct language tag, offer Download + Wrap actions, and degrade gracefully when nothing was
 * captured or the fetch fails. Monaco is stubbed with a lightweight component that echoes the props we
 * care about (value / language / wordWrap) so the assertions never depend on the real editor loading.
 */

// Stub `@monaco-editor/react` with a component that surfaces the props under test.
jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({
    value,
    language,
    options,
  }: {
    value?: string;
    language?: string;
    options?: { wordWrap?: string; readOnly?: boolean };
  }) => (
    <div
      data-testid="mock-monaco"
      data-language={language}
      data-wordwrap={options?.wordWrap}
      data-readonly={String(options?.readOnly)}
    >
      {value}
    </div>
  ),
}));

import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { CatalogSourceViewer } from '../src/app/components/ade/dashboard/catalog/CatalogSourceViewer';
import type { CatalogSource } from '../src/app/utils/catalog-format-registry';

const SOURCE_HREF = '/api/catalog/item-1/source';
const FILE_SOURCE: CatalogSource = { kind: 'file', label: 'acme.proto', title: 'acme.proto' };

const RAW_PROTO = 'syntax = "proto3";\nmessage Order { string id = 1; }';

/** Mock `fetch` to return raw source text (ok) or a JSON error (not ok). */
function mockSourceFetch(text: string, ok = true, error = 'No source captured') {
  global.fetch = jest.fn().mockResolvedValue({
    ok,
    text: async () => text,
    json: async () => ({ success: false, error }),
  }) as unknown as typeof fetch;
}

function renderViewer(overrides: Partial<React.ComponentProps<typeof CatalogSourceViewer>> = {}) {
  return render(
    <CatalogSourceViewer
      sourceHref={SOURCE_HREF}
      sourceFormat="protobuf"
      resolvedSource={FILE_SOURCE}
      downloadable
      hasContent
      sourceUri={null}
      active
      {...overrides}
    />,
  );
}

describe('CatalogSourceViewer (MFI-25.4)', () => {
  afterEach(() => jest.restoreAllMocks());

  it('lazily fetches the raw source and renders it read-only in Monaco', async () => {
    mockSourceFetch(RAW_PROTO);
    renderViewer();

    const editor = await screen.findByTestId('mock-monaco');
    expect(editor).toHaveTextContent('syntax = "proto3"');
    expect(editor).toHaveAttribute('data-readonly', 'true');
    expect(global.fetch).toHaveBeenCalledWith(SOURCE_HREF);
  });

  it('shows the correct language tag and maps protobuf → protobuf', async () => {
    mockSourceFetch(RAW_PROTO);
    renderViewer();

    await screen.findByTestId('mock-monaco');
    expect(screen.getByTestId('catalog-detail-source-lang')).toHaveTextContent('language: protobuf');
    expect(screen.getByTestId('mock-monaco')).toHaveAttribute('data-language', 'protobuf');
  });

  it('refines a JSON-or-YAML format from the fetched bytes (OpenAPI JSON → json)', async () => {
    mockSourceFetch('{\n  "openapi": "3.1.0"\n}');
    renderViewer({ sourceFormat: 'openapi' });

    const editor = await screen.findByTestId('mock-monaco');
    expect(editor).toHaveAttribute('data-language', 'json');
    expect(screen.getByTestId('catalog-detail-source-lang')).toHaveTextContent('language: json');
  });

  it('does not fetch until the tab is active, then fetches once on activation', async () => {
    mockSourceFetch(RAW_PROTO);
    const { rerender } = renderViewer({ active: false });

    // Inactive: no fetch, no editor.
    expect(global.fetch).not.toHaveBeenCalled();
    expect(screen.queryByTestId('mock-monaco')).not.toBeInTheDocument();

    rerender(
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
    await screen.findByTestId('mock-monaco');
    expect(global.fetch).toHaveBeenCalledTimes(1);

    // Re-activating never re-fetches.
    rerender(
      <CatalogSourceViewer
        sourceHref={SOURCE_HREF}
        sourceFormat="protobuf"
        resolvedSource={FILE_SOURCE}
        downloadable
        hasContent
        sourceUri={null}
        active={false}
      />,
    );
    rerender(
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
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it('toggles word-wrap on the editor via the Wrap button', async () => {
    mockSourceFetch(RAW_PROTO);
    renderViewer();

    const editor = await screen.findByTestId('mock-monaco');
    // Wrap is on by default.
    expect(editor).toHaveAttribute('data-wordwrap', 'on');
    const wrap = screen.getByTestId('catalog-detail-source-wrap');
    expect(wrap).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(wrap);
    expect(screen.getByTestId('catalog-detail-source-wrap')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByTestId('mock-monaco')).toHaveAttribute('data-wordwrap', 'off');
  });

  it('offers a raw-source download hitting the source endpoint', async () => {
    mockSourceFetch(RAW_PROTO);
    renderViewer();

    const dl = await screen.findByTestId('catalog-detail-download');
    expect(dl).toHaveAttribute('href', SOURCE_HREF);
    expect(dl).toHaveTextContent(/download raw source/i);
    expect(dl).toHaveAttribute('download', '');
  });

  it('surfaces a "View source" (new tab) affordance when there is no captured content', async () => {
    mockSourceFetch(RAW_PROTO);
    renderViewer({ hasContent: false });

    const dl = await screen.findByTestId('catalog-detail-download');
    expect(dl).toHaveTextContent(/view source/i);
    expect(dl).toHaveAttribute('target', '_blank');
    expect(dl).not.toHaveAttribute('download');
  });

  it('shows an "Open source URL" link when a source URI is present', async () => {
    mockSourceFetch(RAW_PROTO);
    renderViewer({ sourceUri: 'https://example.com/acme.proto' });

    await screen.findByTestId('mock-monaco');
    const link = screen.getByRole('link', { name: /open source url/i });
    expect(link).toHaveAttribute('href', 'https://example.com/acme.proto');
  });

  it('degrades to a "not captured" note when the source is not downloadable', () => {
    mockSourceFetch(RAW_PROTO);
    renderViewer({ downloadable: false });

    expect(screen.getByTestId('catalog-detail-no-source')).toHaveTextContent(/not captured/i);
    // No editor, no download, and — critically — no fetch for a source that cannot be retrieved.
    expect(screen.queryByTestId('catalog-detail-download')).not.toBeInTheDocument();
    expect(screen.queryByTestId('mock-monaco')).not.toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('shows an error note when the source fetch fails', async () => {
    mockSourceFetch('', false, 'No source material captured');
    renderViewer();

    const err = await screen.findByTestId('catalog-detail-source-error');
    expect(err).toHaveTextContent('No source material captured');
    expect(screen.queryByTestId('mock-monaco')).not.toBeInTheDocument();
  });

  it('shows an error note when the network throws (offline)', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('Failed to fetch')) as unknown as typeof fetch;
    renderViewer();

    const err = await screen.findByTestId('catalog-detail-source-error');
    expect(err).toHaveTextContent('Failed to fetch');
  });
});
