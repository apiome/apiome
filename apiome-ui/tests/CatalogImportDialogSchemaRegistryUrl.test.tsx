/**
 * CatalogImportDialog — a Confluent schema registry URL in URL Import (MFI-12.6, #3787).
 *
 * A registry's subject-version route answers with a JSON envelope around the schema, and its
 * versions route with a version list. The URL intake follows either to the raw `…/schema` route and
 * detects the schema instead, so the catalog item is built from the Avro schema and its URL is the
 * raw-schema URL. A raw-schema URL is detected as it is, with no second fetch.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { CatalogImportDialog } from '../src/app/components/ade/dashboard/catalog/CatalogImportDialog';
import type { ImportSourceDescriptor } from '../src/app/components/ade/dashboard/importSourceCatalog';

const SUBJECT = 'https://registry.example.com:8081/subjects/orders-value';
const VERSION_URL = `${SUBJECT}/versions/3`;
const VERSIONS_URL = `${SUBJECT}/versions`;
const RAW_URL = `${SUBJECT}/versions/3/schema`;
const LATEST_RAW_URL = `${SUBJECT}/versions/latest/schema`;

const SCHEMA = '{"type":"record","name":"Order","namespace":"com.example.orders","fields":[{"name":"id","type":"string"}]}';

/** The envelope `GET …/subjects/<subject>/versions/<version>` returns. */
const ENVELOPE = JSON.stringify({ subject: 'orders-value', version: 3, id: 21, schema: SCHEMA });

const SOURCES: ImportSourceDescriptor[] = [
  {
    key: 'avro',
    label: 'Avro',
    description: 'Import an Apache Avro schema (.avsc) or Avro IDL protocol (.avdl) as a catalog source.',
    icon: 'binary',
    paradigm: 'data_schema',
    input_kinds: ['file', 'url', 'paste', 'fileset'],
    supports_live_discovery: false,
    formats: ['avro', 'avsc', 'avro-idl'],
    available: true,
  },
];

const DETECTION = {
  matched: true,
  detected: { format: 'avro', confidence: 0.97, reason: 'Avro record schema', importable: true },
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

describe('CatalogImportDialog — schema registry URL (MFI-12.6)', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('follows a subject-version envelope to the raw schema and detects the schema', async () => {
    const detected: Array<Record<string, unknown>> = [];
    global.fetch = mockFetch(detected, { [VERSION_URL]: ENVELOPE, [RAW_URL]: SCHEMA }) as unknown as typeof fetch;

    await fetchAndDetect(VERSION_URL);

    expect(remoteFetches()).toEqual([VERSION_URL, RAW_URL]);
    expect(detected).toHaveLength(1);
    expect(detected[0].text).toBe(SCHEMA);
    expect(detected[0].url).toBe(RAW_URL);
  });

  it("follows a subject's version list to its latest schema", async () => {
    const detected: Array<Record<string, unknown>> = [];
    global.fetch = mockFetch(detected, { [VERSIONS_URL]: '[1, 2, 3]', [LATEST_RAW_URL]: SCHEMA }) as unknown as typeof fetch;

    await fetchAndDetect(VERSIONS_URL);

    expect(remoteFetches()).toEqual([VERSIONS_URL, LATEST_RAW_URL]);
    expect(detected[0].text).toBe(SCHEMA);
    expect(detected[0].url).toBe(LATEST_RAW_URL);
  });

  it('detects a raw-schema URL as it is, with one fetch', async () => {
    const detected: Array<Record<string, unknown>> = [];
    global.fetch = mockFetch(detected, { [RAW_URL]: SCHEMA }) as unknown as typeof fetch;

    await fetchAndDetect(RAW_URL);

    expect(remoteFetches()).toEqual([RAW_URL]);
    expect(detected[0].text).toBe(SCHEMA);
    expect(detected[0].url).toBe(RAW_URL);
  });

  it('reports the raw-schema fetch failing', async () => {
    const detected: Array<Record<string, unknown>> = [];
    global.fetch = mockFetch(detected, { [VERSION_URL]: ENVELOPE }) as unknown as typeof fetch;

    render(<CatalogImportDialog open onClose={jest.fn()} onSuccess={jest.fn()} />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()));
    fireEvent.click(screen.getByTestId('catalog-import-source-url'));
    fireEvent.change(screen.getByLabelText('Document URL'), { target: { value: VERSION_URL } });
    fireEvent.click(screen.getByRole('button', { name: /fetch and detect/i }));

    await waitFor(() => expect(screen.getByText(/Fetch failed with HTTP 404/i)).toBeInTheDocument());
    expect(detected).toHaveLength(0);
  });
});
