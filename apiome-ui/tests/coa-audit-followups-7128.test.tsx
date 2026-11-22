/**
 * COA-4.3c (#7128) — the Catalog and Projects audit's S3/S4 follow-ups.
 *
 * One file per ticket because each fix is small and they share no fixture:
 *  - the overflow-edge decision behind the Versions tab strip's and the catalog kind tiles' fade;
 *  - the import done step: the stored item's id off the job poll, and one dismiss button;
 *  - the Overview's "not captured yet" note, dropped when the parsed model is already known;
 *  - a finding's location as the resolved source line, and centring that line inside the raw
 *    viewer only;
 *  - the Convert summary leaving out the `n/a` "Source OpenAPI version" row;
 *  - the Versions row menu no longer hiding the page from assistive tech while it is open.
 */

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, it, jest } from '@jest/globals';

import { overflowEdges } from '../src/app/components/ui/useOverflowEdges';
import {
  ImportWizardFooter,
  catalogImportFooterFor,
  storedCatalogItemId,
  type CatalogImportFooterState,
} from '../src/app/components/ade/import';
import { catalogItemHrefForId } from '../src/app/components/ade/catalog/catalogModel';
import { CatalogItemOverview } from '../src/app/components/ade/catalog/detail/CatalogItemOverview';
import type { CatalogParsedGroup } from '../src/app/components/ade/dashboard/catalog/CatalogParsedModel';
import { centerWithinScroller, findingLocationLabel } from '../src/app/utils/import-preflight';
import {
  isIrrelevantSourceNote,
  partitionChecklist,
  type ChecklistItem,
} from '../src/app/utils/conversion-fidelity';
import { VersionRowMenu } from '../src/app/components/ade/versions/VersionRowMenu';
import type { Version, VersionRowMenuContext } from '../src/app/components/ade/versions/versionsModel';

describe('overflowEdges', () => {
  it('reports no hidden edge when the strip fits', () => {
    expect(overflowEdges({ scrollLeft: 0, scrollWidth: 800, clientWidth: 800 })).toEqual({
      start: false,
      end: false,
    });
  });

  it('reports the end edge when tabs run past the strip', () => {
    expect(overflowEdges({ scrollLeft: 0, scrollWidth: 1200, clientWidth: 800 })).toEqual({
      start: false,
      end: true,
    });
  });

  it('reports both edges mid-scroll and only the start at the end', () => {
    expect(overflowEdges({ scrollLeft: 200, scrollWidth: 1200, clientWidth: 800 })).toEqual({
      start: true,
      end: true,
    });
    expect(overflowEdges({ scrollLeft: 400, scrollWidth: 1200, clientWidth: 800 })).toEqual({
      start: true,
      end: false,
    });
  });

  it('absorbs a sub-pixel rounding difference and an RTL negative scroll', () => {
    expect(overflowEdges({ scrollLeft: 0, scrollWidth: 801, clientWidth: 800 }).end).toBe(false);
    expect(overflowEdges({ scrollLeft: -200, scrollWidth: 1200, clientWidth: 800 })).toEqual({
      start: true,
      end: true,
    });
  });
});

describe('import done step', () => {
  it('reads the stored item id off the job poll result', () => {
    expect(storedCatalogItemId({ state: 'completed', result: { project_id: 'p-1' } })).toBe('p-1');
  });

  it.each([
    ['no payload', null],
    ['no result', { state: 'completed' }],
    ['a null result', { result: null }],
    ['a blank id', { result: { project_id: '  ' } }],
    ['a non-string id', { result: { project_id: 42 } }],
  ])('returns null for %s', (_label, payload) => {
    expect(storedCatalogItemId(payload)).toBeNull();
  });

  it('links the item by its encoded id', () => {
    expect(catalogItemHrefForId('a b/c')).toBe('/ade/dashboard/catalog/a%20b%2Fc');
  });

  const base: CatalogImportFooterState = {
    step: 'import',
    storing: false,
    done: true,
    canContinueFromDetect: true,
    adapterUnavailable: false,
    destination: 'catalog',
    canStoreCatalog: true,
  };

  it('keeps only Done once the item is stored', () => {
    const footer = catalogImportFooterFor(base);
    expect(footer.primary).toEqual({ label: 'Done', disabled: false });
    expect(footer.cancel.hidden).toBe(true);
  });

  it('still offers the dismiss button while the store runs', () => {
    const footer = catalogImportFooterFor({ ...base, done: false, storing: true });
    expect(footer.primary).toBeNull();
    expect(footer.cancel.hidden).toBeFalsy();
  });

  it('does not draw a hidden dismiss button', () => {
    render(
      <ImportWizardFooter
        footer={catalogImportFooterFor(base)}
        onBack={jest.fn()}
        onCancel={jest.fn()}
        onPrimary={jest.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();
  });
});

describe('CatalogItemOverview — the summary-missing note', () => {
  const EMPTY_SUMMARY = { services: null, operations: null, types: null, channels: null };
  const PARSED: CatalogParsedGroup[] = [
    {
      title: 'Operations',
      entities: [
        { name: 'listBooks', tag: 'QUERY', fields: [] },
        { name: 'getBook', tag: 'QUERY', fields: [] },
      ],
    },
  ];

  function renderOverview(parsed: CatalogParsedGroup[]) {
    return render(
      <CatalogItemOverview
        summary={EMPTY_SUMMARY}
        parsed={parsed}
        summaryNote={null}
        source={null}
        qualityScore={null}
        qualityGrade={null}
        onOpenLint={jest.fn()}
        onOpenSource={jest.fn()}
      />,
    );
  }

  it('says the summary is not captured when nothing is known', () => {
    renderOverview([]);
    expect(screen.getByTestId('catalog-detail-summary-missing')).toBeInTheDocument();
  });

  it('drops the note when the parsed model already lists operations', () => {
    renderOverview(PARSED);
    expect(screen.queryByTestId('catalog-detail-summary-missing')).not.toBeInTheDocument();
  });

  it('keeps the note when the parsed groups are all empty', () => {
    renderOverview([{ title: 'Operations', entities: [] }]);
    expect(screen.getByTestId('catalog-detail-summary-missing')).toBeInTheDocument();
  });
});

describe('finding location', () => {
  it('shows the resolved source line rather than the model path', () => {
    expect(
      findingLocationLabel('services.Books 2026-11-21.operations.GET /books/{bookId}.messages', 42),
    ).toBe('Line 42');
  });

  it('falls back to the path, then to the document root', () => {
    expect(findingLocationLabel('/paths/~1pets/get', null)).toBe('/paths/~1pets/get');
    expect(findingLocationLabel('', null)).toBe('document root');
  });

  it('centres the line by scrolling only the viewer', () => {
    const container = document.createElement('div');
    const target = document.createElement('div');
    Object.defineProperty(container, 'clientHeight', { value: 380 });
    container.getBoundingClientRect = () => ({ top: 100, height: 380 }) as DOMRect;
    target.getBoundingClientRect = () => ({ top: 700, height: 20 }) as DOMRect;
    container.scrollTop = 50;

    centerWithinScroller(container, target);

    // 600 px below the viewer's top, minus half of (380 − 20) to centre it, on top of 50.
    expect(container.scrollTop).toBe(50 + 600 - 180);
  });

  it('never scrolls the viewer above its start', () => {
    const container = document.createElement('div');
    const target = document.createElement('div');
    Object.defineProperty(container, 'clientHeight', { value: 380 });
    container.getBoundingClientRect = () => ({ top: 100, height: 380 }) as DOMRect;
    target.getBoundingClientRect = () => ({ top: 104, height: 20 }) as DOMRect;
    container.scrollTop = 0;

    centerWithinScroller(container, target);
    expect(container.scrollTop).toBe(0);
  });
});

describe('Convert summary', () => {
  const item = (overrides: Partial<ChecklistItem>): ChecklistItem => ({
    key: 'responses',
    title: 'Responses',
    coverage: 'missing',
    weight: 5,
    count: 1,
    examples: [],
    reason: '',
    ...overrides,
  });

  it('leaves out the n/a Source OpenAPI version row for a non-OpenAPI source', () => {
    const note = item({
      key: 'source.openapi-version',
      title: 'Source OpenAPI version',
      coverage: 'n/a',
      weight: 0,
      count: 0,
      reason: 'source is not OpenAPI 3.2',
    });
    expect(isIrrelevantSourceNote(note)).toBe(true);
    const { provided, missing } = partitionChecklist([note, item({})]);
    expect(provided).toEqual([]);
    expect(missing.map((row) => row.key)).toEqual(['responses']);
  });

  it('keeps the 3.2 → 3.1 downgrade row', () => {
    const downgrade = item({ key: 'source.openapi-version', coverage: 'partial' });
    expect(isIrrelevantSourceNote(downgrade)).toBe(false);
    expect(partitionChecklist([downgrade]).missing).toEqual([downgrade]);
  });

  it('keeps other n/a rows', () => {
    const other = item({ key: 'webhooks', coverage: 'n/a' });
    expect(partitionChecklist([other]).missing).toEqual([other]);
  });
});

describe('VersionRowMenu', () => {
  const VERSION: Version = {
    id: 'rev-1',
    project_id: 'proj-1',
    creator_id: 'user-1',
    version_id: '1.0.0',
    shortMessage: null,
    changelog: null,
    enabled: true,
    published: false,
    deleted_at: null,
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
    published_at: null,
    creator_name: 'A Tester',
    creator_email: 'tester@example.com',
  };
  const CONTEXT: VersionRowMenuContext = {
    headRevisionId: 'rev-1',
    effectiveIsAdmin: true,
    currentUserId: 'user-1',
    hasBranches: false,
    schemaFrozen: false,
    publishable: true,
    freezing: false,
    gitlike: { flagOn: false, visible: false, marked: false, enabled: false },
  };

  it('leaves the page outside the menu exposed while it is open (no aria-hidden-focus)', async () => {
    render(
      <div>
        <header data-testid="page-chrome">
          <button type="button">Header action</button>
        </header>
        <VersionRowMenu version={VERSION} context={CONTEXT} onAction={jest.fn()} />
      </div>,
    );
    fireEvent.keyDown(screen.getByTestId('versions-row-menu-rev-1'), { key: 'Enter' });
    expect(await screen.findAllByRole('menuitem')).not.toHaveLength(0);

    // A modal Radix menu marks every sibling of its portal `aria-hidden` while their controls
    // stay focusable; the non-modal row menu leaves them alone.
    expect(document.querySelectorAll('[aria-hidden="true"] button')).toHaveLength(0);
    expect(screen.getByTestId('page-chrome').closest('[aria-hidden="true"]')).toBeNull();
  });
});
