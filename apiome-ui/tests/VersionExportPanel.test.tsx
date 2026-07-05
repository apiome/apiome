/**
 * VersionExportPanel — the version-scoped export entry point (MFX-6.5, #3859).
 *
 * Covers the ticket's acceptance criteria for the version view:
 *  1. The fidelity pre-summary renders from a mocked `GET /api/export/targets`, grouping
 *     targets into best-fidelity (lossless) vs lossy (lossy, then types-only) rows.
 *  2. "Export this version" hands off to the caller (which opens the ExportDialog).
 *  3. The recent-exports list renders this version's recorded exports with fidelity % badges
 *     and relative times, newest first, and shows an empty state when nothing was exported.
 *  4. Nothing is fetched while the panel is inactive, and a fetch failure surfaces the error.
 */

import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

import { VersionExportPanel } from '../src/app/components/ade/dashboard/export/VersionExportPanel';
import type { ExportTargetsResponse } from '../src/app/components/ade/dashboard/export/exportTargetCatalog';
import {
  recentExportsStorageKey,
  type RecentExport,
} from '../src/app/components/ade/dashboard/export/recentExports';

const ARTIFACT = 'proj-petstore';
const VERSION = 'rev-1';

function makeTarget(
  key: string,
  label: string,
  tier: 'lossless' | 'lossy' | 'types-only',
  preserved_percent: number,
): ExportTargetsResponse['targets'][number] {
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
      preserved_percent,
      total: 58,
      preserved: Math.round((preserved_percent / 100) * 58),
      dropped: 0,
      approximated: 0,
      synthesized: 0,
    },
  };
}

/** Lossless OpenAPI + TypeSpec, lossy GraphQL, types-only Avro — mirrors the mockup's rows. */
const TARGETS: ExportTargetsResponse = {
  artifact: ARTIFACT,
  version: VERSION,
  version_record_id: VERSION,
  version_label: '1.2.0',
  targets: [
    makeTarget('avro', 'Avro', 'types-only', 31),
    makeTarget('graphql', 'GraphQL SDL', 'lossy', 82),
    makeTarget('openapi', 'OpenAPI 3.1', 'lossless', 100),
    makeTarget('typespec', 'TypeSpec', 'lossless', 100),
  ],
};

function mockFetch(response: ExportTargetsResponse | null = TARGETS): jest.Mock {
  return jest.fn(() =>
    response
      ? Promise.resolve({ ok: true, json: () => Promise.resolve(response) })
      : Promise.resolve({ ok: false, json: () => Promise.resolve({ error: 'Targets unavailable.' }) }),
  ) as unknown as jest.Mock;
}

function seedRecentExports(entries: RecentExport[]): void {
  localStorage.setItem(recentExportsStorageKey(ARTIFACT, VERSION), JSON.stringify(entries));
}

describe('VersionExportPanel — fidelity pre-summary (MFX-6.5)', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('groups targets into best-fidelity vs lossy rows for this source', async () => {
    global.fetch = mockFetch() as unknown as typeof fetch;
    render(
      <VersionExportPanel artifact={ARTIFACT} version={VERSION} active onOpenExport={jest.fn()} />,
    );

    await waitFor(() =>
      expect(screen.getByTestId('version-export-presummary')).toBeInTheDocument(),
    );
    expect(screen.getByText('Best-fidelity targets')).toBeInTheDocument();
    expect(screen.getByText('Lossy targets')).toBeInTheDocument();

    const [bestRow, lossyRow] = screen
      .getByTestId('version-export-presummary')
      .querySelectorAll(':scope > div');
    expect(bestRow).toHaveTextContent('OpenAPI 3.1');
    expect(bestRow).toHaveTextContent('TypeSpec');
    expect(bestRow).not.toHaveTextContent('GraphQL SDL');
    // Lossy row lists lossy before types-only (amber before red, per the mockup).
    expect(lossyRow?.textContent?.indexOf('GraphQL SDL')).toBeLessThan(
      lossyRow?.textContent?.indexOf('Avro') ?? -1,
    );
  });

  it('does not fetch while inactive', () => {
    const fetchMock = mockFetch();
    global.fetch = fetchMock as unknown as typeof fetch;
    render(
      <VersionExportPanel
        artifact={ARTIFACT}
        version={VERSION}
        active={false}
        onOpenExport={jest.fn()}
      />,
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('surfaces a targets load failure', async () => {
    global.fetch = mockFetch(null) as unknown as typeof fetch;
    render(
      <VersionExportPanel artifact={ARTIFACT} version={VERSION} active onOpenExport={jest.fn()} />,
    );
    await waitFor(() => expect(screen.getByText('Targets unavailable.')).toBeInTheDocument());
    expect(screen.queryByTestId('version-export-presummary')).not.toBeInTheDocument();
  });

  it('hands "Export this version" off to the caller', async () => {
    const onOpenExport = jest.fn();
    global.fetch = mockFetch() as unknown as typeof fetch;
    render(
      <VersionExportPanel artifact={ARTIFACT} version={VERSION} active onOpenExport={onOpenExport} />,
    );

    fireEvent.click(screen.getByRole('button', { name: /export this version/i }));
    expect(onOpenExport).toHaveBeenCalledTimes(1);
  });
});

describe('VersionExportPanel — recent exports (MFX-6.5)', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('shows an empty state when this version was never exported', async () => {
    global.fetch = mockFetch() as unknown as typeof fetch;
    render(
      <VersionExportPanel artifact={ARTIFACT} version={VERSION} active onOpenExport={jest.fn()} />,
    );
    expect(screen.getByText('No exports of this version yet.')).toBeInTheDocument();
    expect(screen.queryByTestId('version-recent-exports')).not.toBeInTheDocument();
  });

  it('lists recorded exports with fidelity badges and relative times, newest first', async () => {
    const now = Date.now();
    seedRecentExports([
      {
        targetKey: 'graphql',
        targetLabel: 'GraphQL SDL',
        tier: 'lossy',
        preservedPercent: 82,
        filename: 'petstore.graphql',
        exportedAt: now - 2 * 60 * 60 * 1000,
      },
      {
        targetKey: 'openapi',
        targetLabel: 'OpenAPI 3.1',
        tier: 'lossless',
        preservedPercent: 100,
        filename: 'petstore.json',
        exportedAt: now - 3 * 24 * 60 * 60 * 1000,
      },
    ]);
    global.fetch = mockFetch() as unknown as typeof fetch;
    render(
      <VersionExportPanel artifact={ARTIFACT} version={VERSION} active onOpenExport={jest.fn()} />,
    );

    const list = screen.getByTestId('version-recent-exports');
    const rows = Array.from(list.querySelectorAll('li')).map((li) => li.textContent ?? '');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toContain('GraphQL SDL');
    expect(rows[0]).toContain('82% fidelity');
    expect(rows[0]).toContain('2h ago');
    expect(rows[1]).toContain('OpenAPI 3.1');
    expect(rows[1]).toContain('lossless');
    expect(rows[1]).toContain('3d ago');
  });

  it('re-reads the list when refreshToken bumps', async () => {
    global.fetch = mockFetch() as unknown as typeof fetch;
    const { rerender } = render(
      <VersionExportPanel
        artifact={ARTIFACT}
        version={VERSION}
        active
        onOpenExport={jest.fn()}
        refreshToken={0}
      />,
    );
    expect(screen.getByText('No exports of this version yet.')).toBeInTheDocument();

    seedRecentExports([
      {
        targetKey: 'openapi',
        targetLabel: 'OpenAPI 3.1',
        tier: 'lossless',
        preservedPercent: 100,
        filename: 'petstore.json',
        exportedAt: Date.now(),
      },
    ]);
    rerender(
      <VersionExportPanel
        artifact={ARTIFACT}
        version={VERSION}
        active
        onOpenExport={jest.fn()}
        refreshToken={1}
      />,
    );
    expect(screen.getByTestId('version-recent-exports')).toHaveTextContent('OpenAPI 3.1');
  });
});
