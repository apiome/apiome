'use client';

/**
 * Convert several catalog items to OpenAPI at once (MFI-28.5, #4121).
 *
 * Opened by the bulk bar's **Convert…** on the catalog list. It is the EPIC-22 fidelity-gated
 * flow, once per item, not a shortcut around it:
 *
 *  1. On open it previews every item in turn (the same dry-run the single-item dialog runs —
 *     no side effects), and lists each with its fidelity grade, tier and status.
 *  2. A `low`-tier item needs its own acknowledgement before it is committed, exactly as in
 *     the single-item dialog — or the one explicit **apply the fidelity warning to all** gate,
 *     whose label says what it stands in for. Any item can be unticked to leave it out, and
 *     **Review…** opens the full single-item preview (summary, projection graph, raw OpenAPI,
 *     gap-filling defaults) for it.
 *  3. **Convert** commits the queued items one at a time — sequential for the reason the bulk
 *     delete is: these are per-item endpoints, and each conversion mints a project. Each row
 *     then says what happened to *it*, and a failed row can be retried.
 *
 * Every rule here (the queue, the gate, the outcome line) is `catalogBulkConvertModel.ts`.
 */

import * as React from 'react';
import Link from 'next/link';
import { ArrowLeftRight } from 'lucide-react';

import { Alert } from '@/app/components/ui/Alert';
import { Badge, type BadgeTone } from '@/app/components/ui/Badge';
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
import { gradeBand } from '@/app/components/ui/statusVocabulary';
import { useReturnFocus } from '@/app/components/dialogs/useReturnFocus';
import { ConversionPreviewDialog } from '@/app/components/ade/dashboard/catalog/ConversionPreviewDialog';
import { convertedProjectHref } from '@/app/utils/catalog-conversion';
import {
  CONVERSION_WARNING_SENTENCE,
  commitConversion,
  fetchConversionDryRun,
  tierTone,
  tierWarning,
} from '@/app/utils/conversion-fidelity';
import { cn } from '@lib/utils';

import {
  bulkConvertGate,
  bulkConvertInitialRows,
  bulkConvertLowTierCount,
  bulkConvertNeedsAck,
  bulkConvertOffersApplyToAll,
  bulkConvertQueue,
  bulkConvertStatusLabel,
  bulkConvertSummary,
  type BulkConvertRow,
  type BulkConvertStatus,
} from './catalogBulkConvertModel';
import type { CatalogItem } from './catalogModel';

/** The status tone each row state is drawn in. */
const STATUS_TONE: Readonly<Record<BulkConvertStatus, BadgeTone>> = {
  previewing: 'neutral',
  ready: 'neutral',
  'preview-failed': 'danger',
  converting: 'neutral',
  converted: 'ok',
  failed: 'danger',
};

export interface CatalogBulkConvertDialogProps {
  /** Whether the dialog is showing. Mount it with a fresh `key` per opening. */
  open: boolean;
  /** The items to convert — the bulk plan's `convertible` rows. */
  items: readonly CatalogItem[];
  /** Called with `false` to close. */
  onOpenChange: (open: boolean) => void;
  /** Called once when the dialog closes after at least one item converted, so the list reloads. */
  onFinished?: () => void;
}

/**
 * Render the bulk convert review. See {@link CatalogBulkConvertDialogProps}.
 *
 * @returns The dialog, plus the single-item preview while a row is being reviewed.
 */
export function CatalogBulkConvertDialog({
  open,
  items,
  onOpenChange,
  onFinished,
}: CatalogBulkConvertDialogProps) {
  const returnFocus = useReturnFocus(open);
  const [rows, setRows] = React.useState<BulkConvertRow[]>(() => bulkConvertInitialRows(items));
  const [applyToAll, setApplyToAll] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  /** The row whose full single-item preview is open, if any. */
  const [reviewing, setReviewing] = React.useState<CatalogItem | null>(null);

  /** Replace one row by id. */
  const patchRow = React.useCallback((id: string, patch: Partial<BulkConvertRow>) => {
    setRows((current) => current.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  }, []);

  // Preview every item once, in order, when the dialog opens; abort the rest on close.
  React.useEffect(() => {
    if (!open) return undefined;
    const controller = new AbortController();
    void (async () => {
      for (const item of items) {
        if (controller.signal.aborted) return;
        try {
          const result = await fetchConversionDryRun(item.id, { signal: controller.signal });
          if (controller.signal.aborted) return;
          patchRow(item.id, { status: 'ready', report: result.report, error: null });
        } catch (error) {
          if (controller.signal.aborted) return;
          patchRow(item.id, {
            status: 'preview-failed',
            error:
              error instanceof Error && error.message
                ? error.message
                : 'Failed to preview conversion',
          });
        }
      }
    })();
    return () => controller.abort();
  }, [open, items, patchRow]);

  const lowTierCount = bulkConvertLowTierCount(rows);
  /** The apply-to-all gate, in force only while it is offered (see the model). */
  const applyAllOffered = bulkConvertOffersApplyToAll(rows);
  const applyAll = applyToAll && applyAllOffered;
  const gate = bulkConvertGate(rows, applyAll, busy);
  const summary = bulkConvertSummary(rows);
  const anyConverted = rows.some((row) => row.status === 'converted');

  /** Commit every queued row, one at a time, recording each outcome on its row. */
  const handleConvert = async () => {
    const queue = bulkConvertQueue(rows, applyAll);
    if (queue.length === 0) return;
    setBusy(true);
    for (const row of queue) {
      patchRow(row.id, { status: 'converting', error: null });
      try {
        const result = await commitConversion(row.id);
        patchRow(row.id, { status: 'converted', projectId: result.projectId ?? null });
      } catch (error) {
        patchRow(row.id, {
          status: 'failed',
          error: error instanceof Error && error.message ? error.message : 'Failed to convert',
        });
      }
    }
    setBusy(false);
  };

  /** Close, telling the list to reload when anything was created. */
  const handleOpenChange = (next: boolean) => {
    if (!next && busy) return;
    if (!next && anyConverted) onFinished?.();
    onOpenChange(next);
  };

  const finished = summary !== null && !busy;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        size="lg"
        onCloseAutoFocus={returnFocus}
        data-testid="catalog-bulk-convert-dialog"
        className="cbc-dialog"
      >
        <DialogHeader>
          <DialogTitle>
            Convert {items.length} {items.length === 1 ? 'catalog item' : 'catalog items'} to
            OpenAPI
          </DialogTitle>
          <DialogDescription>
            Each item is previewed and converted on its own, and each becomes a new OpenAPI project.{' '}
            {CONVERSION_WARNING_SENTENCE}
          </DialogDescription>
        </DialogHeader>

        <ul className="cbc-list" data-testid="catalog-bulk-convert-rows">
          {rows.map((row) => {
            const item = items.find((candidate) => candidate.id === row.id) ?? null;
            const needsAck = bulkConvertNeedsAck(row);
            const editable = !busy && (row.status === 'ready' || row.status === 'failed');
            const warning = row.report ? tierWarning(row.report.tier) : null;
            return (
              <li
                key={row.id}
                className="cbc-row"
                data-status={row.status}
                data-testid={`catalog-bulk-convert-row-${row.id}`}
              >
                <div className="cbc-row__main">
                  <Checkbox
                    checked={row.included}
                    disabled={!editable}
                    onCheckedChange={(next) => patchRow(row.id, { included: next === true })}
                    aria-label={`Include ${row.name}`}
                  />
                  <span className="cbc-row__name">{row.name}</span>
                  {row.report ? (
                    <span className="cbc-row__fidelity">
                      <span
                        className={cn('cbc-row__grade', gradeBand(row.report.grade).solidClass)}
                      >
                        {row.report.grade}
                      </span>
                      <Badge status={tierTone(row.report.tier)}>{row.report.tier} fidelity</Badge>
                    </span>
                  ) : null}
                  <Badge
                    variant={STATUS_TONE[row.status]}
                    data-testid="catalog-bulk-convert-status"
                  >
                    {bulkConvertStatusLabel(row)}
                  </Badge>
                  {row.status === 'converted' && row.projectId ? (
                    <Link
                      href={convertedProjectHref({ projectId: row.projectId })}
                      className="cbc-row__link"
                    >
                      Open project
                    </Link>
                  ) : null}
                  {item && editable ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setReviewing(item)}
                      data-testid={`catalog-bulk-convert-review-${row.id}`}
                    >
                      Review…
                    </Button>
                  ) : null}
                </div>
                {row.error ? (
                  <div className="cbc-row__error" role="alert">
                    {row.error}
                  </div>
                ) : null}
                {needsAck && warning && row.included && editable && !applyAll ? (
                  <label className="cbc-row__ack">
                    <Checkbox
                      checked={row.acknowledged}
                      onCheckedChange={(next) => patchRow(row.id, { acknowledged: next === true })}
                      data-testid={`catalog-bulk-convert-ack-${row.id}`}
                    />
                    <span>{warning.ackLabel}</span>
                  </label>
                ) : null}
              </li>
            );
          })}
        </ul>

        {applyAllOffered && !finished ? (
          <Alert variant="danger">
            <label className="cbc-apply-all">
              <Checkbox
                checked={applyToAll}
                disabled={busy}
                onCheckedChange={(next) => setApplyToAll(next === true)}
                data-testid="catalog-bulk-convert-apply-all"
              />
              <span>
                Apply the fidelity warning to all {lowTierCount} low-fidelity items: I understand
                their converted specs will be incomplete and want to convert anyway.
              </span>
            </label>
          </Alert>
        ) : null}

        <DialogFooter>
          <p className="cbc-footer__status" role="status" aria-live="polite">
            {summary ?? gate.reason ?? ''}
          </p>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => handleOpenChange(false)}
            data-testid="catalog-bulk-convert-close"
          >
            {finished ? 'Done' : 'Cancel'}
          </Button>
          <Button
            variant="primary"
            disabled={!gate.canConvert}
            onClick={() => void handleConvert()}
            data-testid="catalog-bulk-convert-submit"
          >
            <ArrowLeftRight aria-hidden />
            Convert {bulkConvertQueue(rows, applyAll).length || ''}
          </Button>
        </DialogFooter>

        {/* Inside the content, so Radix stacks it as a child layer of this dialog — focus
              moves into it, Escape closes it alone, and focus comes back here. */}
        {reviewing ? (
          <ConversionPreviewDialog
            key={`${reviewing.id}:bulk-review`}
            itemId={reviewing.id}
            itemName={reviewing.name}
            sourceFormat={reviewing.sourceFormat ?? null}
            open
            onOpenChange={(next) => {
              if (!next) setReviewing(null);
            }}
            onConverted={() => patchRow(reviewing.id, { status: 'converted', error: null })}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
