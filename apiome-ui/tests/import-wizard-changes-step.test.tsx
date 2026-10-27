/**
 * The Import wizard's Changes step (IXH-3.7, #6321).
 *
 * Pins, without starting a real import:
 *
 *   1. the data helpers — `fetchProjectDelta` (ready / skip / error, never throws), the filter,
 *      the value formatting;
 *   2. the model — the conditional stepper stop, the visibility rule, the footer verbs;
 *   3. `ImportChangesPanel` — summary bar, breaking callout, ranked list with filter and paging,
 *      the "No changes from v…" state, `ErrorState` with retry, the lazily mounted side-by-side
 *      diff (latest left, incoming right), and axe;
 *   4. the dialog path — Preview → Changes → Import for an existing Project, Preview → Import for
 *      a first-time one, a failed comparison that still lets the import continue, Back, dry run;
 *   5. the browser fixture `e2e/hive-import-wizard.spec.ts` and the docs screenshot
 *      `import-wizard-changes` mount, written when `IMPORT_WIZARD_FIXTURE_DUMP=1` is set:
 *
 *          IMPORT_WIZARD_FIXTURE_DUMP=1 npx jest tests/import-wizard-changes-step.test.tsx -t fixture
 */

import * as fs from 'fs';
import * as path from 'path';
import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';
import { jest } from '@jest/globals';

import {
  IMPORT_WIZARD_COPY,
  IMPORT_WIZARD_STEPS,
  importFooterFor,
  importWizardStepsFor,
  noChangesTitle,
  showsChangesStep,
  stepperIdFor,
} from '@/app/components/ade/import/importWizardModel';
import {
  describeDeltaValues,
  fetchProjectDelta,
  filterProjectDeltaChanges,
  formatDeltaValue,
  prettyDeltaDocument,
  type ProjectDelta,
  type ProjectDeltaChange,
} from '@/app/utils/import-project-delta';

const AXE_OPTIONS = {
  rules: {
    'color-contrast': { enabled: false },
    region: { enabled: false },
  },
} as const;

/* -------------------------------------------------------------------------
   Stubs
   ------------------------------------------------------------------------- */

const getImportStatus = jest.fn<(jobId: string) => Promise<Record<string, unknown>>>();
const startImport = jest.fn<(input: unknown) => Promise<{ jobId: string }>>();

jest.mock('@lib/db/import-actions', () => ({
  __esModule: true,
  getImportStatus: (...args: [string]) => getImportStatus(...args),
  startImport: (...args: [unknown]) => startImport(...args),
  rollbackImport: jest.fn(async () => ({})),
  cancelImport: jest.fn(async () => ({})),
  commitImport: jest.fn(async () => ({ success: true })),
  retryImport: jest.fn(async () => ({ success: true })),
}));

/** Monaco: the diff editor echoes its sides and labels so the test can read them. */
jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: () => <textarea aria-label="Specification content" />,
  DiffEditor: ({ original, modified }: { original?: string; modified?: string }) => (
    <div data-testid="mock-monaco-diff" data-original={original} data-modified={modified} />
  ),
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
  AnalysisPanel: () => <div data-testid="analysis-panel" />,
}));

jest.mock('@/app/components/ade/dashboard/PreviewPanel', () => ({
  __esModule: true,
  PreviewPanel: ({ onImportOptionsChange }: { onImportOptionsChange: (o: Record<string, unknown>) => void }) => (
    <div data-testid="preview-panel">
      <button
        type="button"
        onClick={() =>
          onImportOptionsChange({ projectName: 'Payments API', projectSlug: 'payments-api', selectedSchemas: ['Refund'] })
        }
      >
        Select Refund
      </button>
      <button
        type="button"
        onClick={() =>
          onImportOptionsChange({
            projectName: 'Payments API',
            projectSlug: 'payments-api',
            selectedSchemas: ['Refund'],
            dryRun: true,
          })
        }
      >
        Select Refund (dry run)
      </button>
    </div>
  ),
}));

import ImportDialog from '@/app/components/ade/dashboard/ImportDialog';
import { ImportChangesPanel } from '@/app/components/ade/import/ImportChangesPanel';

/* -------------------------------------------------------------------------
   Fixtures
   ------------------------------------------------------------------------- */

const BASE_DOC = { openapi: '3.1.0', info: { title: 'Payments API', version: '2.4.0' }, paths: { '/refunds/{id}': {} } };
const INCOMING_DOC = { openapi: '3.1.0', info: { title: 'Payments API', version: '2.5.0' }, paths: { '/payouts': {} } };

function change(overrides: Partial<ProjectDeltaChange>): ProjectDeltaChange {
  return {
    kind: 'added',
    scope: 'path',
    entity: '/payouts',
    label: 'path /payouts',
    pointer: '/paths/~1payouts',
    before: null,
    after: '{1 key}',
    severity: 'safe',
    rules: ['path_added'],
    message: 'New path added',
    ...overrides,
  };
}

const CHANGES: ProjectDeltaChange[] = [
  change({
    kind: 'removed',
    scope: 'operation',
    entity: 'DELETE /refunds/{id}',
    label: 'DELETE /refunds/{id}',
    pointer: '/paths/~1refunds~1{id}/delete',
    before: '{1 key}',
    after: null,
    severity: 'breaking',
    rules: ['operation_removed'],
    message: 'HTTP DELETE removed from path',
  }),
  change({
    kind: 'changed',
    scope: 'schema',
    entity: 'Refund',
    label: 'schema Refund.amount minimum',
    pointer: '/components/schemas/Refund/properties/amount/minimum',
    before: 0,
    after: 0.01,
    severity: 'breaking',
  }),
  change({}),
  change({ label: 'GET /refunds/{id} summary', pointer: '/paths/~1refunds~1{id}/get/summary', kind: 'changed', before: 'Fetch a refund', after: 'Fetch one refund', severity: null, rules: [] }),
];

const DELTA: ProjectDelta = {
  project_id: 'p-1',
  project_slug: 'payments-api',
  project_name: 'Payments API',
  base_revision_id: 'r-1',
  base_version_label: '2.4.0',
  overall: 'breaking',
  counts: { added: 1, changed: 2, removed: 1, breaking: 2, total: 4 },
  changes: CHANGES,
  truncated: false,
  base_document: BASE_DOC,
  incoming_document: INCOMING_DOC,
};

const NO_CHANGES: ProjectDelta = {
  ...DELTA,
  overall: 'safe',
  counts: { added: 0, changed: 0, removed: 0, breaking: 0, total: 0 },
  changes: [],
};

function jsonResponse(body: unknown, ok = true) {
  return Promise.resolve({ ok, json: async () => body } as Response);
}

/* -------------------------------------------------------------------------
   1. Data helpers
   ------------------------------------------------------------------------- */

describe('fetchProjectDelta', () => {
  it('posts the document and slug, and returns the delta', async () => {
    const fetchImpl = jest.fn(() => jsonResponse({ success: true, delta: DELTA }));
    const state = await fetchProjectDelta({ document: INCOMING_DOC, project_slug: 'payments-api' }, fetchImpl as never);
    expect(state).toEqual({ status: 'ready', delta: DELTA });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/import/project-delta');
    expect(JSON.parse(String(init.body))).toEqual({ document: INCOMING_DOC, project_slug: 'payments-api' });
  });

  it('reads a null delta as "skip" — a first-time or Catalog import', async () => {
    const fetchImpl = jest.fn(() => jsonResponse({ success: true, delta: null }));
    expect(await fetchProjectDelta({ document: {}, project_slug: 'x' }, fetchImpl as never)).toEqual({ status: 'skip' });
  });

  it('reports a failed request as an error and never throws', async () => {
    const failing = jest.fn(() => jsonResponse({ success: false, error: 'boom' }, false));
    expect(await fetchProjectDelta({ document: {}, project_slug: 'x' }, failing as never)).toEqual({
      status: 'error',
      message: 'boom',
    });
    const throwing = jest.fn(() => Promise.reject(new Error('offline')));
    expect(await fetchProjectDelta({ document: {}, project_slug: 'x' }, throwing as never)).toEqual({
      status: 'error',
      message: 'offline',
    });
  });
});

describe('the change-list helpers', () => {
  it('filters by kind, by breaking, and by text, keeping the ranked order', () => {
    expect(filterProjectDeltaChanges(CHANGES, 'all')).toHaveLength(4);
    expect(filterProjectDeltaChanges(CHANGES, 'breaking').map((c) => c.label)).toEqual([
      'DELETE /refunds/{id}',
      'schema Refund.amount minimum',
    ]);
    expect(filterProjectDeltaChanges(CHANGES, 'changed')).toHaveLength(2);
    expect(filterProjectDeltaChanges(CHANGES, 'all', 'REFUND.amount')).toHaveLength(1);
    expect(filterProjectDeltaChanges(CHANGES, 'all', '~1payouts')).toHaveLength(1);
  });

  it('formats values and describes changed scalars only', () => {
    expect(formatDeltaValue(null)).toBe('—');
    expect(formatDeltaValue('{3 keys}')).toBe('{3 keys}');
    expect(formatDeltaValue('text')).toBe('"text"');
    expect(formatDeltaValue(0.01)).toBe('0.01');
    expect(describeDeltaValues(CHANGES[1])).toBe('0 → 0.01');
    expect(describeDeltaValues(CHANGES[0])).toBeNull();
    expect(prettyDeltaDocument(null)).toBe('');
    expect(prettyDeltaDocument({ a: 1 })).toBe('{\n  "a": 1\n}');
  });
});

/* -------------------------------------------------------------------------
   2. Model
   ------------------------------------------------------------------------- */

describe('the Changes step in the wizard model', () => {
  it('adds a Changes stop between Preview and Import only when it applies', () => {
    expect(importWizardStepsFor(false)).toBe(IMPORT_WIZARD_STEPS);
    expect(importWizardStepsFor(true).map((s) => s.id)).toEqual([
      'source',
      'analyze',
      'preview',
      'changes',
      'import',
      'done',
    ]);
    expect(stepperIdFor('changes')).toBe('changes');
  });

  it('is shown for a delta or a failed comparison, never for a skip', () => {
    expect(showsChangesStep({ status: 'ready', delta: DELTA })).toBe(true);
    expect(showsChangesStep({ status: 'error', message: 'x' })).toBe(true);
    expect(showsChangesStep({ status: 'skip' })).toBe(false);
    expect(showsChangesStep({ status: 'idle' })).toBe(false);
    expect(showsChangesStep({ status: 'checking' })).toBe(false);
  });

  it('never refuses "Continue to import", and says when Preview is checking', () => {
    const base = { source: 'file', importComplete: false, importSucceeded: false };
    expect(importFooterFor({ ...base, step: 'changes' }).primary).toEqual({ label: 'Continue to import', disabled: false });
    expect(importFooterFor({ ...base, step: 'changes' }).back).toEqual({ label: '← Back', disabled: false });
    expect(importFooterFor({ ...base, step: 'preview', hasSelection: true, checkingChanges: true }).primary).toEqual({
      label: 'Checking for changes…',
      disabled: true,
    });
    expect(importFooterFor({ ...base, step: 'preview', hasSelection: true }).primary?.label).toBe('Import →');
  });

  it('names the version in the empty state', () => {
    expect(noChangesTitle('2.4.0')).toBe('No changes from v2.4.0');
    expect(noChangesTitle('')).toBe('No changes from the latest version');
  });
});

/* -------------------------------------------------------------------------
   3. The panel
   ------------------------------------------------------------------------- */

describe('ImportChangesPanel', () => {
  it('leads with the summary bar and a breaking callout, then the ranked list', () => {
    render(<ImportChangesPanel state={{ status: 'ready', delta: DELTA }} onRetry={jest.fn()} />);
    expect(screen.getByRole('heading', { name: /Changes vs\. Payments API v2\.4\.0/ })).toBeInTheDocument();
    expect(screen.getByTestId('import-changes-count-added')).toHaveTextContent('1 added');
    expect(screen.getByTestId('import-changes-count-changed')).toHaveTextContent('2 changed');
    expect(screen.getByTestId('import-changes-count-removed')).toHaveTextContent('1 removed');
    expect(screen.getByTestId('import-changes-count-breaking')).toHaveTextContent('2 breaking');
    expect(screen.getByTestId('import-changes-breaking')).toHaveTextContent(IMPORT_WIZARD_COPY.changesBreakingTitle);

    const rows = within(screen.getByTestId('import-changes-list')).getAllByRole('listitem');
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent('DELETE /refunds/{id}');
    expect(rows[0]).toHaveAttribute('data-severity', 'breaking');
    expect(rows[1]).toHaveTextContent('schema Refund.amount minimum 0 → 0.01');
    // An ungraded change carries no badge, so it never reads as safe.
    expect(rows[3]).toHaveAttribute('data-severity', 'ungraded');
    expect(within(rows[3]).queryByText('safe')).not.toBeInTheDocument();
  });

  it('filters the list and pages it', () => {
    render(<ImportChangesPanel state={{ status: 'ready', delta: DELTA }} onRetry={jest.fn()} pageSize={2} />);
    const list = () => within(screen.getByTestId('import-changes-list')).getAllByRole('listitem');
    expect(list()).toHaveLength(2);
    expect(list()[0]).toHaveAttribute('aria-setsize', '4');
    fireEvent.click(screen.getByRole('button', { name: 'Show more (2)' }));
    expect(list()).toHaveLength(4);

    fireEvent.change(screen.getByTestId('import-changes-filter'), { target: { value: 'added' } });
    expect(list()).toHaveLength(1);
    fireEvent.change(screen.getByTestId('import-changes-filter'), { target: { value: 'all' } });
    fireEvent.change(screen.getByRole('searchbox', { name: IMPORT_WIZARD_COPY.changesSearchLabel }), {
      target: { value: 'nothing-matches' },
    });
    expect(screen.getByText('No changes match this filter.')).toBeInTheDocument();
  });

  it('mounts the side-by-side diff only on its tab, latest version left and incoming right', async () => {
    render(<ImportChangesPanel state={{ status: 'ready', delta: DELTA }} onRetry={jest.fn()} />);
    expect(screen.queryByTestId('mock-monaco-diff')).not.toBeInTheDocument();
    const tab = screen.getByRole('tab', { name: IMPORT_WIZARD_COPY.changesSideBySideTab });
    fireEvent.mouseDown(tab);
    fireEvent.click(tab);
    const diff = await screen.findByTestId('mock-monaco-diff');
    expect(diff).toHaveAttribute('data-original', JSON.stringify(BASE_DOC, null, 2));
    expect(diff).toHaveAttribute('data-modified', JSON.stringify(INCOMING_DOC, null, 2));
  });

  it('says so when nothing changed, and draws no breaking callout', () => {
    render(<ImportChangesPanel state={{ status: 'ready', delta: NO_CHANGES }} onRetry={jest.fn()} />);
    expect(screen.getByText('No changes from v2.4.0')).toBeInTheDocument();
    expect(screen.queryByTestId('import-changes-breaking')).not.toBeInTheDocument();
    expect(screen.queryByTestId('import-changes-count-breaking')).not.toBeInTheDocument();
  });

  it('offers a retry when the comparison failed', () => {
    const onRetry = jest.fn();
    render(<ImportChangesPanel state={{ status: 'error', message: 'Server unavailable.' }} onRetry={onRetry} />);
    expect(screen.getByRole('alert')).toHaveTextContent(IMPORT_WIZARD_COPY.changesErrorTitle);
    expect(screen.getByRole('alert')).toHaveTextContent('You can still continue to import.');
    fireEvent.click(screen.getByRole('button', { name: /Try again|Retry/ }));
    expect(onRetry).toHaveBeenCalled();
  });

  it('draws nothing for a skipped step', () => {
    const { container } = render(<ImportChangesPanel state={{ status: 'skip' }} onRetry={jest.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('is axe-clean with changes, with none, and on error', async () => {
    for (const state of [
      { status: 'ready', delta: DELTA },
      { status: 'ready', delta: NO_CHANGES },
      { status: 'error', message: 'x' },
    ] as const) {
      const { container, unmount } = render(<ImportChangesPanel state={state} onRetry={jest.fn()} />);
      expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();
      unmount();
    }
  });
});

/* -------------------------------------------------------------------------
   4. The dialog path
   ------------------------------------------------------------------------- */

const GOOD_ANALYSIS = {
  isValid: true,
  formatSupported: true,
  format: 'openapi',
  formatDisplayName: 'OpenAPI 3.1',
  version: '3.1.0',
  syntax: 'json',
  syntaxValid: true,
  schemaValid: true,
  metrics: {
    schemaCount: 1,
    propertyCount: 1,
    referenceCount: 0,
    pathCount: 1,
    externalReferences: [],
    circularReferences: [],
    customExtensions: [],
    compositionSchemas: { allOf: 0, oneOf: 0, anyOf: 0 },
  },
  qualityScore: { overall: 90, grade: 'A', categories: {}, issues: [] },
  errors: [],
  warnings: [],
  unsupportedFeatures: [],
  document: INCOMING_DOC,
};

const fetchMock = jest.fn<(input: RequestInfo | URL, init?: RequestInit) => Promise<Response>>();
global.fetch = fetchMock as unknown as typeof fetch;

/** Answer the registry and the comparison; `delta` is what the comparison says. */
function stubFetch(delta: () => Promise<Response>) {
  fetchMock.mockImplementation((input) => {
    const url = String(input);
    if (url.includes('/api/import/project-delta')) return delta();
    if (url.includes('/api/import/sources')) return jsonResponse({ sources: [] });
    return jsonResponse({});
  });
}

async function reachPreview(select = 'Select Refund') {
  render(<ImportDialog open onClose={jest.fn()} tenantId="tenant-1" userId="user-1" initialLLMSpec="{}" />);
  await screen.findByTestId('analysis-panel');
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  await screen.findByTestId('preview-panel');
  fireEvent.click(screen.getByRole('button', { name: select }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Import →' })).toBeEnabled());
}

function deltaCalls() {
  return fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/import/project-delta'));
}

describe('the wizard with a Changes step', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    analyzeSpecification.mockResolvedValue(GOOD_ANALYSIS);
    startImport.mockResolvedValue({ jobId: 'job-1' });
    getImportStatus.mockResolvedValue({ state: 'running', percent: 10, events: [] });
  });

  it('stops at Changes for an existing Project, then imports on "Continue to import"', async () => {
    stubFetch(() => jsonResponse({ success: true, delta: DELTA }));
    await reachPreview();
    fireEvent.click(screen.getByRole('button', { name: 'Import →' }));

    await screen.findByTestId('import-changes');
    expect(startImport).not.toHaveBeenCalled();
    const body = JSON.parse(String(deltaCalls()[0][1]?.body));
    expect(body).toEqual({ document: INCOMING_DOC, project_slug: 'payments-api' });
    // The stepper gained the conditional stop, and it is the current one.
    expect(within(screen.getByLabelText('Import progress')).getByText('Changes')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Continue to import' }));
    await waitFor(() => expect(startImport).toHaveBeenCalledTimes(1));
    expect(startImport).toHaveBeenCalledWith(
      expect.objectContaining({ project: expect.objectContaining({ slug: 'payments-api' }) }),
    );
  });

  it('goes straight to Import for a first-time import', async () => {
    stubFetch(() => jsonResponse({ success: true, delta: null }));
    await reachPreview();
    fireEvent.click(screen.getByRole('button', { name: 'Import →' }));
    await waitFor(() => expect(startImport).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId('import-changes')).not.toBeInTheDocument();
  });

  it('never blocks the import when the comparison fails, and retries on request', async () => {
    stubFetch(() => jsonResponse({ success: false, error: 'REST is down.' }, false));
    await reachPreview();
    fireEvent.click(screen.getByRole('button', { name: 'Import →' }));

    await screen.findByTestId('import-changes-error');
    expect(screen.getByRole('button', { name: 'Continue to import' })).toBeEnabled();

    stubFetch(() => jsonResponse({ success: true, delta: NO_CHANGES }));
    fireEvent.click(screen.getByRole('button', { name: /Try again|Retry/ }));
    await screen.findByText('No changes from v2.4.0');
    // The retry asked again — one call from Preview, one from the step.
    expect(deltaCalls()).toHaveLength(2);

    fireEvent.click(screen.getByRole('button', { name: 'Continue to import' }));
    await waitFor(() => expect(startImport).toHaveBeenCalledTimes(1));
  });

  it('shows the Changes step for a dry run too', async () => {
    stubFetch(() => jsonResponse({ success: true, delta: DELTA }));
    await reachPreview('Select Refund (dry run)');
    fireEvent.click(screen.getByRole('button', { name: 'Import →' }));
    await screen.findByTestId('import-changes');
    fireEvent.click(screen.getByRole('button', { name: 'Continue to import' }));
    await waitFor(() =>
      expect(startImport).toHaveBeenCalledWith(expect.objectContaining({ options: expect.objectContaining({ dryRun: true }) })),
    );
  });

  it('goes Back from Changes to Preview', async () => {
    stubFetch(() => jsonResponse({ success: true, delta: DELTA }));
    await reachPreview();
    fireEvent.click(screen.getByRole('button', { name: 'Import →' }));
    await screen.findByTestId('import-changes');
    fireEvent.click(screen.getByRole('button', { name: '← Back' }));
    await screen.findByTestId('preview-panel');
  });
});

/* -------------------------------------------------------------------------
   5. The browser fixture
   ------------------------------------------------------------------------- */

describe('the browser fixture', () => {
  const OUT = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-import-wizard');

  beforeEach(() => {
    jest.clearAllMocks();
    analyzeSpecification.mockResolvedValue(GOOD_ANALYSIS);
  });

  it('renders the Changes step the browser spec mounts (and writes the fixture on request)', async () => {
    stubFetch(() => jsonResponse({ success: true, delta: DELTA }));
    await reachPreview();
    fireEvent.click(screen.getByRole('button', { name: 'Import →' }));
    await screen.findByTestId('import-changes');

    const html = (document.querySelector('.imp-wizard') as HTMLElement).outerHTML;
    expect(html).toContain('imp-changes__summary');
    if (process.env.IMPORT_WIZARD_FIXTURE_DUMP !== '1') return;
    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, 'changes.html'), html);
  });
});
