/**
 * The Projects importer picks up a source handed over from Import to catalog (COA-4.3b, #7127).
 *
 * `initialHandoff` loads the source into the intake it came in through — Clipboard for a paste,
 * File for an upload, URL for a fetch — runs Analyze on open, and lands on the Analyze step.
 * Finishing the wizard starts the same `startImport` job a native import does, so the project is
 * created; a URL hand-off is also recorded for auto-refresh like a URL fetched in this dialog.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import type { ProjectsImportHandoff } from '@/app/components/ade/import';

const getImportStatus = jest.fn<(jobId: string) => Promise<Record<string, unknown>>>();
const startImport = jest.fn<(input: unknown) => Promise<{ jobId: string }>>();
const rollbackImport = jest.fn<(jobId: string) => Promise<unknown>>();

jest.mock('@lib/db/import-actions', () => ({
  __esModule: true,
  getImportStatus: (...args: [string]) => getImportStatus(...args),
  startImport: (...args: [unknown]) => startImport(...args),
  rollbackImport: (...args: [string]) => rollbackImport(...args),
  cancelImport: jest.fn(),
  commitImport: jest.fn(),
  retryImport: jest.fn(),
}));

/** Monaco is the clipboard intake's editor; jsdom has no canvas for it. */
jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: () => null,
}));

jest.mock('@/app/utils/project-quality-score-history', () => ({
  __esModule: true,
  appendProjectQualitySnapshot: jest.fn(),
  buildQualitySnapshotReportExtras: () => ({}),
}));

const analyzeSpecification = jest.fn<(content: string, filename: string) => Promise<unknown>>();
jest.mock('@/app/utils/openapi-analyzer', () => {
  const actual = jest.requireActual<typeof import('@/app/utils/openapi-analyzer')>(
    '@/app/utils/openapi-analyzer'
  );
  return {
    __esModule: true,
    ...actual,
    analyzeSpecification: (...args: [string, string]) => analyzeSpecification(...args),
  };
});

jest.mock('@/app/components/ade/dashboard/AnalysisPanel', () => ({
  __esModule: true,
  AnalysisPanel: ({ fileName }: { fileName: string }) => (
    <div data-testid="analysis-panel">{fileName}</div>
  ),
}));

/** Preview is reduced to its one contract with the wizard: it emits the options the footer reads. */
jest.mock('@/app/components/ade/dashboard/PreviewPanel', () => ({
  __esModule: true,
  PreviewPanel: ({
    onImportOptionsChange,
  }: {
    onImportOptionsChange: (options: Record<string, unknown>) => void;
  }) => (
    <button
      type="button"
      data-testid="preview-panel"
      onClick={() =>
        onImportOptionsChange({ projectName: 'Pets', projectSlug: 'pets', selectedSchemas: ['Pet'] })
      }
    >
      Select Pet
    </button>
  ),
}));

import ImportDialog from '@/app/components/ade/dashboard/ImportDialog';

const OPENAPI_YAML = 'openapi: 3.1.0\ninfo:\n  title: Pets\n  version: 1.0.0\npaths: {}\n';

const GOOD_ANALYSIS = {
  isValid: true,
  formatSupported: true,
  format: 'openapi',
  formatDisplayName: 'OpenAPI 3.1',
  version: '3.1.0',
  syntax: 'yaml',
  syntaxValid: true,
  schemaValid: true,
  metrics: {
    schemaCount: 1,
    propertyCount: 1,
    referenceCount: 0,
    pathCount: 0,
    externalReferences: [],
    circularReferences: [],
    customExtensions: [],
    compositionSchemas: { allOf: 0, oneOf: 0, anyOf: 0 },
  },
  qualityScore: { overall: 90, grade: 'A', categories: {}, issues: [] },
  errors: [],
  warnings: [],
  unsupportedFeatures: [],
  document: { info: { title: 'Pets', version: '1.0.0' } },
};

const fetchMock = jest.fn();
global.fetch = fetchMock as unknown as typeof fetch;

/** The hand-off payload for a method. */
function handoff(method: ProjectsImportHandoff['method']): ProjectsImportHandoff {
  return {
    text: OPENAPI_YAML,
    filename: method === 'paste' ? 'openapi-spec.yaml' : 'pets.yaml',
    method,
    url: method === 'url' ? 'https://specs.example.com/pets.yaml' : null,
    format: 'openapi-3.1',
  };
}

function renderWizard(initialHandoff: ProjectsImportHandoff) {
  const onConsumeInitialHandoff = jest.fn();
  render(
    <ImportDialog
      open
      onClose={jest.fn()}
      tenantId="tenant-1"
      userId="user-1"
      variant="projects"
      initialHandoff={initialHandoff}
      onConsumeInitialHandoff={onConsumeInitialHandoff}
    />
  );
  return { onConsumeInitialHandoff };
}

beforeEach(() => {
  jest.clearAllMocks();
  fetchMock.mockImplementation(((input: RequestInfo | URL) => {
    if (String(input).includes('/api/import/project-delta')) {
      return Promise.resolve({ ok: true, json: async () => ({ success: true, delta: null }) });
    }
    return Promise.resolve({ ok: true, json: async () => ({ success: true, sources: [] }) });
  }) as never);
  analyzeSpecification.mockResolvedValue(GOOD_ANALYSIS);
  getImportStatus.mockResolvedValue({
    state: 'completed',
    percent: 100,
    events: [],
    result: { projectId: 'project-1', versionId: 'version-1' },
  });
  startImport.mockResolvedValue({ jobId: 'job-1' });
});

describe('a source handed over from Import to catalog', () => {
  it.each([
    ['paste', 'openapi-spec.yaml', /Clipboard/],
    ['file', 'pets.yaml', /File Upload/],
    ['url', 'pets.yaml', /URL Import/],
  ] as const)('analyzes a %s hand-off on open and lands on Analyze', async (method, filename, tab) => {
    const { onConsumeInitialHandoff } = renderWizard(handoff(method));

    await waitFor(() => expect(analyzeSpecification).toHaveBeenCalledWith(OPENAPI_YAML, filename));
    expect(await screen.findByTestId('analysis-panel')).toBeInTheDocument();
    expect(onConsumeInitialHandoff).toHaveBeenCalled();

    // Back returns to the intake the source came in through, with the source still loaded.
    fireEvent.click(screen.getByRole('button', { name: '← Back' }));
    const [tabs] = await screen.findAllByRole('tablist', { name: 'Import source' });
    expect(within(tabs).getByRole('tab', { name: tab })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('button', { name: /Analyze|Continue/ })).toBeEnabled();
  });

  it('finishes into the import job that creates the project', async () => {
    renderWizard(handoff('paste'));
    await screen.findByTestId('analysis-panel');

    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    fireEvent.click(await screen.findByTestId('preview-panel'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Import →' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Import →' }));

    await waitFor(() =>
      expect(startImport).toHaveBeenCalledWith(
        expect.objectContaining({
          tenantId: 'tenant-1',
          userId: 'user-1',
          sourceKind: 'openapi',
          project: expect.objectContaining({ name: 'Pets', slug: 'pets' }),
        })
      )
    );
  });

  it('records a URL hand-off for auto-refresh once the import lands', async () => {
    renderWizard(handoff('url'));
    await screen.findByTestId('analysis-panel');
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    fireEvent.click(await screen.findByTestId('preview-panel'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Import →' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Import →' }));

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/url-imports')).toBe(true),
    { timeout: 5000 });
    const [, init] = fetchMock.mock.calls.find(([url]) => String(url) === '/api/url-imports')!;
    expect(JSON.parse(String((init as RequestInit).body))).toEqual(
      expect.objectContaining({
        projectId: 'project-1',
        url: 'https://specs.example.com/pets.yaml',
        authenticated: false,
      })
    );
  });
});
