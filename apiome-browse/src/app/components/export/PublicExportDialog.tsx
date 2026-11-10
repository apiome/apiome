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
import { publicExportErrorFromResponse } from '../../../../lib/export/publicExportErrors';
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
          throw new Error(await publicExportErrorFromResponse(response));
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
          throw new Error(await publicExportErrorFromResponse(response));
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
        throw new Error(await publicExportErrorFromResponse(response));
      }
      const blob = await response.blob();
      const filename = filenameFromContentDisposition(
        response.headers.get('Content-Disposition'),
        exportFallbackFilename(coords, selected.descriptor.key, serialization, response.headers.get('Content-Type'))
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
        className="absolute inset-0 bg-overlay backdrop-blur-xs"
        onClick={onClose}
        aria-hidden="true"
      />

      <div className="relative flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-xl">
        <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div>
            <h2 className="text-xl font-semibold text-fg">
              Export this version
            </h2>
            <p className="mt-0.5 text-sm text-fg-muted">
              Convert{' '}
              <span className="font-medium text-fg-muted">
                {projectSlug} v{versionSlug}
              </span>{' '}
              to another API description format.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-fg-muted transition-colors hover:bg-subtle hover:text-fg-muted"
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
              <svg className="h-5 w-5 animate-spin text-accent-fg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span className="text-base text-fg-muted">Loading export targets...</span>
            </div>
          )}
          {loadError && (
            <div className="rounded-lg border border-danger/30 bg-danger-soft px-3.5 py-2.5 text-sm text-danger-fg">
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
                        ? 'border-accent bg-accent-soft ring-1 ring-accent'
                        : 'border-border bg-surface hover:border-border-strong hover:bg-subtle'
                    } ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-base font-semibold text-fg">
                        {descriptor.label}
                      </span>
                      <span
                        className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-2xs font-medium ring-1 ring-inset ${tierBadgeClass(fidelity.tier)}`}
                      >
                        {tierLabel(fidelity.tier)}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-sm leading-snug text-fg-muted">
                      {descriptor.description}
                    </p>
                    <p className="mt-1.5 text-2xs text-fg-subtle">
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
            <div className="rounded-lg border border-danger/30 bg-danger-soft px-3.5 py-2.5 text-sm text-danger-fg">
              {exportError}
            </div>
          )}
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-3.5">
          <div className="inline-flex rounded-lg border border-border bg-subtle p-0.5">
            {(['json', 'yaml'] as const).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => setSerialization(value)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  serialization === value
                    ? 'bg-surface text-fg shadow-xs'
                    : 'text-fg-muted hover:text-fg-muted'
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
              className="rounded-md border border-border bg-surface px-3 py-1.5 text-xs font-medium text-fg-muted shadow-xs transition-colors hover:bg-subtle"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={runExport}
              disabled={!canExport}
              className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-fg-on-accent transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
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
