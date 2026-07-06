'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import dynamic from 'next/dynamic';
import { Check, Copy, FileCode2 } from 'lucide-react';
import { monacoLanguageForExportTarget } from '@/app/utils/export-target-language';
import { cn } from '@lib/utils';
import type { LossinessReport } from './exportFidelityPreview';
import {
  artifactBadgeClass,
  buildArtifactBadge,
  formatByteSize,
  utf8ByteLength,
  validateEmittedArtifact,
  type EmittedArtifact,
} from './exportArtifactPreview';

/** Offline fallback when Monaco cannot load — keeps the emitted text visible. */
function OfflineArtifactFallback({ value }: { value?: string }) {
  return (
    <pre
      data-testid="export-artifact-content"
      className="h-full overflow-auto whitespace-pre-wrap break-words p-3 font-mono text-xs leading-5 text-gray-800 dark:text-gray-200"
    >
      {value ?? ''}
    </pre>
  );
}

const MonacoEditor = dynamic(
  () =>
    import('@monaco-editor/react')
      .then((mod) => mod.default)
      .catch(() => OfflineArtifactFallback),
  {
    ssr: false,
    loading: () => (
      <div className="flex h-full items-center justify-center text-sm text-gray-500 dark:text-gray-400">
        Loading preview…
      </div>
    ),
  },
);

interface ArtifactPreviewCardProps {
  /** The emitted document as captured from `POST /api/export/document`. */
  artifact: EmittedArtifact;
  /**
   * The per-construct loss report from the dry-run preview (MFX-2.5), used for the
   * badge's round-trip claim; null when the preview fetch failed or has not loaded.
   */
  report: LossinessReport | null;
  /** The chosen export target's registry key — drives Monaco syntax highlighting. */
  targetKey?: string | null;
  className?: string;
}

/**
 * ArtifactPreviewCard — the emitted-artifact preview (MFX-6.3, #3857).
 *
 * Shows the document the export produced *before* the user downloads it: a compact header
 * (filename + fidelity badge), the full emitted buffer in a read-only Monaco editor with
 * syntax highlighting, a copy-to-clipboard control, and size/meta hints underneath.
 */
export function ArtifactPreviewCard({
  artifact,
  report,
  targetKey,
  className,
}: ArtifactPreviewCardProps) {
  const [isDark, setIsDark] = useState(false);
  const [copied, setCopied] = useState(false);

  const badge = useMemo(
    () => buildArtifactBadge(validateEmittedArtifact(artifact), report),
    [artifact, report],
  );
  const size = useMemo(() => formatByteSize(utf8ByteLength(artifact.text)), [artifact.text]);
  const language = useMemo(
    () => monacoLanguageForExportTarget(targetKey ?? null, artifact.text),
    [artifact.text, targetKey],
  );

  useEffect(() => {
    const sync = () => setIsDark(document.documentElement.classList.contains('dark'));
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  const copyToClipboard = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(artifact.text);
      setCopied(true);
    } catch {
      // Clipboard unavailable — leave the button unchanged.
    }
  }, [artifact.text]);

  const copyButton = (
    <button
      type="button"
      data-testid="export-artifact-copy"
      onClick={() => void copyToClipboard()}
      title={copied ? 'Copied' : 'Copy to clipboard'}
      aria-label={copied ? 'Copied' : 'Copy to clipboard'}
      className={cn(
        'inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium shadow-sm transition-colors',
        copied
          ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300'
          : 'border-gray-200 bg-white/95 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-900/95 dark:text-gray-200 dark:hover:bg-gray-800',
      )}
    >
      {copied ? (
        <Check className="h-3.5 w-3.5" aria-hidden />
      ) : (
        <Copy className="h-3.5 w-3.5" aria-hidden />
      )}
      {copied ? 'Copied' : 'Copy'}
    </button>
  );

  return (
    <div
      data-testid="export-artifact-preview"
      className={cn('flex min-h-0 flex-col rounded-xl border border-gray-200 p-3 dark:border-gray-700', className)}
    >
      <div className="flex shrink-0 flex-wrap items-center gap-2">
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

      <div
        data-testid="export-artifact-editor"
        data-language={language}
        className="relative mt-2 min-h-0 flex-1 overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-[#1e1e1e]"
      >
        <div className="absolute right-2 top-2 z-10">{copyButton}</div>
        <MonacoEditor
          height="100%"
          language={language}
          theme={isDark ? 'vs-dark' : 'light'}
          value={artifact.text}
          options={{
            readOnly: true,
            domReadOnly: true,
            minimap: { enabled: false },
            fontSize: 13,
            fontFamily: "'JetBrains Mono', 'Fira Code', Consolas, monospace",
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            wordWrap: 'off',
            padding: { top: 14, bottom: 14 },
            automaticLayout: true,
            renderLineHighlight: 'none',
            overviewRulerLanes: 0,
            hideCursorInOverviewRuler: true,
            contextmenu: false,
            links: false,
            scrollbar: { verticalScrollbarSize: 8, horizontalScrollbarSize: 8 },
          }}
        />
      </div>

      <p className="mt-2 shrink-0 text-xs text-gray-500 dark:text-gray-400">{badge.hint}</p>
      <p className="mt-0.5 shrink-0 text-[11px] text-gray-400 dark:text-gray-500">
        {size}
        {artifact.mediaType ? ` · ${artifact.mediaType}` : ''}
        {` · ${language}`}
      </p>
    </div>
  );
}

export default ArtifactPreviewCard;
