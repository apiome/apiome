/**
 * CatalogImportDialog — the Options step's Dry run (MFI-26.4, #4097).
 *
 * Contracts:
 *  1. Dry run shows the predicted format and routing and makes **no** store call — the import
 *     job endpoint (`/api/catalog/import`) is never hit; only the pre-flight runs;
 *  2. Continue still commits: after a dry run the quality step's Import starts the job as before;
 *  3. a dry run that predicts a failed import says so, with the importer's remediation;
 *  4. a dry run that could not run offers a retry;
 *  5. a JSON Schema is dry-run through the `json-schema` importer the commit would use;
 *  6. the docs screenshot `catalog-import-dry-run` mounts the dump written when
 *     `IMPORT_WIZARD_FIXTURE_DUMP=1` is set:
 *
 *          IMPORT_WIZARD_FIXTURE_DUMP=1 npx jest tests/CatalogImportDialogDryRun.test.tsx -t fixture
 */

import * as fs from 'fs';
import * as path from 'path';

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, it, jest, beforeEach, afterEach } from '@jest/globals';

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
  {
    key: 'json-schema',
    label: 'JSON Schema',
    description: 'Import a JSON Schema document.',
    icon: 'braces',
    paradigm: 'schema',
    input_kinds: ['file', 'url', 'paste'],
    supports_live_discovery: false,
    formats: ['json-schema'],
    available: true,
  },
];

const GRAPHQL_DOC = 'type Query { hello: String }';
const JSON_SCHEMA_DOC = JSON.stringify({
  $schema: 'https://json-schema.org/draft/2020-12/schema',
  title: 'Customer',
  type: 'object',
});

const GRAPHQL_DETECTION = {
  matched: true,
  detected: { format: 'graphql', confidence: 0.95, reason: 'SDL type marker', importable: true },
};
const JSON_SCHEMA_DETECTION = {
  matched: true,
  detected: { format: 'json-schema-2020-12', confidence: 0.95, reason: '$schema', importable: true },
};

/** A completed pre-flight report; `overrides` swap in the outcome under test. */
function preflightReport(overrides: Record<string, unknown> = {}) {
  return {
    ok: true,
    detection: { adapter_key: 'graphql', confidence: 0.95, matched: true, importable: true },
    routing: { target: 'catalog', publishable: false, reason: 'GraphQL is stored in the catalog unconverted.' },
    paradigm: 'graphql',
    format: 'graphql',
    counts: { services: 1, operations: 1, types: 1, channels: 0 },
    fingerprint: 'fingerprint-0123456789',
    lint: { score: 88, grade: 'B', report_fingerprint: 'fp-1', severity_counts: { warning: 1 }, findings: [] },
    style_guide: { guide_id: null, name: 'Apiome defaults', source: 'fallback', fingerprint: 'sg' },
    policy: {
      verdict: 'pass',
      blocking: false,
      source: 'default',
      reason: 'No import quality policy is configured.',
      threshold_score: null,
      allow_override: true,
    },
    cache: { hit: false, key: 'k', content_hash: 'sha' },
    ...overrides,
  };
}

interface RecordedCall {
  url: string;
  body?: unknown;
}

interface MockOptions {
  detection?: Record<string, unknown>;
  /** Pre-flight responses, served in order; the last one repeats. `'fail'` is a 502. */
  preflight?: Array<Record<string, unknown> | 'fail'>;
}

/** Serve the registry, detection, pre-flight and the import job, recording every call. */
function mockFetch({ detection = GRAPHQL_DETECTION, preflight = [preflightReport()] }: MockOptions = {}) {
  const calls: RecordedCall[] = [];
  let preflightIndex = 0;
  const fn = jest.fn((input: unknown, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : String(input);
    calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (url.includes('/api/import/sources')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, sources: SOURCES }) });
    }
    if (url.includes('/api/import/detect')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(detection) });
    }
    if (url.includes('/api/import/preflight')) {
      const next = preflight[Math.min(preflightIndex, preflight.length - 1)];
      preflightIndex += 1;
      if (next === 'fail') {
        return Promise.resolve({
          ok: false,
          json: () => Promise.resolve({ success: false, error: 'The importer is unreachable.' }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, ...next }) });
    }
    if (url === '/api/catalog/import') {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, job_id: 'job-1' }) });
    }
    if (url.startsWith('/api/catalog/import/')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true, state: 'completed' }) });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
  });
  return { fn, calls };
}

/** Whether the import job (the store call) was ever started. */
function storeCalled(calls: RecordedCall[]): boolean {
  return calls.some((c) => c.url === '/api/catalog/import');
}

/** Render the dialog, paste `text`, detect it, and continue to the Options step. */
async function reachOptions(fetchMock: jest.Mock, text = GRAPHQL_DOC, onSuccess = jest.fn()) {
  global.fetch = fetchMock as unknown as typeof fetch;
  render(<CatalogImportDialog open onClose={jest.fn()} onSuccess={onSuccess} />);
  await waitFor(() =>
    expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()),
  );
  fireEvent.click(screen.getByTestId('catalog-import-source-paste'));
  fireEvent.change(screen.getByLabelText('Source content'), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: /detect pasted source/i }));
  await waitFor(() => expect(screen.getByText(/Auto-detected:/i)).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
}

describe('CatalogImportDialog — Dry run (MFI-26.4)', () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => jest.restoreAllMocks());

  it('is offered on Options only', async () => {
    const { fn } = mockFetch();
    global.fetch = fn as unknown as typeof fetch;
    render(<CatalogImportDialog open onClose={jest.fn()} />);
    await waitFor(() =>
      expect(global.fetch).toHaveBeenCalledWith('/api/import/sources', expect.anything()),
    );
    expect(screen.queryByTestId('catalog-import-dry-run-button')).not.toBeInTheDocument();
  });

  it('shows the predicted format and routing without a store call, and Continue still commits', async () => {
    const { fn, calls } = mockFetch();
    const onSuccess = jest.fn();
    await reachOptions(fn, GRAPHQL_DOC, onSuccess);

    fireEvent.click(screen.getByTestId('catalog-import-dry-run-button'));
    await waitFor(() => expect(screen.getByTestId('catalog-import-dry-run')).toBeInTheDocument());

    expect(screen.getByText(/Dry run complete\. Nothing was saved\./)).toBeInTheDocument();
    expect(screen.getByTestId('catalog-import-dry-run-format')).toHaveTextContent('GraphQL');
    expect(screen.getByTestId('catalog-import-dry-run-destination')).toHaveTextContent(/Catalog item/);
    expect(screen.getByTestId('catalog-import-dry-run-item')).toHaveTextContent('Pasted source');

    // The dry run scored the candidate the commit would send — and stored nothing.
    const dryRun = calls.find((c) => c.url === '/api/import/preflight');
    expect(dryRun?.body).toMatchObject({
      source_kind: 'graphql',
      input_kind: 'paste',
      import_target: 'catalog',
    });
    expect(storeCalled(calls)).toBe(false);

    // Continue → quality → Import still commits.
    fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
    await waitFor(() => expect(screen.getByTestId('import-quality-grade')).toHaveTextContent('B'));
    expect(storeCalled(calls)).toBe(false);
    fireEvent.click(screen.getByTestId('import-quality-import'));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled(), { timeout: 3000 });
    expect(storeCalled(calls)).toBe(true);
  });

  it('reports an import that would fail, with the remediation', async () => {
    const { fn, calls } = mockFetch({
      preflight: [
        preflightReport({
          ok: false,
          routing: null,
          lint: null,
          error: {
            code: 'PARSE_ERROR',
            category: 'intake',
            message: 'Syntax error at line 1.',
            remediation: 'Fix the SDL and try again.',
            retriable: false,
          },
        }),
      ],
    });
    await reachOptions(fn);

    fireEvent.click(screen.getByTestId('catalog-import-dry-run-button'));
    await waitFor(() =>
      expect(screen.getByTestId('catalog-import-dry-run-failure')).toHaveTextContent(
        /Import would fail: Syntax error at line 1\..*Fix the SDL/,
      ),
    );
    expect(storeCalled(calls)).toBe(false);
  });

  it('offers a retry when the dry run itself could not run', async () => {
    const { fn, calls } = mockFetch({ preflight: ['fail', preflightReport()] });
    await reachOptions(fn);

    fireEvent.click(screen.getByTestId('catalog-import-dry-run-button'));
    await waitFor(() =>
      expect(screen.getByTestId('catalog-import-dry-run-error')).toHaveTextContent(
        /The importer is unreachable\./,
      ),
    );

    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    await waitFor(() => expect(screen.getByTestId('catalog-import-dry-run')).toBeInTheDocument());
    expect(calls.filter((c) => c.url === '/api/import/preflight')).toHaveLength(2);
    expect(storeCalled(calls)).toBe(false);
  });

  it('dry-runs a JSON Schema through the json-schema importer the commit would use', async () => {
    const { fn, calls } = mockFetch({
      detection: JSON_SCHEMA_DETECTION,
      preflight: [preflightReport({ format: 'json-schema', paradigm: 'schema' })],
    });
    await reachOptions(fn, JSON_SCHEMA_DOC);

    fireEvent.click(screen.getByTestId('catalog-import-dry-run-button'));
    await waitFor(() => expect(screen.getByTestId('catalog-import-dry-run')).toBeInTheDocument());
    expect(calls.find((c) => c.url === '/api/import/preflight')?.body).toMatchObject({
      source_kind: 'json-schema',
      import_target: 'catalog',
    });
    expect(storeCalled(calls)).toBe(false);
  });
});

describe('the docs fixture', () => {
  const OUT = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-import-wizard');

  afterEach(() => jest.restoreAllMocks());

  it('renders the dry run result (and writes the fixture on request)', async () => {
    const { fn } = mockFetch({
      preflight: [
        preflightReport({
          counts: { services: 1, operations: 6, types: 9, channels: 0 },
          fingerprint: '9f2c4e81b07a5d3361e0c2f4',
          lint: { score: 91, grade: 'A', report_fingerprint: 'fp-a', severity_counts: {}, findings: [] },
        }),
      ],
    });
    await reachOptions(fn, 'type Query {\n  user(id: ID!): User\n}\n\ntype User {\n  id: ID!\n  name: String\n}\n');
    fireEvent.click(screen.getByTestId('catalog-import-dry-run-button'));
    await waitFor(() => expect(screen.getByTestId('catalog-import-dry-run')).toBeInTheDocument());

    const html = (document.querySelector('.imp-wizard') as HTMLElement).outerHTML;
    expect(html).toContain('cat-imp-dryrun__facts');
    if (process.env.IMPORT_WIZARD_FIXTURE_DUMP !== '1') return;
    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, 'catalog-dry-run.html'), html);
  });
});
