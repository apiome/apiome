'use client';

import * as React from 'react';
import { ChevronRight } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import { Checkbox } from '@/app/components/ui/Checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { Input } from '@/app/components/ui/Input';
import { Spinner } from '@/app/components/ui/Spinner';
import { cn } from '@lib/utils';

import {
  buildSelectionPayload,
  groupAvailableFields,
  isFieldPicked,
  isOperationPicked,
  operationKey,
  operationLabel,
  selectionTotals,
  toggleField,
  toggleOperation,
  type AvailableOperation,
  type AvailableSurface,
  type PickerSelection,
  type SelectionPayloadOperation,
} from './consumersModel';

/**
 * Declare a consumer's surface without a Pact file — CTG-4.1 (#4479).
 *
 * The second ingestion path: pick the operations a consumer calls and, under each, the fields
 * it reads. Everything drawn here comes from the project's own stored specification, so a
 * person cannot pick something that is not there.
 *
 * ### Picking a field picks its operation
 *
 * The two cannot disagree — a field declared on an operation the consumer does not call is not
 * a statement about anything — so ticking a field ticks its operation, and unticking an
 * operation takes its fields with it. Making a person click twice to say one thing is how
 * wrong contracts get declared.
 *
 * ### Declaring an operation with no fields is a real answer
 *
 * "I call this, and I do not care which fields it returns" is a legitimate contract, and it is
 * what a caller that only checks the status code actually means. So an operation with no
 * ticked fields is stored as an operation, not refused.
 */

/** Props for {@link SurfacePickerDialog}. */
export interface SurfacePickerDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** Close it. */
  onOpenChange: (open: boolean) => void;
  /** Whose surface is being declared. */
  consumerName: string;
  /** The catalogue, or `null` while it loads. */
  catalogue: AvailableSurface | null;
  /** Whether the catalogue is still loading. */
  loading?: boolean;
  /** Why the catalogue could not be read, if it could not. */
  loadError?: string;
  /** What is already declared, as picker state. */
  initialSelection: PickerSelection;
  /**
   * Store the picked surface.
   *
   * @param operations The selection, as the request body.
   * @returns The error to show inline, or `null` on success.
   */
  onSubmit: (operations: SelectionPayloadOperation[]) => Promise<string | null>;
}

/**
 * One operation row, with its expandable field list.
 *
 * @param props.operation The catalogue entry.
 * @param props.selection The current picks.
 * @param props.onToggleOperation Toggle the whole operation.
 * @param props.onToggleField Toggle one field.
 * @returns The row.
 */
function OperationRow({
  operation,
  selection,
  onToggleOperation,
  onToggleField,
}: {
  operation: AvailableOperation;
  selection: PickerSelection;
  onToggleOperation: (operation: AvailableOperation) => void;
  onToggleField: (operation: AvailableOperation, field: { location: string; status: string | null; path: string }) => void;
}) {
  const [expanded, setExpanded] = React.useState(false);
  const picked = isOperationPicked(selection, operation);
  const pickedFields = selection[operationKey(operation)]?.length ?? 0;
  const groups = groupAvailableFields(operation);

  return (
    <li className={cn('cns-pick', picked && 'is-picked')}>
      <div className="cns-pick__head">
        <Checkbox
          checked={picked}
          onCheckedChange={() => onToggleOperation(operation)}
          aria-label={`Declare ${operationLabel(operation)}`}
        />
        <button
          type="button"
          className="cns-pick__toggle"
          aria-expanded={expanded}
          onClick={() => setExpanded((current) => !current)}
          disabled={groups.length === 0}
        >
          <ChevronRight className="cns-pick__chevron" aria-hidden="true" />
          <code className="cns-pick__op mono">{operationLabel(operation)}</code>
          {operation.summary && <span className="cns-pick__summary">{operation.summary}</span>}
        </button>
        <span className="cns-pick__count">
          {pickedFields > 0
            ? `${pickedFields} of ${operation.fields.length} fields`
            : `${operation.fields.length} fields`}
        </span>
      </div>

      {expanded && (
        <div className="cns-pick__fields">
          {operation.truncated && (
            <p className="cns-pick__truncated">
              This operation has more fields than are listed; the walk stopped at the limit.
            </p>
          )}
          {groups.map((group) => (
            <div className="cns-pick__group" key={group.location}>
              <h4 className="cns-pick__grouphead">{group.label}</h4>
              <ul className="cns-pick__fieldlist">
                {group.fields.map((field) => (
                  <li className="cns-pick__field" key={`${field.pointer}-${field.status ?? ''}`}>
                    <label className="cns-pick__label">
                      <Checkbox
                        checked={isFieldPicked(selection, operation, field)}
                        onCheckedChange={() => onToggleField(operation, field)}
                      />
                      <code className="cns-pick__path mono">{field.path}</code>
                      {field.type_name && (
                        <span className="cns-pick__type">{field.type_name}</span>
                      )}
                      {field.status && <span className="cns-pick__status">{field.status}</span>}
                      {field.required && <span className="cns-pick__required">required</span>}
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </li>
  );
}

/**
 * The surface picker.
 *
 * @param props See {@link SurfacePickerDialogProps}.
 * @returns The dialog.
 */
export default function SurfacePickerDialog({
  open,
  onOpenChange,
  consumerName,
  catalogue,
  loading,
  loadError,
  initialSelection,
  onSubmit,
}: SurfacePickerDialogProps) {
  const [selection, setSelection] = React.useState<PickerSelection>({});
  const [query, setQuery] = React.useState('');
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (!open) return;
    setSelection(initialSelection);
    setQuery('');
    setError('');
    setBusy(false);
  }, [open, initialSelection]);

  const operations = React.useMemo(() => {
    const all = catalogue?.operations ?? [];
    const needle = query.trim().toLowerCase();
    if (!needle) return all;
    return all.filter((operation) =>
      `${operation.method} ${operation.path} ${operation.summary ?? ''}`
        .toLowerCase()
        .includes(needle),
    );
  }, [catalogue, query]);

  const totals = selectionTotals(selection);

  const handleSubmit = async () => {
    if (totals.operations === 0 || busy) return;
    setBusy(true);
    setError('');
    const failure = await onSubmit(buildSelectionPayload(selection, catalogue?.operations ?? []));
    setBusy(false);
    if (failure) {
      setError(failure);
      return;
    }
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="cns-dialog cns-dialog--wide">
        <DialogHeader>
          <DialogTitle>Declare what {consumerName} uses</DialogTitle>
          <DialogDescription>
            Pick the operations this consumer calls, and the fields it reads on them. Everything
            here comes from
            {catalogue?.version_label ? ` version ${catalogue.version_label}` : ' this project'}
            &apos;s stored specification.
          </DialogDescription>
        </DialogHeader>

        <div className="cns-picker">
          <Input
            value={query}
            placeholder="Filter operations…"
            aria-label="Filter operations"
            onChange={(event) => setQuery(event.target.value)}
          />

          {loading && (
            <p className="cns-picker__state">
              <Spinner className="size-4" /> Loading the specification…
            </p>
          )}

          {!loading && loadError && <Alert variant="danger">{loadError}</Alert>}

          {!loading && !loadError && operations.length === 0 && (
            <p className="cns-picker__state">
              {catalogue && catalogue.count === 0
                ? 'This version declares no operations, so there is nothing to declare against.'
                : 'No operation matches that filter.'}
            </p>
          )}

          {!loading && !loadError && operations.length > 0 && (
            <ul className="cns-picker__list">
              {operations.map((operation) => (
                <OperationRow
                  key={operation.pointer}
                  operation={operation}
                  selection={selection}
                  onToggleOperation={(target) =>
                    setSelection((current) => toggleOperation(current, target))
                  }
                  onToggleField={(target, field) =>
                    setSelection((current) => toggleField(current, target, field))
                  }
                />
              ))}
            </ul>
          )}

          {error && <Alert variant="danger">{error}</Alert>}
        </div>

        <DialogFooter>
          <span className="cns-picker__totals" data-testid="picker-totals">
            {totals.operations} operations · {totals.fields} fields
          </span>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" onClick={handleSubmit} disabled={totals.operations === 0 || busy}>
            {busy && <Spinner className="size-4" />}
            Save contract
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
