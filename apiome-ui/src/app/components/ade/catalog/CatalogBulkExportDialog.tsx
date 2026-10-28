'use client';

/**
 * The Catalog bulk bar's **Export…** (E1-3, #6219).
 *
 * Several ticked catalog items, one target: the dialog lists the targets the first item can export
 * to, runs **one** batch export job over every item (each at its latest version) and downloads one
 * `.zip` with a folder per item. Failures are per item — the outcome table names each one, and the
 * archive holds the rest. Exporting produces files; it never turns a catalog item into a project.
 *
 * Shown only while `export-studio` is released (the bulk plan's `exportable` list is empty
 * otherwise), so without the preview override nothing changes from RC6.
 */

import * as React from 'react';

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
import { useReturnFocus } from '@/app/components/dialogs/useReturnFocus';
import { MultiExportRun } from '@/app/components/ade/dashboard/export/MultiExportRun';
import { MAX_EXPORT_PAIRS, itemsBatchJobBody } from '@/app/components/ade/dashboard/export/exportBatchJob';
import { exportTargetCards } from '@/app/components/ade/dashboard/export/exportTargetCatalog';
import { useExportTargets } from '@/app/components/ade/dashboard/export/useExportTargets';
import type { CatalogItem } from './catalogModel';

/** Props for {@link CatalogBulkExportDialog}. */
export interface CatalogBulkExportDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** The ticked items to export (the bulk plan's `exportable`). */
  items: readonly CatalogItem[];
  /** Open/close callback. */
  onOpenChange: (open: boolean) => void;
}

/** Export several catalog items to one target as one archive. */
export function CatalogBulkExportDialog({ open, items, onOpenChange }: CatalogBulkExportDialogProps) {
  const returnFocus = useReturnFocus(open);
  const chosen = items.slice(0, MAX_EXPORT_PAIRS);
  const first = chosen[0]?.id ?? '';
  const { response, loading, error } = useExportTargets(open, first, null);
  const cards = React.useMemo(
    () => exportTargetCards(response).filter((card) => card.available),
    [response],
  );
  const [target, setTarget] = React.useState<string | null>(null);

  const body = target ? itemsBatchJobBody(chosen.map((item) => item.id), target) : null;
  const labels: Record<string, string> = {
    ...Object.fromEntries(chosen.map((item) => [item.id, item.name])),
    ...Object.fromEntries(cards.map((card) => [card.key, card.entry.descriptor.label])),
  };
  const noun = chosen.length === 1 ? 'catalog item' : 'catalog items';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg" onCloseAutoFocus={returnFocus} data-testid="catalog-bulk-export-dialog">
        <DialogHeader>
          <DialogTitle>
            Export {chosen.length} {noun}
          </DialogTitle>
          <DialogDescription>
            Pick one target. Each item exports at its latest version into its own folder of one .zip;
            an item that fails is listed and the archive holds the rest. Exporting never turns an item
            into a project.
          </DialogDescription>
        </DialogHeader>

        {items.length > MAX_EXPORT_PAIRS ? (
          <Alert variant="warning" data-testid="catalog-bulk-export-capped">
            One export runs at most {MAX_EXPORT_PAIRS} items; the first {MAX_EXPORT_PAIRS} of the{' '}
            {items.length} ticked are exported.
          </Alert>
        ) : null}

        {error ? (
          <Alert variant="error" data-testid="catalog-bulk-export-targets-error">
            {error}
          </Alert>
        ) : null}

        <fieldset className="xstd-stack xstd-stack--tight" disabled={loading}>
          <legend className="xstd-source__name">Target</legend>
          {loading ? <p className="xstd-quiet">Loading export targets…</p> : null}
          <ul className="xstd-multi__list" data-testid="catalog-bulk-export-targets">
            {cards.map((card) => (
              <li key={card.key}>
                <label className="xstd-multi__row" data-testid={`catalog-bulk-export-target-${card.key}`}>
                  <input
                    type="radio"
                    name="catalog-bulk-export-target"
                    value={card.key}
                    checked={target === card.key}
                    onChange={() => setTarget(card.key)}
                  />
                  <span className="xstd-multi__name">{card.entry.descriptor.label}</span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>

        {body && target ? (
          <MultiExportRun
            key={target}
            mode="generate"
            body={body}
            labels={labels}
            showItem
            archiveName="export-batch.zip"
          />
        ) : null}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} data-testid="catalog-bulk-export-close">
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
