'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { sanitizeSearchInput, SAFE_SEARCH_HTML_PATTERN } from '../utils/searchValidation';

interface Column<T> {
  key: string;
  header: string;
  width?: string;
  sortable?: boolean;
  render?: (item: T) => React.ReactNode;
}

interface DataTableProps<T> {
  data: T[];
  columns: Column<T>[];
  keyField: string;
  onRowClick?: (item: T) => void;
  getRowHref?: (item: T) => string;
  emptyMessage?: string;
  searchable?: boolean;
  searchPlaceholder?: string;
  searchFields?: string[];
  initialPageSize?: number;
}

const PAGE_SIZE_OPTIONS = [10, 25, 50];

export function DataTable<T extends object>({
  data,
  columns,
  keyField,
  onRowClick,
  getRowHref,
  emptyMessage = 'No data available',
  searchable = false,
  searchPlaceholder = 'Search...',
  searchFields = [],
  initialPageSize = 10,
}: DataTableProps<T>) {
  const router = useRouter();
  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc');
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(initialPageSize);

  const filteredData = useMemo(() => {
    if (!searchable || !searchQuery) return data;
    const q = searchQuery.toLowerCase();
    return data.filter((item) =>
      searchFields.some((field) => {
        const value = (item as Record<string, unknown>)[field];
        return value != null && String(value).toLowerCase().includes(q);
      })
    );
  }, [data, searchable, searchQuery, searchFields]);

  const sortedData = useMemo(() => {
    if (!sortColumn) return filteredData;
    return [...filteredData].sort((a, b) => {
      const aVal = (a as Record<string, unknown>)[sortColumn];
      const bVal = (b as Record<string, unknown>)[sortColumn];
      if (aVal === bVal) return 0;
      if (aVal == null) return 1;
      if (bVal == null) return -1;
      const comparison = aVal < bVal ? -1 : 1;
      return sortDirection === 'asc' ? comparison : -comparison;
    });
  }, [filteredData, sortColumn, sortDirection]);

  const totalPages = Math.max(1, Math.ceil(sortedData.length / pageSize));
  const safePage = Math.min(currentPage, totalPages);
  const paginatedData = sortedData.slice((safePage - 1) * pageSize, safePage * pageSize);

  const handleSort = (columnKey: string) => {
    if (sortColumn === columnKey) {
      setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortColumn(columnKey);
      setSortDirection('asc');
    }
  };

  const SortIcon = ({ column }: { column: string }) => {
    if (sortColumn !== column) {
      return (
        <svg
          className="h-3 w-3 text-zinc-400 opacity-0 transition-opacity group-hover/header:opacity-100"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M8 9l4-4 4 4m0 6l-4 4-4-4" />
        </svg>
      );
    }
    return (
      <svg
        className="h-3 w-3 text-[var(--brand)]"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.5}
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d={sortDirection === 'asc' ? 'M5 15l7-7 7 7' : 'M19 9l-7 7-7-7'}
        />
      </svg>
    );
  };

  const RowWrapper = ({ item, children }: { item: T; children: React.ReactNode }) => {
    const baseClassName =
      'transition-colors hover:bg-zinc-50/80 dark:hover:bg-zinc-800/40';
    const clickableClassName = `${baseClassName} cursor-pointer group`;

    if (getRowHref) {
      const href = getRowHref(item);
      return (
        <tr
          className={clickableClassName}
          onClick={() => router.push(href)}
          role="link"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              router.push(href);
            }
          }}
        >
          {children}
        </tr>
      );
    }

    if (onRowClick) {
      return (
        <tr className={clickableClassName} onClick={() => onRowClick(item)}>
          {children}
        </tr>
      );
    }

    return <tr className={baseClassName}>{children}</tr>;
  };

  return (
    <div className="space-y-3">
      {searchable && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="relative max-w-md flex-1">
            <svg
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.75}
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(sanitizeSearchInput(e.target.value));
                setCurrentPage(1);
              }}
              pattern={SAFE_SEARCH_HTML_PATTERN}
              title="Only letters, numbers, spaces, dashes, and underscores are allowed"
              placeholder={searchPlaceholder}
              className="h-9 w-full rounded-md border border-zinc-200 bg-white pl-9 pr-9 text-sm text-zinc-900 placeholder-zinc-400 shadow-xs transition-colors focus-visible:border-[var(--brand)] focus-visible:outline-none dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100 dark:placeholder-zinc-500"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
                aria-label="Clear search"
              >
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>
          <span className="text-xs text-zinc-500 dark:text-zinc-400 tabular-nums">
            {filteredData.length} {filteredData.length === 1 ? 'result' : 'results'}
          </span>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-xs dark:border-zinc-800 dark:bg-zinc-950">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 bg-zinc-50/80 text-left dark:border-zinc-800 dark:bg-zinc-900/40">
                {columns.map((column) => (
                  <th
                    key={column.key}
                    scope="col"
                    className={`px-4 py-2.5 text-[12px] font-semibold uppercase tracking-wider text-zinc-600 dark:text-zinc-400 ${column.width || ''} ${
                      column.sortable
                        ? 'cursor-pointer select-none transition-colors hover:bg-zinc-100/80 dark:hover:bg-zinc-800/60 group/header'
                        : ''
                    }`}
                    onClick={() => column.sortable && handleSort(column.key)}
                  >
                    <div className="flex items-center gap-1.5">
                      {column.header}
                      {column.sortable && <SortIcon column={column.key} />}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/80">
              {paginatedData.length === 0 ? (
                <tr>
                  <td
                    colSpan={columns.length}
                    className="px-4 py-12 text-center text-sm text-zinc-500 dark:text-zinc-400"
                  >
                    {emptyMessage}
                  </td>
                </tr>
              ) : (
                paginatedData.map((item) => (
                  <RowWrapper key={String((item as Record<string, unknown>)[keyField])} item={item}>
                    {columns.map((column) => (
                      <td
                        key={column.key}
                        className="px-4 py-2.5 align-middle text-[13.5px] text-zinc-700 dark:text-zinc-300"
                      >
                        {column.render
                          ? column.render(item)
                          : String((item as Record<string, unknown>)[column.key] ?? '')}
                      </td>
                    ))}
                  </RowWrapper>
                ))
              )}
            </tbody>
          </table>
        </div>

        {sortedData.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-200 bg-zinc-50/60 px-4 py-2.5 dark:border-zinc-800 dark:bg-zinc-900/40">
            <div className="flex items-center gap-3 text-xs text-zinc-500 dark:text-zinc-400">
              <span className="tabular-nums">
                Showing {(safePage - 1) * pageSize + 1}–
                {Math.min(safePage * pageSize, sortedData.length)} of {sortedData.length}
              </span>
              <span aria-hidden="true" className="text-zinc-300 dark:text-zinc-700">|</span>
              <label className="flex items-center gap-1.5">
                Per page
                <select
                  value={pageSize}
                  onChange={(e) => {
                    setPageSize(Number(e.target.value));
                    setCurrentPage(1);
                  }}
                  className="h-7 rounded-md border border-zinc-200 bg-white px-1.5 text-xs text-zinc-700 shadow-xs focus-visible:border-[var(--brand)] focus-visible:outline-none dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300"
                  aria-label="Rows per page"
                >
                  {PAGE_SIZE_OPTIONS.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {totalPages > 1 && (
              <div className="flex items-center gap-1">
                <PagerButton
                  onClick={() => setCurrentPage(1)}
                  disabled={safePage === 1}
                  label="First page"
                >
                  <span aria-hidden="true">&laquo;</span>
                </PagerButton>
                <PagerButton
                  onClick={() => setCurrentPage(safePage - 1)}
                  disabled={safePage === 1}
                  label="Previous page"
                >
                  <span aria-hidden="true">&lsaquo;</span>
                </PagerButton>
                <span className="px-2 text-xs tabular-nums text-zinc-700 dark:text-zinc-300">
                  Page {safePage} of {totalPages}
                </span>
                <PagerButton
                  onClick={() => setCurrentPage(safePage + 1)}
                  disabled={safePage === totalPages}
                  label="Next page"
                >
                  <span aria-hidden="true">&rsaquo;</span>
                </PagerButton>
                <PagerButton
                  onClick={() => setCurrentPage(totalPages)}
                  disabled={safePage === totalPages}
                  label="Last page"
                >
                  <span aria-hidden="true">&raquo;</span>
                </PagerButton>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function PagerButton({
  onClick,
  disabled,
  label,
  children,
}: {
  onClick: () => void;
  disabled: boolean;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className="flex h-7 min-w-7 items-center justify-center rounded-md border border-zinc-200 bg-white px-1.5 text-xs font-medium text-zinc-700 shadow-xs transition-colors hover:bg-zinc-100 disabled:cursor-not-allowed disabled:opacity-40 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
    >
      {children}
    </button>
  );
}
