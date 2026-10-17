/**
 * Layout-stable loading placeholders for the Catalog (MFI-28.6, #4122).
 *
 * Pins three things about every placeholder in `CatalogSkeletons`:
 *
 *   1. **It is the shape of the content.** The card placeholder is drawn on the real card's
 *      frame classes, checked here against a rendered `CatalogCard`; the detail placeholder
 *      draws the real header, an eight-tab strip and one tile per API-surface tile.
 *   2. **It is announced once, and only as text.** Each region is a polite `role="status"`
 *      naming what is loading; the bars themselves are `aria-hidden`.
 *   3. **It is not a spinner.** Nothing animates as `animate-spin`.
 */

import React from 'react';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import {
  CATALOG_CARD_SKELETON_COUNT,
  CatalogAnalysisSkeleton,
  CatalogCard,
  CatalogCardGridSkeleton,
  CatalogCardSkeleton,
  CatalogCodeSkeleton,
  CatalogDetailSkeleton,
  CatalogLintSkeleton,
  CatalogTimelineSkeleton,
  type CatalogItem,
} from '../src/app/components/ade/catalog';
import { CATALOG_SURFACE_TILES } from '../src/app/components/ade/catalog/detail/catalogItemView';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn() }),
  usePathname: () => '/ade/dashboard/catalog',
  useSearchParams: () => new URLSearchParams(),
}));

/** A live catalog item, enough for `CatalogCard` to draw every region. */
const ITEM: CatalogItem = {
  id: '4d1e9a00-0000-4000-8000-000000000001',
  tenant_id: 't-acme',
  name: 'Ledger Graph',
  slug: 'ledger-graph',
  description: 'Double-entry ledger schema exposed to finance tooling.',
  enabled: true,
  deleted_at: null,
  created_at: '2026-06-01T00:00:00.000Z',
  updated_at: '2026-08-14T16:02:00.000Z',
  creator_name: 'Ada Lovelace',
  creator_email: 'ada@acme.io',
  metadata: null,
  qualityScore: 91,
  qualityGrade: 'A',
  versionsCount: 3,
  publishable: false,
  sourceFormat: 'graphql',
  protocol: 'graph',
  formatMetadata: { inputKind: 'file', fileName: 'ledger.graphql' },
};

/** No-op handlers for the card's menu and orbs. */
const HANDLERS = {
  onOpenDetail: jest.fn(),
  onOpenVersions: jest.fn(),
  onOpenLint: jest.fn(),
  onExport: jest.fn(),
  onConvert: jest.fn(),
  onDelete: jest.fn(),
  onRestore: jest.fn(),
  onPermanentDelete: jest.fn(),
  onOpenQuality: jest.fn(),
};

/**
 * The `cat-card` frame classes under a root, i.e. every `cat-card*` class except the
 * interactive-only ones a placeholder must not have (`__link`, `__actions`, `__above`, the
 * promotion strip that only converted items draw).
 */
function frameClasses(root: Element): string[] {
  const classes = new Set<string>();
  for (const node of [root, ...root.querySelectorAll('*')]) {
    for (const name of node.classList) {
      if (!name.startsWith('cat-card')) continue;
      if (/__(link|actions|above|promotion|versions|stamp|creator-name|name|id|link)$/.test(name))
        continue;
      classes.add(name);
    }
  }
  return [...classes].sort();
}

/** Nothing in the region is a spinner. */
function expectNoSpinner(root: Element) {
  expect(root.querySelector('.animate-spin, [class*="animate-spin"]')).toBeNull();
}

describe('CatalogCardSkeleton', () => {
  it('is drawn on the same frame as a real card, so the card lands in its box', () => {
    const { container: real } = render(
      <CatalogCard item={ITEM} qualityHistory={[]} {...HANDLERS} />
    );
    const { container: placeholder } = render(<CatalogCardSkeleton />);
    const card = real.querySelector('.cat-card')!;
    const skeleton = placeholder.querySelector('.cat-card')!;
    expect(frameClasses(skeleton)).toEqual(frameClasses(card));
  });

  it('is decoration only', () => {
    render(<CatalogCardSkeleton />);
    expect(screen.getByTestId('catalog-card-skeleton')).toHaveAttribute('aria-hidden', 'true');
  });
});

describe('CatalogCardGridSkeleton', () => {
  it('draws the cards view grid inside one polite live region', () => {
    render(<CatalogCardGridSkeleton />);
    const region = screen.getByTestId('catalog-cards-loading');
    expect(region).toHaveAttribute('role', 'status');
    expect(region).toHaveAttribute('aria-busy', 'true');
    expect(region).toHaveTextContent('Loading catalog…');
    expect(region.querySelector('.cat-grid')).not.toBeNull();
    expect(within(region).getAllByTestId('catalog-card-skeleton')).toHaveLength(
      CATALOG_CARD_SKELETON_COUNT
    );
    expectNoSpinner(region);
  });
});

describe('CatalogDetailSkeleton', () => {
  it('draws the page header, an eight-tab strip and one tile per surface tile', () => {
    const { container } = render(<CatalogDetailSkeleton />);
    expect(container.querySelector('.page-header')).not.toBeNull();
    expect(container.querySelector('.cid-tabs')?.children).toHaveLength(8);
    expect(container.querySelectorAll('.cid-tile')).toHaveLength(CATALOG_SURFACE_TILES.length);
    expect(container.querySelector('.cid-overview__aside')).not.toBeNull();
  });

  it('names what is loading in its live region and draws no spinner', () => {
    const { container } = render(<CatalogDetailSkeleton />);
    const region = screen.getByTestId('catalog-detail-loading');
    expect(region).toHaveAttribute('role', 'status');
    expect(region).toHaveTextContent('Loading catalog item…');
    expectNoSpinner(container);
  });
});

describe('the pane presets', () => {
  it.each([
    ['lint', <CatalogLintSkeleton key="l" message="Loading lint report…" testId="pane" />],
    ['timeline', <CatalogTimelineSkeleton key="t" message="Loading versions…" testId="pane" />],
    [
      'analysis',
      <CatalogAnalysisSkeleton key="a" message="Loading the analysis…" testId="pane" />,
    ],
    ['code', <CatalogCodeSkeleton key="c" message="Loading source…" testId="pane" />],
  ])('the %s preset keeps the pane test id, announces, and does not spin', (_name, node) => {
    render(node);
    const region = screen.getByTestId('pane');
    expect(region).toHaveAttribute('role', 'status');
    expect(region.textContent).toMatch(/Loading/);
    expect(region.querySelectorAll('.hive-skeleton').length).toBeGreaterThan(0);
    expectNoSpinner(region);
  });

  it('draws the lint pane’s five summary cards, the last with its gauge bar', () => {
    render(<CatalogLintSkeleton message="Loading lint report…" testId="pane" />);
    const grid = screen.getByTestId('pane').querySelector('.lg\\:grid-cols-5')!;
    expect(grid.children).toHaveLength(5);
    expect(grid.children[4].querySelector('.rounded-full')).not.toBeNull();
  });

  it('draws as many timeline rows as asked', () => {
    render(<CatalogTimelineSkeleton message="Loading versions…" testId="pane" rows={4} />);
    expect(screen.getByTestId('pane').querySelectorAll('li')).toHaveLength(4);
  });
});
