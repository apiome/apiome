'use client';

/**
 * Public export dialog — MFX-7.1 (#3860) + MFX-7.2 (#3861).
 *
 * Lets an anonymous visitor export the published version they are viewing to any registered
 * target format, via the no-auth `/v1/browse/.../export/*` REST surface. Mirrors the ADE's
 * ExportDialog flow in browse's own styling: a card grid of targets with fidelity badges, the
 * full fidelity advisory + per-construct report (MFX-7.2), an explicit "Export anyway"
 * acknowledgement for any non-lossless target, a JSON/YAML serialization toggle, and a browser
 * download of the emitted document.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  exportFallbackFilename,
  filenameFromContentDisposition,
  publicExportDocumentUrl,
  publicExportPreviewUrl,
  publicExportTargetsUrl,
  requiresExportAcknowledgement,
  serializationAcceptHeader,
  sortTargetsForDisplay,
  tierBadgeClass,
  tierLabel,
  type ExportSerialization,
  type PublicExportTarget,
  type PublicExportTargetsResponse,
} from '../../../../lib/export/publicExport';
import type { PublicExportPreviewResponse } from '../../../../lib/export/exportFidelityPreview';
import { PublicFidelityWarningPanel } from './PublicFidelityWarningPanel';

interface PublicExportDialogProps {
  open: boolean;
  onClose: () => void;
  tenantSlug: string;
  projectSlug: string;
  versionSlug: string;
  restApiBaseUrl: string;
}

export function PublicExportDialog({
  open,
  onClose,
  tenantSlug,
  projectSlug,
  versionSlug,
  restApiBaseUrl,
}: PublicExportDialogProps) {
  const [targets, setTargets] = useState<PublicExportTarget[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [serialization, setSerialization] = useState<ExportSerialization>('json');
  const [acknowledged, setAcknowledged] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [preview, setPreview] = useState<PublicExportPreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const coords = useMemo(
    () => ({ tenantSlug, projectSlug, versionSlug }),
    [tenantSlug, projectSlug, versionSlug]
  );

  // (Re)load the target catalog each time the dialog opens, resetting prior choices.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setTargets(null);
    setLoadError(null);
    setSelectedKey(null);
    setSerialization('json');
    setAcknowledged(false);
    setExportError(null);
    setPreview(null);
    setPreviewLoading(false);
    setPreviewError(null);

    (async () => {
      try {
        const response = await fetch(publicExportTargetsUrl(restApiBaseUrl, coords));
        if (!response.ok) {
          throw new Error(`Failed to load export targets (${response.status})`);
        }
        const data: PublicExportTargetsResponse = await response.json();
        if (!cancelled) setTargets(sortTargetsForDisplay(data.targets));
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : 'Failed to load export targets');
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, restApiBaseUrl, coords]);

  // Load the dry-run fidelity preview when a target is selected (MFX-7.2).
  useEffect(() => {
    if (!open || !selectedKey) return;

    let cancelled = false;
    setPreview(null);
    setPreviewLoading(true);
    setPreviewError(null);

    (async () => {
      try {
        const response = await fetch(publicExportPreviewUrl(restApiBaseUrl, coords), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ target: selectedKey }),
        });
        if (!response.ok) {
          throw new Error(`Could not load the fidelity report (${response.status})`);
        }
        const data: PublicExportPreviewResponse = await response.json();
        if (!cancelled) setPreview(data);
      } catch {
        if (!cancelled) {
          setPreviewError('Could not load the fidelity report.');
          setPreview(null);
        }
      } finally {
        if (!cancelled) setPreviewLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [open, selectedKey, restApiBaseUrl, coords]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  const selected = targets?.find((t) => t.descriptor.key === selectedKey) ?? null;
  const needsAck = selected ? requiresExportAcknowledgement(selected.fidelity.tier) : false;
  const canExport = !!selected && !exporting && (!needsAck || acknowledged);

  const selectTarget = useCallback((target: PublicExportTarget) => {
    if (!target.descriptor.available) return;
    setSelectedKey(target.descriptor.key);
    setAcknowledged(false);
    setExportError(null);
  }, []);

  const runExport = useCallback(async () => {
    if (!selected) return;
    setExporting(true);
    setExportError(null);
    try {
      const response = await fetch(publicExportDocumentUrl(restApiBaseUrl, coords), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: serializationAcceptHeader(serialization),
        },
        body: JSON.stringify({ target: selected.descriptor.key }),
      });
      if (!response.ok) {
        const detail = await response.text();
        throw new Error(
          `Export failed (${response.status})${detail ? `: ${detail.substring(0, 200)}` : ''}`
        );
      }
      const blob = await response.blob();
      const filename = filenameFromContentDisposition(
        response.headers.get('Content-Disposition'),
        exportFallbackFilename(coords, selected.descriptor.key, serialization)
      );
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      onClose();
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setExporting(false);
    }
  }, [selected, serialization, restApiBaseUrl, coords, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label="Export this version">
      <div
        className="absolute inset-0 bg-zinc-950/40 backdrop-blur-xs dark:bg-zinc-950/60"
        onClick={onClose}
        aria-hidden="true"
      />

      <div className="relative flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-xl dark:border-zinc-800 dark:bg-zinc-950">
        <header className="flex items-start justify-between gap-3 border-b border-zinc-100 px-5 py-4 dark:border-zinc-800/80">
          <div>
            <h2 className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
              Export this version
            </h2>
            <p className="mt-0.5 text-[13px] text-zinc-500 dark:text-zinc-400">
              Convert{' '}
              <span className="font-medium text-zinc-700 dark:text-zinc-300">
                {projectSlug} v{versionSlug}
              </span>{' '}
              to another API description format.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-zinc-500 transition-colors hover:bg-zinc-100 hover:text-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-200"
            aria-label="Close export dialog"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
          {!targets && !loadError && (
            <div className="flex items-center justify-center gap-3 py-10">
              <svg className="h-5 w-5 animate-spin text-[var(--brand)]" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span className="text-sm text-zinc-600 dark:text-zinc-400">Loading export targets...</span>
            </div>
          )}
          {loadError && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-[13px] text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
              {loadError}
            </div>
          )}

          {targets && (
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2" role="listbox" aria-label="Export targets">
              {targets.map((target) => {
                const { descriptor, fidelity } = target;
                const isSelected = descriptor.key === selectedKey;
                const disabled = !descriptor.available;
                return (
                  <button
                    key={descriptor.key}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    disabled={disabled}
                    onClick={() => selectTarget(target)}
                    className={`rounded-lg border p-3 text-left transition-colors ${
                      isSelected
                        ? 'border-[var(--brand)] bg-[var(--brand-soft)] ring-1 ring-[var(--brand)]'
                        : 'border-zinc-200 bg-white hover:border-zinc-300 hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950 dark:hover:border-zinc-700 dark:hover:bg-zinc-900'
                    } ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[13.5px] font-semibold text-zinc-900 dark:text-zinc-50">
                        {descriptor.label}
                      </span>
                      <span
                        className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${tierBadgeClass(fidelity.tier)}`}
                      >
                        {tierLabel(fidelity.tier)}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-[12.5px] leading-snug text-zinc-500 dark:text-zinc-400">
                      {descriptor.description}
                    </p>
                    <p className="mt-1.5 text-[11.5px] text-zinc-400 dark:text-zinc-500">
                      {disabled
                        ? descriptor.unavailable_reason || 'Unavailable in this environment'
                        : `${fidelity.preserved_percent}% preserved`}
                    </p>
                  </button>
                );
              })}
            </div>
          )}

          {selected && (
            <PublicFidelityWarningPanel
              targetLabel={selected.descriptor.label}
              targetDescription={selected.descriptor.description}
              fidelity={selected.fidelity}
              preview={preview}
              previewLoading={previewLoading}
              previewError={previewError}
              acknowledged={acknowledged}
              onAcknowledgedChange={setAcknowledged}
            />
          )}

          {exportError && (
            <div className="rounded-lg border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-[13px] text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300">
              {exportError}
            </div>
          )}
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 px-5 py-3.5 dark:border-zinc-800/80">
          <div className="inline-flex rounded-lg border border-zinc-200 bg-zinc-50 p-0.5 dark:border-zinc-800 dark:bg-zinc-900">
            {(['json', 'yaml'] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setSerialization(value)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  serialization === value
                    ? 'bg-white text-zinc-900 shadow-xs dark:bg-zinc-800 dark:text-zinc-50'
                    : 'text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200'
                }`}
                aria-pressed={serialization === value}
              >
                {value.toUpperCase()}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium text-zinc-700 shadow-xs transition-colors hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={runExport}
              disabled={!canExport}
              className="inline-flex items-center gap-1.5 rounded-md bg-[var(--brand)] px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-[var(--brand-hover)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {exporting ? (
                <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
              )}
              {exporting ? 'Exporting...' : 'Export'}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
