/**
 * Export studio → Presets tab, Apply a preset and Save as preset, rendered (MFX-39.3, #4335).
 *
 * Against a mocked `fetch`: the tab lists presets with their targets, delivery and CLI line, edits one
 * (the PATCH body, every problem the server listed), deletes after a confirmation and is read-only
 * without `projects:edit`; the picker applies a preset; Save as preset sends the studio's targets and the
 * ticked delivery profile. The last block writes the docs fixtures on request.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

jest.mock('next/navigation', () => ({
  usePathname: () => '/ade/dashboard/export/studio',
  useSearchParams: () => new URLSearchParams('tab=presets'),
}));

import { liveMarkup } from './helpers/a11y-fixture-dump';
import ExportPresetsClient from '@/app/components/ade/export-studio/presets/ExportPresetsClient';
import { ExportPresetPicker, SavePresetForm } from '@/app/components/ade/export-studio/presets/ExportPresetControls';
import type { ExportPreset } from '@/app/components/ade/export-studio/presets/exportPresetsModel';

const NIGHTLY: ExportPreset = {
  id: 'x1', name: 'nightly-sync', description: 'Every night, for the data lake',
  targets: [{ target: 'openapi', options: { openapi_version: '3.0' } }, { target: 'protobuf', options: null }],
  deliveryProfileId: 'p1', deliveryProfileName: 'lake',
};
const RELEASE: ExportPreset = {
  id: 'x2', name: 'release-graphql', description: null, targets: [{ target: 'graphql', options: null }],
  deliveryProfileId: null, deliveryProfileName: null,
};

let calls: { url: string; init?: RequestInit }[] = [];

function mockFetch(options: { presets?: ExportPreset[]; canEdit?: boolean; refuse?: { error: string; errors: string[] } } = {}) {
  global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    const json = (body: unknown, status = 200) =>
      ({ ok: status < 400, status, json: async () => body }) as unknown as Response;
    const path = String(url);
    if (path.startsWith('/api/access/permissions/me')) {
      return json({ success: true, data: { is_admin: false, permissions: options.canEdit === false ? ['projects:view'] : ['projects:edit'] } });
    }
    if (path.startsWith('/api/export/delivery-profiles')) {
      return json({ success: true, data: { profiles: [{ id: 'p1', name: 'lake', channel: 'object_storage', destination: {}, credentialRef: { kind: 'storage_credential', id: 'c1' } }] } });
    }
    if (path.startsWith('/api/export/presets') && init?.method && init.method !== 'GET') {
      if (options.refuse) return json({ success: false, ...options.refuse }, 400);
      if (init.method === 'DELETE') return json({ success: true, data: null });
      return json({ success: true, data: { ...NIGHTLY, ...JSON.parse(String(init.body)) } }, init.method === 'POST' ? 201 : 200);
    }
    if (path.startsWith('/api/export/presets')) {
      return json({ success: true, data: { presets: options.presets ?? [NIGHTLY, RELEASE] } });
    }
    return json({ success: false, error: `unmocked ${path}` }, 500);
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  calls = [];
});

describe('Presets tab', () => {
  it('lists presets with their targets, delivery and CLI line', async () => {
    mockFetch();
    render(<ExportPresetsClient />);
    const [nightly] = await screen.findAllByTestId('xprs-preset');
    expect(within(nightly).getByText('nightly-sync')).toBeInTheDocument();
    expect(within(nightly).getByText('openapi (openapi_version=3.0), protobuf')).toBeInTheDocument();
    expect(within(nightly).getByText(/Delivered with lake/)).toBeInTheDocument();
    expect(within(nightly).getByText('apiome export --preset nightly-sync ARTIFACT --out PATH')).toBeInTheDocument();
  });

  it('edits a preset and sends the whole PATCH body', async () => {
    mockFetch();
    render(<ExportPresetsClient />);
    const [nightly] = await screen.findAllByTestId('xprs-preset');
    await waitFor(() => expect(within(nightly).getByRole('button', { name: 'Edit' })).toBeInTheDocument());
    fireEvent.click(within(nightly).getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Options (JSON)', { selector: '#xprs-options-1' }), { target: { value: '{"package": "acme.v1"}' } });
    fireEvent.change(screen.getByLabelText('Delivery profile'), { target: { value: '' } });
    fireEvent.click(screen.getByTestId('xprs-save'));
    await waitFor(() => expect(calls.some((c) => c.init?.method === 'PATCH')).toBe(true));
    const patch = calls.find((c) => c.init?.method === 'PATCH')!;
    expect(patch.url).toBe('/api/export/presets/x1');
    expect(JSON.parse(String(patch.init!.body))).toEqual({
      name: 'nightly-sync', description: 'Every night, for the data lake', deliveryProfileId: null,
      targets: [{ target: 'openapi', options: { openapi_version: '3.0' } }, { target: 'protobuf', options: { package: 'acme.v1' } }],
    });
  });

  it('shows every problem the server listed, and checks JSON first', async () => {
    mockFetch({ refuse: { error: 'invalid', errors: ['targets[0] (openapi): bogus is not an option'] } });
    render(<ExportPresetsClient />);
    const [nightly] = await screen.findAllByTestId('xprs-preset');
    await waitFor(() => expect(within(nightly).getByRole('button', { name: 'Edit' })).toBeInTheDocument());
    fireEvent.click(within(nightly).getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByLabelText('Options (JSON)', { selector: '#xprs-options-0' }), { target: { value: '{' } });
    fireEvent.click(screen.getByTestId('xprs-save'));
    expect(await screen.findByText('The options of openapi must be a JSON object.')).toBeInTheDocument();
    expect(calls.some((c) => c.init?.method === 'PATCH')).toBe(false);
    fireEvent.change(screen.getByLabelText('Options (JSON)', { selector: '#xprs-options-0' }), { target: { value: '{"bogus": 1}' } });
    fireEvent.click(screen.getByTestId('xprs-save'));
    expect(await screen.findByText('targets[0] (openapi): bogus is not an option')).toBeInTheDocument();
  });

  it('deletes only after the confirmation, and is read-only without projects:edit', async () => {
    mockFetch();
    const { unmount } = render(<ExportPresetsClient />);
    const [nightly] = await screen.findAllByTestId('xprs-preset');
    await waitFor(() => expect(within(nightly).getByRole('button', { name: 'Delete' })).toBeInTheDocument());
    fireEvent.click(within(nightly).getByRole('button', { name: 'Delete' }));
    fireEvent.click(within(nightly).getByRole('button', { name: 'Delete nightly-sync' }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === 'DELETE' && c.url.endsWith('/x1'))).toBe(true));
    unmount();
    mockFetch({ canEdit: false });
    render(<ExportPresetsClient />);
    expect(await screen.findByText(/Read-only for members/)).toBeInTheDocument();
    expect(within((await screen.findAllByTestId('xprs-preset'))[0]).queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
  });
});

describe('Apply a preset and Save as preset', () => {
  it('applies the chosen preset', async () => {
    mockFetch();
    const onApply = jest.fn();
    render(<ExportPresetPicker onApply={onApply} manageHref="/ade/dashboard/export/studio?tab=presets" notice="Applied nightly-sync." />);
    fireEvent.change(await screen.findByLabelText('Export preset'), { target: { value: 'x1' } });
    expect(screen.getByText(/delivered with lake/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onApply).toHaveBeenCalledWith(NIGHTLY);
    expect(screen.getByRole('status')).toHaveTextContent('Applied nightly-sync.');
  });

  it('renders nothing without presets', async () => {
    mockFetch({ presets: [] });
    const { container } = render(<ExportPresetPicker onApply={() => undefined} manageHref="/x" />);
    await waitFor(() => expect(calls.length).toBe(1));
    expect(container).toBeEmptyDOMElement();
  });

  it('saves the studio targets and delivery as a preset', async () => {
    mockFetch();
    render(<SavePresetForm targets={[{ target: 'openapi', options: { openapi_version: '3.0' } }]} deliveryProfileId="p1" />);
    fireEvent.click(screen.getByRole('button', { name: 'Save as preset' }));
    fireEvent.click(screen.getByTestId('xprs-save-preset'));
    expect(await screen.findByText('Name the preset.')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Preset name'), { target: { value: 'nightly-sync' } });
    fireEvent.click(screen.getByTestId('xprs-save-preset'));
    expect(await screen.findByText('Saved preset nightly-sync.')).toBeInTheDocument();
    const post = calls.find((c) => c.init?.method === 'POST')!;
    expect(JSON.parse(String(post.init!.body))).toEqual({
      name: 'nightly-sync', targets: [{ target: 'openapi', options: { openapi_version: '3.0' } }], deliveryProfileId: 'p1',
    });
  });
});

/**
 * The docs fixtures (`apiome-docs/screens.json`: `export-studio-presets`, `export-studio-preset-edit`).
 * Written into `e2e/fixtures/hive-export-studio/` when `EXPORT_STUDIO_FIXTURE_DUMP=1`.
 */
describe('the docs fixtures', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const fs = require('node:fs') as typeof import('node:fs');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const path = require('node:path') as typeof import('node:path');
  const OUT = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-export-studio');
  const write = (name: string) => {
    const html = liveMarkup(document.querySelector('.page') as HTMLElement);
    expect(html.length).toBeGreaterThan(0);
    if (process.env.EXPORT_STUDIO_FIXTURE_DUMP !== '1') return;
    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, `${name}.html`), `${html}\n`);
  };
  const render_ = async (edit: boolean) => {
    mockFetch();
    const preview = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'all';
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const { ExportStudioTabs } = require('@/app/components/ade/export-studio/ExportStudioTabs.tsx');
      render(<ExportPresetsClient tabs={<ExportStudioTabs />} />);
      const [nightly] = await screen.findAllByTestId('xprs-preset');
      if (edit) {
        await waitFor(() => expect(within(nightly).getByRole('button', { name: 'Edit' })).toBeInTheDocument());
        fireEvent.click(within(nightly).getByRole('button', { name: 'Edit' }));
        await screen.findByLabelText('Delivery profile');
        await screen.findByRole('option', { name: 'lake' });
      }
      expect(screen.getByRole('link', { name: 'Presets' })).toHaveAttribute('aria-current', 'page');
      write(edit ? 'preset-edit' : 'presets');
    } finally {
      if (preview === undefined) delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
      else process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = preview;
    }
  };

  it('renders the Presets tab (fixtures)', async () => {
    await render_(false);
  });

  it('renders a preset being edited (fixtures)', async () => {
    await render_(true);
  });
});
