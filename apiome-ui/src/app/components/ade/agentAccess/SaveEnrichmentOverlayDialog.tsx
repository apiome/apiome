'use client';

import * as React from 'react';
import { Layers } from 'lucide-react';

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
import { Spinner } from '@/app/components/ui/Spinner';
import { formatVersionWithPrefix } from '@/app/utils/version-display';
import {
  addVersionOverlay,
  type VersionOverlaysRevisionRow,
} from '@/app/components/ade/versionOverlays/versionOverlaysApi';

import { fetchEnrichmentOverlay, fetchProjectRevisions, type EnrichmentOverlay } from './agentAccessApi';

/** Props for {@link SaveEnrichmentOverlayDialog}. */
export interface SaveEnrichmentOverlayDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** Close it. Ignored while the save runs. */
  onOpenChange: (open: boolean) => void;
  /** The toolset whose accepted enrichment is saved. */
  toolsetId: string;
}

/**
 * **Save as overlay** — GVM-4.3 (#5878).
 *
 * Copies a toolset's **accepted** description enrichment (AGX-1.3) into a draft revision's stored
 * overlay chain, so the descriptions agents are served also reach that revision's exports. The
 * toolset's own revision is published (read-only), so the overlay goes to a draft revision of the
 * same project. The enrichment itself is not changed.
 *
 * @param props See {@link SaveEnrichmentOverlayDialogProps}.
 * @returns The dialog.
 */
export default function SaveEnrichmentOverlayDialog({ open, onOpenChange, toolsetId }: SaveEnrichmentOverlayDialogProps) {
  const [overlay, setOverlay] = React.useState<EnrichmentOverlay | null>(null);
  const [drafts, setDrafts] = React.useState<VersionOverlaysRevisionRow[]>([]);
  const [target, setTarget] = React.useState('');
  const [loading, setLoading] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState('');
  const [saved, setSaved] = React.useState('');
  const selectId = React.useId();

  React.useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    setSaved('');
    (async () => {
      try {
        const projection = await fetchEnrichmentOverlay(toolsetId);
        const revisions = await fetchProjectRevisions(projection.project_id);
        if (cancelled) return;
        const draftRows = revisions.filter((r) => !r.published && !r.deleted_at);
        setOverlay(projection);
        setDrafts(draftRows);
        setTarget(draftRows[0]?.id ?? '');
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'The enrichment could not be read.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, toolsetId]);

  const canSave = !!overlay && overlay.action_count > 0 && !!target && !busy;
  const disabledReason = !overlay
    ? 'Loading the accepted enrichment…'
    : overlay.action_count === 0
      ? 'No accepted descriptions to save yet.'
      : !target
        ? 'This project has no draft revision to save the overlay to.'
        : busy
          ? 'Saving…'
          : undefined;

  const save = React.useCallback(async () => {
    if (!overlay || !target) return;
    setBusy(true);
    setError('');
    try {
      const label = overlay.version_label ?? overlay.version_id.slice(0, 8);
      await addVersionOverlay(overlay.project_id, target, {
        name: `Agent enrichment (${label})`,
        source: 'enrichment-export',
        document: overlay.document,
      });
      const draft = drafts.find((d) => d.id === target);
      setSaved(`Saved to ${formatVersionWithPrefix(draft?.version_id)}. It applies when that revision is exported or published.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The overlay could not be saved.');
    } finally {
      setBusy(false);
    }
  }, [overlay, target, drafts]);

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent data-testid="agx-save-enrichment-overlay">
        <DialogHeader>
          <DialogTitle className="agx-dialog-title">
            <span className="tnt-icon-tile" data-tone="accent">
              <Layers aria-hidden />
            </span>
            Save enrichment as overlay
          </DialogTitle>
          <DialogDescription>
            Accepted descriptions go into a draft revision&apos;s overlays, so its exports carry them.
          </DialogDescription>
        </DialogHeader>

        <div className="agx-dialog-body">
          {loading ? (
            <Spinner aria-label="Loading" />
          ) : overlay ? (
            <>
              <p className="hive-quiet" data-testid="agx-save-enrichment-overlay-count">
                {overlay.action_count} accepted {overlay.action_count === 1 ? 'description' : 'descriptions'}
                {overlay.skipped.length > 0
                  ? ` · ${overlay.skipped.length} not addressable in OpenAPI (left out)`
                  : ''}
              </p>
              {drafts.length > 0 ? (
                <>
                  <Label htmlFor={selectId}>Draft revision</Label>
                  <select
                    id={selectId}
                    className="hive-control vovl-select"
                    value={target}
                    onChange={(event) => setTarget(event.target.value)}
                    data-testid="agx-save-enrichment-overlay-target"
                  >
                    {drafts.map((d) => (
                      <option key={d.id} value={d.id}>
                        {formatVersionWithPrefix(d.version_id)}
                      </option>
                    ))}
                  </select>
                </>
              ) : (
                <Alert variant="warning" data-testid="agx-save-enrichment-overlay-no-draft">
                  This project has no draft revision. Create one, then save the overlay to it.
                </Alert>
              )}
            </>
          ) : null}
          {saved && (
            <Alert variant="success" data-testid="agx-save-enrichment-overlay-saved">
              {saved}
            </Alert>
          )}
          {error && (
            <Alert variant="error" data-testid="agx-save-enrichment-overlay-error">
              {error}
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy} title={busy ? 'Saving…' : undefined}>
            {saved ? 'Done' : 'Cancel'}
          </Button>
          {saved ? null : (
            <Button
              onClick={() => void save()}
              disabled={!canSave}
              title={canSave ? undefined : disabledReason}
              data-testid="agx-save-enrichment-overlay-save"
            >
              {busy ? 'Saving…' : 'Save as overlay'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
