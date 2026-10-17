'use client';

/**
 * Layout-stable loading placeholders for the Catalog list and the item detail page (MFI-28.6,
 * #4122).
 *
 * DESIGN.md §8: *"Loading = skeletons shaped like the final content (never spinners in
 * tables)"*. Before this, the cards view drew three empty boxes, the detail page a centred
 * spinner, and every detail pane a spinner or a single "Loading…" line — so the whole layout
 * jumped when the data landed.
 *
 * Each placeholder here is built from **the same classes as the content it stands in for**
 * (`cat-card__*`, `cid-*`, the lint summary grid, the version-row frame), with `Skeleton`
 * bars where the text and figures will go. That is what makes the arrival a fill rather than a
 * jump: the boxes, gaps and paddings are the real ones, only their contents are pending.
 *
 * Every placeholder is decoration (`Skeleton` is `aria-hidden`). The pane presets are wrapped
 * in {@link LoadingState}, which is the polite live region that names what is loading, and
 * each takes the pane's existing loading `data-testid` so tests and callers keep finding it.
 *
 * | Export | Stands in for |
 * | --- | --- |
 * | {@link CatalogCardSkeleton} | one `CatalogCard` |
 * | {@link CatalogCardGridSkeleton} | the cards view's grid, with its live region |
 * | {@link CatalogDetailSkeleton} | the whole detail page: header, tab strip, Overview |
 * | {@link CatalogLintSkeleton} | the Lint & score pane: summary tiles, categories, findings |
 * | {@link CatalogTimelineSkeleton} | a list of rows — versions, conversion history |
 * | {@link CatalogAnalysisSkeleton} | the Format details pane: tiles and a structure tree |
 * | {@link CatalogCodeSkeleton} | the raw source viewer |
 */

import * as React from 'react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Card, CardBody, CardHeader } from '@/app/components/ui/Card';
import { LoadingState } from '@/app/components/ui/LoadingState';
import { Skeleton, SkeletonText } from '@/app/components/ui/Skeleton';
import { TAB_LIST_CLASS } from '@/app/components/ui/tabStyles';
import { cn } from '@lib/utils';

import { CATALOG_SURFACE_TILES } from './detail/catalogItemView';

/** How many cards the cards view draws while the first read is in flight. */
export const CATALOG_CARD_SKELETON_COUNT = 3;

/** The detail page's tab strip has eight tabs; the placeholder draws the same number. */
const DETAIL_TAB_COUNT = 8;

/** Widths for a row of chip placeholders, cycled so a row never reads as a progress bar. */
const CHIP_WIDTHS = ['w-16', 'w-20', 'w-14'] as const;

/** Props shared by the pane presets. */
export interface CatalogPaneSkeletonProps {
  /** What the live region says, e.g. `Loading lint report…`. */
  message: string;
  /** The pane's existing loading test id, kept so callers and tests still find it. */
  testId?: string;
  /** Extra classes on the region — usually the margin the real content starts with. */
  className?: string;
}

/**
 * A row of chip-shaped bars.
 *
 * @param props `count` chips.
 * @returns The chips.
 */
function SkeletonChips({ count }: { count: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, index) => (
        <Skeleton
          key={index}
          className={cn('h-5 rounded-sm', CHIP_WIDTHS[index % CHIP_WIDTHS.length])}
        />
      ))}
    </>
  );
}

/**
 * One `CatalogCard`, pending.
 *
 * Drawn on the card's own classes — the hex avatar's box, the name and id lines, the
 * two-line summary (whose `min-block-size` is what keeps a grid of cards aligned), the dashed
 * format slot, the three orbs and the footer — so a loaded card occupies exactly this box.
 *
 * @returns The placeholder card, hidden from assistive technology.
 */
export function CatalogCardSkeleton() {
  return (
    <div className="cat-card" aria-hidden data-testid="catalog-card-skeleton">
      <div className="cat-card__body">
        <div className="cat-card__head">
          <Skeleton className="size-11 shrink-0 rounded-md" />
          <div className="cat-card__identity">
            <Skeleton className="h-5 w-3/5" />
            <Skeleton className="mt-1.5 h-3 w-2/5" />
          </div>
          <Skeleton className="h-5 w-14 rounded-full" />
        </div>
        <SkeletonText lines={2} lastLineWidth="45%" className="cat-card__summary" />
        <div className="cat-card__formats">
          <SkeletonChips count={3} />
        </div>
        <div className="cat-card__meter">
          <div className="cat-card__scores">
            {[0, 1, 2].map((index) => (
              <span key={index} className="cat-orb">
                <Skeleton className="size-7.5 rounded-full" />
                <Skeleton className="h-3 w-10" />
              </span>
            ))}
          </div>
          <Skeleton className="h-3 w-16" />
        </div>
      </div>
      <div className="cat-card__footer">
        <span className="cat-card__creator">
          <Skeleton className="size-5 rounded-full" />
          <Skeleton className="h-3 w-28" />
        </span>
        <Skeleton className="h-3 w-20" />
      </div>
    </div>
  );
}

/**
 * The cards view's grid while the first read is in flight.
 *
 * The same `.cat-grid` the cards land in, inside a live region that says what is loading.
 *
 * @param props `count` — how many cards to draw.
 * @returns The region.
 */
export function CatalogCardGridSkeleton({
  count = CATALOG_CARD_SKELETON_COUNT,
}: {
  count?: number;
}) {
  return (
    <LoadingState
      message="Loading catalog…"
      data-testid="catalog-cards-loading"
      skeleton={
        <div className="cat-grid">
          {Array.from({ length: count }, (_, index) => (
            <CatalogCardSkeleton key={index} />
          ))}
        </div>
      }
    />
  );
}

/**
 * The item detail page while the item is loading.
 *
 * The real `PageHeader` (so the header's height, the leading hex, the title row, the meta row,
 * the orbs and the tab strip all sit where they will), then the Overview's two columns: the API
 * surface card with its tiles, and the Quality and Source snapshot panels.
 *
 * @returns The page, with a live region naming what is loading.
 */
export function CatalogDetailSkeleton() {
  return (
    <Page>
      <PageHeader
        leading={<Skeleton className="size-18 shrink-0 rounded-lg" />}
        breadcrumb={[{ label: 'Catalog', href: '/ade/dashboard/catalog' }]}
        title={<Skeleton className="h-7 w-64 max-w-full" />}
        description={<Skeleton className="h-3.5 w-96 max-w-full" />}
        meta={
          <div className="cid-meta" aria-hidden>
            <SkeletonChips count={3} />
          </div>
        }
        actions={
          <div className="cid-orbs" aria-hidden>
            <Skeleton className="size-18 rounded-full" />
            <Skeleton className="size-18 rounded-full" />
          </div>
        }
        tabs={
          <div className={cn(TAB_LIST_CLASS, 'cid-tabs')} aria-hidden>
            {Array.from({ length: DETAIL_TAB_COUNT }, (_, index) => (
              <span key={index} className="px-3 py-2.5">
                <Skeleton className="h-3.5 w-20" />
              </span>
            ))}
          </div>
        }
      />
      <PageBody>
        <LoadingState
          message="Loading catalog item…"
          data-testid="catalog-detail-loading"
          skeleton={
            <div className="cid-overview">
              <div className="cid-overview__main">
                <Card>
                  <CardHeader>
                    <Skeleton className="h-4 w-28" />
                  </CardHeader>
                  <CardBody>
                    <div className="cid-tiles">
                      {CATALOG_SURFACE_TILES.map((tile) => (
                        <div key={tile.key} className="cid-tile">
                          <Skeleton className="h-3 w-20" />
                          <Skeleton className="h-6 w-10" />
                          <Skeleton className="h-2.5 w-16" />
                        </div>
                      ))}
                    </div>
                  </CardBody>
                </Card>
              </div>
              <aside className="cid-overview__aside">
                <Card className="cid-panel">
                  <Skeleton className="h-4 w-32" />
                  <div className="cid-score">
                    <Skeleton className="size-10 rounded-full" />
                    <div className="flex flex-col gap-2">
                      <Skeleton className="h-6 w-16" />
                      <Skeleton className="h-3 w-24" />
                    </div>
                  </div>
                </Card>
                <Card className="cid-panel">
                  <Skeleton className="h-4 w-32" />
                  <SkeletonText lines={2} lastLineWidth="50%" />
                </Card>
              </aside>
            </div>
          }
        />
      </PageBody>
    </Page>
  );
}

/**
 * The Lint & score pane while its report loads.
 *
 * The five-card severity strip on the real grid (MUST · SHOULD · Advisory · Rules triggered ·
 * the score card with its gauge bar), then the 3/7 split of categories and findings.
 *
 * @param props See {@link CatalogPaneSkeletonProps}.
 * @returns The region.
 */
export function CatalogLintSkeleton({ message, testId, className }: CatalogPaneSkeletonProps) {
  return (
    <LoadingState
      message={message}
      data-testid={testId}
      className={className}
      skeleton={
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {[0, 1, 2, 3, 4].map((index) => (
              <div key={index} className="rounded-xl border border-border bg-surface p-3">
                <Skeleton className="h-2.5 w-16" />
                <Skeleton className="mt-2 h-5 w-10" />
                {index === 4 ? <Skeleton className="mt-2 h-1.5 w-full rounded-full" /> : null}
                <Skeleton className="mt-2 h-2.5 w-24" />
              </div>
            ))}
          </div>
          <div className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-10">
            <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4 lg:col-span-3">
              <Skeleton className="h-3 w-24" />
              <SkeletonText lines={4} lastLineWidth="70%" />
            </div>
            <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-4 lg:col-span-7">
              <SkeletonText lines={8} lastLineWidth="40%" />
            </div>
          </div>
        </>
      }
    />
  );
}

/**
 * A list of rows while it loads — the Versions timeline and the conversion history.
 *
 * Each row is the version row's own frame (bordered, `p-3`, a leading control, a title line
 * and a meta line), so the first real rows land in the same boxes.
 *
 * @param props See {@link CatalogPaneSkeletonProps}, plus `rows`.
 * @returns The region.
 */
export function CatalogTimelineSkeleton({
  message,
  testId,
  className,
  rows = 3,
}: CatalogPaneSkeletonProps & { rows?: number }) {
  return (
    <LoadingState
      message={message}
      data-testid={testId}
      className={className}
      skeleton={
        <ol className="space-y-2">
          {Array.from({ length: rows }, (_, index) => (
            <li
              key={index}
              className="flex items-start gap-3 rounded-lg border border-border bg-subtle p-3"
            >
              <Skeleton className="mt-0.5 size-4 shrink-0 rounded-sm" />
              <div className="flex min-w-0 flex-1 flex-col gap-2">
                <Skeleton className="h-3.5 w-1/3" />
                <Skeleton className="h-2.5 w-1/2" />
              </div>
            </li>
          ))}
        </ol>
      }
    />
  );
}

/**
 * The Format details pane while the native payload analysis loads: a row of stat tiles and a
 * structure tree of indented rows.
 *
 * @param props See {@link CatalogPaneSkeletonProps}.
 * @returns The region.
 */
export function CatalogAnalysisSkeleton({
  message,
  testId,
  className,
}: CatalogPaneSkeletonProps) {
  return (
    <LoadingState
      message={message}
      data-testid={testId}
      className={className}
      skeleton={
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[0, 1, 2, 3].map((index) => (
              <div key={index} className="rounded-xl border border-border bg-surface p-3">
                <Skeleton className="h-2.5 w-16" />
                <Skeleton className="mt-2 h-5 w-10" />
              </div>
            ))}
          </div>
          <div className="mt-4 flex flex-col gap-2 rounded-xl border border-border bg-surface p-4">
            {['w-2/5', 'ml-6 w-1/3', 'ml-6 w-1/2', 'ml-12 w-1/4', 'w-2/5', 'ml-6 w-1/3'].map(
              (width, index) => (
                <Skeleton key={index} className={cn('h-3', width)} />
              )
            )}
          </div>
        </>
      }
    />
  );
}

/**
 * The raw source viewer while the source (or the editor) loads: lines of code at varied
 * widths, filling the viewer's own box.
 *
 * @param props See {@link CatalogPaneSkeletonProps}.
 * @returns The region.
 */
export function CatalogCodeSkeleton({ message, testId, className }: CatalogPaneSkeletonProps) {
  return (
    <LoadingState
      message={message}
      data-testid={testId}
      className={cn('h-full', className)}
      skeleton={
        <div className="flex flex-col gap-2 p-4">
          {['w-1/3', 'ml-4 w-1/2', 'ml-4 w-2/5', 'ml-8 w-1/3', 'ml-4 w-1/4', 'w-1/5', 'w-2/5', 'ml-4 w-1/2'].map(
            (width, index) => (
              <Skeleton key={index} className={cn('h-3', width)} />
            )
          )}
        </div>
      }
    />
  );
}
