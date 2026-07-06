'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Check, Copy, FolderTree } from 'lucide-react';
import { monacoLanguageForArtifact } from '@/app/utils/export-target-language';
import { cn } from '@lib/utils';
import { ReadOnlyCodeViewer } from './ReadOnlyCodeViewer';
import { BundleTree } from './BundleTree';
import { BundleFileTabs } from './BundleFileTabs';
import { formatByteSize } from './exportArtifactPreview';
import {
  buildBundleTree,
  isMultiFileBundle,
  type BundleManifest,
  type FileFindingCounts,
} from './exportBundle';

/** How many recently-opened files the tab strip keeps before dropping the oldest. */
const MAX_OPEN_TABS = 8;

export interface BundleExplorerProps {
  /** The emitted bundle to explore. */
  manifest: BundleManifest;
  /** Per-file finding counts (from {@link countFindingsByFile}); drives tree/tab badges. */
  countsByPath: Map<string, FileFindingCounts>;
  /** The chosen export target's registry key — drives Monaco syntax highlighting. */
  targetKey?: string | null;
  className?: string;
}

/**
 * BundleExplorer — the multi-file review surface (MFX-43.2, #4362).
 *
 * Composes the three parts of reviewing a bundle: the {@link BundleTree} left rail to navigate the
 * files, the {@link BundleFileTabs} strip of recently-opened files, and the shared read-only Monaco
 * viewer (MFX-43.1) showing the active file with per-file syntax highlighting. Opening a file from
 * the tree activates it and pushes it onto the recent-files strip.
 *
 * A single-file bundle skips the tree and tabs entirely (MFX-43.2 acceptance) — it is just the
 * viewer over the one file, so the navigation chrome never appears for a lone document.
 */
export function BundleExplorer({ manifest, countsByPath, targetKey, className }: BundleExplorerProps) {
  const multi = isMultiFileBundle(manifest);
  const tree = useMemo(() => buildBundleTree(manifest.files), [manifest.files]);
  const filesByPath = useMemo(
    () => new Map(manifest.files.map((file) => [file.path, file])),
    [manifest.files],
  );

  const [activePath, setActivePath] = useState<string | null>(manifest.primaryPath);
  // The recent-files strip; the primary opens first. Single-file bundles never show it.
  const [openPaths, setOpenPaths] = useState<string[]>(multi ? [manifest.primaryPath] : []);
  const [copied, setCopied] = useState(false);

  // A fresh manifest (a new generate) resets navigation to its primary file.
  const [manifestKey, setManifestKey] = useState(manifest.primaryPath);
  if (manifest.primaryPath !== manifestKey) {
    setManifestKey(manifest.primaryPath);
    setActivePath(manifest.primaryPath);
    setOpenPaths(multi ? [manifest.primaryPath] : []);
  }

  const selectFile = useCallback(
    (path: string) => {
      setActivePath(path);
      setOpenPaths((current) => {
        const withoutPath = current.filter((p) => p !== path);
        return [path, ...withoutPath].slice(0, MAX_OPEN_TABS);
      });
    },
    [],
  );

  const closeTab = useCallback(
    (path: string) => {
      setOpenPaths((current) => {
        const index = current.indexOf(path);
        const next = current.filter((p) => p !== path);
        // Closing the active tab moves focus to a neighbour (the one before it, else the new first).
        if (path === activePath) {
          const fallback = next[Math.max(0, index - 1)] ?? next[0] ?? null;
          setActivePath(fallback);
        }
        return next;
      });
    },
    [activePath],
  );

  const activeFile = activePath ? filesByPath.get(activePath) ?? null : null;

  const language = useMemo(
    () =>
      activeFile
        ? monacoLanguageForArtifact({
            targetFormat: targetKey ?? null,
            mediaType: activeFile.mediaType,
            filename: activeFile.path,
            sample: activeFile.text,
          })
        : 'plaintext',
    [activeFile, targetKey],
  );

  useEffect(() => {
    if (!copied) return undefined;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  const copyActive = useCallback(async () => {
    if (!activeFile) return;
    try {
      await navigator.clipboard.writeText(activeFile.text);
      setCopied(true);
    } catch {
      // Clipboard unavailable — leave the button unchanged.
    }
  }, [activeFile]);

  const copyButton = (
    <button
      type="button"
      data-testid="bundle-copy"
      onClick={() => void copyActive()}
      title={copied ? 'Copied' : 'Copy file'}
      aria-label={copied ? 'Copied' : 'Copy file'}
      className={cn(
        'inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium shadow-sm transition-colors',
        copied
          ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300'
          : 'border-gray-200 bg-white/95 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-900/95 dark:text-gray-200 dark:hover:bg-gray-800',
      )}
    >
      {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  );

  const viewer = activeFile ? (
    <ReadOnlyCodeViewer
      value={activeFile.text}
      language={language}
      overlay={copyButton}
      className="min-h-0 flex-1 rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-[#1e1e1e]"
      editorTestId="bundle-file-editor"
      fallbackTestId="bundle-file-content"
    />
  ) : (
    <div
      data-testid="bundle-empty"
      className="flex min-h-0 flex-1 items-center justify-center rounded-lg border border-dashed border-gray-200 text-sm text-gray-500 dark:border-gray-700 dark:text-gray-400"
    >
      Select a file from the tree to view it.
    </div>
  );

  // Single-file bundle: no tree, no tabs — just the one file in the viewer.
  if (!multi) {
    return (
      <div
        data-testid="bundle-explorer"
        data-multi="false"
        className={cn('flex min-h-0 flex-col rounded-xl border border-gray-200 p-3 dark:border-gray-700', className)}
      >
        <BundleHeader fileCount={manifest.files.length} activeFile={activeFile} language={language} />
        <div className="mt-2 flex min-h-0 flex-1 flex-col">{viewer}</div>
      </div>
    );
  }

  return (
    <div
      data-testid="bundle-explorer"
      data-multi="true"
      className={cn('flex min-h-0 flex-col rounded-xl border border-gray-200 p-3 dark:border-gray-700', className)}
    >
      <BundleHeader fileCount={manifest.files.length} activeFile={activeFile} language={language} />
      <div className="mt-2 grid min-h-0 flex-1 grid-cols-1 gap-3 sm:grid-cols-[minmax(11rem,15rem)_1fr]">
        <BundleTree
          nodes={tree}
          countsByPath={countsByPath}
          activePath={activePath}
          onSelect={selectFile}
          className="max-h-[420px]"
        />
        <div className="flex min-h-0 flex-col">
          <BundleFileTabs
            openPaths={openPaths}
            activePath={activePath}
            countsByPath={countsByPath}
            onActivate={setActivePath}
            onClose={closeTab}
          />
          <div className="mt-2 flex min-h-0 flex-1 flex-col">{viewer}</div>
        </div>
      </div>
    </div>
  );
}

interface BundleHeaderProps {
  fileCount: number;
  activeFile: { path: string; sizeBytes: number; mediaType: string } | null;
  language: string;
}

/** The bundle header: file count and the active file's path/size/language meta. */
function BundleHeader({ fileCount, activeFile, language }: BundleHeaderProps) {
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-2">
      <FolderTree className="h-4 w-4 text-indigo-500" aria-hidden />
      <span className="text-xs font-semibold uppercase tracking-wide text-gray-900 dark:text-gray-100">
        Bundle · {fileCount} file{fileCount === 1 ? '' : 's'}
      </span>
      {activeFile && (
        <span
          data-testid="bundle-active-meta"
          className="ml-auto truncate text-[11px] text-gray-400 dark:text-gray-500"
        >
          {activeFile.path} · {formatByteSize(activeFile.sizeBytes)}
          {activeFile.mediaType ? ` · ${activeFile.mediaType}` : ''} · {language}
        </span>
      )}
    </div>
  );
}

export default BundleExplorer;
