'use client';

import * as React from 'react';
import { Bot } from 'lucide-react';

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
import { Label } from '@/app/components/ui/Label';
import { Segmented, SegmentedItem } from '@/app/components/ui/Segmented';
import { Spinner } from '@/app/components/ui/Spinner';

import type { AgentToolsetTarget, PublishedVersionOption } from './agentAccessModel';

/**
 * Enable Agent Access for a published version — AGX-3.4 (#4540).
 *
 * Creates the version's toolset (AGX-1.2). apiome-rest seeds it **safe by default**: every read
 * operation exposed, every write operation off. The dialog says so, because the next thing the
 * reader sees is the tool list and they should not be surprised that writes are off.
 */

/** Props for {@link EnableToolsetDialog}. */
export interface EnableToolsetDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Published versions without a toolset. */
  versions: readonly PublishedVersionOption[];
  /**
   * Create the toolset.
   *
   * @returns `null` on success, or the message to show.
   */
  onSubmit: (versionId: string, target: AgentToolsetTarget) => Promise<string | null>;
}

/** Field id prefix; one instance is mounted at a time. */
const FIELD_ID = 'agx-enable';

/**
 * The dialog.
 *
 * @param props See {@link EnableToolsetDialogProps}.
 * @returns The dialog.
 */
export default function EnableToolsetDialog({
  open,
  onOpenChange,
  versions,
  onSubmit,
}: EnableToolsetDialogProps) {
  const [versionId, setVersionId] = React.useState('');
  const [target, setTarget] = React.useState<AgentToolsetTarget>('prod');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');

  React.useEffect(() => {
    if (!open) return;
    setVersionId(versions[0]?.id ?? '');
    setTarget('prod');
    setBusy(false);
    setError('');
  }, [open, versions]);

  const submit = React.useCallback(async () => {
    if (!versionId) {
      setError('Choose a published version.');
      return;
    }
    setBusy(true);
    setError('');
    const failure = await onSubmit(versionId, target);
    setBusy(false);
    if (failure) {
      setError(failure);
      return;
    }
    onOpenChange(false);
  }, [onOpenChange, onSubmit, target, versionId]);

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent data-testid="agx-enable-dialog">
        <DialogHeader>
          <DialogTitle className="agx-dialog-title">
            <span className="tnt-icon-tile" data-tone="honey">
              <Bot aria-hidden />
            </span>
            Enable Agent Access
          </DialogTitle>
          <DialogDescription>
            Let AI agents call a published version&apos;s operations as MCP tools.
          </DialogDescription>
        </DialogHeader>

        <form
          className="agx-form"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          {error && (
            <Alert variant="error" data-testid="agx-enable-error">
              {error}
            </Alert>
          )}

          {versions.length === 0 ? (
            <Alert variant="info" data-testid="agx-enable-no-versions">
              Every published version already has Agent Access, or nothing is published yet.
              Publish a version first.
            </Alert>
          ) : (
            <div className="agx-field">
              <Label htmlFor={`${FIELD_ID}-version`}>Published version</Label>
              <select
                id={`${FIELD_ID}-version`}
                className="hive-control agx-select"
                value={versionId}
                disabled={busy}
                onChange={(event) => setVersionId(event.target.value)}
              >
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.projectName ? `${v.projectName} · ${v.label}` : v.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div className="agx-field">
            <span className="agx-legend" id={`${FIELD_ID}-target`}>
              Calls go to
            </span>
            <Segmented
              aria-labelledby={`${FIELD_ID}-target`}
              value={target}
              onValueChange={(value) => setTarget(value === 'mock' ? 'mock' : 'prod')}
              size="sm"
            >
              <SegmentedItem value="prod" disabled={busy}>
                Production
              </SegmentedItem>
              <SegmentedItem value="mock" disabled={busy}>
                Mock
              </SegmentedItem>
            </Segmented>
            <p className="agx-hint">
              Read operations are exposed right away. Write operations stay off until you enable
              each one and confirm it.
            </p>
          </div>
        </form>

        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={busy || versions.length === 0}
            data-testid="agx-enable-submit"
            onClick={() => void submit()}
          >
            {busy ? <Spinner size="sm" aria-hidden /> : <Bot aria-hidden />}
            {busy ? 'Enabling…' : 'Enable Agent Access'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
