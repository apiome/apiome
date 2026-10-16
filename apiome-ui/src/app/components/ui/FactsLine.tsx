'use client';

import * as React from 'react';
import { ChartNoAxesColumn } from 'lucide-react';

import { cn } from '../../../../lib/utils';
import { readFlag, statsKey, writeFlag } from '../../../../lib/seen';
import { Button } from './Button';
import { FormatPill } from './catalog/FormatPill';
import { Skeleton } from './Skeleton';

/**
 * FactsLine — a stat strip folded into one line (HIVE-11.5, #5601).
 *
 * Authority: `docs/mockups/proposals/catalog-quiet.html` (annotation 2) and
 * `docs/mockups/PROPOSALS.md`. Seven list pages opened with a 4–6 tile `StatGrid` (≈ 125 px)
 * before the first row of data. The facts line says the same numbers in one tabular row —
 * `3 items · 3 formats · avg quality B · 83` — and keeps the grid one click away behind a
 * ghost **Show stats** toggle that reveals it in place.
 *
 * ```tsx
 * <FactsLine
 *   page="catalog"
 *   facts={[
 *     { id: 'items', value: 3, label: 'items' },
 *     { id: 'formats', value: 3, label: 'formats', formats: ['graphql', 'protobuf'] },
 *     { id: 'quality', label: 'avg quality', value: 'B · 83', labelFirst: true },
 *     { id: 'gone', label: '1 deleted · 1 disabled', muted: true },
 *   ]}
 *   stats={<StatGrid columns={4}>…</StatGrid>}
 * />
 * ```
 *
 * ### Behaviour
 *
 * - The toggle shows only when there is a `stats` grid to reveal, and never when `empty`.
 * - Expanded or collapsed is remembered **per page, per device** under `hive.<page>.stats`
 *   (`lib/seen.ts`). It is read after mount, so the server and first client render agree;
 *   blocked storage simply starts collapsed.
 * - `empty` draws the single fact `0 <emptyLabel>` (default `items`) and no toggle.
 * - `loading` draws one skeleton bar the height of the line.
 *
 * The toggle is a `<button aria-expanded aria-controls>` pointing at the region that holds the
 * grid. The grid stays mounted and is `hidden` when collapsed, so `aria-controls` always
 * resolves. Everything visual is in the `FACTS LINE` section of `globals.css`.
 */

/** One fact on the line. */
export interface FactsLineFact {
  /** Stable key for the fact. */
  id: string;
  /** The number (or short value) drawn in full ink, e.g. `3` or `B · 83`. Omit for a text-only fact. */
  value?: React.ReactNode;
  /** The words beside the value, e.g. `items`. */
  label: React.ReactNode;
  /** Put the label before the value (`avg quality B · 83`). Defaults to value first. */
  labelFirst?: boolean;
  /** Draw the whole fact in the muted ink — for asides like `1 deleted · 1 disabled`. */
  muted?: boolean;
  /** Format strings to draw as `FormatPill`s after the fact. */
  formats?: readonly string[];
}

/** Props for {@link FactsLine}. */
export interface FactsLineProps {
  /** The facts, in reading order. */
  facts: readonly FactsLineFact[];
  /**
   * The page's name for its `hive.<page>.stats` flag, e.g. `catalog`. Required whenever
   * `stats` is given, so two pages never share a choice.
   */
  page: string;
  /** The page's existing `StatGrid`, revealed in place by the toggle. */
  stats?: React.ReactNode;
  /** The list is empty: draw `0 <emptyLabel>` and no toggle. */
  empty?: boolean;
  /** What a count of this page's things is called. Defaults to `items`. */
  emptyLabel?: string;
  /** Draw a skeleton line while the numbers load. */
  loading?: boolean;
  /** Names the line for assistive technology. Defaults to `Summary`. */
  'aria-label'?: string;
  /** Extra classes for the wrapper. */
  className?: string;
}

/**
 * One fact: value and label in reading order, then any format pills.
 *
 * @param props The fact.
 * @returns The segment.
 */
function Fact({ fact }: { fact: FactsLineFact }) {
  const value = fact.value === undefined || fact.value === null ? null : <b>{fact.value}</b>;
  return (
    <li className={cn('facts__item', fact.muted && 'facts__item--muted')}>
      {fact.labelFirst ? (
        <>
          {fact.label}
          {value ? <> {value}</> : null}
        </>
      ) : (
        <>
          {value ? <>{value} </> : null}
          {fact.label}
        </>
      )}
      {fact.formats?.map((format) => (
        <FormatPill key={format} format={format} className="facts__pill" />
      ))}
    </li>
  );
}

/**
 * A stat strip folded into one tabular line, with an optional **Show stats** toggle.
 *
 * @param props See {@link FactsLineProps}.
 * @returns The line, and the (possibly hidden) stats region below it.
 */
export function FactsLine({
  facts,
  page,
  stats,
  empty = false,
  emptyLabel = 'items',
  loading = false,
  'aria-label': ariaLabel = 'Summary',
  className,
}: FactsLineProps) {
  const regionId = React.useId();
  const [expanded, setExpanded] = React.useState(false);

  React.useEffect(() => {
    setExpanded(readFlag(statsKey(page)) === true);
  }, [page]);

  /** Flips the stats region and remembers the choice for this page. */
  const toggle = () => {
    const next = !expanded;
    setExpanded(next);
    writeFlag(statsKey(page), next);
  };

  if (loading) {
    return (
      <div className={cn('facts-line', className)} aria-busy="true">
        <div className="facts">
          <Skeleton className="facts__skeleton" />
          <span className="sr-only">Loading summary…</span>
        </div>
      </div>
    );
  }

  const shown: readonly FactsLineFact[] = empty ? [{ id: 'empty', value: 0, label: emptyLabel }] : facts;
  const hasToggle = Boolean(stats) && !empty;
  const open = hasToggle && expanded;

  return (
    <div className={cn('facts-line', className)}>
      <div className="facts">
        <ul className="facts__list" aria-label={ariaLabel}>
          {shown.map((fact) => (
            <Fact key={fact.id} fact={fact} />
          ))}
        </ul>
        {hasToggle ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="facts__toggle"
            aria-expanded={open}
            aria-controls={regionId}
            onClick={toggle}
          >
            <ChartNoAxesColumn aria-hidden />
            {open ? 'Hide stats' : 'Show stats'}
          </Button>
        ) : null}
      </div>
      {hasToggle ? (
        <div id={regionId} className="facts-line__stats" hidden={!open}>
          {stats}
        </div>
      ) : null}
    </div>
  );
}

export default FactsLine;
