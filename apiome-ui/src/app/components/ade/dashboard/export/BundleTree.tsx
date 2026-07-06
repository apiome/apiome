'use client';

import { useState } from 'react';
import { ChevronRight, FileCode2, Folder, FolderOpen } from 'lucide-react';
import { cn } from '@lib/utils';
import { formatByteSize } from './exportArtifactPreview';
import {
  aggregateFolderCounts,
  type BundleTreeNode,
  type FileFindingCounts,
} from './exportBundle';
import { BundleFindingBadge } from './BundleFindingBadge';

/**
 * BundleTree — the left-rail file explorer for a multi-file export bundle (MFX-43.2, #4362).
 *
 * Renders the manifest's folder/file tree (built by {@link buildBundleTree}) as an IDE-style
 * explorer: folders collapse/expand, files select into the viewer, and every node badges its own
 * finding count (a folder rolls up the counts of everything inside it). It is the navigation
 * backbone the MFX-43.3 problem markers hang off — clicking a finding will reveal its file here.
 *
 * Large bundles stay responsive without a windowing dependency: the scroll region uses CSS
 * `content-visibility` so off-screen rows skip layout/paint until scrolled into view (MFX-43.5
 * deepens the large-output guards).
 */

export interface BundleTreeProps {
  /** The bundle's root-level tree nodes (from {@link buildBundleTree}). */
  nodes: BundleTreeNode[];
  /** Per-file finding counts (from {@link countFindingsByFile}); folders roll these up. */
  countsByPath: Map<string, FileFindingCounts>;
  /** The currently open file's path, highlighted in the tree. */
  activePath: string | null;
  /** Called with a file's path when the user selects it. */
  onSelect: (path: string) => void;
  /** Extra classes for the scroll container. */
  className?: string;
}

/**
 * The bundle file tree. Folders are open by default (small bundles read best fully expanded); the
 * user can collapse any subtree.
 *
 * @param props The tree nodes, finding counts, active file, and selection callback.
 * @returns The scrollable file explorer.
 */
export function BundleTree({ nodes, countsByPath, activePath, onSelect, className }: BundleTreeProps) {
  return (
    <div
      role="tree"
      aria-label="Bundle files"
      data-testid="bundle-tree"
      className={cn(
        'overflow-auto rounded-lg border border-gray-200 bg-gray-50/60 p-1 dark:border-gray-700 dark:bg-gray-900/40',
        className,
      )}
    >
      {nodes.map((node) => (
        <BundleTreeRow
          key={node.path}
          node={node}
          depth={0}
          countsByPath={countsByPath}
          activePath={activePath}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}

interface BundleTreeRowProps {
  node: BundleTreeNode;
  depth: number;
  countsByPath: Map<string, FileFindingCounts>;
  activePath: string | null;
  onSelect: (path: string) => void;
}

/** One tree row — a folder (with its collapsible children) or a selectable file. */
function BundleTreeRow({ node, depth, countsByPath, activePath, onSelect }: BundleTreeRowProps) {
  const [open, setOpen] = useState(true);
  const counts = aggregateFolderCounts(node, countsByPath);
  // Data-driven indentation via a CSS var so the depth is class-computed, not a hard-coded value.
  const indentStyle = { '--tree-depth': depth } as React.CSSProperties;
  const indentClass = 'pl-[calc(0.375rem+var(--tree-depth)*0.875rem)]';
  // Off-screen rows skip paint/layout until scrolled in — cheap virtualization for large bundles.
  const virtualizeClass = '[content-visibility:auto] [contain-intrinsic-size:auto_1.75rem]';

  if (node.kind === 'folder') {
    return (
      <div
        role="treeitem"
        aria-expanded={open}
        aria-selected={false}
        data-testid={`bundle-tree-folder-${node.path}`}
      >
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          style={indentStyle}
          className={cn(
            'flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left text-xs text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-800',
            indentClass,
            virtualizeClass,
          )}
        >
          <ChevronRight
            className={cn('h-3.5 w-3.5 shrink-0 text-gray-400 transition-transform', open && 'rotate-90')}
            aria-hidden
          />
          {open ? (
            <FolderOpen className="h-3.5 w-3.5 shrink-0 text-indigo-500" aria-hidden />
          ) : (
            <Folder className="h-3.5 w-3.5 shrink-0 text-indigo-500" aria-hidden />
          )}
          <span className="truncate font-medium">{node.name}</span>
          <span className="ml-auto shrink-0">
            <BundleFindingBadge counts={counts} testId={`bundle-tree-badge-${node.path}`} />
          </span>
        </button>
        {open && (
          <div role="group">
            {node.children.map((child) => (
              <BundleTreeRow
                key={child.path}
                node={child}
                depth={depth + 1}
                countsByPath={countsByPath}
                activePath={activePath}
                onSelect={onSelect}
              />
            ))}
          </div>
        )}
      </div>
    );
  }

  const selected = node.path === activePath;
  return (
    <button
      type="button"
      role="treeitem"
      aria-selected={selected}
      data-testid={`bundle-tree-file-${node.path}`}
      data-selected={selected}
      onClick={() => onSelect(node.path)}
      style={indentStyle}
      className={cn(
        'flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left text-xs',
        indentClass,
        virtualizeClass,
        selected
          ? 'bg-indigo-100 font-medium text-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-200'
          : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800',
      )}
    >
      {/* Spacer aligning file names under the folder chevron column. */}
      <span className="h-3.5 w-3.5 shrink-0" aria-hidden />
      <FileCode2 className="h-3.5 w-3.5 shrink-0 text-gray-400" aria-hidden />
      <span className="truncate">{node.name}</span>
      <span className="ml-auto flex shrink-0 items-center gap-1.5">
        <BundleFindingBadge counts={counts} testId={`bundle-tree-badge-${node.path}`} />
        <span className="text-[0.65rem] tabular-nums text-gray-400 dark:text-gray-500">
          {formatByteSize(node.file.sizeBytes)}
        </span>
      </span>
    </button>
  );
}

export default BundleTree;
