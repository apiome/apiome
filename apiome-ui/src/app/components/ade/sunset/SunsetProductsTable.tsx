'use client';

/**
 * The **Products and plans** table on the sunset timeline — APX-1.4 (#6101).
 *
 * Deprecated and retired API products and plans, soonest retirement first, beside the version
 * schedule: what retires, when, what consumers move to and what they were told. Each row opens the
 * product's editor, where a plan is migrated or retired. Nothing renders when there is nothing to
 * show, so a workspace without API products sees the page as before.
 *
 * @see `./sunsetProductsModel.ts` — the rules these cells draw.
 */

import * as React from 'react';
import Link from 'next/link';
import { Boxes } from 'lucide-react';

import { Badge } from '@/app/components/ui/Badge';
import { DataTable, DataTableCellPrimary, type DataTableColumn } from '@/app/components/ui/DataTable';

import { sunsetTimelineStatus } from './sunsetModel';
import {
  productLifecycleLabel,
  productRetireDay,
  productRowHref,
  productRowId,
  productRowName,
  type SunsetProductEntry,
} from './sunsetProductsModel';

/** The dash a cell prints when the API has nothing for it. */
const ABSENT = '—';

export interface SunsetProductsTableProps {
  /** The deprecated and retired products and plans. */
  entries: readonly SunsetProductEntry[];
}

/**
 * Render the products-and-plans table. See {@link SunsetProductsTableProps}.
 *
 * @returns The table card, or nothing when there are no entries.
 */
export function SunsetProductsTable({ entries }: SunsetProductsTableProps) {
  const columns = React.useMemo<Array<DataTableColumn<SunsetProductEntry>>>(
    () => [
      {
        id: 'product',
        header: 'Product or plan',
        cell: (entry) => (
          <div className="stl-project">
            <Boxes className="stl-project__icon" aria-hidden />
            <DataTableCellPrimary className="stl-project__name">
              <Link href={productRowHref(entry)}>{productRowName(entry)}</Link>
            </DataTableCellPrimary>
          </div>
        ),
      },
      {
        id: 'retires',
        header: 'Retires',
        className: 'stl-col-sunset',
        cell: (entry) => {
          const day = productRetireDay(entry);
          return day ? <span className="stl-instant">{day}</span> : <span className="stl-absent">{ABSENT}</span>;
        },
      },
      {
        id: 'timeline',
        header: 'Timeline',
        cell: (entry) => (
          <Badge
            status={sunsetTimelineStatus(entry.timelineStatus)}
            dot
            data-testid={`sunset-product-status-${productRowId(entry)}`}
          >
            {sunsetTimelineStatus(entry.timelineStatus)}
          </Badge>
        ),
      },
      {
        id: 'lifecycle',
        header: 'Lifecycle',
        className: 'stl-col-lifecycle',
        cell: (entry) => <span className="stl-lifecycle">{productLifecycleLabel(entry.lifecyclePhase)}</span>,
      },
      {
        id: 'successor',
        header: 'Moves to',
        className: 'stl-col-successor',
        cell: (entry) =>
          entry.successorPlanName ? (
            <span>{entry.successorPlanName}</span>
          ) : (
            <span className="stl-absent">{ABSENT}</span>
          ),
      },
      {
        id: 'notes',
        header: 'Message',
        className: 'stl-col-notes',
        cell: (entry) =>
          entry.deprecationMessage ? (
            <p className="stl-note__text">{entry.deprecationMessage}</p>
          ) : (
            <span className="stl-absent">{ABSENT}</span>
          ),
      },
    ],
    []
  );

  if (entries.length === 0) return null;
  return (
    <section className="stl-products" aria-labelledby="stl-products-title" data-testid="sunset-products">
      <h2 id="stl-products-title" className="stl-products__title">
        API products and plans
      </h2>
      <div className="stl-table-host">
        <DataTable<SunsetProductEntry>
          className="stl-table"
          caption="Deprecated and retired API products and plans"
          columns={columns}
          rows={entries}
          getRowId={productRowId}
          getRowLabel={productRowName}
          scrollX
          data-testid="sunset-products-table"
        />
      </div>
    </section>
  );
}
