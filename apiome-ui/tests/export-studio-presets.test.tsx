/**
 * Export presets inside Export studio — integration (MFX-39.3, #4335).
 *
 * The real {@link ExportStudio} against a mocked backend: on the Target step, **Apply a preset** with
 * a one-target preset selects that card; with a multi-target preset it turns on **Several targets** and
 * ticks each one, naming a target this source cannot export to. The multi-target Generate body then
 * carries each target's preset options and the preset's delivery profile.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, it, jest, beforeEach } from '@jest/globals';

jest.mock('@monaco-editor/react', () => ({ __esModule: true, default: () => <div /> }));
jest.mock('next/link', () => {
  const Link = React.forwardRef<HTMLAnchorElement, { children: React.ReactNode; href: string } & Record<string, unknown>>(
    ({ children, href, ...rest }, ref) => {
      const attrs = { ...rest };
      delete attrs.prefetch;
      return (
        <a ref={ref} href={typeof href === 'string' ? href : '#'} {...attrs}>
          {children}
        </a>
      );
    },
  );
  Link.displayName = 'Link';
  return { __esModule: true, default: Link };
});
jest.mock('sonner', () => ({ __esModule: true, toast: Object.assign(jest.fn(), { success: jest.fn(), error: jest.fn() }) }));

import { ExportStudio } from '../src/app/components/ade/dashboard/export/ExportStudio';
import { __resetExportJobTrackerForTests } from '../src/app/components/ade/dashboard/export/exportJobTracker';
import type { ExportTargetEntry } from '../src/app/components/ade/dashboard/export/exportTargetCatalog';

function entry(key: string, label: string, paradigm: string): ExportTargetEntry {
  return {
    descriptor: {
      key, format: `${key}-1`, label, description: `Export as ${label}.`, icon: 'file-json', paradigm,
      multi_file: false, needs_toolchain: false, available: true, unavailable_reason: null,
    },
    capability_profile: { operations: true },
    options_schema: { properties: { flavor: { type: 'string', default: 'plain' } } },
    default_options: { flavor: 'plain' },
    fidelity: { tier: 'lossless', preserved_percent: 100, total: 1, preserved: 1, dropped: 0, approximated: 0, synthesized: 0 },
  } as ExportTargetEntry;
}

const TARGETS = {
  artifact: 'proj-petstore', version: null, version_record_id: 'rev-1', version_label: '1.2.0',
  targets: [entry('openapi', 'OpenAPI 3.1', 'rest'), entry('graphql', 'GraphQL SDL', 'graph'), entry('proto', 'Protocol Buffers', 'rpc')],
};

const PRESETS = [
  { id: 'one', name: 'just-graphql', description: null, targets: [{ target: 'graphql', options: { flavor: 'fancy' } }],
    deliveryProfileId: null, deliveryProfileName: null },
  { id: 'many', name: 'nightly-sync', description: null,
    targets: [{ target: 'openapi', options: { flavor: 'fancy' } }, { target: 'proto' }, { target: 'wsdl' }],
    deliveryProfileId: 'p1', deliveryProfileName: 'lake' },
];

function mockFetch(): jest.Mock {
  return jest.fn((input: unknown) => {
    const url = String(input);
    const ok = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    if (url.includes('/api/export/targets')) return ok({ success: true, ...TARGETS });
    if (url.startsWith('/api/export/presets')) return ok({ success: true, data: { presets: PRESETS } });
    if (url.startsWith('/api/export/delivery-profiles')) {
      return ok({ success: true, data: { profiles: [{ id: 'p1', name: 'lake', channel: 'object_storage', destination: {}, credentialRef: { kind: 'storage_credential', id: 'c' } }] } });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({ success: false }) });
  }) as unknown as jest.Mock;
}

async function openTargetStep() {
  global.fetch = mockFetch() as unknown as typeof fetch;
  render(<ExportStudio artifact="proj-petstore" artifactLabel="Pet Store API" version="rev-1" workspaceName="Acme" />);
  await waitFor(() => expect(screen.getByText(/export targets available/)).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: /choose target/i }));
  return screen.findByLabelText('Export preset');
}

beforeEach(() => {
  __resetExportJobTrackerForTests();
  window.sessionStorage.clear();
});

describe('Apply a preset in Export studio', () => {
  it('selects a one-target preset’s card', async () => {
    const picker = await openTargetStep();
    fireEvent.change(picker, { target: { value: 'one' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(await screen.findByText('Applied just-graphql.')).toBeInTheDocument();
    const card = document.querySelector('[data-selected="true"]');
    expect(card).not.toBeNull();
    expect(card).toHaveTextContent('GraphQL SDL');
  });

  it('ticks a multi-target preset under Several targets and names what it cannot export to', async () => {
    const picker = await openTargetStep();
    fireEvent.change(picker, { target: { value: 'many' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(await screen.findByText(/Applied nightly-sync, except wsdl/)).toBeInTheDocument();
    const toggle = screen.getByTestId('export-studio-multi-toggle').querySelector('input') as HTMLInputElement;
    expect(toggle.checked).toBe(true);
    const ticked = Array.from(document.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'))
      .filter((box) => box.checked && box !== toggle)
      .map((box) => box.closest('label')?.textContent ?? '');
    expect(ticked.some((text) => text.includes('OpenAPI 3.1'))).toBe(true);
    expect(ticked.some((text) => text.includes('Protocol Buffers'))).toBe(true);
    expect(ticked.some((text) => text.includes('GraphQL SDL'))).toBe(false);
  });
});

describe('the multi-target run carries a preset’s options and delivery', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { MultiExportRun } = require('../src/app/components/ade/dashboard/export/MultiExportRun');
  const body = {
    artifact: 'a1',
    targets: [{ target: 'openapi', options: { flavor: 'fancy' } }, { target: 'proto' }],
    delivery_profiles: ['p1'],
  };

  const submitted = async (mode: 'verify' | 'generate') => {
    const fetchMock = jest.fn((input: unknown, init?: RequestInit) => {
      const ok = (data: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(data) });
      if (String(input) === '/api/export/jobs' && init?.method === 'POST') return ok({ success: true, job_id: 'j1' });
      return ok({ success: true, job_id: 'j1', state: 'completed', percent: 100, events: [], result: null });
    }) as unknown as jest.Mock;
    global.fetch = fetchMock as unknown as typeof fetch;
    const { unmount } = render(<MultiExportRun body={body} mode={mode} archiveName="a.zip" pollIntervalMs={1} />);
    fireEvent.click(screen.getByTestId(`multi-export-${mode}-start`));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [, init] = fetchMock.mock.calls.find(([, i]) => (i as RequestInit | undefined)?.method === 'POST') as [string, RequestInit];
    unmount();
    return JSON.parse(String(init.body));
  };

  it('sends the delivery profiles with Generate', async () => {
    const sent = await submitted('generate');
    expect(sent.delivery_profiles).toEqual(['p1']);
    expect(sent.targets[0].options).toEqual({ flavor: 'fancy' });
  });

  it('drops them from Verify, a dry run', async () => {
    const sent = await submitted('verify');
    expect(sent.dry_run).toBe(true);
    expect(sent).not.toHaveProperty('delivery_profiles');
  });
});
