'use client';

/**
 * Property conflicts on the import wizard's Preview step (#583).
 *
 * When the selected schemas use one property name with more than one definition (`status` an enum
 * of `active | inactive` in one schema and `pending | completed` in another, `id` a UUID string in
 * one and an `int64` in another), the import stores each definition as its own property in the
 * project library — `status`, then `status_1` — and every schema keeps its own. Nothing is lost,
 * but a reader who expected one shared `status` is surprised later, so the wizard says so before
 * the import runs. It is a warning, never a block.
 *
 * The conflicts come from {@link findPropertyConflicts}; this component only lays them out.
 */

import { Alert, AlertDescription, AlertTitle } from '@/app/components/ui/Alert';
import type { PropertyConflict } from '@/app/utils/property-conflict-detection';

/** At most this many conflicts are listed; the title still counts them all. */
const MAX_LISTED = 20;

export interface PropertyConflictsAlertProps {
  /** The conflicts among the selected schemas; nothing renders when there are none. */
  conflicts: PropertyConflict[];
}

/**
 * The warning, with one row per conflicting property and one line per definition.
 *
 * @param props See {@link PropertyConflictsAlertProps}.
 * @returns The alert, or `null` when there is no conflict.
 */
export function PropertyConflictsAlert({ conflicts }: PropertyConflictsAlertProps) {
  if (conflicts.length === 0) return null;
  const listed = conflicts.slice(0, MAX_LISTED);
  const noun = conflicts.length === 1 ? 'property is' : 'properties are';
  return (
    // `status`, not the default `alert`: the list changes as schemas are ticked, and a polite
    // region does not interrupt the reader on every checkbox.
    <Alert variant="warn" role="status" data-testid="property-conflicts">
      <AlertTitle>
        {conflicts.length} {noun} defined differently in the selected schemas
      </AlertTitle>
      <AlertDescription>
        <p>
          Each definition is imported as its own property in the project library (for example{' '}
          <code className="mono">status</code> and <code className="mono">status_1</code>), and every
          schema keeps its own. Make the definitions match in the spec if they should be one property.
        </p>
        <ul className="mt-2 flex flex-col gap-2">
          {listed.map(({ property, definitions }) => (
            <li key={property} data-testid={`property-conflict-${property}`}>
              <code className="mono font-semibold">{property}</code>
              <ul className="mt-1 flex flex-col gap-0.5 pl-4">
                {definitions.map(({ schemas, summary }) => (
                  <li key={summary}>
                    <span className="font-medium">{schemas.join(', ')}</span>
                    {': '}
                    <code className="mono break-all">{summary}</code>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
        {conflicts.length > listed.length && (
          <p className="mt-2">and {conflicts.length - listed.length} more.</p>
        )}
      </AlertDescription>
    </Alert>
  );
}
