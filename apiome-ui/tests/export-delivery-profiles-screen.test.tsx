/**
 * Export studio → Delivery tab and the Review step's delivery panel, rendered (MFX-38.4, #4331).
 *
 * Against a mocked `fetch`: the tab lists the workspace's profiles, creates one with the body the
 * REST layer takes (a webhook secret sent once, never shown), lists every problem the server
 * refused, deletes after a confirmation, shows a profile's trail, and is read-only without
 * `projects:edit`. The Review panel offers the profiles for a new export, then lists a finished
 * job's deliveries and delivers it now with a chosen profile.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

jest.mock('next/navigation', () => ({
  usePathname: () => '/ade/dashboard/export/studio',
  useSearchParams: () => new URLSearchParams('tab=delivery'),
}));

import { liveMarkup } from './helpers/a11y-fixture-dump';
import DeliveryProfilesClient from '@/app/components/ade/export-studio/delivery/DeliveryProfilesClient';
import { ExportJobDeliveryPanel } from '@/app/components/ade/export-studio/delivery/ExportJobDeliveryPanel';
import type { DeliveryProfile } from '@/app/components/ade/export-studio/delivery/deliveryProfilesModel';

const LAKE: DeliveryProfile = {
  id: 'p1',
  name: 'lake',
  description: 'Nightly copy',
  channel: 'object_storage',
  destination: { credentialId: 'c1', bucket: 'data-lake', prefix: 'exports', partitioning: [] },
  credentialRef: { kind: 'storage_credential', id: 'c1' },
};

const ATTEMPT = {
  channel: 'object_storage', runId: 'r1', jobId: 'job-1', status: 'delivered', outcome: 'delivered',
  profileId: 'p1', profileName: 'lake', destination: 'data-lake/exports', attemptCount: 1,
  errorCode: null, errorMessage: null, startedAt: '2026-11-04T10:00:00Z',
};

let calls: { url: string; init?: RequestInit }[] = [];

function mockFetch(options: {
  profiles?: DeliveryProfile[];
  canEdit?: boolean;
  createError?: { error: string; errors?: string[] };
  deliveries?: unknown[];
} = {}) {
  global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    const json = (body: unknown, status = 200) =>
      ({ ok: status < 400, status, json: async () => body }) as unknown as Response;
    const path = String(url);
    if (path.startsWith('/api/access/permissions/me')) {
      return json({ success: true, data: { is_admin: false, permissions: options.canEdit === false ? ['projects:view'] : ['projects:edit'] } });
    }
    if (path === '/api/repositories') return json({ success: true, repositories: [{ id: 'repo1', full_name: 'acme/specs' }] });
    if (path === '/api/export/storage-credentials') {
      return json({ success: true, data: { credentials: [{ id: 'c1', name: 'lake-key', accessKeyHint: 'WXYZ' }] } });
    }
    if (path.endsWith('/deliveries') && init?.method === 'POST') return json({ success: true, data: ATTEMPT });
    if (path.endsWith('/deliveries')) return json({ success: true, data: { deliveries: options.deliveries ?? [ATTEMPT] } });
    if (path === '/api/export/delivery-profiles' && init?.method === 'POST') {
      if (options.createError) return json({ success: false, ...options.createError }, 400);
      return json({ success: true, data: LAKE }, 201);
    }
    if (path.startsWith('/api/export/delivery-profiles/') && init?.method === 'DELETE') {
      return json({ success: true, data: null });
    }
    if (path.startsWith('/api/export/delivery-profiles')) {
      return json({ success: true, data: { profiles: options.profiles ?? [LAKE] } });
    }
    return json({ success: false, error: `unmocked ${path}` }, 500);
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  calls = [];
});

describe('Delivery tab', () => {
  it('lists the profiles with their destination and channel', async () => {
    mockFetch();
    render(<DeliveryProfilesClient />);
    const row = await screen.findByTestId('xdlv-profile');
    expect(within(row).getByText('lake')).toBeInTheDocument();
    expect(within(row).getByText('Object storage')).toBeInTheDocument();
    expect(within(row).getByText('data-lake/exports')).toBeInTheDocument();
  });

  it('creates a webhook profile, sending the secret once', async () => {
    mockFetch({ profiles: [] });
    render(<DeliveryProfilesClient />);
    fireEvent.click(await screen.findByTestId('xdlv-new'));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'ci' } });
    fireEvent.click(screen.getByLabelText('Webhook'));
    fireEvent.change(screen.getByLabelText('Receiver URL'), { target: { value: 'https://ci.example.com/h' } });
    fireEvent.change(screen.getByLabelText('Signing secret'), { target: { value: 'a-long-enough-signing-secret' } });
    fireEvent.click(screen.getByTestId('xdlv-save'));
    await waitFor(() => expect(calls.some((c) => c.init?.method === 'POST')).toBe(true));
    const post = calls.find((c) => c.init?.method === 'POST')!;
    expect(JSON.parse(String(post.init!.body))).toEqual({
      name: 'ci', channel: 'webhook',
      webhook: { url: 'https://ci.example.com/h', artifact: 'auto', secret: 'a-long-enough-signing-secret' },
    });
  });

  it('lists every problem before sending, and every problem the server refused', async () => {
    mockFetch({ profiles: [], createError: { error: 'invalid', errors: ['objectStorage.bucket must be …'] } });
    render(<DeliveryProfilesClient />);
    fireEvent.click(await screen.findByTestId('xdlv-new'));
    fireEvent.click(screen.getByTestId('xdlv-save'));
    expect(await screen.findByText('Name the profile.')).toBeInTheDocument();
    expect(screen.getByText('Choose a repository.')).toBeInTheDocument();
    expect(calls.some((c) => c.init?.method === 'POST')).toBe(false);

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'lake' } });
    fireEvent.click(screen.getByLabelText('Object storage'));
    await screen.findByRole('option', { name: 'lake-key (…WXYZ)' });
    fireEvent.change(screen.getByLabelText('Storage credential'), { target: { value: 'c1' } });
    fireEvent.change(screen.getByLabelText('Bucket'), { target: { value: 'data-lake' } });
    fireEvent.click(screen.getByTestId('xdlv-save'));
    expect(await screen.findByText('objectStorage.bucket must be …')).toBeInTheDocument();
  });

  it('deletes only after the confirmation', async () => {
    mockFetch();
    render(<DeliveryProfilesClient />);
    const row = await screen.findByTestId('xdlv-profile');
    await waitFor(() => expect(within(row).getByRole('button', { name: 'Delete' })).toBeInTheDocument());
    fireEvent.click(within(row).getByRole('button', { name: 'Delete' }));
    expect(calls.some((c) => c.init?.method === 'DELETE')).toBe(false);
    fireEvent.click(within(row).getByRole('button', { name: 'Delete lake' }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === 'DELETE' && c.url.endsWith('/p1'))).toBe(true));
  });

  it("shows a profile's delivery trail", async () => {
    mockFetch();
    render(<DeliveryProfilesClient />);
    const row = await screen.findByTestId('xdlv-profile');
    fireEvent.click(within(row).getByRole('button', { name: 'Deliveries' }));
    expect(await screen.findByTestId('delivery-attempt')).toHaveTextContent('Delivered');
    expect(calls.some((c) => c.url === '/api/export/delivery-profiles/p1/deliveries')).toBe(true);
  });

  it('is read-only without projects:edit', async () => {
    mockFetch({ canEdit: false });
    render(<DeliveryProfilesClient />);
    expect(await screen.findByText(/Read-only for members/)).toBeInTheDocument();
    expect(screen.queryByTestId('xdlv-new')).not.toBeInTheDocument();
    const row = await screen.findByTestId('xdlv-profile');
    expect(within(row).queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
  });
});

describe('Review delivery panel', () => {
  it('offers the profiles to deliver with on completion', async () => {
    mockFetch();
    const onSelectedChange = jest.fn();
    render(<ExportJobDeliveryPanel jobId={null} selected={[]} onSelectedChange={onSelectedChange} expected={0}
      manageHref="/ade/dashboard/export/studio?tab=delivery" />);
    expect(await screen.findByText('Deliver when it completes')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('checkbox'));
    expect(onSelectedChange).toHaveBeenCalledWith(['p1']);
  });

  it("lists a finished job's deliveries and delivers it now", async () => {
    mockFetch();
    render(<ExportJobDeliveryPanel jobId="job-1" selected={[]} onSelectedChange={() => undefined} expected={1}
      manageHref="/ade/dashboard/export/studio?tab=delivery" />);
    expect(await screen.findByTestId('delivery-attempt')).toHaveTextContent('data-lake/exports');
    fireEvent.change(screen.getByLabelText('Delivery profile'), { target: { value: 'p1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Deliver now' }));
    await waitFor(() => {
      const post = calls.find((c) => c.init?.method === 'POST');
      expect(post?.url).toBe('/api/export/jobs/job-1/deliveries');
      expect(JSON.parse(String(post!.init!.body))).toEqual({ profileId: 'p1' });
    });
  });

  it('points at the Delivery tab when there are no profiles', async () => {
    mockFetch({ profiles: [] });
    render(<ExportJobDeliveryPanel jobId={null} selected={[]} onSelectedChange={() => undefined} expected={0}
      manageHref="/ade/dashboard/export/studio?tab=delivery" />);
    expect(await screen.findByText(/No delivery profiles yet/)).toBeInTheDocument();
  });
});

/**
 * The docs fixtures (`apiome-docs/screens.json`: `export-studio-delivery`,
 * `export-studio-delivery-form`, `export-studio-job-delivery`). Written into
 * `e2e/fixtures/hive-export-studio/` when `EXPORT_STUDIO_FIXTURE_DUMP=1`:
 *
 *     EXPORT_STUDIO_FIXTURE_DUMP=1 npx jest tests/export-delivery-profiles-screen.test.tsx -t fixtures
 */
describe('the docs fixtures', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const fs = require('node:fs') as typeof import('node:fs');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const path = require('node:path') as typeof import('node:path');
  const OUT = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-export-studio');
  const write = (name: string, html: string) => {
    expect(html.length).toBeGreaterThan(0);
    if (process.env.EXPORT_STUDIO_FIXTURE_DUMP !== '1') return;
    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, `${name}.html`), `${html}\n`);
  };
  const PROFILES: DeliveryProfile[] = [
    LAKE,
    {
      id: 'p2', name: 'ci-pipeline', description: 'Tells the release pipeline a spec is ready', channel: 'webhook',
      destination: { url: 'https://ci.example.com/hooks/apiome?…', artifact: 'auto' },
      credentialRef: { kind: 'webhook_secret', id: null },
    },
    {
      id: 'p3', name: 'specs-repo', description: null, channel: 'git',
      destination: { repositoryId: 'repo1', targetPath: 'specs/orders', mode: 'pr' },
      credentialRef: { kind: 'repository', id: 'repo1' },
    },
  ];
  const TRAIL = [
    ATTEMPT,
    { ...ATTEMPT, runId: 'r0', status: 'failed', outcome: 'failed', errorCode: 'export-object-storage-delivery-bucket-missing',
      errorMessage: 'The bucket does not exist at that endpoint.', startedAt: '2026-11-03T10:00:00Z' },
  ];

  const withPreview = async (run: () => Promise<void>) => {
    const preview = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'all';
    try {
      await run();
    } finally {
      if (preview === undefined) delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
      else process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = preview;
    }
  };

  it('renders the Delivery tab with a profile trail open (fixtures)', async () => {
    mockFetch({ profiles: PROFILES, deliveries: TRAIL });
    await withPreview(async () => {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const { ExportStudioTabs } = require('@/app/components/ade/export-studio/ExportStudioTabs.tsx');
      render(<DeliveryProfilesClient tabs={<ExportStudioTabs />} />);
      const rows = await screen.findAllByTestId('xdlv-profile');
      await screen.findByRole('option', { name: 'acme/specs' }).catch(() => undefined);
      fireEvent.click(within(rows[0]).getByRole('button', { name: 'Deliveries' }));
      await screen.findAllByTestId('delivery-attempt');
      expect(screen.getByRole('link', { name: 'Delivery' })).toHaveAttribute('aria-current', 'page');
      write('delivery-profiles', liveMarkup(document.querySelector('.page') as HTMLElement));
    });
  });

  it('renders the new profile form for a webhook (fixtures)', async () => {
    mockFetch({ profiles: PROFILES });
    await withPreview(async () => {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const { ExportStudioTabs } = require('@/app/components/ade/export-studio/ExportStudioTabs.tsx');
      render(<DeliveryProfilesClient tabs={<ExportStudioTabs />} />);
      fireEvent.click(await screen.findByTestId('xdlv-new'));
      fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'release-hook' } });
      fireEvent.click(screen.getByLabelText('Webhook'));
      fireEvent.change(screen.getByLabelText('Receiver URL'), { target: { value: 'https://ci.example.com/hooks/release' } });
      write('delivery-profile-form', liveMarkup(document.querySelector('.page') as HTMLElement));
    });
  });

  it("renders a finished job's deliveries on Review (fixtures)", async () => {
    mockFetch({ profiles: PROFILES, deliveries: [ATTEMPT, { ...TRAIL[1], profileName: 'ci-pipeline', channel: 'webhook',
      status: 'retrying', outcome: 'in_progress', attemptCount: 2, destination: 'https://ci.example.com/hooks/apiome?…',
      errorCode: null, errorMessage: null }] });
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { Page, PageBody } = require('@/app/components/shell/pageChrome');
    const { container } = render(
      <Page>
        <PageBody>
          <ExportJobDeliveryPanel jobId="job-1" selected={[]} onSelectedChange={() => undefined} expected={2}
            manageHref="/ade/dashboard/export/studio?tab=delivery" />
        </PageBody>
      </Page>,
    );
    await screen.findAllByTestId('delivery-attempt');
    write('job-delivery', liveMarkup(container.querySelector('.page') as HTMLElement));
  });
});
