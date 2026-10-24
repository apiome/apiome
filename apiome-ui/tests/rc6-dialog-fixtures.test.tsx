/**
 * The Catalog, Projects and Versions dialogs no other suite dumps (RC6-H2, #6209).
 *
 * RC6 releases Catalog, Projects and Versions, and the axe gate (`e2e/a11y/gate.spec.ts`) must
 * hold every screen and dialog of them. The page suites already dump their pages and most of
 * their dialogs; these five overlays were drawn nowhere the gate could reach:
 *
 *   - **Convert to OpenAPI** (`ConversionPreviewDialog`), at a low tier — the warning banner and
 *     the acknowledgement it gates the commit behind;
 *   - **Import to catalog** (`CatalogImportDialog`): the source step, a detected paste, and the
 *     quality step;
 *   - the version **Export** dialog (`ExportDialog`): target, fidelity and emitted steps;
 *   - the **Unpublish** confirm (`ConfirmDialog` with `unpublishVersionConfirm`).
 *
 * Each render is written into `e2e/fixtures/hive-rc6-dialogs/` when `RC6_DIALOGS_FIXTURE_DUMP=1`:
 *
 *     RC6_DIALOGS_FIXTURE_DUMP=1 npx jest tests/rc6-dialog-fixtures.test.tsx
 *
 * Without the variable every render still runs, and jest-axe checks its structure (names, roles,
 * labels). Colour contrast and target size need a browser: that is the gate, which mounts these
 * dumps in light, dark and high contrast. The suite runs with no preview override, so the
 * dialogs are drawn as RC6 ships them (no **Open in Export Studio**).
 */

import fs from 'node:fs';
import path from 'node:path';
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';
import { jest } from '@jest/globals';

jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({ value, options }: { value?: string; options?: { ariaLabel?: string } }) => (
    <textarea readOnly aria-label={options?.ariaLabel ?? 'Editor content'} value={value ?? ''} />
  ),
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), prefetch: jest.fn() }),
  usePathname: () => '/ade/dashboard/versions',
  useSearchParams: () => new URLSearchParams(),
}));

import { ConversionPreviewDialog } from '../src/app/components/ade/dashboard/catalog/ConversionPreviewDialog';
import { CatalogImportDialog } from '../src/app/components/ade/dashboard/catalog/CatalogImportDialog';
import { ExportDialog } from '../src/app/components/ade/dashboard/export/ExportDialog';
import ConfirmDialog from '../src/app/components/dialogs/ConfirmDialog';
import { unpublishVersionConfirm } from '../src/app/components/ade/versions/versionsModel';
import type { ImportSourceDescriptor } from '../src/app/components/ade/dashboard/importSourceCatalog';

import { mockExportDialogFetch } from './helpers/export-dialog-fixture';

const OUT = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-rc6-dialogs');
const DUMP = process.env.RC6_DIALOGS_FIXTURE_DUMP === '1';

/** Structure only: jsdom cannot compute contrast, and a lone dialog is not a page's regions. */
const AXE_OPTIONS = {
  rules: {
    'color-contrast': { enabled: false },
    region: { enabled: false },
  },
} as const;

/**
 * The open dialog's own element — what the browser gate mounts.
 *
 * @param role `dialog` or `alertdialog`.
 * @returns The Radix content element.
 */
function openDialog(role: 'dialog' | 'alertdialog' = 'dialog'): HTMLElement {
  return screen.getByRole(role);
}

/**
 * Check a dialog's structure with axe, then write it as a fixture when asked.
 *
 * @param name The fixture's file name, without `.html`.
 * @param element The dialog.
 */
async function judgeAndWrite(name: string, element: HTMLElement): Promise<void> {
  expect(await axe(element, AXE_OPTIONS)).toHaveNoViolations();
  if (!DUMP) return;
  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, `${name}.html`), `${element.outerHTML}\n`);
}

/** A response with `ok` and a JSON body. */
const ok = (body: unknown) => Promise.resolve({ ok: true, json: () => Promise.resolve(body) });

beforeAll(() => {
  delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('Convert to OpenAPI', () => {
  /** A low-tier dry run: gaps and a loss, gated behind the acknowledgement. */
  const LOW_TIER = {
    success: true,
    report: {
      score: 41,
      grade: 'F',
      tier: 'low',
      penalty: 59,
      coverage_counts: { present: 1, inferred: 1, missing: 1, 'n/a': 1 },
      items: [
        { key: 'schemas', title: 'Component schemas', coverage: 'present', weight: 5, count: 3, examples: ['#/components/schemas/Order'], reason: 'schemas carried from the source' },
        { key: 'operationId', title: 'Operation ids', coverage: 'inferred', weight: 2, count: 2, examples: [], reason: 'operationIds synthesized from channel names' },
        { key: 'servers', title: 'Servers', coverage: 'missing', weight: 3, count: 0, examples: [], reason: 'source declares no servers' },
        { key: 'responses', title: 'Responses', coverage: 'n/a', weight: 4, count: 0, examples: [], reason: 'a pub/sub source has no responses' },
      ],
      losses: [
        { kind: 'n/a', subject: 'pubsub-action', detail: 'publish/subscribe actions have no OpenAPI representation', pointer: null },
      ],
    },
    openapi: { openapi: '3.1.0', info: { title: 'Orders events' } },
    sourceFormat: 'asyncapi',
  };

  it('draws the low-tier preview with its warning and acknowledgement', async () => {
    global.fetch = jest.fn(() => ok(LOW_TIER)) as unknown as typeof fetch;
    render(
      <ConversionPreviewDialog itemId="cat-1" itemName="Orders events" sourceFormat="asyncapi" open onOpenChange={() => {}} />
    );
    await waitFor(() => expect(screen.getByTestId('conversion-ack')).toBeInTheDocument());
    await judgeAndWrite('convert', openDialog());
  });
});

describe('Import to catalog', () => {
  const SOURCES: ImportSourceDescriptor[] = [
    {
      key: 'raml',
      label: 'RAML',
      description: 'Import a RAML 1.0 API description.',
      icon: 'file-code',
      paradigm: 'rest',
      input_kinds: ['file', 'url', 'paste'],
      supports_live_discovery: false,
      formats: ['raml'],
      available: true,
    },
  ];
  const RAML = '#%RAML 1.0\ntitle: Bookstore API\nversion: v1\n/books:\n  get:\n    description: List all books.\n';
  const DETECTION = {
    matched: true,
    detected: { format: 'raml', confidence: 0.97, reason: '#%RAML 1.0 header', importable: true },
  };
  const PREFLIGHT = {
    ok: true,
    detection: { adapter_key: 'raml', confidence: 0.97, matched: true, importable: true },
    lint: { score: 84, grade: 'B', report_fingerprint: 'fp', severity_counts: { error: 0, warning: 2, info: 1 }, findings: [] },
    style_guide: { guide_id: null, name: 'Apiome defaults', source: 'fallback', fingerprint: 'sg' },
    policy: {
      verdict: 'pass',
      blocking: false,
      source: 'default',
      reason: 'No import quality policy is configured.',
      threshold_score: null,
      allow_override: true,
    },
    cache: { hit: false, key: 'k', content_hash: 'sha' },
  };

  it('draws the source step, a detected paste and the quality step', async () => {
    global.fetch = jest.fn((input: unknown) => {
      const url = String(input);
      if (url.includes('/api/import/sources')) return ok({ success: true, sources: SOURCES });
      if (url.includes('/api/import/detect')) return ok(DETECTION);
      if (url.includes('/api/import/preflight')) return ok({ success: true, ...PREFLIGHT });
      return Promise.resolve({ ok: false, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;

    render(<CatalogImportDialog open onClose={() => {}} onSuccess={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('catalog-import-source-paste')).toBeInTheDocument());
    await judgeAndWrite('catalog-import-source', openDialog());

    fireEvent.click(screen.getByTestId('catalog-import-source-paste'));
    fireEvent.change(screen.getByLabelText('Source content'), { target: { value: RAML } });
    fireEvent.click(screen.getByRole('button', { name: /detect pasted source/i }));
    await waitFor(() => expect(screen.getAllByText(/Auto-detected/i).length).toBeGreaterThan(0));
    await judgeAndWrite('catalog-import-detected', openDialog());

    // Through the routing and options steps to the quality step.
    for (let step = 0; step < 3 && !screen.queryByTestId('import-quality-grade'); step += 1) {
      fireEvent.click(screen.getByRole('button', { name: /^continue$/i }));
      await waitFor(() =>
        expect(
          screen.queryByTestId('import-quality-grade') ?? screen.queryByRole('button', { name: /^continue$/i })
        ).toBeInTheDocument()
      );
    }
    await waitFor(() => expect(screen.getByTestId('import-quality-grade')).toBeInTheDocument());
    await judgeAndWrite('catalog-import-quality', openDialog());
  });
});

describe('the keyboard path into Import to catalog', () => {
  /** The Catalog page opens the importer from a plain button, as this harness does. */
  function Harness() {
    const [open, setOpen] = React.useState(false);
    return (
      <>
        <button type="button" onClick={() => setOpen(true)}>
          Import to catalog
        </button>
        <CatalogImportDialog open={open} onClose={() => setOpen(false)} onSuccess={() => {}} />
      </>
    );
  }

  it('opens from the keyboard, takes focus, and returns it to the button on Escape', async () => {
    global.fetch = jest.fn(() => ok({ success: true, sources: [] })) as unknown as typeof fetch;
    const user = userEvent.setup();
    render(<Harness />);
    const trigger = screen.getByRole('button', { name: 'Import to catalog' });
    trigger.focus();
    await user.keyboard('{Enter}');
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });
});

describe('the version Export dialog', () => {
  it('draws the target, fidelity and emitted steps', async () => {
    global.fetch = mockExportDialogFetch() as unknown as typeof fetch;
    render(<ExportDialog open onClose={() => {}} artifact="proj-petstore" artifactLabel="Pet Store API" version="rev-1" />);

    const chooseTarget = await screen.findByTestId('export-dialog-choose-target');
    await waitFor(() => expect(chooseTarget).toBeEnabled());
    expect(screen.queryByText('Open in Export Studio')).toBeNull();
    fireEvent.click(chooseTarget);
    await waitFor(() => expect(screen.getByTestId('export-target-proto')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('export-target-proto'));
    await judgeAndWrite('export-target', openDialog());

    fireEvent.click(screen.getByTestId('export-dialog-continue'));
    await waitFor(() => expect(screen.getByTestId('export-ack')).toBeInTheDocument());
    await judgeAndWrite('export-fidelity', openDialog());

    fireEvent.click(screen.getByTestId('export-ack'));
    const exportButton = screen.getByTestId('export-dialog-export');
    await waitFor(() => expect(exportButton).toBeEnabled());
    fireEvent.click(exportButton);
    await waitFor(() => expect(screen.getByTestId('export-dialog-emitted')).toBeInTheDocument());
    await judgeAndWrite('export-emitted', openDialog());
  });
});

describe('the Unpublish confirm', () => {
  it('draws the destructive confirm the Versions row menu opens', async () => {
    render(
      <ConfirmDialog open {...unpublishVersionConfirm({ version_id: '1.2.0' })} onConfirm={() => {}} onCancel={() => {}} />
    );
    expect(screen.getByRole('button', { name: 'Unpublish' })).toBeInTheDocument();
    await judgeAndWrite('unpublish-confirm', openDialog('alertdialog'));
  });
});
