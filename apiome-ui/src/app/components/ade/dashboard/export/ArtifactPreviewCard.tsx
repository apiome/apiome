'use client';

import { useMemo } from 'react';
import { FileCode2 } from 'lucide-react';
import type { LossinessReport } from './exportFidelityPreview';
import {
  artifactBadgeClass,
  buildArtifactBadge,
  formatByteSize,
  utf8ByteLength,
  validateEmittedArtifact,
  type EmittedArtifact,
} from './exportArtifactPreview';

interface ArtifactPreviewCardProps {
  /** The emitted document as captured from `POST /api/export/document`. */
  artifact: EmittedArtifact;
  /**
   * The per-construct loss report from the dry-run preview (MFX-2.5), used for the
   * badge's round-trip claim; null when the preview fetch failed or has not loaded.
   */
  report: LossinessReport | null;
}

/**
 * ArtifactPreviewCard — the emitted-artifact preview (MFX-6.3, #3857).
 *
 * Shows the document the export produced *before* the user downloads it, per the mockup:
 * a header with the filename and the "valid · round-trip OK" status badge, the document
 * text in a scrollable code block, a hint line stating exactly what the badge is based on
 * (the client-side parse + the fidelity engine's prediction), and a size/media-type meta
 * line. Pure presentation — validation and badge derivation live in
 * `./exportArtifactPreview.ts`.
 */
export function ArtifactPreviewCard({ artifact, report }: ArtifactPreviewCardProps) {
  const badge = useMemo(
    () => buildArtifactBadge(validateEmittedArtifact(artifact), report),
    [artifact, report],
  );
  const size = useMemo(() => formatByteSize(utf8ByteLength(artifact.text)), [artifact.text]);

  return (
    <div
      data-testid="export-artifact-preview"
      className="rounded-xl border border-gray-200 p-4 text-left dark:border-gray-700"
    >
      <div className="flex flex-wrap items-center gap-2">
        <FileCode2 className="h-4 w-4 text-indigo-500" aria-hidden />
        <span className="text-xs font-semibold uppercase tracking-wide text-gray-900 dark:text-gray-100">
          Emitted {artifact.filename}
        </span>
        <span
          data-testid="export-artifact-badge"
          className={`ml-auto rounded-full px-2 py-0.5 text-[10px] font-semibold ${artifactBadgeClass(badge.tone)}`}
        >
          {badge.label}
        </span>
      </div>
      <div className="my-3 h-px bg-gray-200 dark:bg-gray-700" />
      <pre
        data-testid="export-artifact-content"
        className="max-h-64 overflow-auto whitespace-pre rounded-lg bg-gray-50 p-3 font-mono text-xs leading-5 text-gray-800 dark:bg-gray-900 dark:text-gray-200"
      >
        {artifact.text}
      </pre>
      <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">{badge.hint}</p>
      <p className="mt-1 text-[11px] text-gray-400 dark:text-gray-500">
        {size}
        {artifact.mediaType ? ` · ${artifact.mediaType}` : ''}
      </p>
    </div>
  );
}

export default ArtifactPreviewCard;
