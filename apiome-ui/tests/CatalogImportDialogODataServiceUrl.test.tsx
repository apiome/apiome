/**
 * CatalogImportDialog — an OData service root in URL Import (MFI-11.6, #3781).
 *
 * A service root answers with its service document, which has no model. The URL intake follows it
 * to `<service root>/$metadata` and detects that document instead, so the catalog item is built from
 * the metadata and its URL is the `$metadata` URL. A URL that returns anything else is detected as
 * it is, with no second fetch.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { CatalogImportDialog } from '../src/app/components/ade/dashboard/catalog/CatalogImportDialog';
import type { ImportSourceDescriptor } from '../src/app/components/ade/dashboard/importSourceCatalog';

const SERVICE_ROOT = 'https://odata.example.com/trippin/';
const METADATA_URL = 'https://odata.example.com/trippin/$metadata';

/** A v4 JSON service document, as `GET <service root>` returns it. */
const SERVICE_DOCUMENT = JSON.stringify({
  '@odata.context': METADATA_URL,
  value: [{ name: 'People', kind: 'EntitySet', url: 'People' }],
});

const EDMX =
  '<edmx:Edmx xmlns:edmx="http://docs.oasis-open.org/odata/ns/edmx" Version="4.0"><edmx:DataServices>' +
  '<Schema xmlns="http://docs.oasis-open.org/odata/ns/edm" Namespace="Trippin"/></edmx:DataServices></edmx:Edmx>';

const SOURCES: ImportSourceDescriptor[] = [
  {
    key: 'odata',
    label: 'OData',
    description: 'Import an OData v2, v3 or v4 CSDL / EDMX service metadata document.',
    icon: 'database',
    paradigm: 'rest',
    input_kinds: ['file', 'url', 'paste', 'discovery', 'fileset'],
    supports_live_discovery: true,
    formats: ['odata', 'odata-v2', 'odata-v3', 'edmx'],
    available: true,
  },
];

const DETECTION = {
  matched: true,
  detected: { format: 'odata', confidence: 0.98, reason: '`<edmx:Edmx>` root, CSDL 4.0', importable: true },
};

/**
 * A routing fetch mock: the registry, detection, and the two remote documents. Each detection
 * request body is recorded so a test can assert what was detected.
 *
 * @param detected Collects the parsed body of every `/api/import/detect` request.
 * @param remote The remote URL → body map the URL intake fetches from.
 */
function mockFetch(detected: Array<Record<string, unknown>>, remote: Record<string, string>): jest.Mock {
  return jest.fn((input: unknown, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : String(input);
    if (url.includes('/api/import/sources')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, sources: SOURCES }) });
    }
    if (url.includes('/api/import/detect')) {
      detected.push(JSON.parse(String(init?.body ?? '{}')));
      return Promise.resolve({ ok: true, json: () => Promise.resolve(DETECTION) });
    }
    if (url in remote) {
      return Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(remote[url]) });
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
  }) as unknown as jest.Mock;
}

/** Open the dialog on URL Import, enter `url` and click **Fetch and detect**. */
async function fetchAndDetect(url: string): Promise<void> {
  render(<CatalogImportDialog open onClose={jest.fn()} onSuccess={jest.fn()} />);
  await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()));
  fireEvent.click(screen.getByTestId('catalog-import-source-url'));
  fireEvent.change(screen.getByLabelText('Document URL'), { target: { value: url } });
  fireEvent.click(screen.getByRole('button', { name: /fetch and detect/i }));
  await waitFor(() => expect(screen.getByText(/Auto-detected:/i)).toBeInTheDocument());
}

/** The URLs the browser fetched directly (everything outside `/api/`). */
function remoteFetches(): string[] {
  return (global.fetch as unknown as jest.Mock).mock.calls
    .map((call) => String(call[0]))
    .filter((url) => !url.startsWith('/api/'));
}

describe('CatalogImportDialog — OData service root (MFI-11.6)', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('follows a service document to $metadata and detects the metadata', async () => {
    const detected: Array<Record<string, unknown>> = [];
    global.fetch = mockFetch(detected, {
      [SERVICE_ROOT]: SERVICE_DOCUMENT,
      [METADATA_URL]: EDMX,
    }) as unknown as typeof fetch;

    await fetchAndDetect(SERVICE_ROOT);

    expect(remoteFetches()).toEqual([SERVICE_ROOT, METADATA_URL]);
    expect(detected).toHaveLength(1);
    expect(detected[0].text).toBe(EDMX);
    expect(detected[0].url).toBe(METADATA_URL);
  });

  it('detects a $metadata URL as it is, with one fetch', async () => {
    const detected: Array<Record<string, unknown>> = [];
    global.fetch = mockFetch(detected, { [METADATA_URL]: EDMX }) as unknown as typeof fetch;

    await fetchAndDetect(METADATA_URL);

    expect(remoteFetches()).toEqual([METADATA_URL]);
    expect(detected[0].text).toBe(EDMX);
    expect(detected[0].url).toBe(METADATA_URL);
  });

  it('reports the $metadata fetch failing', async () => {
    const detected: Array<Record<string, unknown>> = [];
    global.fetch = mockFetch(detected, { [SERVICE_ROOT]: SERVICE_DOCUMENT }) as unknown as typeof fetch;

    render(<CatalogImportDialog open onClose={jest.fn()} onSuccess={jest.fn()} />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()));
    fireEvent.click(screen.getByTestId('catalog-import-source-url'));
    fireEvent.change(screen.getByLabelText('Document URL'), { target: { value: SERVICE_ROOT } });
    fireEvent.click(screen.getByRole('button', { name: /fetch and detect/i }));

    await waitFor(() => expect(screen.getByText(/Fetch failed with HTTP 404/i)).toBeInTheDocument());
    expect(detected).toHaveLength(0);
  });
});
