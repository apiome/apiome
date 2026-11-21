'use client';

import * as React from 'react';
import { Wrench } from 'lucide-react';

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
import { Textarea } from '@/app/components/ui/Textarea';
import { MAX_FIX_REASON_LENGTH, defaultFixReason } from '@/app/utils/lint-fix';

/**
 * The "why are these fixes applied" dialog — GVM-3.6 (#5874).
 *
 * Every apply is audited with a reason (`version.lint_fix_applied`), so both surfaces — the
 * Lint report dialog and the Lint posture drawer / bulk bar — confirm through this one form.
 * The reason is prefilled so a one-click fix stays one confirmation away, and it can be edited
 * before it is recorded.
 */

/** What the dialog is about to apply. */
export interface LintFixApplyTarget {
  /** How many fixes will be applied. */
  count: number;
  /** The rule, when exactly one fix is applied. */
  ruleId?: string | null;
  /** How many revisions the fixes span (posture bulk apply); 1 when omitted. */
  revisions?: number;
}

/** Props for {@link LintFixApplyDialog}. */
export interface LintFixApplyDialogProps {
  /** What is about to be applied, or `null` when the dialog is closed. */
  target: LintFixApplyTarget | null;
  /** True while the apply is in flight. */
  busy?: boolean;
  /** Close without applying. */
  onClose: () => void;
  /** Apply with the given (trimmed, non-blank) reason. */
  onSubmit: (reason: string) => void;
}

/**
 * The confirm-with-reason form.
 *
 * @param props See {@link LintFixApplyDialogProps}.
 * @returns The dialog, or nothing when closed.
 */
export default function LintFixApplyDialog({
  target,
  busy = false,
  onClose,
  onSubmit,
}: LintFixApplyDialogProps) {
  const [reason, setReason] = React.useState('');
  const count = target?.count ?? 0;
  const ruleId = target?.ruleId ?? null;
  const isOpen = target !== null;

  // Prefill on open. Keyed on the open flag and the values, not the target object, so a
  // caller that builds the target inline does not wipe the reader's edits on every render.
  React.useEffect(() => {
    if (isOpen) setReason(defaultFixReason(count, ruleId));
  }, [isOpen, count, ruleId]);

  if (!target) return null;

  const trimmed = reason.trim();
  const canSubmit = Boolean(trimmed) && !busy;
  const revisions = target.revisions ?? 1;
  const noun = count === 1 ? 'fix' : 'fixes';

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (canSubmit) onSubmit(trimmed);
  };

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent data-testid="lint-fix-apply-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span className="tnt-icon-tile" data-tone="ok">
              <Wrench aria-hidden />
            </span>
            {count === 1 ? 'Apply fix' : `Apply ${count} fixes`}
          </DialogTitle>
          <DialogDescription>
            {revisions > 1
              ? `The ${noun} are applied to ${revisions} revisions. Each one gets a new lint-fix revision; the originals are not changed.`
              : `The ${noun} ${count === 1 ? 'is' : 'are'} applied as a new lint-fix revision; this revision is not changed. The new revision is linted again and its report stored.`}
          </DialogDescription>
        </DialogHeader>

        <form className="lw-form" noValidate onSubmit={submit}>
          <FormField
            label="Reason"
            required
            helperText="Recorded in the audit trail with the new revision."
          >
            <Textarea
              autoFocus
              value={reason}
              maxLength={MAX_FIX_REASON_LENGTH}
              data-testid="lint-fix-reason"
              onChange={(event) => setReason(event.target.value)}
            />
          </FormField>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              title={busy ? 'The fixes are being applied.' : undefined}
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              data-testid="lint-fix-submit"
              disabled={!canSubmit}
              title={
                busy
                  ? 'The fixes are being applied.'
                  : !trimmed
                    ? 'Give a reason first.'
                    : undefined
              }
            >
              {busy ? 'Applying…' : count === 1 ? 'Apply fix' : `Apply ${count} fixes`}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
