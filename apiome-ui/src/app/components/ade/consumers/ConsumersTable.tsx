'use client';

import * as React from 'react';
import { Ellipsis, FileJson, Pencil, SquareStack, Trash2 } from 'lucide-react';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';

import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import {
  DataTable,
  type DataTableColumn,
  type DataTableSortState,
} from '@/app/components/ui/DataTable';
import { cn } from '@lib/utils';

import {
  CONSUMER_STATUS_LABEL,
  CONSUMER_STATUS_TONE,
  consumerStatus,
  contractProvenanceLine,
  contractSummaryLine,
  operationLabel,
  type ConsumerSummary,
} from './consumersModel';

/**
 * The consumer list — CTG-4.1 (#4479).
 *
 * One row per registered consumer of the project, with what it declares it uses. The row is
 * the answer to "who would this change break", so the surface line is on the row itself rather
 * than behind a click: a list that showed only names would need opening four times to answer
 * the question it exists for.
 *
 * ### Three declared paths, then a count
 *
 * A contract with forty operations cannot be rendered in a cell, and a cell that says "40
 * operations" and nothing else is not evidence either. The row shows the first three declared
 * operations and how many more there are — enough to recognise the consumer that reads the
 * endpoint you are about to change, with the full surface a click away.
 */

/** How many declared operations a row previews before it counts the rest. */
const PREVIEW_OPERATIONS = 3;

/** The shared row-menu item chrome, as the projects and tenants lists spell it. */
const MENU_ITEM_CLASS = 'tnt-menu__item';

/** Props for {@link ConsumersTable}. */
export interface ConsumersTableProps {
  /** The rows to draw. */
  rows: readonly ConsumerSummary[];
  /** Whether the list is still loading. */
  loading?: boolean;
  /** Why the list could not be read, if it could not. */
  error?: React.ReactNode;
  /** Retry the failed read. */
  onRetry?: () => void;
  /** What to draw when there are no rows. */
  empty?: React.ReactNode;
  /** The strip above the table. */
  toolbar?: React.ReactNode;
  /** The strip below it. */
  footer?: React.ReactNode;
  /** The sorted column, or `null` for the registry's own order (newest consumer first). */
  sort?: DataTableSortState | null;
  /** Called when a sortable header is activated. */
  onSortChange?: (next: DataTableSortState | null) => void;
  /** Open a consumer's declared surface. */
  onOpen: (row: ConsumerSummary) => void;
  /** Edit a consumer's identity. */
  onEdit: (row: ConsumerSummary) => void;
  /** Declare a consumer's surface in the picker. */
  onDeclare: (row: ConsumerSummary) => void;
  /** Import a Pact file for a consumer. */
  onImport: (row: ConsumerSummary) => void;
  /** Retire a consumer. */
  onRetire: (row: ConsumerSummary) => void;
  /** Whether the viewer may change a contract (`consumer_contracts:edit`). */
  canEdit: boolean;
  /** Whether the viewer may retire a consumer (`consumer_contracts:delete`). */
  canDelete: boolean;
}

/**
 * The declared surface of one row, as a short list of paths.
 *
 * @param props.row The row.
 * @returns The preview, or the reason there is nothing to preview.
 */
function SurfaceCell({ row }: { row: ConsumerSummary }) {
  const operations = row.contract?.surface.operations ?? [];
  const shown = operations.slice(0, PREVIEW_OPERATIONS);
  const remaining = operations.length - shown.length;

  return (
    <div className="cns-surface">
      <span className="cns-surface__line">{contractSummaryLine(row.contract)}</span>
      {shown.length > 0 && (
        <span className="cns-surface__ops">
          {shown.map((operation) => (
            <code className="cns-op mono" key={operation.pointer}>
              {operationLabel(operation)}
            </code>
          ))}
          {remaining > 0 && <span className="cns-surface__more">+{remaining} more</span>}
        </span>
      )}
    </div>
  );
}

/**
 * The consumer list.
 *
 * @param props See {@link ConsumersTableProps}.
 * @returns The table.
 */
export default function ConsumersTable({
  rows,
  loading,
  error,
  onRetry,
  empty,
  toolbar,
  footer,
  sort,
  onSortChange,
  onOpen,
  onEdit,
  onDeclare,
  onImport,
  onRetire,
  canEdit,
  canDelete,
}: ConsumersTableProps) {
  const columns: ReadonlyArray<DataTableColumn<ConsumerSummary>> = React.useMemo(
    () => [
      {
        id: 'consumer',
        header: 'Consumer',
        sortable: true,
        skeletonWidth: '12rem',
        cell: (row) => (
          <div className="cns-identity">
            <span className="cns-identity__name">{row.consumer.name}</span>
            <code className="cns-identity__slug mono">{row.consumer.slug}</code>
          </div>
        ),
      },
      {
        id: 'owner',
        header: 'Owner',
        sortable: true,
        skeletonWidth: '8rem',
        cell: (row) =>
          row.consumer.owner ? (
            <span className="cns-owner">{row.consumer.owner}</span>
          ) : (
            <span className="cns-owner cns-owner--none">Unassigned</span>
          ),
      },
      {
        id: 'surface',
        header: 'Declared surface',
        sortable: true,
        skeletonWidth: '18rem',
        cell: (row) => <SurfaceCell row={row} />,
      },
      {
        id: 'status',
        header: 'Contract',
        skeletonWidth: '6rem',
        cell: (row) => {
          const status = consumerStatus(row);
          return (
            <div className="cns-status">
              <Badge variant={CONSUMER_STATUS_TONE[status]} dot>
                {CONSUMER_STATUS_LABEL[status]}
              </Badge>
              {row.contract && (
                <span className="cns-status__meta">{contractProvenanceLine(row.contract)}</span>
              )}
            </div>
          );
        },
      },
      {
        id: 'actions',
        headerLabel: 'Actions',
        actions: true,
        align: 'end',
        cell: (row) => (
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="px-1.5"
                aria-label={`Actions for ${row.consumer.name}`}
                data-testid={`consumers-menu-${row.consumer.id}`}
              >
                <Ellipsis aria-hidden="true" />
              </Button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content className="tnt-menu" sideOffset={4} align="end">
                <DropdownMenu.Item className={MENU_ITEM_CLASS} onSelect={() => onOpen(row)}>
                  <SquareStack aria-hidden="true" />
                  View declared surface
                </DropdownMenu.Item>
                {canEdit && (
                  <>
                    <DropdownMenu.Item
                      className={MENU_ITEM_CLASS}
                      onSelect={() => onDeclare(row)}
                    >
                      <Pencil aria-hidden="true" />
                      Declare surface…
                    </DropdownMenu.Item>
                    <DropdownMenu.Item
                      className={MENU_ITEM_CLASS}
                      onSelect={() => onImport(row)}
                    >
                      <FileJson aria-hidden="true" />
                      Import Pact file…
                    </DropdownMenu.Item>
                    <DropdownMenu.Item className={MENU_ITEM_CLASS} onSelect={() => onEdit(row)}>
                      <Pencil aria-hidden="true" />
                      Edit consumer…
                    </DropdownMenu.Item>
                  </>
                )}
                {canDelete && (
                  <DropdownMenu.Item
                    className={cn(MENU_ITEM_CLASS, 'cns-menu__item--danger')}
                    onSelect={() => onRetire(row)}
                  >
                    <Trash2 aria-hidden="true" />
                    Retire consumer
                  </DropdownMenu.Item>
                )}
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        ),
      },
    ],
    [canDelete, canEdit, onDeclare, onEdit, onImport, onOpen, onRetire],
  );

  return (
    <DataTable
      caption="Consumers of this project"
      columns={columns}
      rows={rows}
      getRowId={(row) => row.consumer.id}
      getRowLabel={(row) => row.consumer.name}
      onRowActivate={onOpen}
      loading={loading}
      loadingLabel="Loading consumers…"
      error={error}
      errorTitle="Couldn't load this project's consumers"
      onRetry={onRetry}
      empty={empty}
      toolbar={toolbar}
      footer={footer}
      sort={sort}
      onSortChange={onSortChange}
      scrollX
    />
  );
}
