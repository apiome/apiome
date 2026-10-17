'use client';

/**
 * The per-item failure report of a partial bulk write (MFI-28.5, #4121).
 *
 * The toast after a bulk delete or undelete states the split ("Deleted 3 of 5 · 2 refused");
 * this list, shown in the message box that follows, names *which* items were refused and the
 * server's reason for each, so the reader can retry the right ones.
 */

import type { CatalogBulkFailure } from './catalogModel';

export interface CatalogBulkFailureListProps {
  /** The items the write refused, each with its reason. */
  failures: readonly CatalogBulkFailure[];
}

/**
 * Render one line per refused item.
 *
 * @param props See {@link CatalogBulkFailureListProps}.
 * @returns The list.
 */
export function CatalogBulkFailureList({ failures }: CatalogBulkFailureListProps) {
  return (
    <ul className="cbc-failures" data-testid="catalog-bulk-failures">
      {failures.map((failure) => (
        <li key={failure.id} className="cbc-failures__item">
          <span className="cbc-failures__name">{failure.name}</span>
          <span className="cbc-failures__reason">{failure.reason}</span>
        </li>
      ))}
    </ul>
  );
}
