/**
 * CatalogImportDialog — JSON Schema 2020-12 disambiguation prompt (MFI-26.7, #4102).
 *
 * JSON Schema is the only detected format that asks the user where it should go:
 *  1. On JSON Schema detection the detect step routes to "Choose destination" and the options step
 *     shows the Catalog-vs-Types/Projects prompt (not the plain "Store in catalog" note).
 *  2. The **Catalog** choice stores a non-publishable, schemas-only catalog item via the shared
 *     `/api/catalog/import` job with `source_kind: 'json-schema'` (kept verbatim, never converted).
 *  3. The **Types/Projects** choice hands the schema off (`onJsonSchemaAsCurrent`) to the existing
 *     type-import review and closes the dialog — it never hits the catalog store.
 *  4. Other formats never prompt: OpenAPI routes straight to Projects and GraphQL straight to the
 *     catalog, with no destination choice.
 *
 * Detection is mocked via `/api/import/detect`; the catalog store job is mocked via
 * `/api/catalog/import` (start) + `/api/catalog/import/{jobId}` (poll).
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { CatalogImportDialog } from '../src/app/components/ade/dashboard/catalog/CatalogImportDialog';
import type { ImportSourceDescriptor } from '../src/app/components/ade/dashboard/importSourceCatalog';

const SOURCES: ImportSourceDescriptor[] = [
  {
    key: 'json-schema',
    label: 'JSON Schema',
    description: 'Import a JSON Schema (2020-12 and variants) into the catalog as a schemas-only source.',
    icon: 'braces',
    paradigm: 'data_schema',
    input_kinds: ['file', 'url', 'paste'],
    supports_live_discovery: false,
    formats: ['json-schema'],
    available: true,
  },
];

const JSON_SCHEMA_DOC = JSON.stringify({
  $schema: 'https://json-schema.org/draft/2020-12/schema',
  title: 'User',
  type: 'object',
  properties: { id: { type: 'string' } },
});

/**
 * Route the registry, a detection response, and (optionally) the catalog store job through one
 * fetch mock. The store start returns a job id and the poll reports the terminal state supplied.
 */
function mockFetch(detection: unknown, opts: { jobState?: string } = {}): jest.Mock {
  const calls: Array<{ url: string; body?: unknown }> = [];
  const fn = jest.fn((input: unknown, init?: { body?: string }) => {
    const url = typeof input === 'string' ? input : String(input);
    const body = init?.body ? JSON.parse(init.body) : undefined;
    calls.push({ url, body });
    if (url.includes('/api/import/sources')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, sources: SOURCES }) });
    }
    if (url.includes('/api/import/detect')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(detection) });
    }
    // Catalog store: start (POST /api/catalog/import) then poll (/api/catalog/import/<jobId>).
    if (url.match(/\/api\/catalog\/import\/.+/)) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, state: opts.jobState ?? 'completed' }),
      });
    }
    if (url.includes('/api/catalog/import')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, job_id: 'job-1' }) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  }) as unknown as jest.Mock;
  (fn as unknown as { calls: typeof calls }).calls = calls;
  return fn;
}

/** Drive Source → Detect by pasting content and detecting it. */
async function pasteAndDetect(text: string) {
  fireEvent.click(screen.getByTestId('catalog-import-source-paste'));
  fireEvent.change(screen.getByLabelText('Source content'), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: /detect pasted source/i }));
  await waitFor(() => expect(screen.getByText(/Auto-detected:/i)).toBeInTheDocument());
}

/** The recorded fetch calls, for asserting the request body of the store job. */
function recordedCalls(fetchMock: jest.Mock): Array<{ url: string; body?: unknown }> {
  return (fetchMock as unknown as { calls: Array<{ url: string; body?: unknown }> }).calls;
}

describe('CatalogImportDialog — JSON Schema disambiguation prompt (MFI-26.7)', () => {
  afterEach(() => jest.restoreAllMocks());

  const jsonSchemaDetection = {
    matched: true,
    detected: {
      format: 'json-schema-2020-12',
      confidence: 0.95,
      reason: '`$schema` JSON Schema 2020-12 marker',
      importable: true,
    },
  };

  it('routes JSON Schema to a destination choice with both branches', async () => {
    global.fetch = mockFetch(jsonSchemaDetection) as unknown as typeof fetch;
    render(<CatalogImportDialog open onClose={jest.fn()} onJsonSchemaAsCurrent={jest.fn()} />);
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()),
    );
    await pasteAndDetect(JSON_SCHEMA_DOC);

    // The detect step calls out a destination choice rather than a fixed routing.
    expect(screen.getByText(/Routing decision → Choose destination/i)).toBeInTheDocument();

    // The options step offers both branches.
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));
    expect(screen.getByText(/Choose where this JSON Schema should go/i)).toBeInTheDocument();
    expect(screen.getByText(/Catalog for later conversion/i)).toBeInTheDocument();
    expect(screen.getByText(/Types\/Projects as current schema/i)).toBeInTheDocument();
  });

  it('Catalog choice stores a non-publishable catalog item via the json-schema adapter', async () => {
    const fetchMock = mockFetch(jsonSchemaDetection, { jobState: 'completed' });
    global.fetch = fetchMock as unknown as typeof fetch;
    const onSuccess = jest.fn();
    render(
      <CatalogImportDialog open onClose={jest.fn()} onSuccess={onSuccess} onJsonSchemaAsCurrent={jest.fn()} />,
    );
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()),
    );
    await pasteAndDetect(JSON_SCHEMA_DOC);

    fireEvent.click(screen.getByRole('button', { name: /continue/i }));
    // The Catalog radio is the default; Continue kicks off the store-raw job.
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));

    await waitFor(() => expect(onSuccess).toHaveBeenCalled(), { timeout: 3000 });

    // The store hit the shared catalog import job with source_kind 'json-schema'.
    const startCall = recordedCalls(fetchMock).find(
      (c) => c.url === '/api/catalog/import' && (c.body as { metadata?: unknown })?.metadata,
    );
    expect(startCall).toBeDefined();
    expect((startCall?.body as { metadata: { source_kind: string } }).metadata.source_kind).toBe(
      'json-schema',
    );
  });

  it('Types/Projects choice hands off as current and never stores to the catalog', async () => {
    const fetchMock = mockFetch(jsonSchemaDetection);
    global.fetch = fetchMock as unknown as typeof fetch;
    const onJsonSchemaAsCurrent = jest.fn();
    const onClose = jest.fn();
    render(
      <CatalogImportDialog open onClose={onClose} onJsonSchemaAsCurrent={onJsonSchemaAsCurrent} />,
    );
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()),
    );
    await pasteAndDetect(JSON_SCHEMA_DOC);

    fireEvent.click(screen.getByRole('button', { name: /continue/i }));
    // Pick the Types/Projects branch.
    fireEvent.click(screen.getByLabelText(/Types\/Projects as current schema/i));
    fireEvent.click(screen.getByRole('button', { name: /continue/i }));

    await waitFor(() => expect(onJsonSchemaAsCurrent).toHaveBeenCalled());
    const payload = onJsonSchemaAsCurrent.mock.calls[0][0] as { text: string; document: unknown };
    expect(payload.text).toBe(JSON_SCHEMA_DOC);
    expect(payload.document).toMatchObject({ title: 'User' });
    // The dialog closed and no catalog store job ran.
    expect(onClose).toHaveBeenCalled();
    expect(recordedCalls(fetchMock).some((c) => c.url === '/api/catalog/import')).toBe(false);
  });

  it('does not prompt for OpenAPI (Projects) or GraphQL (catalog)', async () => {
    // OpenAPI → Projects, no choice.
    global.fetch = mockFetch({
      matched: true,
      detected: { format: 'openapi-3.1', confidence: 0.99, reason: '`openapi` marker', importable: true },
    }) as unknown as typeof fetch;
    const { unmount } = render(<CatalogImportDialog open onClose={jest.fn()} />);
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()),
    );
    await pasteAndDetect('openapi: 3.1.0');
    expect(screen.getByText(/Routing decision → Projects/i)).toBeInTheDocument();
    expect(screen.queryByText(/Choose destination/i)).not.toBeInTheDocument();
    unmount();

    // GraphQL → Catalog, no choice.
    global.fetch = mockFetch({
      matched: true,
      detected: { format: 'graphql', confidence: 0.95, reason: 'SDL', importable: true },
    }) as unknown as typeof fetch;
    render(<CatalogImportDialog open onClose={jest.fn()} />);
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()),
    );
    await pasteAndDetect('type Query { hello: String }');
    expect(screen.getByText(/Routing decision → Catalog/i)).toBeInTheDocument();
    expect(screen.queryByText(/Choose destination/i)).not.toBeInTheDocument();
  });
});
