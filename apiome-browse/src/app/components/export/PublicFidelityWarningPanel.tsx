'use client';

/**
 * PublicFidelityWarningPanel — the public export dialog's fidelity advisory body (MFX-7.2, #3861).
 *
 * Renders the same advisory (MFX-2.4), preserved-% ring, count chips, expandable per-construct
 * report, and "Export anyway" acknowledgement as the ADE's FidelityWarningPanel — verbatim
 * server copy, identical severity palette. The ring and chips render immediately from the coarse
 * targets summary; the advisory and report arrive from `POST …/export/preview`.
 */

import { useMemo, useState } from 'react';
import {
  advisoryBannerClass,
  advisoryPresentation,
  advisorySeverityPillClass,
} from '../../../../lib/export/export-advisory';
import {
  fidelityChips,
  kindBadgeClass,
  kindLabel,
  ringGeometry,
  ringStrokeClass,
  sortReportItemsWorstFirst,
  type LossItem,
  type PublicExportPreviewResponse,
} from '../../../../lib/export/exportFidelityPreview';
import {
  requiresExportAcknowledgement,
  tierBadgeClass,
  tierLabel,
  type TargetFidelitySummary,
} from '../../../../lib/export/publicExport';

const RING_RADIUS = 40;

export interface PublicFidelityWarningPanelProps {
  targetLabel: string;
  targetDescription: string;
  fidelity: TargetFidelitySummary;
  preview: PublicExportPreviewResponse | null;
  previewLoading: boolean;
  previewError: string | null;
  acknowledged: boolean;
  onAcknowledgedChange: (acknowledged: boolean) => void;
}

export function PublicFidelityWarningPanel({
  targetLabel,
  targetDescription,
  fidelity,
  preview,
  previewLoading,
  previewError,
  acknowledged,
  onAcknowledgedChange,
}: PublicFidelityWarningPanelProps) {
  const [reportOpen, setReportOpen] = useState(false);

  const advisory = preview?.fidelity.advisory ?? null;
  const reportItems = useMemo(
    () => sortReportItemsWorstFirst(preview?.fidelity.report.items ?? []),
    [preview]
  );
  const needsAck = requiresExportAcknowledgement(fidelity.tier);
  const ring = ringGeometry(fidelity.preserved_percent, RING_RADIUS);

  return (
    <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
            Exporting to {targetLabel}
          </div>
          <div className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">{targetDescription}</div>
        </div>
        <span
          className={`inline-flex shrink-0 items-center rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset ${tierBadgeClass(fidelity.tier)}`}
        >
          {tierLabel(fidelity.tier)}
        </span>
      </div>

      {previewLoading && (
        <div className="mt-4 flex items-center gap-2 text-sm text-zinc-600 dark:text-zinc-300">
          <svg
            className="h-4 w-4 animate-spin text-[var(--brand)]"
            fill="none"
            viewBox="0 0 24 24"
            aria-hidden="true"
          >
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Computing the detailed fidelity report…
        </div>
      )}
      {!previewLoading && previewError && (
        <div
          data-testid="export-advisory-error"
          className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
        >
          The detailed fidelity report could not be loaded — the summary below still reflects
          this conversion.
        </div>
      )}
      {advisory && advisory.show && (
        <div
          data-testid="export-advisory"
          className={`mt-4 rounded-lg border p-3 ${advisoryBannerClass(advisoryPresentation(advisory).strength)}`}
        >
          <div className="flex flex-wrap items-center gap-2">
            <svg
              className="h-4 w-4 shrink-0"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.75}
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z"
              />
            </svg>
            <span className="text-sm font-semibold">{advisory.headline}</span>
            <span
              className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${advisorySeverityPillClass(advisory.severity)}`}
            >
              {advisory.severity ?? 'info'}
            </span>
          </div>
          <p className="mt-1.5 text-sm">{advisory.message}</p>
        </div>
      )}
      {advisory && !advisory.show && (
        <p
          data-testid="export-advisory"
          className="mt-4 text-sm text-emerald-700 dark:text-emerald-300"
        >
          {advisory.headline}
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-5">
        <div className="relative h-24 w-24 shrink-0">
          <svg
            viewBox="0 0 96 96"
            className="h-24 w-24 -rotate-90"
            role="img"
            aria-label={`${fidelity.preserved_percent}% of constructs preserved`}
          >
            <circle
              cx="48"
              cy="48"
              r={RING_RADIUS}
              fill="none"
              strokeWidth="8"
              className="stroke-zinc-200 dark:stroke-zinc-700"
            />
            <circle
              cx="48"
              cy="48"
              r={RING_RADIUS}
              fill="none"
              strokeWidth="8"
              strokeLinecap="round"
              strokeDasharray={ring.circumference}
              strokeDashoffset={ring.dashOffset}
              className={ringStrokeClass(fidelity.tier)}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <div
              data-testid="export-preserved-percent"
              className="text-xl font-bold text-zinc-900 dark:text-zinc-50"
            >
              {fidelity.preserved_percent}%
            </div>
            <div className="text-[9px] uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              preserved
            </div>
          </div>
        </div>

        <div className="flex flex-1 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            {fidelityChips(fidelity).map((chip) => (
              <span
                key={chip.key}
                className={`rounded-full px-2 py-0.5 text-xs font-semibold ${chip.className}`}
              >
                {chip.count} {chip.label}
              </span>
            ))}
          </div>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            {fidelity.total} construct{fidelity.total === 1 ? '' : 's'} considered for this source.
          </p>
        </div>
      </div>

      {reportItems.length > 0 && (
        <div className="mt-4">
          <button
            type="button"
            data-testid="export-report-toggle"
            onClick={() => setReportOpen((open) => !open)}
            className="flex items-center gap-1 text-xs font-medium text-[var(--brand)] hover:opacity-80"
          >
            <svg
              className={`h-3.5 w-3.5 transition-transform ${reportOpen ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
            {reportOpen ? 'Hide per-construct report' : 'Show per-construct report'} (
            {reportItems.length} construct{reportItems.length === 1 ? '' : 's'})
          </button>
          {reportOpen && (
            <ul
              data-testid="export-fidelity-report"
              className="mt-2 max-h-60 divide-y divide-zinc-100 overflow-y-auto rounded-lg border border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800"
            >
              {reportItems.map((item) => (
                <FidelityReportRow
                  key={`${item.construct}-${item.kind}-${item.message}`}
                  item={item}
                />
              ))}
            </ul>
          )}
        </div>
      )}

      {needsAck && (
        <label
          data-testid="export-ack"
          className="mt-4 flex cursor-pointer items-start gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
        >
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(e) => onAcknowledgedChange(e.target.checked)}
            className="mt-0.5 h-3.5 w-3.5 rounded border-amber-300 accent-amber-600"
          />
          <span>
            <span className="font-medium">
              I understand this conversion is lossy and want to export anyway.
            </span>
            <span className="mt-0.5 block text-xs opacity-80">
              The export stays disabled until you acknowledge the fidelity loss above.
            </span>
          </span>
        </label>
      )}
    </div>
  );
}

function FidelityReportRow({ item }: { item: LossItem }) {
  return (
    <li className="flex items-start gap-3 p-2.5 text-sm">
      <span
        className={`mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold ${kindBadgeClass(item.kind)}`}
      >
        {kindLabel(item.kind)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <code className="break-all font-mono text-xs font-medium text-zinc-900 dark:text-zinc-100">
            {item.construct}
          </code>
          {item.severity !== 'info' && (
            <span
              className={`rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase ${advisorySeverityPillClass(item.severity)}`}
            >
              {item.severity}
            </span>
          )}
        </span>
        <span className="mt-0.5 block text-xs text-zinc-600 dark:text-zinc-300">{item.message}</span>
        {item.target_mapping && (
          <span className="mt-0.5 block text-xs text-zinc-500 dark:text-zinc-400">
            In the target: {item.target_mapping}
          </span>
        )}
      </span>
    </li>
  );
}

export default PublicFidelityWarningPanel;
