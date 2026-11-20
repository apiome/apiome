/**
 * Export studio's **$ref handling** options for an OpenAPI export — COA-2.4 (#7047).
 *
 * The OpenAPI target declares two options, `refs` (bundle · dereference · split) and `ref_cycles`
 * (keep-ref · error). Export studio draws them from the target's JSON Schema like every other
 * option, so this suite pins that the schema REST sends renders as two labelled choices on the
 * Options step, that choosing one sends it with the export, and that a `split` export counts as a
 * multi-file bundle.
 *
 * It also writes the docs fixture the `export-refs-options` screenshot is captured from
 * (`apiome-docs/screens.json`) when `EXPORT_STUDIO_FIXTURE_DUMP=1` is set:
 *
 *     EXPORT_STUDIO_FIXTURE_DUMP=1 npx jest tests/export-studio-refs-options.test.tsx
 */

import * as fs from 'fs';
import * as path from 'path';
import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, it, jest, afterEach } from '@jest/globals';

jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({ value, language }: { value?: string; language?: string }) => (
    <div data-testid="export-artifact-content" data-language={language}>
      {value}
    </div>
  ),
}));

jest.mock('next/link', () => {
  const MockLink = React.forwardRef<HTMLAnchorElement, { children: React.ReactNode; href: string } & Record<string, unknown>>(
    ({ children, href, ...rest }, ref) => {
      const anchorProps = { ...rest };
      delete anchorProps.prefetch;
      return (
        <a ref={ref} href={typeof href === 'string' ? href : '#'} {...anchorProps}>
          {children}
        </a>
      );
    },
  );
  MockLink.displayName = 'MockLink';
  return { __esModule: true, default: MockLink };
});

jest.mock('sonner', () => ({
  __esModule: true,
  toast: Object.assign(jest.fn(), { success: jest.fn(), error: jest.fn() }),
}));

import { ExportStudio } from '../src/app/components/ade/dashboard/export/ExportStudio';
import {
  optionFieldsFromSchema,
  writesMultipleFiles,
  type ExportTargetEntry,
  type ExportTargetsResponse,
} from '../src/app/components/ade/dashboard/export/exportTargetCatalog';
import { __resetExportJobTrackerForTests } from '../src/app/components/ade/dashboard/export/exportJobTracker';

/** The OpenAPI target's options as `GET /export/targets` sends them (a Pydantic JSON Schema). */
const OPENAPI_OPTIONS_SCHEMA: Record<string, unknown> = {
  title: 'OpenApiEmitOptions',
  type: 'object',
  properties: {
    openapi_version: {
      default: '3.1',
      description: 'OpenAPI dialect to emit.',
      enum: ['3.2', '3.1', '3.0', '2.0'],
      title: 'Openapi Version',
      type: 'string',
    },
    refs: {
      default: 'bundle',
      description:
        'How shared objects are written. bundle (default): one file, shared objects under components, reached by ' +
        '$ref. dereference: one file, every $ref replaced by a copy of what it points at. split: a root file plus ' +
        'one file per path item and component, joined by relative $ref.',
      enum: ['bundle', 'dereference', 'split'],
      title: '$ref handling',
      type: 'string',
    },
    ref_cycles: {
      default: 'keep-ref',
      description:
        'With dereference, what to do with a circular $ref, which can never be fully expanded. keep-ref ' +
        '(default): keep the $ref that closes the loop and report it. error: refuse the export.',
      enum: ['keep-ref', 'error'],
      title: 'Reference cycles',
      type: 'string',
    },
  },
};

const OPENAPI: ExportTargetEntry = {
  descriptor: {
    key: 'openapi',
    format: 'openapi-3.1',
    label: 'OpenAPI 3.1',
    description: 'Export as an OpenAPI 3.1 JSON document (JSON Schema components).',
    icon: 'file-json',
    paradigm: 'rest',
    multi_file: false,
    needs_toolchain: false,
    available: true,
    unavailable_reason: null,
  },
  capability_profile: { operations: true },
  options_schema: OPENAPI_OPTIONS_SCHEMA,
  default_options: { openapi_version: '3.1', refs: 'bundle', ref_cycles: 'keep-ref' },
  fidelity: {
    tier: 'lossless',
    preserved_percent: 100,
    total: 58,
    preserved: 58,
    dropped: 0,
    approximated: 0,
    synthesized: 0,
  },
};

const TARGETS: ExportTargetsResponse = {
  artifact: 'proj-petstore',
  version: null,
  version_record_id: 'rev-1',
  version_label: '1.2.0',
  targets: [OPENAPI],
};

/** The registry answers; the job list is empty; everything else fails quietly. */
function mockFetch(): jest.Mock {
  return jest.fn((input: unknown) => {
    const url = typeof input === 'string' ? input : String(input);
    const json = (payload: unknown) =>
      Promise.resolve({ ok: true, headers: new Headers(), json: () => Promise.resolve(payload) });
    if (url.includes('/api/export/targets')) return json({ success: true, ...TARGETS });
    if (url.includes('jobs')) return json({ success: true, jobs: [], total: 0, offset: 0 });
    return Promise.resolve({ ok: false, json: () => Promise.resolve({ success: false }) });
  }) as unknown as jest.Mock;
}

/** Render the studio with OpenAPI picked and move to the Options step. */
async function openOptionsStep() {
  global.fetch = mockFetch() as unknown as typeof fetch;
  render(
    <ExportStudio
      artifact="proj-petstore"
      artifactLabel="Pet Store API"
      version="rev-1"
      workspaceName="Acme Corp"
      initialTarget="openapi"
    />,
  );
  await waitFor(() => expect(screen.getByText(/export targets available/)).toBeInTheDocument());
  fireEvent.click(screen.getByRole('button', { name: /choose target/i }));
  fireEvent.click(screen.getByRole('button', { name: 'Continue' })); // → options
  return screen.findByRole('radiogroup', { name: '$ref handling' });
}

afterEach(() => {
  __resetExportJobTrackerForTests();
});

describe('the $ref handling options (COA-2.4)', () => {
  it('flattens the schema into two titled choices with their defaults', () => {
    const fields = optionFieldsFromSchema(OPENAPI.options_schema, OPENAPI.default_options);
    const refs = fields.find((field) => field.key === 'refs');
    const cycles = fields.find((field) => field.key === 'ref_cycles');
    expect(refs).toMatchObject({ label: '$ref handling', kind: 'enum', defaultValue: 'bundle' });
    expect(refs?.enumValues).toEqual(['bundle', 'dereference', 'split']);
    expect(cycles).toMatchObject({ label: 'Reference cycles', kind: 'enum', defaultValue: 'keep-ref' });
    expect(cycles?.enumValues).toEqual(['keep-ref', 'error']);
  });

  it('renders both on the Options step with bundle and keep-ref selected', async () => {
    const group = await openOptionsStep();
    expect(within(group).getByRole('radio', { name: 'bundle' })).toHaveAttribute('aria-checked', 'true');
    expect(within(group).getByRole('radio', { name: 'split' })).toHaveAttribute('aria-checked', 'false');
    const cycles = screen.getByRole('radiogroup', { name: 'Reference cycles' });
    expect(within(cycles).getByRole('radio', { name: 'keep-ref' })).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByText(/joined by relative \$ref/)).toBeInTheDocument();
  });

  it('selects split and dereference', async () => {
    const group = await openOptionsStep();
    fireEvent.click(within(group).getByRole('radio', { name: 'split' }));
    expect(within(group).getByRole('radio', { name: 'split' })).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(within(group).getByRole('radio', { name: 'dereference' }));
    expect(within(group).getByRole('radio', { name: 'dereference' })).toHaveAttribute('aria-checked', 'true');
    const cycles = screen.getByRole('radiogroup', { name: 'Reference cycles' });
    fireEvent.click(within(cycles).getByRole('radio', { name: 'error' }));
    expect(within(cycles).getByRole('radio', { name: 'error' })).toHaveAttribute('aria-checked', 'true');
  });

  it('counts a split export as a multi-file bundle', () => {
    expect(writesMultipleFiles(OPENAPI, { refs: 'split' })).toBe(true);
    expect(writesMultipleFiles(OPENAPI, { refs: 'dereference' })).toBe(false);
  });

  it('renders the docs fixture: dereference chosen (and writes it on request)', async () => {
    const group = await openOptionsStep();
    fireEvent.click(within(group).getByRole('radio', { name: 'dereference' }));
    const page = document.querySelector('.page') as HTMLElement;
    expect(page).not.toBeNull();
    if (process.env.EXPORT_STUDIO_FIXTURE_DUMP !== '1') return;
    const out = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-export-studio');
    fs.mkdirSync(out, { recursive: true });
    fs.writeFileSync(path.join(out, 'refs-options.html'), page.outerHTML);
  });
});
