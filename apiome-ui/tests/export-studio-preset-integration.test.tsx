/**
 * Preset & schedule integration — MFX-46.4 (#4382).
 *
 * Export studio feeds the presets (MFX-39.3) and auto-export subscriptions (MFX-39.4) instead of
 * duplicating them:
 *  - a preset keeps every delivery profile, in order, so Studio → preset → Studio is identical;
 *  - the selection's fingerprint decides which preset is *in play*;
 *  - the `preset` link param (the Presets tab's **Open in Studio**) survives the Source picker and is
 *    applied once the targets load;
 *  - **Auto-export on publish** on Review subscribes / unsubscribes this project to the preset in play.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, it, jest, beforeEach } from '@jest/globals';

jest.mock('@monaco-editor/react', () => ({ __esModule: true, default: () => <div /> }));
jest.mock('sonner', () => ({ __esModule: true, toast: Object.assign(jest.fn(), { success: jest.fn(), error: jest.fn() }) }));

import {
  applyPresetToStudio,
  draftFromPreset,
  presetBody,
  presetProfileIds,
  presetProfileNames,
  selectionSignature,
  updateFromDraft,
  type ExportPreset,
} from '../src/app/components/ade/export-studio/presets/exportPresetsModel';
import { StudioAutoExportToggle } from '../src/app/components/ade/export-studio/presets/StudioAutoExportToggle';
import { parseExportStudioUrlState } from '../src/app/components/ade/dashboard/export/exportStudioUrlState';
import { exportStudioHref } from '../src/app/components/ade/dashboard/export/exportStudioLink';
import { catalogSourceHref, projectSourceHref } from '../src/app/components/ade/export-studio/exportSourcePicker';
import { ExportStudio } from '../src/app/components/ade/dashboard/export/ExportStudio';
import { __resetExportJobTrackerForTests } from '../src/app/components/ade/dashboard/export/exportJobTracker';
import type { ExportTargetEntry } from '../src/app/components/ade/dashboard/export/exportTargetCatalog';

const NIGHTLY: ExportPreset = {
  id: 'x1', name: 'nightly-sync', description: null,
  targets: [{ target: 'openapi', options: { flavor: 'fancy' } }, { target: 'proto', options: null }],
  deliveryProfileId: 'p1', deliveryProfileName: 'lake',
  deliveryProfileIds: ['p1', 'p2'], deliveryProfileNames: ['lake', 'release-bucket'],
};

const card = (key: string) => ({ key, available: true, entry: { descriptor: { key, format: `${key}-1` } } });

beforeEach(() => {
  __resetExportJobTrackerForTests();
  window.sessionStorage.clear();
});

// ===========================================================================
// The model
// ===========================================================================

describe('a preset holds every delivery profile', () => {
  it('reads the ordered list, falling back to the single profile', () => {
    expect(presetProfileIds(NIGHTLY)).toEqual(['p1', 'p2']);
    expect(presetProfileIds({ deliveryProfileId: 'p1' })).toEqual(['p1']);
    expect(presetProfileIds({ deliveryProfileId: null, deliveryProfileIds: [] })).toEqual([]);
    expect(presetProfileNames(NIGHTLY)).toEqual(['lake', 'release-bucket']);
    expect(presetProfileNames({ deliveryProfileName: 'lake' })).toEqual(['lake']);
    expect(presetProfileNames({ deliveryProfileName: null })).toEqual([]);
  });

  it('ticks every profile when applied', () => {
    expect(applyPresetToStudio(NIGHTLY, [card('openapi'), card('proto')]).deliveryProfiles).toEqual(['p1', 'p2']);
  });

  it('saves every ticked profile once, in order, at most five', () => {
    expect(presetBody('n', '', [{ target: 'openapi' }], ['p2', ' ', 'p1', 'p2']).deliveryProfileIds).toEqual(['p2', 'p1']);
    expect(presetBody('n', '', [{ target: 'openapi' }], ['a', 'b', 'c', 'd', 'e', 'f']).deliveryProfileIds)
      .toEqual(['a', 'b', 'c', 'd', 'e']);
    expect(presetBody('n', '', [{ target: 'openapi' }], [])).not.toHaveProperty('deliveryProfileIds');
  });

  it('round-trips Studio → preset → Studio unchanged', () => {
    const targets = [{ target: 'openapi', options: { flavor: 'fancy' } }, { target: 'proto', options: null }];
    const body = presetBody('nightly-sync', '', targets, ['p2', 'p1']);
    const stored: ExportPreset = {
      id: 'x9', name: 'nightly-sync', description: null, deliveryProfileId: 'p2', deliveryProfileName: null,
      targets: body.targets as ExportPreset['targets'], deliveryProfileIds: body.deliveryProfileIds as string[],
    };
    const applied = applyPresetToStudio(stored, [card('openapi'), card('proto')]);
    expect(applied.missing).toEqual([]);
    const reapplied = applied.multi!.keys.map((key) => ({ target: key, options: applied.multi!.options[key] }));
    expect(selectionSignature(reapplied, applied.deliveryProfiles)).toBe(selectionSignature(targets, ['p2', 'p1']));
  });

  it('keeps, reorders and checks the profiles on the Presets tab form', () => {
    const draft = draftFromPreset(NIGHTLY);
    expect(draft.deliveryProfileIds).toEqual(['p1', 'p2']);
    expect(updateFromDraft({ ...draft, deliveryProfileIds: ['p2', 'p1'] }).body?.deliveryProfileIds).toEqual(['p2', 'p1']);
    expect(updateFromDraft({ ...draft, deliveryProfileIds: ['p1', 'p1'] }).problems).toEqual(['Name each delivery profile once.']);
    expect(updateFromDraft({ ...draft, deliveryProfileIds: ['a', 'b', 'c', 'd', 'e', 'f'] }).problems)
      .toEqual(['A preset delivers with at most 5 profiles.']);
  });
});

describe('the selection fingerprint', () => {
  it('ignores option key order and treats no options as empty', () => {
    expect(selectionSignature([{ target: 'a', options: { x: 1, y: { b: 2, a: 1 } } }], ['p1']))
      .toBe(selectionSignature([{ target: 'a', options: { y: { a: 1, b: 2 }, x: 1 } }], ['p1']));
    expect(selectionSignature([{ target: 'a', options: null }], [])).toBe(selectionSignature([{ target: 'a', options: {} }], []));
  });

  it('changes with a target, an option, the target order or the profiles', () => {
    const base = selectionSignature([{ target: 'a' }, { target: 'b' }], ['p1', 'p2']);
    expect(selectionSignature([{ target: 'b' }, { target: 'a' }], ['p1', 'p2'])).not.toBe(base);
    expect(selectionSignature([{ target: 'a', options: { x: 1 } }, { target: 'b' }], ['p1', 'p2'])).not.toBe(base);
    expect(selectionSignature([{ target: 'a' }, { target: 'b' }], ['p2', 'p1'])).not.toBe(base);
    expect(selectionSignature([{ target: 'a' }, { target: 'b' }], ['p1'])).not.toBe(base);
    expect(selectionSignature([{ target: 'a' }], ['p1', 'p2'])).not.toBe(base);
  });
});

// ===========================================================================
// The link
// ===========================================================================

describe('the preset link param', () => {
  it('is read, built and carried through the Source picker', () => {
    expect(parseExportStudioUrlState(new URLSearchParams('preset=x1')).state.preset).toBe('x1');
    expect(parseExportStudioUrlState(new URLSearchParams('artifact=a')).state.preset).toBeNull();
    expect(exportStudioHref({ artifact: 'a', preset: 'x1' })).toBe('/ade/dashboard/export/studio?artifact=a&preset=x1');
    expect(catalogSourceHref({ id: 'c1', name: 'Pets' } as Parameters<typeof catalogSourceHref>[0], 'x1')).toContain('preset=x1');
    expect(projectSourceHref({ id: 'p1', name: 'Pets' } as Parameters<typeof projectSourceHref>[0], null, 'x1'))
      .toContain('preset=x1');
    expect(projectSourceHref({ id: 'p1', name: 'Pets' } as Parameters<typeof projectSourceHref>[0], null)).not.toContain('preset');
  });
});

// ===========================================================================
// Auto-export on publish, on Review
// ===========================================================================

type Call = { url: string; init?: RequestInit };

function mockAutoExports(subs: unknown[]): Call[] {
  const calls: Call[] = [];
  let current = [...subs];
  global.fetch = jest.fn((input: unknown, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    const ok = (data: unknown, status = 200) =>
      Promise.resolve({ ok: true, status, json: () => Promise.resolve({ success: true, data }) });
    if (url.startsWith('/api/export/auto-exports') && init?.method === 'POST') {
      const body = JSON.parse(String(init.body));
      const sub = { id: 's-new', projectId: body.projectId, projectName: null, presetId: body.preset, presetName: null,
        haltAt: body.haltAt, approveLoss: body.approveLoss, active: true };
      current = [sub];
      return ok(sub, 201);
    }
    if (url.startsWith('/api/export/auto-exports/') && init?.method === 'DELETE') {
      current = [];
      return ok(null);
    }
    if (url.startsWith('/api/export/auto-exports')) return ok({ subscriptions: current });
    return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ success: false }) });
  }) as unknown as typeof fetch;
  return calls;
}

describe('Auto-export on publish in Export studio', () => {
  it('asks for a preset first when none is in play', () => {
    const calls = mockAutoExports([]);
    render(<StudioAutoExportToggle projectId="proj-1" preset={null} presetsHref="/presets" />);
    expect(screen.getByTestId('studio-auto-export-needs-preset')).toHaveTextContent(/Save these settings as a preset/);
    expect(calls).toHaveLength(0);
  });

  it('subscribes this project to the preset in play, then removes it', async () => {
    const calls = mockAutoExports([
      { id: 's-other', projectId: 'proj-1', presetId: 'someone-else', haltAt: 'warn', approveLoss: false, active: true },
    ]);
    render(<StudioAutoExportToggle projectId="proj-1" preset={NIGHTLY} presetsHref="/presets" />);
    const toggle = (await screen.findByTestId('studio-auto-export-toggle')) as HTMLInputElement;
    await waitFor(() => expect(toggle).not.toBeDisabled());
    expect(toggle.checked).toBe(false);
    expect(calls[0].url).toBe('/api/export/auto-exports?projectId=proj-1');
    expect(screen.getByRole('link', { name: 'Manage on Presets' })).toHaveAttribute('href', '/presets');

    fireEvent.click(toggle);
    await waitFor(() => expect(toggle.checked).toBe(true));
    const post = calls.find((c) => c.init?.method === 'POST')!;
    expect(JSON.parse(String(post.init!.body))).toEqual({ projectId: 'proj-1', preset: 'x1', haltAt: 'critical', approveLoss: false });
    expect(screen.getByText('Halts at critical loss')).toBeInTheDocument();

    fireEvent.click(toggle);
    await waitFor(() => expect(toggle.checked).toBe(false));
    expect(calls.find((c) => c.init?.method === 'DELETE')!.url).toBe('/api/export/auto-exports/s-new');
  });

  it('shows a subscription that already exists, and a refusal', async () => {
    mockAutoExports([{ id: 's1', projectId: 'proj-1', presetId: 'x1', haltAt: 'warn', approveLoss: true, active: false }]);
    render(<StudioAutoExportToggle projectId="proj-1" preset={NIGHTLY} presetsHref="/presets" />);
    const toggle = (await screen.findByTestId('studio-auto-export-toggle')) as HTMLInputElement;
    await waitFor(() => expect(toggle.checked).toBe(true));
    expect(screen.getByText('Delivers whatever the loss (pre-approved) · off')).toBeInTheDocument();
    global.fetch = jest.fn(() =>
      Promise.resolve({ ok: false, status: 403, json: () => Promise.resolve({ success: false, error: 'Needs versions:publish' }) }),
    ) as unknown as typeof fetch;
    fireEvent.click(toggle);
    expect(await screen.findByRole('alert')).toHaveTextContent('Needs versions:publish');
  });
});

// ===========================================================================
// Open in Studio: the link's preset is applied once the targets load
// ===========================================================================

function entry(key: string, label: string): ExportTargetEntry {
  return {
    descriptor: {
      key, format: `${key}-1`, label, description: `Export as ${label}.`, icon: 'file-json', paradigm: 'rest',
      multi_file: false, needs_toolchain: false, available: true, unavailable_reason: null,
    },
    capability_profile: { operations: true },
    options_schema: { properties: { flavor: { type: 'string', default: 'plain' } } },
    default_options: { flavor: 'plain' },
    fidelity: { tier: 'lossless', preserved_percent: 100, total: 1, preserved: 1, dropped: 0, approximated: 0, synthesized: 0 },
  } as ExportTargetEntry;
}

function mockStudio(): void {
  global.fetch = jest.fn((input: unknown) => {
    const url = String(input);
    const ok = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    if (url.includes('/api/export/targets')) {
      return ok({ success: true, artifact: 'proj-petstore', version: null, version_record_id: 'rev-1', version_label: '1.2.0',
        targets: [entry('openapi', 'OpenAPI 3.1'), entry('graphql', 'GraphQL SDL')] });
    }
    if (url.startsWith('/api/export/presets')) {
      return ok({ success: true, data: { presets: [
        { id: 'one', name: 'just-graphql', description: null, targets: [{ target: 'graphql', options: { flavor: 'fancy' } }],
          deliveryProfileId: null, deliveryProfileName: null, deliveryProfileIds: [], deliveryProfileNames: [] },
      ] } });
    }
    return Promise.resolve({ ok: false, json: () => Promise.resolve({ success: false }) });
  }) as unknown as typeof fetch;
}

describe('Open in Studio with a preset', () => {
  it.each([['by id', 'one'], ['by name', 'just-graphql']])('applies the link’s preset %s', async (_how, ref) => {
    mockStudio();
    render(<ExportStudio artifact="proj-petstore" version="rev-1" initialStep="target" initialPreset={ref} workspaceName="Acme" />);
    expect(await screen.findByText('Applied just-graphql.')).toBeInTheDocument();
    const selected = document.querySelector('[data-selected="true"]');
    expect(selected).toHaveTextContent('GraphQL SDL');
  });

  it('explains a preset that no longer exists', async () => {
    mockStudio();
    render(<ExportStudio artifact="proj-petstore" version="rev-1" initialStep="target" initialPreset="gone" workspaceName="Acme" />);
    expect(await screen.findByText(/The preset “gone” in this link no longer exists/)).toBeInTheDocument();
  });
});

/**
 * The docs fixture (`apiome-docs/screens.json`: `export-studio-review-auto-export`): Review's **Save as
 * preset** and **Auto-export on publish** with the saved preset in play and the project subscribed.
 * Written into `e2e/fixtures/hive-export-studio/` when `EXPORT_STUDIO_FIXTURE_DUMP=1`.
 */
describe('the docs fixtures', () => {
  it('writes Review with the preset in play subscribed to every publish', async () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const fs = require('node:fs') as typeof import('node:fs');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const path = require('node:path') as typeof import('node:path');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { liveMarkup } = require('./helpers/a11y-fixture-dump') as typeof import('./helpers/a11y-fixture-dump');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { Page, PageBody } = require('@/app/components/shell/pageChrome');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { SavePresetForm } = require('@/app/components/ade/export-studio/presets/ExportPresetControls');
    mockAutoExports([{ id: 's1', projectId: 'proj-1', projectName: 'Orders API', presetId: 'x1', presetName: 'nightly-sync',
      haltAt: 'critical', approveLoss: false, active: true }]);
    const { container } = render(
      <Page>
        <PageBody>
          <div className="xstd-stack">
            <SavePresetForm targets={NIGHTLY.targets} deliveryProfileIds={['p1', 'p2']} />
            <StudioAutoExportToggle projectId="proj-1" preset={NIGHTLY}
              presetsHref="/ade/dashboard/export/studio?tab=presets" />
          </div>
        </PageBody>
      </Page>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Save as preset' }));
    fireEvent.change(screen.getByLabelText('Preset name'), { target: { value: 'nightly-sync' } });
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Every night, for the data lake' } });
    const toggle = (await screen.findByTestId('studio-auto-export-toggle')) as HTMLInputElement;
    await waitFor(() => expect(toggle.checked).toBe(true));
    const html = liveMarkup(container.querySelector('.page') as HTMLElement);
    expect(html.length).toBeGreaterThan(0);
    if (process.env.EXPORT_STUDIO_FIXTURE_DUMP !== '1') return;
    const out = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-export-studio');
    fs.mkdirSync(out, { recursive: true });
    fs.writeFileSync(path.join(out, 'review-auto-export.html'), `${html}\n`);
  });
});
