/**
 * Batch / preset / schedule UI — MFX-39.5 (#4337).
 *
 * The Export dialog: **Several targets** ticks targets with this source's fidelity badges and runs one
 * multi-target job; **Apply a preset** selects a one-target preset's card and options, or ticks a
 * multi-target preset's targets — whose job then carries each target's options and the preset's delivery
 * profile; **Save as preset** saves the selection. The version view: **Export all versions…** runs the
 * project-level batch (`all_versions`), and **Auto-export on publish** lists, adds and releases the
 * presets that run on every publish of the project, next to the recent exports.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

jest.mock('@monaco-editor/react', () => ({ __esModule: true, default: () => <div /> }));
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), prefetch: jest.fn() }),
}));
jest.mock('next/link', () => {
  const Link = ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => (
    <a href={typeof href === 'string' ? href : '#'} {...rest}>
      {children}
    </a>
  );
  Link.displayName = 'Link';
  return { __esModule: true, default: Link };
});

import { ExportDialog } from '../src/app/components/ade/dashboard/export/ExportDialog';
import { VersionExportPanel } from '../src/app/components/ade/dashboard/export/VersionExportPanel';
import { allVersionsJobBody, withTargetOptions } from '../src/app/components/ade/dashboard/export/exportBatchJob';
import { mockExportDialogFetch } from './helpers/export-dialog-fixture';

const ONE_TARGET = {
  id: 'one', name: 'just-proto', description: null, targets: [{ target: 'proto', options: { package: 'acme.v1' } }],
  deliveryProfileId: null, deliveryProfileName: null,
};
const TWO_TARGETS = {
  id: 'two', name: 'nightly-sync', description: null,
  targets: [{ target: 'openapi', options: { openapi_version: '3.0' } }, { target: 'proto' }, { target: 'wsdl' }],
  deliveryProfileId: 'p1', deliveryProfileName: 'lake',
};

type Call = { url: string; init?: RequestInit };
let calls: Call[] = [];

/** The dialog's own backend, plus presets, auto-exports, permissions, projects and export jobs. */
function mockFetch(): jest.Mock {
  const base = mockExportDialogFetch();
  return jest.fn((input: unknown, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    const ok = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    if (url.startsWith('/api/export/presets') && init?.method === 'POST') {
      return ok({ success: true, data: { ...TWO_TARGETS, id: 'new', ...JSON.parse(String(init.body)) } });
    }
    if (url.startsWith('/api/export/presets')) return ok({ success: true, data: { presets: [ONE_TARGET, TWO_TARGETS] } });
    if (url === '/api/export/jobs' && init?.method === 'POST') return ok({ success: true, job_id: 'job-1' });
    if (url.startsWith('/api/export/jobs/job-1')) {
      return ok({ success: true, job_id: 'job-1', state: 'completed', percent: 100, events: [], result: null });
    }
    if (url.startsWith('/api/access/permissions/me')) {
      return ok({ success: true, data: { is_admin: false, permissions: ['projects:edit'] } });
    }
    if (url.startsWith('/api/export/auto-export-runs') && init?.method === 'POST') {
      return ok({ success: true, data: { id: 'r1', status: 'delivered' } });
    }
    if (url.startsWith('/api/export/auto-export-runs')) {
      return ok({ success: true, data: { runs: [{ id: 'r1', projectId: 'proj-petstore', projectName: 'Pet Store API',
        versionRecordId: 'rev-2', subscriptionId: 's1', presetName: 'nightly-sync', status: 'halted', lossSeverity: 'critical',
        lossReasons: ['avro: a severe conversion (9% preserved)'], deliveries: [], errorCode: null, errorMessage: null,
        releasedAt: null, createdAt: '2026-11-05T09:00:00Z' }] } });
    }
    if (url.startsWith('/api/export/auto-exports') && init?.method === 'POST') return ok({ success: true, data: {} });
    if (url.startsWith('/api/export/auto-exports')) {
      return ok({ success: true, data: { subscriptions: [{ id: 's1', projectId: 'proj-petstore', projectName: 'Pet Store API',
        presetId: 'two', presetName: 'nightly-sync', haltAt: 'critical', approveLoss: false, active: true }] } });
    }
    return base(input, init as never);
  }) as unknown as jest.Mock;
}

beforeEach(() => {
  calls = [];
});

const posted = (url: string) => {
  const call = calls.find((c) => c.url === url && c.init?.method === 'POST');
  return call ? JSON.parse(String(call.init!.body)) : null;
};

async function openTargetStep() {
  global.fetch = mockFetch() as unknown as typeof fetch;
  render(<ExportDialog open onClose={jest.fn()} artifact="proj-petstore" artifactLabel="Pet Store API" />);
  await waitFor(() => expect(screen.getByTestId('export-dialog-choose-target')).not.toBeDisabled());
  fireEvent.click(screen.getByTestId('export-dialog-choose-target'));
  await screen.findByTestId('export-dialog-multi-toggle');
}

describe('the job bodies', () => {
  it('gives targets their options and builds the all-versions batch', () => {
    expect(withTargetOptions({ artifact: 'a', targets: [{ target: 'openapi' }, { target: 'avro' }] },
      { openapi: { openapi_version: '3.0' }, avro: {} }))
      .toEqual({ artifact: 'a', targets: [{ target: 'openapi', options: { openapi_version: '3.0' } }, { target: 'avro' }] });
    expect(allVersionsJobBody('a', ['openapi', 'avro', 'openapi']))
      .toEqual({ artifact: 'a', all_versions: true, targets: [{ target: 'openapi' }, { target: 'avro' }] });
  });
});

describe('the Export dialog', () => {
  it('runs several ticked targets as one job, each with its fidelity badge', async () => {
    await openTargetStep();
    fireEvent.click(within(screen.getByTestId('export-dialog-multi-toggle')).getByRole('checkbox'));
    const list = screen.getByTestId('export-studio-multi-targets');
    expect(within(list).getAllByText(/%$/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByTestId('export-dialog-continue')).toBeDisabled();
    fireEvent.click(within(screen.getByTestId('export-studio-multi-target-openapi')).getByRole('checkbox'));
    fireEvent.click(within(screen.getByTestId('export-studio-multi-target-proto')).getByRole('checkbox'));
    fireEvent.click(screen.getByTestId('export-dialog-continue'));
    fireEvent.click(await screen.findByTestId('multi-export-generate-start'));
    await waitFor(() => expect(posted('/api/export/jobs')).not.toBeNull());
    expect(posted('/api/export/jobs')).toEqual({ artifact: 'proj-petstore', targets: [{ target: 'openapi' }, { target: 'proto' }] });
  });

  it('applies a multi-target preset with its options and delivery profile', async () => {
    await openTargetStep();
    fireEvent.change(await screen.findByLabelText('Export preset'), { target: { value: 'two' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(await screen.findByText('Applied nightly-sync, except wsdl, which this source cannot export to.')).toBeInTheDocument();
    expect(within(screen.getByTestId('export-studio-multi-target-openapi')).getByRole('checkbox')).toBeChecked();
    expect(within(screen.getByTestId('export-studio-multi-target-proto')).getByRole('checkbox')).toBeChecked();
    fireEvent.click(screen.getByTestId('export-dialog-continue'));
    expect(await screen.findByText(/Delivered with/)).toHaveTextContent('Delivered with lake as soon as the archive is built.');
    fireEvent.click(screen.getByTestId('multi-export-generate-start'));
    await waitFor(() => expect(posted('/api/export/jobs')).not.toBeNull());
    expect(posted('/api/export/jobs')).toEqual({
      artifact: 'proj-petstore',
      targets: [{ target: 'openapi', options: { openapi_version: '3.0' } }, { target: 'proto' }],
      delivery_profiles: ['p1'],
    });
  });

  it('applies a one-target preset and saves the selection as a preset', async () => {
    await openTargetStep();
    fireEvent.change(await screen.findByLabelText('Export preset'), { target: { value: 'one' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(await screen.findByText('Applied just-proto.')).toBeInTheDocument();
    expect(screen.getByTestId('export-dialog-continue')).not.toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Save as preset' }));
    fireEvent.change(screen.getByLabelText('Preset name'), { target: { value: 'proto-again' } });
    fireEvent.click(screen.getByTestId('xprs-save-preset'));
    await waitFor(() => expect(posted('/api/export/presets')).not.toBeNull());
    expect(posted('/api/export/presets')).toEqual({
      name: 'proto-again', targets: [{ target: 'proto', options: { package: 'acme.v1' } }],
    });
  });
});

describe('the version view', () => {
  it('runs every version of the project to the ticked targets', async () => {
    global.fetch = mockFetch() as unknown as typeof fetch;
    render(<VersionExportPanel artifact="proj-petstore" version="rev-1" artifactLabel="Pet Store API" active />);
    fireEvent.click(await screen.findByTestId('version-export-all-versions'));
    await screen.findByText('Export every version of this project to');
    expect(screen.queryByTestId('multi-export-generate')).not.toBeInTheDocument();
    fireEvent.click(within(await screen.findByTestId('export-studio-multi-target-openapi')).getByRole('checkbox'));
    fireEvent.click(await screen.findByTestId('multi-export-generate-start'));
    await waitFor(() => expect(posted('/api/export/jobs')).not.toBeNull());
    expect(posted('/api/export/jobs')).toEqual({ artifact: 'proj-petstore', all_versions: true, targets: [{ target: 'openapi' }] });
  });

  it('manages the presets that run on every publish, next to the recent exports', async () => {
    global.fetch = mockFetch() as unknown as typeof fetch;
    render(<VersionExportPanel artifact="proj-petstore" version="rev-1" artifactLabel="Pet Store API" active />);
    const panel = await screen.findByTestId('auto-export-panel');
    expect(screen.getByText('Recent exports')).toBeInTheDocument();
    expect(await within(panel).findByText('nightly-sync')).toBeInTheDocument();
    expect(await within(panel).findByTestId('auto-export-run')).toHaveTextContent('Halted');
    expect(calls.some((c) => c.url === '/api/export/auto-exports?projectId=proj-petstore')).toBe(true);

    await within(panel).findByRole('option', { name: 'just-proto' });
    expect(within(panel).queryByRole('option', { name: 'nightly-sync' })).not.toBeInTheDocument();
    fireEvent.change(within(panel).getByLabelText('Export preset'), { target: { value: 'one' } });
    fireEvent.click(within(panel).getByTestId('auto-export-add-button'));
    await waitFor(() => expect(posted('/api/export/auto-exports')).not.toBeNull());
    expect(posted('/api/export/auto-exports')).toEqual({ projectId: 'proj-petstore', preset: 'one', haltAt: 'critical',
      approveLoss: false });

    fireEvent.click(await within(panel).findByRole('button', { name: 'Release' }));
    await waitFor(() => expect(calls.some((c) => c.url === '/api/export/auto-export-runs/r1/release')).toBe(true));
  });
});
