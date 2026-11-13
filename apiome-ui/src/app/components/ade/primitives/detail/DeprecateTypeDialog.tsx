'use client';

/**
 * The Deprecate dialog on the type-detail page (#3482).
 *
 * Three optional fields — a sunset date, a message, a replacement type — and one write. The same
 * dialog changes the details of a type that is already deprecated: it opens pre-filled, and a
 * field cleared here is cleared on the type.
 *
 * Every rule is in `primitiveLifecycleModel.ts` (validation, request body, which types may be a
 * replacement), so this file only holds the form's state, the read that fills the replacement
 * picker and the write. The picker is a native `<select>`, like the dialog's siblings in this
 * folder: it is a plain list of the tenant's types and gains nothing from a custom popover.
 *
 * A failed write keeps the dialog open and says why in place; nothing is reported through a
 * toaster, because the detail page has none.
 */

import * as React from 'react';
import { Archive } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Button } from '@/app/components/ui/Button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/app/components/ui/Dialog';
import { FormField } from '@/app/components/ui/FormField';
import { Input } from '@/app/components/ui/Input';
import { Textarea } from '@/app/components/ui/Textarea';
import {
  MAX_DEPRECATION_MESSAGE,
  buildDeprecateRequestBody,
  deprecateFormFrom,
  replacementOptions,
  todayIsoDate,
  validateDeprecateForm,
  type DeprecateFormData,
  type ReplacementCandidate,
} from '@/app/ade/dashboard/primitives/primitiveLifecycleModel';

import { DEPRECATION_ADVISORY, isDeprecated, type PrimitiveDetail } from './primitiveDetailView';

export interface DeprecateTypeDialogProps {
  /** The type being deprecated, or whose deprecation details are being changed. */
  primitive: PrimitiveDetail;
  /** Dismiss without saving. */
  onClose: () => void;
  /** The write landed — the caller shows the returned type and closes. */
  onSaved: (primitive: PrimitiveDetail) => void;
}

/**
 * Render the dialog. See {@link DeprecateTypeDialogProps}.
 *
 * @returns The form: sunset date, message, replacement type.
 */
export default function DeprecateTypeDialog({ primitive, onClose, onSaved }: DeprecateTypeDialogProps) {
  const alreadyDeprecated = isDeprecated(primitive);
  const [form, setForm] = React.useState<DeprecateFormData>(() => deprecateFormFrom(primitive));
  const [candidates, setCandidates] = React.useState<ReplacementCandidate[]>([]);
  const [submitting, setSubmitting] = React.useState(false);
  const [failure, setFailure] = React.useState<string | null>(null);

  const today = React.useMemo(() => todayIsoDate(), []);
  const errors = React.useMemo(() => validateDeprecateForm(form, today), [form, today]);
  const hasErrors = Object.keys(errors).length > 0;
  const options = React.useMemo(
    () => replacementOptions(candidates, primitive.id),
    [candidates, primitive.id]
  );

  // Fill the replacement picker. A failed read leaves the picker empty rather than blocking the
  // dialog: the replacement is optional, and the type can still be deprecated without one.
  React.useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch('/api/primitives');
        const data = await response.json();
        if (!cancelled && response.ok && data.success && Array.isArray(data.primitives)) {
          setCandidates(data.primitives as ReplacementCandidate[]);
        }
      } catch {
        // Leave the picker with "No replacement" only.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const update = <K extends keyof DeprecateFormData>(key: K, value: DeprecateFormData[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async () => {
    if (hasErrors || submitting) return;
    setSubmitting(true);
    setFailure(null);
    try {
      const response = await fetch(`/api/primitives/${encodeURIComponent(primitive.id)}/deprecate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildDeprecateRequestBody(form)),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        setFailure(data.error || 'The type could not be deprecated.');
        return;
      }
      onSaved(data.primitive as PrimitiveDetail);
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'The type could not be deprecated.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="prm-dialog" data-testid="primitive-deprecate-dialog">
        <DialogHeader className="prm-dialog__head">
          <span className="tnt-icon-tile" data-tone="warn" aria-hidden>
            <Archive />
          </span>
          <div className="prm-dialog__heading">
            <DialogTitle>
              {alreadyDeprecated ? 'Edit deprecation' : `Deprecate ${primitive.name}`}
            </DialogTitle>
            <DialogDescription>
              Marks the type as one to stop using. {DEPRECATION_ADVISORY}
            </DialogDescription>
          </div>
        </DialogHeader>

        <div className="prm-dialog__body">
          <FormField
            label="Sunset date"
            error={errors.sunsetDate}
            helperText="Optional. The date after which this type should no longer be used."
          >
            <Input
              type="date"
              value={form.sunsetDate}
              min={today}
              onChange={(e) => update('sunsetDate', e.target.value)}
              aria-label="Sunset date"
              data-testid="deprecate-sunset-date"
            />
          </FormField>

          <FormField
            label="Message"
            error={errors.message}
            helperText={`Optional. Why it is deprecated and what to do instead (${
              form.message.trim().length
            }/${MAX_DEPRECATION_MESSAGE}).`}
          >
            <Textarea
              value={form.message}
              onChange={(e) => update('message', e.target.value)}
              placeholder="Use money-v2, which carries the currency as an ISO 4217 code."
              rows={3}
              aria-label="Message"
              data-testid="deprecate-message"
            />
          </FormField>

          <FormField
            label="Replacement type"
            helperText="Optional. Readers of this type are pointed at the replacement."
          >
            <select
              value={form.replacementId}
              onChange={(e) => update('replacementId', e.target.value)}
              aria-label="Replacement type"
              data-testid="deprecate-replacement"
              className="hive-control prm-select"
            >
              <option value="">No replacement</option>
              {/* Keep the stored replacement selectable even before (or without) the list. */}
              {form.replacementId && !options.some((o) => o.id === form.replacementId) ? (
                <option value={form.replacementId}>
                  {primitive.replacement?.name ?? form.replacementId}
                </option>
              ) : null}
              {options.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </FormField>

          {failure ? (
            <Alert variant="error" data-testid="deprecate-error">
              <span>{failure}</span>
            </Alert>
          ) : null}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={onClose}
            disabled={submitting}
            title={submitting ? 'Saving the deprecation…' : undefined}
          >
            Cancel
          </Button>
          <Button
            variant="danger"
            onClick={() => void handleSubmit()}
            disabled={hasErrors || submitting}
            title={hasErrors ? 'Fix the highlighted fields first' : undefined}
            data-testid="deprecate-submit"
          >
            {submitting ? 'Saving…' : alreadyDeprecated ? 'Save changes' : 'Deprecate type'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
