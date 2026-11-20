'use client';

/**
 * **Apply as version** — the overlay manager's apply step, COA-2.7 (#7050).
 *
 * Opened from the Versions screen's **Overlays** tab. Applying imports the revision with its whole
 * overlay chain applied — exactly what **Preview** and an export render — as a new version of the
 * same project, through the workspace's import quality gate. The revision and its chain stay as
 * they are; the new version starts with no overlays, since they are now part of its source.
 */

import * as React from 'react';

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
import { useReturnFocus } from '@/app/components/dialogs/useReturnFocus';
import { versionLabelProblem } from '@/app/components/ade/openapi-upgrade/openapiUpgradeModel';

import { applyVersionOverlays, type VersionOverlayApplyResult } from './versionOverlaysApi';

/** Props for {@link OverlayApplyDialog}. */
export interface OverlayApplyDialogProps {
  /** Whether the dialog is showing. Mount it with a fresh `key` per open so it starts over. */
  open: boolean;
  /** Called with the open state. */
  onOpenChange: (open: boolean) => void;
  /** The revision's project. */
  projectId: string;
  /** The revision whose chain is applied. */
  revisionId: string;
  /** The revision's label, for the title. */
  revisionLabel: string;
  /** How many overlays the chain holds. */
  overlayCount: number;
  /** Labels the project already uses (the new label must differ). */
  existingLabels: readonly string[];
  /** Called after the new version was created. */
  onApplied?: (result: VersionOverlayApplyResult) => void;
}

const LABEL_FIELD = 'overlay-apply-label';

/**
 * Render the dialog. See {@link OverlayApplyDialogProps}.
 *
 * @returns The dialog.
 */
export function OverlayApplyDialog({
  open,
  onOpenChange,
  projectId,
  revisionId,
  revisionLabel,
  overlayCount,
  existingLabels,
  onApplied,
}: OverlayApplyDialogProps) {
  const [label, setLabel] = React.useState('');
  const [applying, setApplying] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [applied, setApplied] = React.useState<VersionOverlayApplyResult | null>(null);
  const returnFocus = useReturnFocus(open);
  const labelProblem = versionLabelProblem(label, existingLabels);

  const handleApply = async () => {
    setApplying(true);
    setError(null);
    try {
      const result = await applyVersionOverlays(projectId, revisionId, label);
      setApplied(result);
      onApplied?.(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The overlays could not be applied.');
    } finally {
      setApplying(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (applying ? undefined : onOpenChange(next))}>
      <DialogContent size="default" onCloseAutoFocus={returnFocus} data-testid="overlay-apply-dialog">
        <DialogHeader>
          <DialogTitle>Apply overlays as a new version</DialogTitle>
          <DialogDescription>
            Version {revisionLabel} with its {overlayCount} {overlayCount === 1 ? 'overlay' : 'overlays'} applied
            becomes a new version of this project. Version {revisionLabel} and its overlays stay as they are.
          </DialogDescription>
        </DialogHeader>

        {applied ? (
          <p className="xstd-notice" data-tone="ok" role="status" data-testid="overlay-apply-done">
            Created version <strong>{applied.version_label}</strong> with {applied.change_count}{' '}
            {applied.change_count === 1 ? 'change' : 'changes'}.
          </p>
        ) : (
          <FormField
            label="New version label"
            htmlFor={LABEL_FIELD}
            helperText="Leave empty for a date and time label."
            error={labelProblem ?? undefined}
          >
            <Input
              id={LABEL_FIELD}
              value={label}
              placeholder="1.1.0"
              onChange={(event) => setLabel(event.target.value)}
              data-testid="overlay-apply-label"
            />
          </FormField>
        )}

        {error ? (
          <p className="xstd-notice" data-tone="warn" role="alert" data-testid="overlay-apply-error">
            {error}
          </p>
        ) : null}

        <DialogFooter>
          <Button
            variant="outline"
            disabled={applying}
            title={applying ? 'Wait for the new version to be created' : undefined}
            onClick={() => onOpenChange(false)}
          >
            {applied ? 'Close' : 'Cancel'}
          </Button>
          {applied ? null : (
            <Button
              variant="primary"
              disabled={applying || !!labelProblem}
              title={applying ? 'Creating the new version' : (labelProblem ?? undefined)}
              onClick={() => void handleApply()}
              data-testid="overlay-apply-confirm"
            >
              {applying ? 'Applying…' : 'Apply as version'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
