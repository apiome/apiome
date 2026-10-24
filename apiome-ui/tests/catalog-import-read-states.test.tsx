/**
 * Import to catalog — pending and failed reads (RC6-H3, #6210).
 *
 * The wizard reads three things before it can show a source: format detection, a document URL,
 * and a repository selection. Detection used to show nothing while it ran, and each failure was
 * a bare alert with no way to try again short of re-entering the source. Now detection says it is
 * running, and a failed read is an `ErrorBanner` whose retry runs the same read again. A
 * validation message ("Enter a valid URL.") stays a plain alert: retrying cannot fix it.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { CatalogImportDialog } from '../src/app/components/ade/dashboard/catalog/CatalogImportDialog';
import type { ImportSourceDescriptor } from '../src/app/components/ade/dashboard/importSourceCatalog';

const SDL = 'type Query { hello: String }';
const REMOTE_URL = 'https://api.example.com/schema.graphql';

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

const DETECTION = {
  matched: true,
  detected: { format: 'graphql', confidence: 0.95, reason: 'SDL type definitions', importable: true },
};

/** A JSON response. */
const json = (body: unknown, status = 200) =>
  Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body), text: () => Promise.resolve(SDL) });

/**
 * A fetch whose reads matching `pattern` are held (`'hold'`) or fail (`'fail'`) until
 * `recover()`; everything else answers as the happy path.
 */
function mockFetch(pattern: RegExp, mode: 'hold' | 'fail') {
  let active = true;
  global.fetch = jest.fn((input: unknown) => {
    const url = String(input);
    if (active && pattern.test(url)) {
      if (mode === 'hold') return new Promise(() => {});
      return json({ success: false, error: 'Detector unavailable' }, 503);
    }
    if (url.includes('/api/import/sources')) return json({ success: true, sources: SOURCES });
    if (url.includes('/api/import/detect')) return json(DETECTION);
    if (url.includes('/api/catalog/import/bulk/plan')) return json({ success: true, plan: null });
    if (url === REMOTE_URL) return json(SDL);
    return json({}, 404);
  }) as unknown as typeof fetch;
  return { recover: () => { active = false; } };
}

/** Open the dialog on the paste source with SDL entered. */
async function pasteSdl() {
  render(<CatalogImportDialog open onClose={() => {}} onSuccess={() => {}} />);
  await waitFor(() => expect(screen.getByTestId('catalog-import-source-paste')).toBeInTheDocument());
  fireEvent.click(screen.getByTestId('catalog-import-source-paste'));
  fireEvent.change(screen.getByLabelText('Source content'), { target: { value: SDL } });
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe('format detection', () => {
  it('says detection is running, and holds the paste button, while it is pending', async () => {
    mockFetch(/\/api\/import\/detect/, 'hold');
    await pasteSdl();
    fireEvent.click(screen.getByRole('button', { name: /detect pasted source/i }));
    expect(await screen.findByTestId('catalog-import-detecting')).toHaveTextContent('Detecting the format…');
    expect(screen.getByRole('button', { name: /detect pasted source/i })).toBeDisabled();
  });

  it('says a failed detection failed, with a retry that detects again', async () => {
    const read = mockFetch(/\/api\/import\/detect/, 'fail');
    await pasteSdl();
    fireEvent.click(screen.getByRole('button', { name: /detect pasted source/i }));
    const error = await screen.findByTestId('catalog-import-read-error');
    expect(error).toHaveTextContent("Couldn't read that source");
    expect(error).toHaveTextContent('Detector unavailable');
    read.recover();
    fireEvent.click(within(error).getByRole('button', { name: /try again/i }));
    await waitFor(() => expect(screen.getAllByText(/Auto-detected/i).length).toBeGreaterThan(0));
    expect(screen.queryByTestId('catalog-import-read-error')).toBeNull();
  });
});

describe('URL and repository reads', () => {
  it('retries a failed URL fetch', async () => {
    const read = mockFetch(new RegExp(`^${REMOTE_URL.replace(/[.]/g, '\\.')}$`), 'fail');
    render(<CatalogImportDialog open onClose={() => {}} onSuccess={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('catalog-import-source-url')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('catalog-import-source-url'));
    fireEvent.change(screen.getByLabelText('Document URL'), { target: { value: REMOTE_URL } });
    fireEvent.click(screen.getByRole('button', { name: /fetch and detect/i }));
    const error = await screen.findByTestId('catalog-import-read-error');
    expect(error).toHaveTextContent('Fetch failed with HTTP 503.');
    read.recover();
    fireEvent.click(within(error).getByRole('button', { name: /try again/i }));
    await waitFor(() => expect(screen.getAllByText(/Auto-detected/i).length).toBeGreaterThan(0));
  });

  it('keeps a validation message as a plain alert, with no retry', async () => {
    mockFetch(/never/, 'fail');
    render(<CatalogImportDialog open onClose={() => {}} onSuccess={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('catalog-import-source-url')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('catalog-import-source-url'));
    fireEvent.change(screen.getByLabelText('Document URL'), { target: { value: 'not a url' } });
    fireEvent.click(screen.getByRole('button', { name: /fetch and detect/i }));
    expect(await screen.findByText('Enter a valid URL.')).toBeInTheDocument();
    expect(screen.queryByTestId('catalog-import-read-error')).toBeNull();
  });

  it('retries a failed repository read', async () => {
    const read = mockFetch(/\/api\/catalog\/import\/git$/, 'fail');
    render(<CatalogImportDialog open onClose={() => {}} onSuccess={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('catalog-import-source-git')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('catalog-import-source-git'));
    fireEvent.change(screen.getByLabelText('Repository URL'), { target: { value: 'https://github.com/acme/specs' } });
    fireEvent.click(
      within(screen.getByTestId('catalog-import-git-panel')).getByRole('button', { name: /fetch and detect/i })
    );
    const error = await screen.findByTestId('catalog-import-read-error');
    expect(error).toHaveTextContent('Detector unavailable');
    const before = (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).endsWith('/import/git')).length;
    read.recover();
    fireEvent.click(within(error).getByRole('button', { name: /try again/i }));
    await waitFor(() =>
      expect(
        (global.fetch as jest.Mock).mock.calls.filter(([url]) => String(url).endsWith('/import/git')).length
      ).toBeGreaterThan(before)
    );
  });
});
