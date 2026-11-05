/**
 * Export studio's History tab — MFX-46.1 (#4379).
 *
 * The acceptance criteria at the screen level:
 *
 *  1. **Filterable history with per-run verdicts** — every run shows its source@version → target,
 *     outcome, preserved %, validation and lint verdicts, delivery decision and deliveries, actor and time;
 *     each filter re-asks the server and the pager pages.
 *  2. **Detail renders stored reports** — opening a run shows its deliveries and, per target, the stored
 *     fidelity findings, validation report and delivery gate, read-only.
 *  3. **Re-run pre-fills the Studio** — the drawer's link carries the run's source, version, target and
 *     options.
 *  4. Tenant scope is the server's: the screen only ever calls the workspace-scoped `/api/export/runs…`.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe, toHaveNoViolations } from 'jest-axe';

jest.mock('next/navigation', () => ({
  usePathname: () => '/ade/dashboard/export/studio',
  useSearchParams: () => new URLSearchParams('tab=history'),
}));

import ExportHistoryClient from '@/app/components/ade/export-studio/history/ExportHistoryClient';
import type {
  ExportRunDetail,
  ExportRunSummary,
} from '@/app/components/ade/export-studio/history/exportHistoryModel';
import { decodeStudioOptions } from '@/app/components/ade/dashboard/export/exportStudioUrlState';

expect.extend(toHaveNoViolations);

const LOSSY: ExportRunSummary = {
  job_id: 'job-1',
  artifact_id: 'proj-1',
  artifact_name: 'Petstore',
  version_record_id: 'rev-1',
  version_label: '1.4.0',
  target: 'protobuf',
  actor_id: 'u1',
  actor_label: 'ada@example.com',
  state: 'completed',
  dry_run: false,
  preserved_percent: 64,
  fidelity_tier: 'lossy',
  validation_verdict: 'valid',
  lint_verdict: 'warn',
  delivery_decision: 'allow_with_warning',
  error_code: null,
  error_message: null,
  options: { package: 'acme.v1' },
  deliveries: [
    { channel: 'git', status: 'opened', outcome: 'delivered', destination: 'acme/specs' },
    { channel: 'webhook', status: 'failed', outcome: 'failed', destination: 'https://hooks.example.com/x', error_code: 'export-webhook-http-500' },
  ],
  created_at: '2026-11-05T09:00:00Z',
  finished_at: '2026-11-05T09:01:00Z',
};

const FAILED: ExportRunSummary = {
  ...LOSSY,
  job_id: 'job-2',
  artifact_id: 'cat-9',
  artifact_name: 'Orders',
  version_record_id: null,
  version_label: '2.0.0',
  target: 'graphql',
  actor_id: 'u2',
  actor_label: 'grace@example.com',
  state: 'failed',
  preserved_percent: null,
  fidelity_tier: null,
  validation_verdict: null,
  lint_verdict: null,
  delivery_decision: null,
  error_code: 'SOURCE_LOAD_FAILED',
  error_message: 'No such revision',
  options: null,
  deliveries: [],
};

const DETAIL: ExportRunDetail = {
  ...LOSSY,
  reports: [
    {
      target: 'protobuf',
      fidelity: {
        summary: { tier: 'lossy', preserved_percent: 64 },
        report: {
          items: [
            { construct: 'Pet.id', kind: 'synth', severity: 'warn', message: 'A field number is synthesized.' },
            { construct: 'Pet.tags', kind: 'drop', severity: 'critical', message: 'proto3 has no union.' },
            { construct: 'Pet', kind: 'ok', severity: 'info', message: 'carried' },
          ],
        },
      },
      validation: {
        verdict: 'valid',
        target_format: 'protobuf',
        validator: 'buf',
        findings: [],
        valid: true,
        validated: true,
      },
      delivery_gate: {
        decision: 'allow_with_warning',
        blocks_delivery: false,
        warns: true,
        headline: 'Delivered with a warning',
        message: 'The source carries lint warnings.',
        reasons: [{ code: 'DELIVERY_SOURCE_ERRORS_OPEN', dimension: 'lint', severity: 'warning', message: 'Lint warnings are open.' }],
        target: 'protobuf',
      },
    },
  ],
};

let calls: string[] = [];

function mockFetch(options: { runs?: ExportRunSummary[]; total?: number; fail?: boolean } = {}) {
  global.fetch = jest.fn(async (url: string) => {
    const path = String(url);
    calls.push(path);
    const json = (body: unknown, status = 200) =>
      ({ ok: status < 400, status, json: async () => body }) as unknown as Response;
    if (path === '/api/export/runs/actors') {
      return json({ success: true, data: { actors: [{ actor_id: 'u1', actor_label: 'ada@example.com' }] } });
    }
    if (path.startsWith('/api/export/runs/')) {
      return json({ success: true, data: DETAIL });
    }
    if (path.startsWith('/api/export/runs?')) {
      if (options.fail) return json({ success: false, error: 'projects:view is required' }, 403);
      const runs = options.runs ?? [LOSSY, FAILED];
      return json({ success: true, data: { runs, total: options.total ?? runs.length, limit: 25, offset: 0 } });
    }
    return json({ success: false, error: `unmocked ${path}` }, 500);
  }) as unknown as typeof fetch;
}

const runQueries = () =>
  calls.filter((c) => c.startsWith('/api/export/runs?')).map((c) => Object.fromEntries(new URLSearchParams(c.split('?')[1])));

beforeEach(() => {
  calls = [];
});

async function renderHistory() {
  const utils = render(<ExportHistoryClient />);
  await screen.findByText('Petstore @ 1.4.0');
  return utils;
}

// ---------------------------------------------------------------------------
// 1. Rows and filters
// ---------------------------------------------------------------------------

describe('History tab', () => {
  it('lists every run with its verdicts, deliveries, actor and time', async () => {
    mockFetch();
    await renderHistory();
    const row = screen.getByText('Petstore @ 1.4.0').closest('tr')!;
    expect(within(row).getByText('→ protobuf')).toBeInTheDocument();
    expect(within(row).getByTestId('export-history-state')).toHaveTextContent('Completed');
    expect(within(row).getByTestId('export-history-preserved')).toHaveTextContent('64%');
    expect(within(row).getByText('Valid')).toBeInTheDocument();
    expect(within(row).getByText('Warnings')).toBeInTheDocument();
    expect(within(row).getByText('Allowed with warnings')).toBeInTheDocument();
    expect(within(row).getByTestId('export-history-deliveries')).toHaveTextContent('Git delivered · Webhook failed');
    expect(within(row).getByText('ada@example.com')).toBeInTheDocument();

    const failed = screen.getByText('Orders @ 2.0.0').closest('tr')!;
    expect(within(failed).getByTestId('export-history-state')).toHaveTextContent('Failed');
    expect(within(failed).getByTestId('export-history-deliveries')).toHaveTextContent('Not delivered');
    expect(screen.getByTestId('export-history-range')).toHaveTextContent('1–2 of 2 runs');
  });

  it('asks the server again for every filter, from the first page', async () => {
    mockFetch();
    await renderHistory();
    expect(runQueries()[0]).toEqual({ limit: '25', offset: '0' });

    fireEvent.change(screen.getByTestId('export-history-filter-target'), { target: { value: 'protobuf' } });
    await waitFor(() => expect(runQueries().at(-1)).toMatchObject({ target: 'protobuf', offset: '0' }));
    fireEvent.change(screen.getByTestId('export-history-filter-actor'), { target: { value: 'u1' } });
    fireEvent.change(screen.getByTestId('export-history-filter-channel'), { target: { value: 'none' } });
    fireEvent.change(screen.getByTestId('export-history-filter-validation'), { target: { value: 'invalid' } });
    fireEvent.change(screen.getByTestId('export-history-filter-decision'), { target: { value: 'block' } });
    fireEvent.change(screen.getByTestId('export-history-filter-state'), { target: { value: 'failed' } });
    fireEvent.change(screen.getByTestId('export-history-filter-artifact'), { target: { value: 'cat-9' } });
    fireEvent.change(screen.getByTestId('export-history-filter-from'), { target: { value: '2026-11-01' } });
    await waitFor(() =>
      expect(runQueries().at(-1)).toEqual({
        target: 'protobuf',
        actor: 'u1',
        channel: 'none',
        validation: 'invalid',
        decision: 'block',
        state: 'failed',
        artifact: 'cat-9',
        finished_after: '2026-11-01T00:00:00Z',
        limit: '25',
        offset: '0',
      }),
    );

    fireEvent.click(screen.getByTestId('export-history-clear'));
    await waitFor(() => expect(runQueries().at(-1)).toEqual({ limit: '25', offset: '0' }));
  });

  it('offers the people in the history, and the sources and targets it has seen', async () => {
    mockFetch();
    await renderHistory();
    await waitFor(() =>
      expect(within(screen.getByTestId('export-history-filter-actor')).getByText('ada@example.com')).toBeInTheDocument(),
    );
    const sources = within(screen.getByTestId('export-history-filter-artifact')).getAllByRole('option');
    expect(sources.map((o) => o.textContent)).toEqual(['Source: any', 'Petstore', 'Orders']);
    const targets = within(screen.getByTestId('export-history-filter-target')).getAllByRole('option');
    expect(targets.map((o) => o.textContent)).toEqual(['Target: any', 'graphql', 'protobuf']);
  });

  it('pages through a long history', async () => {
    mockFetch({ total: 60 });
    await renderHistory();
    fireEvent.click(screen.getByRole('button', { name: /next/i }));
    await waitFor(() => expect(runQueries().at(-1)).toMatchObject({ offset: '25' }));
  });

  it('says so when nothing matches, and when the history cannot load', async () => {
    mockFetch({ runs: [] });
    const { unmount } = render(<ExportHistoryClient />);
    expect(await screen.findByText('No exports yet')).toBeInTheDocument();
    unmount();
    mockFetch({ fail: true });
    render(<ExportHistoryClient />);
    expect(await screen.findByText('The export history could not be loaded')).toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // 2–3. The detail and the re-run
  // ---------------------------------------------------------------------------

  it('opens a run read-only with its deliveries and stored reports', async () => {
    mockFetch();
    await renderHistory();
    fireEvent.click(screen.getByText('Petstore @ 1.4.0'));
    const drawer = await screen.findByTestId('export-history-detail');
    await within(drawer).findByTestId('export-history-target-report');
    expect(calls).toContain('/api/export/runs/job-1');

    const deliveries = within(drawer).getByTestId('export-history-detail-deliveries');
    expect(deliveries).toHaveTextContent('Git · opened');
    expect(deliveries).toHaveTextContent('acme/specs');
    expect(deliveries).toHaveTextContent('Webhook · failed');
    expect(deliveries).toHaveTextContent('export-webhook-http-500');

    const report = within(drawer).getByTestId('export-history-target-report');
    expect(report).toHaveTextContent('lossy · 64% preserved · 2 findings beyond OK');
    expect(report).toHaveTextContent('Pet.tags');
    expect(report).toHaveTextContent('A field number is synthesized.');
    expect(report).not.toHaveTextContent('carried');
    expect(report).toHaveTextContent('The source carries lint warnings.');
  });

  it('re-runs in the Studio with the source, version, target and options pre-filled', async () => {
    mockFetch();
    await renderHistory();
    fireEvent.click(screen.getByText('Petstore @ 1.4.0'));
    const link = await screen.findByTestId('export-history-rerun');
    const href = link.getAttribute('href')!;
    const query = new URLSearchParams(href.split('?')[1]);
    expect(href.startsWith('/ade/dashboard/export/studio?')).toBe(true);
    expect([query.get('artifact'), query.get('version'), query.get('target'), query.get('step')]).toEqual([
      'proj-1',
      'rev-1',
      'protobuf',
      'options',
    ]);
    expect(decodeStudioOptions(query.get('opts'))).toEqual({ package: 'acme.v1' });
  });

  it('shows why a failed run failed', async () => {
    mockFetch();
    await renderHistory();
    fireEvent.click(screen.getByText('Orders @ 2.0.0'));
    const drawer = await screen.findByTestId('export-history-detail');
    expect(within(drawer).getByTestId('export-history-error')).toHaveTextContent('SOURCE_LOAD_FAILED No such revision');
  });

  it('is axe-clean', async () => {
    mockFetch();
    const { container } = await renderHistory();
    await act(async () => {});
    expect(await axe(container)).toHaveNoViolations();
  });
});

/**
 * The docs fixtures (`apiome-docs/screens.json`: `export-studio-history`, `export-studio-history-run`).
 * Written into `e2e/fixtures/hive-export-studio/` when `EXPORT_STUDIO_FIXTURE_DUMP=1`.
 */
describe('the docs fixtures', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const fs = require('node:fs') as typeof import('node:fs');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const path = require('node:path') as typeof import('node:path');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { liveMarkup } = require('./helpers/a11y-fixture-dump') as typeof import('./helpers/a11y-fixture-dump');
  const OUT = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-export-studio');
  const write = (name: string, html: string) => {
    expect(html.length).toBeGreaterThan(0);
    if (process.env.EXPORT_STUDIO_FIXTURE_DUMP !== '1') return;
    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, `${name}.html`), `${html}\n`);
  };

  it('writes the history and an opened run', async () => {
    mockFetch();
    const preview = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'all';
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const { ExportStudioTabs } = require('@/app/components/ade/export-studio/ExportStudioTabs.tsx');
      render(<ExportHistoryClient tabs={<ExportStudioTabs />} />);
      await screen.findByText('Petstore @ 1.4.0');
      await waitFor(() =>
        expect(within(screen.getByTestId('export-history-filter-actor')).getByText('ada@example.com')).toBeInTheDocument(),
      );
      const page = document.querySelector('.page') as HTMLElement;
      write('history', liveMarkup(page));

      fireEvent.click(screen.getByText('Petstore @ 1.4.0'));
      const drawer = await screen.findByTestId('export-history-detail');
      await within(drawer).findByTestId('export-history-target-report');
      write('history-run', `${liveMarkup(page)}${liveMarkup(drawer)}`);
    } finally {
      process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = preview;
    }
  });
});
