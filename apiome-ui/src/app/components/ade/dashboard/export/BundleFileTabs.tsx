'use client';

import { X } from 'lucide-react';
import { cn } from '@lib/utils';
import { bundleFileName, type FileFindingCounts } from './exportBundle';
import { BundleFindingBadge } from './BundleFindingBadge';

/**
 * BundleFileTabs — the strip of recently-opened bundle files above the viewer (MFX-43.2, #4362).
 *
 * Opening a file from the tree adds a tab here; the active tab is the file in the viewer. Tabs keep
 * recent files one click away without re-hunting the tree, and each carries its own finding badge.
 * A tab can be closed; closing the active one is handled by the parent (it re-activates a neighbour).
 */

export interface BundleFileTabsProps {
  /** The open file paths, most-recent first. */
  openPaths: string[];
  /** The active file's path. */
  activePath: string | null;
  /** Per-file finding counts (from {@link countFindingsByFile}). */
  countsByPath: Map<string, FileFindingCounts>;
  /** Activate a tab (bring its file into the viewer). */
  onActivate: (path: string) => void;
  /** Close a tab. */
  onClose: (path: string) => void;
}

/**
 * The recent-files tab strip. Renders nothing when no file is open (the viewer shows its own empty
 * state), so a single-file bundle never grows a lone redundant tab.
 *
 * @param props The open paths, active path, counts, and activate/close callbacks.
 * @returns The horizontally-scrollable tab strip, or null when empty.
 */
export function BundleFileTabs({
  openPaths,
  activePath,
  countsByPath,
  onActivate,
  onClose,
}: BundleFileTabsProps) {
  if (openPaths.length === 0) return null;

  return (
    <div
      role="tablist"
      aria-label="Open bundle files"
      data-testid="bundle-file-tabs"
      className="flex shrink-0 items-stretch gap-1 overflow-x-auto border-b border-gray-200 pb-px dark:border-gray-700"
    >
      {openPaths.map((path) => {
        const active = path === activePath;
        const counts = countsByPath.get(path) ?? { errors: 0, warnings: 0 };
        return (
          <div
            key={path}
            data-testid={`bundle-tab-${path}`}
            data-active={active}
            className={cn(
              'group flex shrink-0 items-center gap-1.5 rounded-t-md border border-b-0 px-2.5 py-1.5 text-xs',
              active
                ? 'border-gray-200 bg-white font-medium text-indigo-700 dark:border-gray-700 dark:bg-[#1e1e1e] dark:text-indigo-300'
                : 'border-transparent text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800',
            )}
          >
            <button
              type="button"
              role="tab"
              aria-selected={active}
              data-testid={`bundle-tab-activate-${path}`}
              onClick={() => onActivate(path)}
              className="flex items-center gap-1.5"
              title={path}
            >
              <span className="max-w-[12rem] truncate">{bundleFileName(path)}</span>
              <BundleFindingBadge counts={counts} testId={`bundle-tab-badge-${path}`} />
            </button>
            <button
              type="button"
              aria-label={`Close ${bundleFileName(path)}`}
              data-testid={`bundle-tab-close-${path}`}
              onClick={() => onClose(path)}
              className="rounded p-0.5 text-gray-400 opacity-60 hover:bg-gray-200 hover:text-gray-700 group-hover:opacity-100 dark:hover:bg-gray-700 dark:hover:text-gray-200"
            >
              <X className="h-3 w-3" aria-hidden />
            </button>
          </div>
        );
      })}
    </div>
  );
}

export default BundleFileTabs;
