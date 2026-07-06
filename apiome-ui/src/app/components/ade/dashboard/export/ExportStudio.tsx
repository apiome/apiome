'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  FileArchive,
  FileOutput,
  Loader2,
  Package,
  PanelsTopLeft,
  SlidersHorizontal,
  Sparkles,
} from 'lucide-react';
import { Button } from '../../../ui/Button';
import { Alert } from '../../../ui/Alert';
import {
  dashboardContentStackClass,
  dashboardMainClass,
  dashboardPanelPaddedClass,
} from '../dashboardScreenClasses';
import { useExportTargets } from './useExportTargets';
import { useExportPreview } from './useExportPreview';
import { ExportTargetGrid } from './ExportTargetGrid';
import { ExportOptionsForm } from './ExportOptionsForm';
import { FidelityWarningPanel } from './FidelityWarningPanel';
import { ArtifactPreviewCard } from './ArtifactPreviewCard';
import { requiresExportAcknowledgement } from './exportFidelityPreview';
import { zipFilenameFor, type EmittedArtifact } from './exportArtifactPreview';
import { buildZip } from './zipBundle';
import { downloadBlob, filenameFromDisposition } from './exportDownload';
import type { ExportedArtifactSummary } from './ExportDialog';
import {
  changedOptions,
  exportTargetCards,
  optionFieldsFromSchema,
  tierBadgeClass,
  tierLabel,
  validateExportOptions,
  type ExportTargetCard,
} from './exportTargetCatalog';

interface ExportStudioProps {
  /** The artifact (project / catalog-item) id to export — export is version-scoped. */
  artifact: string;
  /** Human name of the source, shown in the header; falls back to the id. */
  artifactLabel?: string | null;
  /** The revision to export (UUID or version label); the latest revision when omitted. */
  version?: string | null;
  /** A target emitter key to pre-select (carried from the ExportDialog escalation). */
  initialTarget?: string | null;
  /** Called after a successful generate, so an entry point can record it as a recent export. */
  onGenerated?: (summary: ExportedArtifactSummary) => void;
}

/** The Studio's five stepper stops (MFX-41.1). */
type StudioStep = 'source' | 'target' | 'options' | 'verify' | 'review';

const STUDIO_STEPS: { key: StudioStep; label: string }[] = [
  { key: 'source', label: 'Source' },
  { key: 'target', label: 'Target' },
  { key: 'options', label: 'Options' },
  { key: 'verify', label: 'Verify' },
  { key: 'review', label: 'Review & Generate' },
];

const STEP_ORDER: StudioStep[] = STUDIO_STEPS.map((s) => s.key);

/**
 * ExportStudio — the full-page export workspace (MFX-41.1, #4348).
 *
 * The ExportDialog (MFX-6.1) is the quick modal path; the Studio is where an enterprise user can
 * *work* an export: a numbered stepper **Source → Target → Options → Verify → Review & Generate**
 * over the same registry-driven target grid and generated options form the dialog uses (shared
 * components, not forks). Each step gates forward navigation — no Verify until a target is picked,
 * no Options step advance until the options validate, and no Generate until Verify ran (or the
 * user explicitly skips it, acknowledging any fidelity loss). The stepper's state (selected
 * target, option values, acknowledgement) survives moving back and forth between steps.
 *
 * The route is always scoped to a source (`artifact` [+ `version`]); it is never a bare global
 * screen. The ExportDialog's "Open in Export Studio" footer action lands here with the source —
 * and, when one was picked, the target — pre-selected.
 */
export function ExportStudio({
  artifact,
  artifactLabel,
  version = null,
  initialTarget = null,
  onGenerated,
}: ExportStudioProps) {
  const [step, setStep] = useState<StudioStep>('source');
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [optionValues, setOptionValues] = useState<Record<string, unknown>>({});
  /** Whether the Verify step's dry run has run (preview settled) or was explicitly skipped. */
  const [verifyRan, setVerifyRan] = useState(false);
  /** Whether the user acknowledged a lossy conversion ("Generate anyway" / skip-with-ack). */
  const [acknowledged, setAcknowledged] = useState(false);
  const [generating, setGenerating] = useState(false);
  /** The emitted document being reviewed on the Review step, once generated. */
  const [emitted, setEmitted] = useState<EmittedArtifact | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { response, loading, error: targetsError } = useExportTargets(true, artifact, version);
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
  const validation = useMemo(
    () => validateExportOptions(optionFields, optionValues),
    [optionFields, optionValues],
  );

  // The dry-run fidelity preview (advisory + per-construct report, MFX-6.2) for the chosen target,
  // fetched once the Verify step is reached and kept for the Review step's artifact report.
  const {
    preview,
    loading: previewLoading,
    error: previewError,
  } = useExportPreview(
    (step === 'verify' || step === 'review') && !emitted,
    artifact,
    version,
    selectedKey,
  );

  const sourceLabel = artifactLabel || artifact;
  const versionLabel = response?.version_label || version || 'latest';

  const fidelity = selected?.entry.fidelity ?? null;
  // Lossy conversions gate Generate behind an explicit acknowledgement (MFX-6.2), driven by the
  // coarse tier so the gate never depends on the preview fetch.
  const needsAck = fidelity ? requiresExportAcknowledgement(fidelity.tier) : false;

  /** Select a target card and seed the options form with that target's defaults. */
  const selectCard = useCallback((card: ExportTargetCard) => {
    if (!card.available) return;
    setSelectedKey(card.key);
    setError(null);
    // A different target is a different conversion: its loss and verify must be re-established.
    setAcknowledged(false);
    setVerifyRan(false);
    const defaults: Record<string, unknown> = {};
    for (const field of optionFieldsFromSchema(card.entry.options_schema, card.entry.default_options)) {
      defaults[field.key] = field.defaultValue;
    }
    setOptionValues(defaults);
  }, []);

  // Pre-select the target carried from the dialog escalation, once the target list has loaded.
  // Runs at most once (guarded by the ref) so a later manual re-pick is never overwritten.
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current || !initialTarget || cards.length === 0) return;
    const card = cards.find((c) => c.key === initialTarget);
    if (!card) return;
    seeded.current = true;
    selectCard(card);
  }, [initialTarget, cards, selectCard]);

  // The Verify step "ran" as soon as the dry run settles (loaded or errored) — a preview failure
  // degrades to the coarse summary but still counts as verified, matching the dialog.
  useEffect(() => {
    if (step === 'verify' && (preview || previewError)) setVerifyRan(true);
  }, [step, preview, previewError]);

  const setOption = useCallback((key: string, value: unknown) => {
    setOptionValues((current) => ({ ...current, [key]: value }));
  }, []);

  /** Generate the document for the selected target and show it in the Review preview. */
  const handleGenerate = useCallback(async () => {
    if (!selected) return;
    setGenerating(true);
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
      const text = await res.text();
      const filename =
        filenameFromDisposition(res.headers.get('content-disposition')) ||
        `${artifact}-${selected.key}.txt`;
      setEmitted({ filename, mediaType: res.headers.get('content-type') || '', text });
      onGenerated?.({
        targetKey: selected.key,
        targetLabel: selected.entry.descriptor.label,
        tier: selected.entry.fidelity.tier,
        preservedPercent: selected.entry.fidelity.preserved_percent,
        filename,
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The export failed. Try again.');
    } finally {
      setGenerating(false);
    }
  }, [artifact, onGenerated, optionValues, selected, version]);

  /** Download the generated document as its single file. */
  const handleDownloadFile = useCallback(() => {
    if (!emitted) return;
    downloadBlob(
      new Blob([emitted.text], { type: emitted.mediaType || 'text/plain' }),
      emitted.filename,
    );
  }, [emitted]);

  /** Download the generated document as a `.zip` built client-side. */
  const handleDownloadZip = useCallback(() => {
    if (!emitted) return;
    try {
      const bytes = buildZip([{ path: emitted.filename, content: emitted.text }]);
      downloadBlob(new Blob([bytes], { type: 'application/zip' }), zipFilenameFor(emitted.filename));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The zip download failed. Try again.');
    }
  }, [emitted]);

  /** Whether the current step permits advancing to the next one. */
  const canAdvance = useMemo(() => {
    switch (step) {
      case 'source':
        return Boolean(response) && !loading;
      case 'target':
        return Boolean(selected);
      case 'options':
        return Boolean(selected) && validation.valid;
      case 'verify':
        // No Generate until Verify ran (or an explicit lossy-acknowledged skip); a lossy
        // conversion additionally needs the acknowledgement before proceeding.
        return verifyRan && (!needsAck || acknowledged);
      default:
        return false;
    }
  }, [step, response, loading, selected, validation.valid, verifyRan, needsAck, acknowledged]);

  const stepIndex = STEP_ORDER.indexOf(step);
  const goBack = useCallback(() => {
    setStep(STEP_ORDER[Math.max(0, stepIndex - 1)]);
  }, [stepIndex]);
  const goNext = useCallback(() => {
    setStep(STEP_ORDER[Math.min(STEP_ORDER.length - 1, stepIndex + 1)]);
  }, [stepIndex]);

  return (
    <main className={dashboardMainClass} data-testid="export-studio">
      <div className={dashboardContentStackClass}>
        <div>
          <Link
            href="/ade/dashboard/versions"
            className="mb-2 inline-flex items-center gap-1 text-sm text-indigo-600 hover:underline dark:text-indigo-400"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden />
            Back to Versions
          </Link>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-gray-900 dark:text-white">
            <PanelsTopLeft className="h-6 w-6 text-indigo-500" aria-hidden />
            Export Studio
          </h1>
          <p className="mt-1 max-w-3xl text-sm text-gray-600 dark:text-gray-400">
            Verify a conversion before you generate it. Exporting{' '}
            <strong className="text-gray-900 dark:text-gray-100">{sourceLabel}</strong>
            {versionLabel !== 'latest' ? ` (version ${versionLabel})` : ''}.
          </p>
        </div>

        {/* The numbered stepper (MFX-41.1) — the ImportDialog/ExportDialog pill pattern, full width. */}
        <ol
          data-testid="export-studio-stepper"
          className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-5"
        >
          {STUDIO_STEPS.map((s, idx) => {
            const state = idx === stepIndex ? 'current' : idx < stepIndex ? 'done' : 'upcoming';
            return (
              <li
                key={s.key}
                data-testid={`export-studio-step-${s.key}`}
                data-state={state}
                aria-current={state === 'current' ? 'step' : undefined}
                className={`rounded-full border px-3 py-1.5 text-center ${
                  state === 'upcoming'
                    ? 'border-gray-200 text-gray-500 dark:border-gray-700 dark:text-gray-400'
                    : 'border-indigo-200 bg-indigo-50 font-medium text-indigo-700 dark:border-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-200'
                }`}
              >
                {idx + 1}. {s.label}
              </li>
            );
          })}
        </ol>

        {(error || targetsError) && (
          <Alert variant="error" data-testid="export-studio-error">
            {error || targetsError}
          </Alert>
        )}

        <div className={dashboardPanelPaddedClass} data-testid="export-studio-body">
          {step === 'source' && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-900 dark:text-gray-100">
                <Package className="h-4 w-4 text-indigo-500" aria-hidden />
                Source
              </div>
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
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Export is scoped to this version: the fidelity badge on every target card is
                computed for this source, not a generic estimate.
              </p>
            </div>
          )}

          {step === 'target' && (
            <div className="space-y-4">
              <ExportTargetGrid
                cards={cards}
                selectedKey={selectedKey}
                onSelect={selectCard}
                heading={
                  <div className="text-center">
                    <div className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                      Choose a target format
                    </div>
                    <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                      Fidelity badges are computed for <strong>this</strong> source (version{' '}
                      {versionLabel}).
                    </p>
                  </div>
                }
              />
            </div>
          )}

          {step === 'options' && (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gray-900 dark:text-gray-100">
                <SlidersHorizontal className="h-4 w-4 text-indigo-500" aria-hidden />
                {selected ? `${selected.entry.descriptor.label} options` : 'Target options'}
              </div>
              <div className="my-1 h-px bg-gray-200 dark:bg-gray-700" />
              {optionFields.length === 0 ? (
                <p className="text-sm text-gray-500 dark:text-gray-400" data-testid="export-studio-no-options">
                  This target has no options — it exports with its defaults. Continue to verify the
                  conversion.
                </p>
              ) : (
                <ExportOptionsForm
                  targetKey={selected?.key ?? 'target'}
                  fields={optionFields}
                  values={optionValues}
                  errors={validation.errors}
                  onChange={setOption}
                />
              )}
            </div>
          )}

          {step === 'verify' && selected && fidelity && (
            <div className="space-y-4">
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
              {!verifyRan && (
                <div className="flex items-center justify-between gap-3 rounded-lg border border-gray-200 p-3 text-sm dark:border-gray-700">
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    Don’t want to wait for the full report? Skip verification and generate anyway.
                  </span>
                  <Button
                    variant="outline"
                    data-testid="export-studio-skip-verify"
                    onClick={() => setVerifyRan(true)}
                    disabled={needsAck && !acknowledged}
                    title={
                      needsAck && !acknowledged
                        ? 'Acknowledge the fidelity loss to skip verification.'
                        : undefined
                    }
                  >
                    Skip verification
                  </Button>
                </div>
              )}
            </div>
          )}

          {step === 'review' && selected && (
            <div className="space-y-4">
              {emitted ? (
                <div className="flex min-h-0 flex-col gap-2">
                  <p className="shrink-0 text-xs text-gray-600 dark:text-gray-300">
                    <CheckCircle2 className="mr-1.5 inline h-4 w-4 align-text-bottom text-green-500" aria-hidden />
                    Generated <strong>{emitted.filename}</strong>. Review it below, then download the
                    file or a .zip bundle.
                  </p>
                  <ArtifactPreviewCard
                    className="min-h-[420px]"
                    artifact={emitted}
                    report={preview?.fidelity.report ?? null}
                    targetKey={selected.key}
                  />
                </div>
              ) : generating ? (
                <div className="flex flex-col items-center justify-center gap-3 py-10 text-center">
                  <Loader2 className="h-8 w-8 animate-spin text-indigo-500" aria-hidden />
                  <div className="text-sm text-gray-700 dark:text-gray-200">
                    Generating {selected.entry.descriptor.label}…
                  </div>
                </div>
              ) : (
                <ExportReviewSummary
                  sourceLabel={sourceLabel}
                  versionLabel={versionLabel}
                  targetLabel={selected.entry.descriptor.label}
                  tierBadge={
                    fidelity ? (
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs font-semibold ${tierBadgeClass(fidelity.tier)}`}
                      >
                        {tierLabel(fidelity.tier)} · {fidelity.preserved_percent}% preserved
                      </span>
                    ) : null
                  }
                  changedOptionKeys={Object.keys(
                    changedOptions(optionValues, selected.entry.default_options) ?? {},
                  )}
                />
              )}
            </div>
          )}
        </div>

        {/* Step navigation (MFX-41.1): Back / Continue, with Generate + downloads on the last step. */}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Button variant="outline" onClick={goBack} disabled={stepIndex === 0 || generating}>
            <ArrowLeft className="h-4 w-4" aria-hidden />
            Back
          </Button>
          <div className="flex flex-wrap gap-2">
            {step === 'source' && (
              <Button onClick={goNext} disabled={!canAdvance}>
                <FileOutput className="h-4 w-4" aria-hidden />
                Choose target
              </Button>
            )}
            {(step === 'target' || step === 'options') && (
              <Button onClick={goNext} disabled={!canAdvance}>
                Continue
              </Button>
            )}
            {step === 'verify' && (
              <Button
                onClick={goNext}
                disabled={!canAdvance}
                title={
                  !canAdvance
                    ? 'Verify the conversion (or skip it) — acknowledge any fidelity loss — to continue.'
                    : undefined
                }
              >
                Continue to review
              </Button>
            )}
            {step === 'review' && !emitted && (
              <Button
                data-testid="export-studio-generate"
                onClick={() => void handleGenerate()}
                disabled={generating}
              >
                <Sparkles className="h-4 w-4" aria-hidden />
                Generate
              </Button>
            )}
            {step === 'review' && emitted && (
              <>
                <Button variant="outline" onClick={handleDownloadZip}>
                  <FileArchive className="h-4 w-4" aria-hidden />
                  Download .zip
                </Button>
                <Button variant="outline" onClick={handleDownloadFile}>
                  <Download className="h-4 w-4" aria-hidden />
                  Download {emitted.filename}
                </Button>
              </>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}

interface ExportReviewSummaryProps {
  sourceLabel: string;
  versionLabel: string;
  targetLabel: string;
  tierBadge: React.ReactNode;
  changedOptionKeys: string[];
}

/** The pre-generate summary on the Review step: what will be generated, before the user commits. */
function ExportReviewSummary({
  sourceLabel,
  versionLabel,
  targetLabel,
  tierBadge,
  changedOptionKeys,
}: ExportReviewSummaryProps) {
  return (
    <dl className="grid gap-3 text-sm sm:grid-cols-2" data-testid="export-studio-review-summary">
      <div>
        <dt className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          Source
        </dt>
        <dd className="mt-1 text-gray-900 dark:text-gray-100">
          {sourceLabel} {versionLabel !== 'latest' ? `· v${versionLabel}` : ''}
        </dd>
      </div>
      <div>
        <dt className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          Target
        </dt>
        <dd className="mt-1 flex items-center gap-2 text-gray-900 dark:text-gray-100">
          {targetLabel}
          {tierBadge}
        </dd>
      </div>
      <div className="sm:col-span-2">
        <dt className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
          Options
        </dt>
        <dd className="mt-1 text-gray-700 dark:text-gray-300">
          {changedOptionKeys.length === 0
            ? 'Defaults for every option.'
            : `Overridden: ${changedOptionKeys.join(', ')}.`}
        </dd>
      </div>
    </dl>
  );
}

export default ExportStudio;
