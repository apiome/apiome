'use client';

import { useCallback, useMemo, useState } from 'react';
import {
  CheckCircle2,
  Download,
  FileOutput,
  Loader2,
  Package,
  SlidersHorizontal,
} from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '../../../ui/Dialog';
import { Button } from '../../../ui/Button';
import { Alert } from '../../../ui/Alert';
import { useExportTargets } from './useExportTargets';
import { useExportPreview } from './useExportPreview';
import { FidelityWarningPanel } from './FidelityWarningPanel';
import { requiresExportAcknowledgement } from './exportFidelityPreview';
import {
  changedOptions,
  exportTargetCards,
  optionFieldsFromSchema,
  tierBadgeClass,
  tierLabel,
  type ExportTargetCard,
  type OptionField,
} from './exportTargetCatalog';

interface ExportDialogProps {
  open: boolean;
  onClose: () => void;
  /** The artifact (project) id to export — export is version-scoped (MFX-6.5). */
  artifact: string;
  /** Human name of the artifact, shown in the header; falls back to the id. */
  artifactLabel?: string;
  /** The revision to export (UUID or version label); the latest revision when omitted. */
  version?: string | null;
  /** Called after a successful export (the document download has been handed to the browser). */
  onExported?: () => void;
}

type Step = 'source' | 'target' | 'fidelity' | 'export';

const STEP_LABELS = ['Source', 'Target', 'Fidelity', 'Export'] as const;
const STEP_ORDER: Step[] = ['source', 'target', 'fidelity', 'export'];

/** Parse the filename out of a `Content-Disposition: attachment; filename="…"` header. */
function filenameFromDisposition(disposition: string | null): string | null {
  if (!disposition) return null;
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  return match ? match[1] : null;
}

/** Hand a fetched document to the browser as a file download. */
function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/**
 * ExportDialog — the export mirror of the ImportDialog (MFX-6.1, #3855).
 *
 * A numbered stepper (Source → Target → Fidelity → Export) over a data-driven target-card grid:
 * every registered emitter from `GET /api/export/targets`, each card carrying a per-source
 * fidelity badge (`lossless` / `lossy` / `types-only`, MFX-2.5) so the trade-off is visible
 * before selecting. Picking a target updates the fidelity headline under the grid; the Fidelity
 * step renders the full warning panel (MFX-6.2, #3856): the server-computed advisory (MFX-2.4),
 * a preserved-% ring with count chips, and the expandable per-construct report from the
 * `POST /api/export/preview` dry run. A lossy conversion keeps the download gated behind an
 * explicit "Export anyway" acknowledgement; a lossless one stays quiet. Per-target options
 * (MFX-1.4) render from the target's options schema. Export emits via `POST /api/export/document`
 * and downloads the artifact.
 */
export function ExportDialog({
  open,
  onClose,
  artifact,
  artifactLabel,
  version = null,
  onExported,
}: ExportDialogProps) {
  const [step, setStep] = useState<Step>('source');
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [optionValues, setOptionValues] = useState<Record<string, unknown>>({});
  const [exporting, setExporting] = useState(false);
  const [exportedFilename, setExportedFilename] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** Whether the user has acknowledged a lossy conversion ("Export anyway", MFX-6.2). */
  const [acknowledged, setAcknowledged] = useState(false);

  const { response, loading, error: targetsError } = useExportTargets(open, artifact, version);
  const cards = useMemo(() => exportTargetCards(response), [response]);
  const selected = useMemo(
    () => cards.find((card) => card.key === selectedKey) ?? null,
    [cards, selectedKey],
  );
  const optionFields = useMemo(
    () =>
      selected
        ? optionFieldsFromSchema(selected.entry.options_schema, selected.entry.default_options)
        : [],
    [selected],
  );

  // The dry-run fidelity preview (advisory + per-construct report, MFX-6.2) for the chosen
  // target, fetched while the Fidelity step is showing.
  const {
    preview,
    loading: previewLoading,
    error: previewError,
  } = useExportPreview(open && step === 'fidelity', artifact, version, selectedKey);

  const sourceLabel = artifactLabel || artifact;
  const versionLabel = response?.version_label || version || 'latest';

  const reset = useCallback(() => {
    setStep('source');
    setSelectedKey(null);
    setOptionValues({});
    setExporting(false);
    setExportedFilename(null);
    setError(null);
    setAcknowledged(false);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [reset, onClose]);

  /** Select a target card and seed the options form with that target's defaults. */
  const handleSelect = useCallback((card: ExportTargetCard) => {
    if (!card.available) return;
    setSelectedKey(card.key);
    setError(null);
    // A different target is a different conversion — its loss must be re-acknowledged.
    setAcknowledged(false);
    const defaults: Record<string, unknown> = {};
    for (const field of optionFieldsFromSchema(card.entry.options_schema, card.entry.default_options)) {
      defaults[field.key] = field.defaultValue;
    }
    setOptionValues(defaults);
  }, []);

  const setOption = useCallback((key: string, value: unknown) => {
    setOptionValues((current) => ({ ...current, [key]: value }));
  }, []);

  /** Emit the document for the selected target and hand it to the browser as a download. */
  const handleExport = useCallback(async () => {
    if (!selected) return;
    setStep('export');
    setExporting(true);
    setError(null);
    try {
      const res = await fetch('/api/export/document', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          artifact,
          version: version || null,
          target: selected.key,
          options: changedOptions(optionValues, selected.entry.default_options),
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(
          typeof data?.error === 'string' ? data.error : 'The export failed. Try again.',
        );
      }
      const blob = await res.blob();
      const filename =
        filenameFromDisposition(res.headers.get('content-disposition')) ||
        `${artifact}-${selected.key}.txt`;
      downloadBlob(blob, filename);
      setExportedFilename(filename);
      onExported?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The export failed. Try again.');
      setStep('fidelity');
    } finally {
      setExporting(false);
    }
  }, [artifact, onExported, optionValues, selected, version]);

  const stepIndex = STEP_ORDER.indexOf(step);
  const fidelity = selected?.entry.fidelity ?? null;
  // Lossy conversions gate the download behind the explicit "Export anyway" acknowledgement
  // (MFX-6.2). Driven by the coarse tier so the gate never depends on the preview fetch.
  const needsAck = fidelity ? requiresExportAcknowledgement(fidelity.tier) : false;

  return (
    <Dialog open={open} onOpenChange={(o) => (!o ? handleClose() : undefined)}>
      <DialogContent className="flex max-h-[92vh] max-w-4xl flex-col overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            Export “{sourceLabel}” {versionLabel !== 'latest' ? `v${versionLabel}` : ''}
          </DialogTitle>
          <DialogDescription>
            Pick a target format and options. Each target shows how faithfully this source
            survives the conversion before you commit to it.
          </DialogDescription>
        </DialogHeader>

        <div className="mt-3 grid grid-cols-4 gap-2 text-xs">
          {STEP_LABELS.map((label, idx) => (
            <div
              key={label}
              className={`rounded-full border px-3 py-1.5 text-center ${
                idx <= stepIndex
                  ? 'border-indigo-200 bg-indigo-50 font-medium text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-200'
                  : 'border-gray-200 text-gray-500 dark:border-gray-700 dark:text-gray-400'
              }`}
            >
              {idx + 1}. {label}
            </div>
          ))}
        </div>

        {(error || targetsError) && (
          <Alert variant="error" className="mt-3">
            {error || targetsError}
          </Alert>
        )}

        {step === 'source' && (
          <div className="mt-4 space-y-4">
            <div className="rounded-xl border border-gray-200 p-4 dark:border-gray-700">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-900 dark:text-gray-100">
                <Package className="h-4 w-4 text-indigo-500" aria-hidden />
                Source
              </div>
              <div className="my-3 h-px bg-gray-200 dark:bg-gray-700" />
              {loading ? (
                <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
                  <Loader2 className="h-4 w-4 animate-spin text-indigo-500" aria-hidden />
                  Measuring export fidelity for this source…
                </div>
              ) : (
                <div className="space-y-1">
                  <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
                    {sourceLabel}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    Version {versionLabel}
                    {response ? ` · ${cards.length} export targets available` : ''}
                  </div>
                </div>
              )}
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400">
              Export is scoped to this version: the fidelity badge on every target card is
              computed for this source, not a generic estimate.
            </p>
          </div>
        )}

        {step === 'target' && (
          <div className="mt-4 space-y-4">
            <div className="text-center">
              <div className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                Choose a target format
              </div>
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Fidelity badges are computed for <strong>this</strong> source (version{' '}
                {versionLabel}).
              </p>
            </div>

            <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-4">
              {cards.map((card) => {
                const Icon = card.icon;
                const isSelected = card.key === selectedKey;
                return (
                  <button
                    key={card.key}
                    type="button"
                    data-testid={`export-target-${card.key}`}
                    onClick={() => handleSelect(card)}
                    disabled={!card.available}
                    title={
                      card.available
                        ? card.entry.descriptor.description
                        : card.entry.descriptor.unavailable_reason || 'Unavailable in this runtime'
                    }
                    className={`relative rounded-lg border p-3 text-center transition ${
                      isSelected
                        ? 'border-indigo-500 bg-indigo-50 text-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-100'
                        : card.available
                          ? 'border-gray-200 bg-white text-gray-700 hover:border-indigo-200 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-200'
                          : 'cursor-not-allowed border-gray-200 bg-gray-50 text-gray-400 dark:border-gray-800 dark:bg-gray-900 dark:text-gray-600'
                    }`}
                  >
                    <span
                      className={`absolute right-2 top-2 rounded-full px-2 py-0.5 text-[10px] font-semibold ${tierBadgeClass(card.entry.fidelity.tier)}`}
                    >
                      {tierLabel(card.entry.fidelity.tier)}
                    </span>
                    <Icon className="mx-auto mb-2 mt-3 h-5 w-5" aria-hidden />
                    <div className="text-sm font-medium">{card.entry.descriptor.label}</div>
                    <div className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                      {card.entry.descriptor.paradigm}
                      {card.entry.descriptor.multi_file ? ' · multi-file' : ''}
                    </div>
                  </button>
                );
              })}
            </div>

            {selected && fidelity && (
              <div
                data-testid="export-fidelity-headline"
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-gray-200 p-3 text-sm dark:border-gray-700"
              >
                <div className="text-gray-700 dark:text-gray-200">
                  Exporting to <strong>{selected.entry.descriptor.label}</strong>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${tierBadgeClass(fidelity.tier)}`}
                  >
                    {tierLabel(fidelity.tier)}
                  </span>
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {fidelity.preserved_percent}% preserved
                  </span>
                </div>
              </div>
            )}

            {selected && optionFields.length > 0 && (
              <div className="rounded-xl border border-gray-200 p-4 dark:border-gray-700">
                <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-900 dark:text-gray-100">
                  <SlidersHorizontal className="h-4 w-4 text-indigo-500" aria-hidden />
                  Target options
                </div>
                <div className="my-3 h-px bg-gray-200 dark:bg-gray-700" />
                <div className="grid gap-4 sm:grid-cols-2">
                  {optionFields.map((field) => (
                    <ExportOptionControl
                      key={field.key}
                      targetKey={selected.key}
                      field={field}
                      value={optionValues[field.key]}
                      onChange={(value) => setOption(field.key, value)}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {step === 'fidelity' && selected && fidelity && (
          <div className="mt-4 space-y-4">
            <FidelityWarningPanel
              targetLabel={selected.entry.descriptor.label}
              targetDescription={selected.entry.descriptor.description}
              fidelity={fidelity}
              preview={preview}
              previewLoading={previewLoading}
              previewError={previewError}
              acknowledged={acknowledged}
              onAcknowledgedChange={setAcknowledged}
            />
          </div>
        )}

        {step === 'export' && (
          <div className="flex flex-1 flex-col items-center justify-center gap-3 py-10 text-center">
            {exportedFilename ? (
              <>
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-green-500 text-white">
                  <CheckCircle2 className="h-7 w-7" aria-hidden />
                </div>
                <div className="text-sm text-gray-700 dark:text-gray-200">
                  Exported <strong>{exportedFilename}</strong> — check your downloads.
                </div>
              </>
            ) : (
              <>
                <Loader2 className="h-8 w-8 animate-spin text-indigo-500" aria-hidden />
                <div className="text-sm text-gray-700 dark:text-gray-200">
                  Emitting {selected?.entry.descriptor.label ?? 'the document'}…
                </div>
              </>
            )}
          </div>
        )}

        <div className="mt-4 flex justify-between gap-2 border-t border-gray-200 pt-3 dark:border-gray-700">
          <Button variant="outline" onClick={handleClose} disabled={exporting}>
            {exportedFilename ? 'Close' : 'Cancel'}
          </Button>
          <div className="flex gap-2">
            {(step === 'target' || step === 'fidelity') && (
              <Button
                variant="outline"
                onClick={() => setStep(step === 'fidelity' ? 'target' : 'source')}
              >
                Back
              </Button>
            )}
            {step === 'source' && (
              <Button onClick={() => setStep('target')} disabled={loading || !response}>
                <FileOutput className="h-4 w-4" aria-hidden />
                Choose target
              </Button>
            )}
            {step === 'target' && (
              <Button onClick={() => setStep('fidelity')} disabled={!selected}>
                Continue
              </Button>
            )}
            {step === 'fidelity' && (
              <Button
                onClick={() => void handleExport()}
                disabled={exporting || (needsAck && !acknowledged)}
                title={
                  needsAck && !acknowledged
                    ? 'Acknowledge the fidelity loss to enable the export.'
                    : undefined
                }
              >
                <Download className="h-4 w-4" aria-hidden />
                {needsAck ? 'Export anyway' : 'Export'}
              </Button>
            )}
            {step === 'export' && exportedFilename && (
              <Button onClick={handleClose}>Done</Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

interface ExportOptionControlProps {
  /** The selected target's key, used to namespace input ids/names. */
  targetKey: string;
  field: OptionField;
  value: unknown;
  onChange: (value: unknown) => void;
}

/**
 * One per-target option control (MFX-1.4): a checkbox for booleans, a segmented button row for
 * string enums, and a text input for free strings. Complex option types never reach here —
 * `optionFieldsFromSchema` already filters them out.
 */
function ExportOptionControl({ targetKey, field, value, onChange }: ExportOptionControlProps) {
  const inputId = `export-option-${targetKey}-${field.key}`;

  if (field.kind === 'boolean') {
    return (
      <label className="flex items-start gap-3 text-sm text-gray-700 dark:text-gray-200" htmlFor={inputId}>
        <input
          id={inputId}
          type="checkbox"
          checked={value === true}
          onChange={(e) => onChange(e.target.checked)}
          className="mt-0.5"
        />
        <span>
          <span className="block font-medium">{field.label}</span>
          {field.description && (
            <span className="block text-xs text-gray-500 dark:text-gray-400">{field.description}</span>
          )}
        </span>
      </label>
    );
  }

  if (field.kind === 'enum') {
    return (
      <div className="text-sm">
        <div className="font-medium text-gray-700 dark:text-gray-200">{field.label}</div>
        {field.description && (
          <div className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{field.description}</div>
        )}
        <div className="mt-2 inline-flex overflow-hidden rounded-lg border border-gray-300 dark:border-gray-700">
          {field.enumValues.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => onChange(option)}
              className={`px-3 py-1.5 text-xs transition ${
                value === option
                  ? 'bg-indigo-600 font-medium text-white'
                  : 'bg-white text-gray-700 hover:bg-gray-50 dark:bg-gray-950 dark:text-gray-200 dark:hover:bg-gray-900'
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="text-sm">
      <label className="font-medium text-gray-700 dark:text-gray-200" htmlFor={inputId}>
        {field.label}
      </label>
      {field.description && (
        <div className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">{field.description}</div>
      )}
      <input
        id={inputId}
        value={typeof value === 'string' ? value : ''}
        onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
        placeholder="server default"
        className="mt-2 w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-950"
      />
    </div>
  );
}

export default ExportDialog;
