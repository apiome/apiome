/**
 * Auto-export on version publish, in Export studio and the inbox (MFX-39.4, #4336).
 *
 * The helpers (status tones, the subscription line), the inbox's `export_auto_halted` row (its own
 * sentence, its safe link), and the Presets tab's **Auto-export** panel against a mocked `fetch`: it lists
 * the projects that run the preset on publish with their recent runs, adds one with the halt rule, turns
 * one off, releases a halted run, and is read-only without `projects:edit`. The last block writes the docs
 * fixture on request.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

jest.mock('next/navigation', () => ({
  usePathname: () => '/ade/dashboard/export/studio',
  useSearchParams: () => new URLSearchParams('tab=presets'),
}));

import { liveMarkup } from './helpers/a11y-fixture-dump';
import { AutoExportPanel } from '@/app/components/ade/export-studio/presets/AutoExportPanel';
import { runTone, subscriptionSummary } from '@/app/components/ade/export-studio/presets/autoExportApi';
import type { ExportPreset } from '@/app/components/ade/export-studio/presets/exportPresetsModel';
import { notificationHref, notificationSentence, type NotificationRow } from '@lib/notifications';

const PRESET: ExportPreset = {
  id: 'x1', name: 'nightly-sync', description: null,
  targets: [{ target: 'openapi' }, { target: 'avro' }], deliveryProfileId: 'p1', deliveryProfileName: 'lake',
};
const SUB = { id: 's1', projectId: 'pr1', projectName: 'Orders API', presetId: 'x1', presetName: 'nightly-sync',
  haltAt: 'critical', approveLoss: false, active: true };
const RUNS = [
  { id: 'r2', projectId: 'pr1', projectName: 'Orders API', versionRecordId: 'v2', subscriptionId: 's1',
    presetName: 'nightly-sync', status: 'halted', lossSeverity: 'critical',
    lossReasons: ['avro: a severe conversion (12% preserved)'], deliveries: [], errorCode: null, errorMessage: null,
    releasedAt: null, createdAt: '2026-11-05T09:00:00Z' },
  { id: 'r1', projectId: 'pr1', projectName: 'Orders API', versionRecordId: 'v1', subscriptionId: 's1',
    presetName: 'nightly-sync', status: 'delivered', lossSeverity: 'warn', lossReasons: ['openapi-3.1: lossy (96% preserved)'],
    deliveries: [{ profileName: 'lake', outcome: 'delivered' }], errorCode: null, errorMessage: null, releasedAt: null,
    createdAt: '2026-11-04T09:00:00Z' },
];

let calls: { url: string; init?: RequestInit }[] = [];

function mockFetch() {
  global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    const json = (body: unknown, status = 200) =>
      ({ ok: status < 400, status, json: async () => body }) as unknown as Response;
    const path = String(url);
    if (path.startsWith('/api/projects')) {
      return json({ success: true, projects: [{ id: 'pr1', name: 'Orders API' }, { id: 'pr2', name: 'Payments API' }] });
    }
    if (path.startsWith('/api/export/auto-export-runs') && init?.method === 'POST') {
      return json({ success: true, data: { ...RUNS[0], status: 'delivered' } });
    }
    if (path.startsWith('/api/export/auto-export-runs')) return json({ success: true, data: { runs: RUNS } });
    if (path.startsWith('/api/export/auto-exports') && init?.method && init.method !== 'GET') {
      return json({ success: true, data: SUB });
    }
    if (path.startsWith('/api/export/auto-exports')) return json({ success: true, data: { subscriptions: [SUB] } });
    return json({ success: false, error: `unmocked ${path}` }, 500);
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  calls = [];
});

describe('helpers', () => {
  it('tones each status and summarises a subscription', () => {
    expect(runTone('delivered')).toBe('ok');
    expect(runTone('halted')).toBe('warn');
    expect(runTone('delivery_failed')).toBe('danger');
    expect(runTone('running')).toBe('neutral');
    expect(subscriptionSummary(SUB as never)).toBe('Halts at critical loss');
    expect(subscriptionSummary({ ...SUB, approveLoss: true, active: false } as never))
      .toBe('Delivers whatever the loss (pre-approved) · off');
  });
});

describe('the inbox row', () => {
  const row = (payload: Record<string, unknown>) =>
    ({ id: 'n1', type: 'export_auto_halted', payload, project_id: 'pr1', created_at: '', read_at: null } as unknown as NotificationRow);

  it('says what the sweep wrote and links to the Presets tab only', () => {
    expect(notificationSentence(row({ summary: "Auto-export 'nightly' of Orders API was not delivered" })))
      .toBe("Auto-export 'nightly' of Orders API was not delivered");
    expect(notificationSentence(row({}))).toBe('An auto-export was held back before delivery');
    expect(notificationHref(row({ link: '/ade/dashboard/export/studio?tab=presets' })))
      .toBe('/ade/dashboard/export/studio?tab=presets');
    expect(notificationHref(row({ link: 'https://evil.example.com' }))).toBeNull();
  });
});

describe('the Auto-export panel', () => {
  it('lists subscriptions with their recent runs', async () => {
    mockFetch();
    render(<AutoExportPanel scope={{ kind: 'preset', preset: PRESET }} canEdit />);
    const sub = await screen.findByTestId('auto-export-subscription');
    expect(within(sub).getByText('Orders API')).toBeInTheDocument();
    expect(within(sub).getByText('Halts at critical loss')).toBeInTheDocument();
    const runs = await within(sub).findAllByTestId('auto-export-run');
    expect(runs[0]).toHaveTextContent('Halted');
    expect(runs[0]).toHaveTextContent('avro: a severe conversion (12% preserved)');
    expect(runs[1]).toHaveTextContent('Delivered');
    expect(calls.some((c) => c.url === '/api/export/auto-export-runs?subscriptionId=s1&limit=10')).toBe(true);
    expect(calls.some((c) => c.url === '/api/export/auto-exports?preset=x1')).toBe(true);
  });

  it('adds a project with its halt rule, turns one off and releases a halted run', async () => {
    mockFetch();
    render(<AutoExportPanel scope={{ kind: 'preset', preset: PRESET }} canEdit />);
    await screen.findByTestId('auto-export-subscription');
    await screen.findByRole('option', { name: 'Payments API' });
    expect(screen.queryByRole('option', { name: 'Orders API' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Project'), { target: { value: 'pr2' } });
    fireEvent.change(screen.getByLabelText('Halt delivery at'), { target: { value: 'warn' } });
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByTestId('auto-export-add-button'));
    await waitFor(() => expect(calls.some((c) => c.init?.method === 'POST' && c.url === '/api/export/auto-exports')).toBe(true));
    const post = calls.find((c) => c.init?.method === 'POST' && c.url === '/api/export/auto-exports')!;
    expect(JSON.parse(String(post.init!.body))).toEqual({ projectId: 'pr2', preset: 'x1', haltAt: 'warn', approveLoss: true });

    fireEvent.click(await screen.findByRole('button', { name: 'Turn off' }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === 'PATCH')).toBe(true));
    expect(JSON.parse(String(calls.find((c) => c.init?.method === 'PATCH')!.init!.body))).toEqual({ active: false });

    fireEvent.click(await screen.findByRole('button', { name: 'Release' }));
    await waitFor(() => expect(calls.some((c) => c.url === '/api/export/auto-export-runs/r2/release')).toBe(true));
  });

  it('is read-only without projects:edit', async () => {
    mockFetch();
    render(<AutoExportPanel scope={{ kind: 'preset', preset: PRESET }} canEdit={false} />);
    await screen.findAllByTestId('auto-export-run');
    expect(screen.queryByRole('button', { name: 'Release' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Turn off' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('auto-export-add')).not.toBeInTheDocument();
  });
});

/**
 * The docs fixture (`apiome-docs/screens.json`: `export-studio-auto-export`), written into
 * `e2e/fixtures/hive-export-studio/` when `EXPORT_STUDIO_FIXTURE_DUMP=1`.
 */
describe('the docs fixture', () => {
  it('renders the Presets tab with the Auto-export panel open (fixtures)', async () => {
    mockFetch();
    const base = global.fetch as jest.Mock;
    global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
      const path = String(url);
      const json = (body: unknown) => ({ ok: true, status: 200, json: async () => body }) as unknown as Response;
      if (path.startsWith('/api/export/presets')) return json({ success: true, data: { presets: [PRESET] } });
      if (path.startsWith('/api/export/delivery-profiles')) return json({ success: true, data: { profiles: [] } });
      if (path.startsWith('/api/access/permissions/me')) {
        return json({ success: true, data: { is_admin: false, permissions: ['projects:edit'] } });
      }
      return base(url, init);
    }) as unknown as typeof fetch;
    const preview = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'all';
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const ExportPresetsClient = require('@/app/components/ade/export-studio/presets/ExportPresetsClient').default;
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const { ExportStudioTabs } = require('@/app/components/ade/export-studio/ExportStudioTabs.tsx');
      render(<ExportPresetsClient tabs={<ExportStudioTabs />} />);
      const card = await screen.findByTestId('xprs-preset');
      fireEvent.click(within(card).getByRole('button', { name: 'Auto-export' }));
      await screen.findAllByTestId('auto-export-run');
      await screen.findByRole('option', { name: 'Payments API' });
      const html = liveMarkup(document.querySelector('.page') as HTMLElement);
      expect(html).toContain('Auto-export on publish');
      if (process.env.EXPORT_STUDIO_FIXTURE_DUMP === '1') {
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const fs = require('node:fs') as typeof import('node:fs');
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const path = require('node:path') as typeof import('node:path');
        const out = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-export-studio');
        fs.mkdirSync(out, { recursive: true });
        fs.writeFileSync(path.join(out, 'auto-export.html'), `${html}\n`);
      }
    } finally {
      if (preview === undefined) delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
      else process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = preview;
    }
  });
});
