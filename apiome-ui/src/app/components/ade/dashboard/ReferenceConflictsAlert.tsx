'use client';

/**
 * Reference conflicts on the import wizard's Preview step (#584).
 *
 * The import keeps every `$ref` as written (renaming only follows a renamed schema), so two kinds
 * of reference in the selected schemas will not resolve in the project afterwards:
 *
 * - **broken** — `#/components/schemas/Customer` when the document defines no `Customer`;
 * - **external** — `https://…` references, which Apiome does not fetch.
 *
 * The wizard says so before the import runs. It is a warning, never a block. A reference to a
 * schema the reader left unticked cannot happen here: ticking a schema ticks what it references
 * (#579). The conflicts come from {@link findReferenceConflicts}; this component only lays them out.
 */

import { Alert, AlertDescription, AlertTitle } from '@/app/components/ui/Alert';
import type { ReferenceConflict } from '@/app/utils/reference-conflict-detection';

/** At most this many schemas are listed; the title still counts them all. */
const MAX_LISTED = 20;

export interface ReferenceConflictsAlertProps {
  /** The schemas whose references will not resolve; nothing renders when there are none. */
  conflicts: ReferenceConflict[];
}

/**
 * The warning, with one row per schema naming its broken and external references.
 *
 * @param props See {@link ReferenceConflictsAlertProps}.
 * @returns The alert, or `null` when every reference resolves.
 */
export function ReferenceConflictsAlert({ conflicts }: ReferenceConflictsAlertProps) {
  const shown = conflicts.filter((c) => c.broken.length > 0 || c.external.length > 0);
  if (shown.length === 0) return null;
  const listed = shown.slice(0, MAX_LISTED);
  const noun = shown.length === 1 ? 'schema has references' : 'schemas have references';
  return (
    // `status`, not the default `alert`: the list changes as schemas are ticked, and a polite
    // region does not interrupt the reader on every checkbox.
    <Alert variant="warn" role="status" data-testid="reference-conflicts">
      <AlertTitle>
        {shown.length} {noun} that won’t resolve after import
      </AlertTitle>
      <AlertDescription>
        <p>
          References are imported as written. One to a schema this document doesn’t define points at
          nothing in the project, and Apiome doesn’t fetch one to a URL. Add the missing schemas to the
          spec, or replace the URL with a schema in it.
        </p>
        <ul className="mt-2 flex flex-col gap-1.5">
          {listed.map(({ schema, broken, external }) => (
            <li key={schema} data-testid={`reference-conflict-${schema}`}>
              <span className="font-semibold">{schema}</span>
              {broken.length > 0 && (
                <span className="block pl-4">
                  Not defined in this document:{' '}
                  {broken.map((name, i) => (
                    <span key={name}>
                      {i > 0 && ', '}
                      <code className="mono">{name}</code>
                    </span>
                  ))}
                </span>
              )}
              {external.length > 0 && (
                <span className="block pl-4">
                  Not fetched:{' '}
                  {external.map((url, i) => (
                    <span key={url}>
                      {i > 0 && ', '}
                      <code className="mono break-all">{url}</code>
                    </span>
                  ))}
                </span>
              )}
            </li>
          ))}
        </ul>
        {shown.length > listed.length && <p className="mt-2">and {shown.length - listed.length} more.</p>}
      </AlertDescription>
    </Alert>
  );
}
