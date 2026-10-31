/**
 * Several targets and several items in one export job (E1-3, #6219).
 *
 * Pins:
 *  1. the shared job helpers — request bodies and the outcome rows a result reads as;
 *  2. `MultiExportRun` — Verify runs a dry run, Generate runs the job and offers **Download .zip**,
 *     a batch's failed items are listed, a failed job shows its error;
 *  3. the Studio's **Several targets** mode — 2+ ticked targets, Options skipped, Verify gates
 *     Continue;
 *  4. the Catalog bulk bar's **Export…** dialog — one target, one batch job over every item.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';
import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';

jest.mock('@monaco-editor/react', () => ({ __esModule: true, default: () => null }));
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={typeof href === 'string' ? href : '#'}>{children}</a>
  ),
}));
jest.mock('sonner', () => ({
  __esModule: true,
  toast: Object.assign(jest.fn(), { success: jest.fn(), error: jest.fn() }),
}));

import { ExportStudio } from '../src/app/components/ade/dashboard/export/ExportStudio';
import { MultiExportRun } from '../src/app/components/ade/dashboard/export/MultiExportRun';
import { CatalogBulkExportDialog } from '../src/app/components/ade/catalog/CatalogBulkExportDialog';
import { __resetExportJobTrackerForTests } from '../src/app/components/ade/dashboard/export/exportJobTracker';
import {
  exportOutcomeRows,
  itemsBatchJobBody,
  multiTargetJobBody,
  type MultiExportResult,
} from '../src/app/components/ade/dashboard/export/exportBatchJob';
import type { ExportTargetsResponse } from '../src/app/components/ade/dashboard/export/exportTargetCatalog';
import type { CatalogItem } from '../src/app/components/ade/catalog/catalogModel';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';
import { tabTo } from './helpers/keyboard';

const AXE_OPTIONS = { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } } as const;

function target(key: string, label: string, tier: 'lossless' | 'lossy' = 'lossless') {
  return {
    descriptor: {
      key,
      format: key,
      label,
      description: `${label} export.`,
      icon: 'file-json',
      paradigm: 'rest',
      multi_file: false,
      needs_toolchain: false,
      available: true,
      unavailable_reason: null,
    },
    capability_profile: {},
    options_schema: {},
    default_options: {},
    fidelity: {
      tier,
      preserved_percent: tier === 'lossless' ? 100 : 70,
      total: 10,
      preserved: tier === 'lossless' ? 10 : 7,
      dropped: 0,
      approximated: 0,
      synthesized: 0,
    },
  };
}

const TARGETS = {
  artifact: 'proj-1',
  version: null,
  version_record_id: 'rev-1',
  version_label: '1.0.0',
  targets: [target('openapi', 'OpenAPI 3.1'), target('graphql', 'GraphQL SDL', 'lossy')],
} as unknown as ExportTargetsResponse;

const MULTI_TARGET_RESULT: MultiExportResult = {
  artifact: 'proj-1',
  version_label: '1.0.0',
  download_path: '/v1/export/acme/jobs/job-1/download',
  fidelity_rollup: { tier: 'lossy', min_preserved_percent: 70, target_count: 2 },
  targets: [
    { target: 'openapi', fidelity: { summary: { tier: 'lossless', preserved_percent: 100 } } },
    { target: 'graphql', fidelity: { summary: { tier: 'lossy', preserved_percent: 70 } } },
  ],
};

const BATCH_RESULT: MultiExportResult = {
  artifact: '2 items',
  download_path: '/v1/export/acme/jobs/job-1/download',
  batch: {
    item_count: 2,
    completed_count: 1,
    failed_count: 1,
    items: [
      { artifact: 'item-a', version: 'latest', version_label: '2.0.0', target: 'openapi', state: 'completed', tier: 'lossless', preserved_percent: 100 },
      { artifact: 'item-b', version: 'latest', target: 'openapi', state: 'failed', error: { message: 'Artifact not found.' } },
    ],
  },
};

type Call = { url: string; body: Record<string, unknown> | null };

/** A fake BFF: targets, job submit, one poll answering `status`, and the archive download. */
function installFetch(status: Record<string, unknown>): Call[] {
  const calls: Call[] = [];
  global.fetch = jest.fn((input: unknown, init?: { method?: string; body?: string }) => {
    const url = String(input);
    calls.push({ url, body: init?.body ? JSON.parse(init.body) : null });
    const json = (payload: unknown, ok = true) =>
      Promise.resolve({ ok, headers: new Headers(), json: () => Promise.resolve(payload) });
    if (url.includes('/api/export/targets')) return json({ success: true, ...TARGETS });
    if (url === '/api/export/jobs' && init?.method === 'POST') return json({ success: true, job_id: 'job-1' });
    if (url.endsWith('/download')) {
      return Promise.resolve({
        ok: true,
        headers: new Headers({ 'content-disposition': 'attachment; filename="export-batch.zip"' }),
        blob: () => Promise.resolve(new Blob(['PK'])),
      });
    }
    if (url.includes('/api/export/jobs/job-1')) return json({ success: true, job_id: 'job-1', percent: 100, events: [], ...status });
    return json({ success: false }, false);
  }) as unknown as typeof fetch;
  return calls;
}

beforeEach(() => {
  __resetExportJobTrackerForTests();
  window.sessionStorage.clear();
  delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
  URL.createObjectURL = jest.fn(() => 'blob:x') as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = jest.fn() as unknown as typeof URL.revokeObjectURL;
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('job helpers', () => {
  it('builds a multi-target body with each target on its defaults', () => {
    expect(multiTargetJobBody('proj-1', 'rev-1', ['openapi', 'graphql', 'openapi'], true)).toEqual({
      artifact: 'proj-1',
      version: 'rev-1',
      targets: [{ target: 'openapi' }, { target: 'graphql' }],
      dry_run: true,
    });
    expect(multiTargetJobBody('proj-1', null, ['openapi'])).toEqual({ artifact: 'proj-1', targets: [{ target: 'openapi' }] });
  });

  it('builds an items batch body at each item’s latest version', () => {
    expect(itemsBatchJobBody(['a', 'b', 'a'], 'openapi')).toEqual({
      items: [{ artifact: 'a' }, { artifact: 'b' }],
      targets: [{ target: 'openapi' }],
    });
  });

  it('reads a multi-target result as one completed row per target', () => {
    expect(exportOutcomeRows(MULTI_TARGET_RESULT).map((r) => [r.target, r.state, r.tier, r.preservedPercent])).toEqual([
      ['openapi', 'completed', 'lossless', 100],
      ['graphql', 'completed', 'lossy', 70],
    ]);
  });

  it('reads a batch result as one row per item, failures with their message', () => {
    const rows = exportOutcomeRows(BATCH_RESULT);
    expect(rows.map((r) => [r.artifact, r.version, r.state, r.error])).toEqual([
      ['item-a', '2.0.0', 'completed', null],
      ['item-b', 'latest', 'failed', 'Artifact not found.'],
    ]);
    expect(exportOutcomeRows(null)).toEqual([]);
  });
});

describe('MultiExportRun', () => {
  it('Verify runs a dry run and reports every target’s fidelity', async () => {
    const calls = installFetch({ state: 'completed', result: { ...MULTI_TARGET_RESULT, dry_run: true } });
    const onSettled = jest.fn();
    render(
      <MultiExportRun
        mode="verify"
        body={multiTargetJobBody('proj-1', null, ['openapi', 'graphql'])}
        labels={{ openapi: 'OpenAPI 3.1' }}
        archiveName="x.zip"
        onSettled={onSettled}
        pollIntervalMs={1}
      />,
    );
    fireEvent.click(screen.getByTestId('multi-export-verify-start'));
    await waitFor(() => expect(onSettled).toHaveBeenCalled());
    expect(calls.find((c) => c.url === '/api/export/jobs')?.body).toMatchObject({ dry_run: true });
    const table = screen.getByTestId('multi-export-outcomes');
    expect(within(table).getByText('OpenAPI 3.1')).toBeInTheDocument();
    expect(screen.getByTestId('multi-export-summary')).toHaveTextContent('2 of 2 completed — fidelity measured');
    expect(screen.getByTestId('multi-export-summary')).toHaveTextContent('Lowest fidelity: lossy, 70% preserved');
    expect(screen.queryByTestId('multi-export-download')).toBeNull();
  });

  it('Generate lists failed items and downloads the archive', async () => {
    const calls = installFetch({ state: 'completed', result: BATCH_RESULT });
    const { container } = render(
      <MultiExportRun
        mode="generate"
        body={itemsBatchJobBody(['item-a', 'item-b'], 'openapi')}
        labels={{ 'item-a': 'Orders API' }}
        showItem
        archiveName="export-batch.zip"
        pollIntervalMs={1}
      />,
    );
    fireEvent.click(screen.getByTestId('multi-export-generate-start'));
    await screen.findByTestId('multi-export-download');
    expect(calls.find((c) => c.url === '/api/export/jobs')?.body).not.toHaveProperty('dry_run');
    expect(screen.getByText('Orders API')).toBeInTheDocument();
    expect(screen.getByText('Artifact not found.')).toBeInTheDocument();
    expect(screen.getByTestId('multi-export-summary')).toHaveTextContent('1 of 2 completed, 1 failed');
    expect(await axe(container, AXE_OPTIONS)).toHaveNoViolations();

    fireEvent.click(screen.getByTestId('multi-export-download'));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/download'))).toBe(true));
    expect(URL.createObjectURL).toHaveBeenCalled();
  });

  it('shows the error of a job that failed outright', async () => {
    installFetch({ state: 'failed', result: null, error: { code: 'EXPORT_BATCH_FAILED', message: 'Every item failed.' } });
    render(
      <MultiExportRun mode="generate" body={itemsBatchJobBody(['a'], 'openapi')} archiveName="x.zip" pollIntervalMs={1} />,
    );
    fireEvent.click(screen.getByTestId('multi-export-generate-start'));
    expect(await screen.findByTestId('multi-export-error')).toHaveTextContent('Every item failed');
    expect(screen.queryByTestId('multi-export-download')).toBeNull();
  });
});

describe('Export studio — Several targets', () => {
  it('takes 2+ targets, skips Options and gates Continue on the combined Verify', async () => {
    const calls = installFetch({ state: 'completed', result: { ...MULTI_TARGET_RESULT, dry_run: true } });
    render(<ExportStudio artifact="proj-1" artifactLabel="Pets API" version="rev-1" />);
    await waitFor(() => expect(screen.getByText(/export targets available/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /Choose target/ }));

    fireEvent.click(within(screen.getByTestId('export-studio-multi-toggle')).getByRole('checkbox'));
    const continueButton = screen.getByRole('button', { name: 'Continue' });
    fireEvent.click(within(screen.getByTestId('export-studio-multi-target-openapi')).getByRole('checkbox'));
    expect(continueButton).toBeDisabled();
    fireEvent.click(within(screen.getByTestId('export-studio-multi-target-graphql')).getByRole('checkbox'));
    expect(continueButton).toBeEnabled();

    fireEvent.click(continueButton);
    // Options is skipped: the next step is Overlays (GVM-4.2), then Verify.
    expect(screen.getByTestId('export-studio-overlays')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(screen.getByTestId('multi-export-verify')).toBeInTheDocument();
    const toReview = screen.getByRole('button', { name: 'Continue to review' });
    expect(toReview).toBeDisabled();
    fireEvent.click(screen.getByTestId('multi-export-verify-start'));
    await waitFor(() => expect(toReview).toBeEnabled());
    expect(calls.find((c) => c.url === '/api/export/jobs')?.body).toEqual({
      artifact: 'proj-1',
      version: 'rev-1',
      targets: [{ target: 'openapi' }, { target: 'graphql' }],
      dry_run: true,
    });

    fireEvent.click(toReview);
    expect(screen.getByTestId('multi-export-generate')).toBeInTheDocument();
    expect(screen.queryByTestId('export-studio-generate')).toBeNull();

    // Back from Verify passes Overlays and returns to Target, not Options.
    fireEvent.click(screen.getByRole('button', { name: 'Back' })); // → verify
    fireEvent.click(screen.getByRole('button', { name: 'Back' })); // → overlays
    expect(screen.getByTestId('export-studio-overlays')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Back' })); // → target
    expect(screen.getByTestId('export-studio-multi-targets')).toBeInTheDocument();
  });
});

describe('Catalog bulk Export…', () => {
  const ITEMS = [
    { id: 'item-a', name: 'Orders API' },
    { id: 'item-b', name: 'Pets API' },
  ] as unknown as CatalogItem[];

  it('runs one batch job over every item to the picked target', async () => {
    const calls = installFetch({ state: 'completed', result: BATCH_RESULT });
    render(<CatalogBulkExportDialog open items={ITEMS} onOpenChange={() => undefined} />);
    expect(screen.getByRole('heading', { name: 'Export 2 catalog items' })).toBeInTheDocument();
    expect(screen.queryByTestId('multi-export-generate')).toBeNull();

    fireEvent.click(await screen.findByLabelText('OpenAPI 3.1'));
    fireEvent.click(screen.getByTestId('multi-export-generate-start'));
    await screen.findByTestId('multi-export-download');
    expect(calls.find((c) => c.url === '/api/export/jobs')?.body).toEqual({
      items: [{ artifact: 'item-a' }, { artifact: 'item-b' }],
      targets: [{ target: 'openapi' }],
    });
    expect(within(screen.getByTestId('multi-export-outcomes')).getByText('Orders API')).toBeInTheDocument();
    expect(screen.getByText('Artifact not found.')).toBeInTheDocument();
  });
});

// --- keyboard-only and the a11y gate (X3, #6224) -------------------------------------------------

describe('several targets and bulk export with the keyboard alone (X3)', () => {
  const ITEMS = [
    { id: 'item-a', name: 'Orders API' },
    { id: 'item-b', name: 'Pets API' },
  ] as unknown as CatalogItem[];

  /**
   * The Catalog's bulk bar in miniature: a trigger that opens the dialog, as `CatalogClient` does
   * (controlled `open`, no `Dialog.Trigger`), so the focus restore under test is the dialog's own.
   */
  function BulkBar() {
    const [open, setOpen] = React.useState(false);
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          Export 2…
        </button>
        <CatalogBulkExportDialog open={open} items={ITEMS} onOpenChange={setOpen} />
      </>
    );
  }

  it('runs a several-targets export from the Studio without a pointer', async () => {
    installFetch({ state: 'completed', result: { ...MULTI_TARGET_RESULT, dry_run: true } });
    const user = userEvent.setup();
    render(<ExportStudio artifact="proj-1" artifactLabel="Pets API" version="rev-1" />);
    await waitFor(() => expect(screen.getByText(/export targets available/)).toBeInTheDocument());
    await tabTo(user, screen.getByRole('button', { name: /Choose target/ }));
    await user.keyboard('{Enter}');

    await tabTo(user, within(screen.getByTestId('export-studio-multi-toggle')).getByRole('checkbox'));
    await user.keyboard(' ');
    for (const key of ['openapi', 'graphql']) {
      await tabTo(user, within(screen.getByTestId(`export-studio-multi-target-${key}`)).getByRole('checkbox'));
      await user.keyboard(' ');
    }
    await tabTo(user, screen.getByRole('button', { name: 'Continue' }));
    await user.keyboard('{Enter}');
    // Overlays (GVM-4.2) → Verify.
    await tabTo(user, screen.getByRole('button', { name: 'Continue' }));
    await user.keyboard('{Enter}');

    await tabTo(user, screen.getByTestId('multi-export-verify-start'));
    await user.keyboard('{Enter}');
    const toReview = screen.getByRole('button', { name: 'Continue to review' });
    await waitFor(() => expect(toReview).toBeEnabled());
    await tabTo(user, toReview);
    await user.keyboard('{Enter}');
    expect(screen.getByTestId('multi-export-generate')).toBeInTheDocument();
  });

  it('opens the bulk dialog, exports and downloads, and gives focus back on Escape', async () => {
    const calls = installFetch({ state: 'completed', result: BATCH_RESULT });
    // The archive is handed to a download link; jsdom cannot follow it.
    jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined);
    const user = userEvent.setup();
    render(<BulkBar />);
    const trigger = screen.getByRole('button', { name: 'Export 2…' });

    await tabTo(user, trigger);
    await user.keyboard('{Enter}');
    const dialog = await screen.findByRole('dialog', { name: 'Export 2 catalog items' });
    expect(dialog.contains(document.activeElement)).toBe(true);

    await tabTo(user, await screen.findByLabelText('OpenAPI 3.1'));
    await user.keyboard(' ');
    expect(screen.getByLabelText('OpenAPI 3.1')).toBeChecked();
    await tabTo(user, screen.getByTestId('multi-export-generate-start'));
    await user.keyboard('{Enter}');
    await tabTo(user, await screen.findByTestId('multi-export-download'));
    await user.keyboard('{Enter}');
    await waitFor(() => expect(calls.some((c) => c.url.endsWith('/download'))).toBe(true));

    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(trigger).toHaveFocus();
  });

  it('gives focus back to the trigger when Close is pressed', async () => {
    installFetch({ state: 'completed', result: BATCH_RESULT });
    const user = userEvent.setup();
    render(<BulkBar />);
    const trigger = screen.getByRole('button', { name: 'Export 2…' });
    await tabTo(user, trigger);
    await user.keyboard('{Enter}');
    await screen.findByRole('dialog');

    await tabTo(user, screen.getByTestId('catalog-bulk-export-close'));
    await user.keyboard('{Enter}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(trigger).toHaveFocus();
  });

  it('keeps Tab inside the open dialog', async () => {
    installFetch({ state: 'completed', result: BATCH_RESULT });
    const user = userEvent.setup();
    render(<BulkBar />);
    await tabTo(user, screen.getByRole('button', { name: 'Export 2…' }));
    await user.keyboard('{Enter}');
    const dialog = await screen.findByRole('dialog');
    await screen.findByLabelText('OpenAPI 3.1');
    for (let press = 0; press < 12; press += 1) {
      await user.tab({ shift: press % 3 === 2 });
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });

  /**
   * The browser fixture for the axe gate (`e2e/a11y/routes.ts`, entry `export-e1`): the dialog
   * with a target picked, before Generate — `bulk-export.html` (the docs fixture) is the dialog
   * after a run. Written into `e2e/fixtures/hive-a11y/` when `A11Y_FIXTURE_DUMP=1`:
   *
   *     A11Y_FIXTURE_DUMP=1 npx jest tests/export-multi.test.tsx -t "a11y gate"
   */
  it('dumps the bulk dialog with a target picked for the a11y gate', async () => {
    installFetch({ state: 'completed', result: BATCH_RESULT });
    render(<CatalogBulkExportDialog open items={ITEMS} onOpenChange={() => undefined} />);
    fireEvent.click(await screen.findByLabelText('OpenAPI 3.1'));
    await screen.findByTestId('multi-export-generate-start');
    expect(await axe(screen.getByTestId('catalog-bulk-export-dialog'), AXE_OPTIONS)).toHaveNoViolations();
    writeA11yFixture('export-bulk-pick', liveMarkup(screen.getByTestId('catalog-bulk-export-dialog')));
  });
});
