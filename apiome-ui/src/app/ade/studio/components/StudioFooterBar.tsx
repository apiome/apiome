'use client';

import * as React from 'react';
import { usePathname } from 'next/navigation';
import {
  Circle,
  FolderGit2,
  GitBranch,
  Grid3x3,
  Lock,
  Tag,
  ZoomIn,
} from 'lucide-react';
import { useStudio } from '../StudioContext';
import { FEATURE_GITLIKE } from '@lib/feature-flags';

/**
 * VSCode-style status bar pinned to the bottom of the studio layout.
 *
 * Surfaces the programmatic state of the active canvas:
 *   project · version · branch · read-only · unsaved · zoom · grid · snap
 *
 * Canvas-only segments (zoom, grid, snap) are hidden on the /code route
 * since there is no React Flow surface to describe.
 *
 * Pan coordinates are intentionally excluded: surfacing them would require
 * publishing on every onMove frame, which causes context-wide re-renders
 * during pan/zoom of large populated canvases.
 */
export const STUDIO_FOOTER_BAR_HEIGHT_PX = 22;

const segmentClass =
  'inline-flex items-center gap-1 px-2 h-full whitespace-nowrap leading-none';

function Segment({
  icon,
  label,
  title,
  tone = 'default',
}: {
  icon?: React.ReactNode;
  label: React.ReactNode;
  title?: string;
  tone?: 'default' | 'warn' | 'danger' | 'muted';
}) {
  const toneClass =
    tone === 'warn'
      ? 'text-amber-300'
      : tone === 'danger'
        ? 'text-red-300'
        : tone === 'muted'
          ? 'text-gray-400'
          : 'text-gray-100';
  return (
    <div className={`${segmentClass} ${toneClass}`} title={title}>
      {icon ? <span className="opacity-80">{icon}</span> : null}
      <span>{label}</span>
    </div>
  );
}

export default function StudioFooterBar() {
  const pathname = usePathname();
  const {
    selectedProjectId,
    selectedProjectName,
    selectedVersionLabel,
    selectedBranchId,
    versionBranchesByProjectId,
    isReadOnly,
    syncLocalDirty,
    canvasViewport,
    showGrid,
    gridStyle,
    gridSize,
    snapToGrid,
  } = useStudio();

  const onCodeRoute = !!pathname?.includes('/code');

  const branchLabel = React.useMemo(() => {
    if (!selectedProjectId) return null;
    const branches = versionBranchesByProjectId[selectedProjectId] ?? [];
    if (!branches.length) return null;
    const match = selectedBranchId
      ? branches.find((b) => b.id === selectedBranchId)
      : null;
    return match?.name?.trim() || null;
  }, [selectedProjectId, selectedBranchId, versionBranchesByProjectId]);

  const zoomPct = Math.round((canvasViewport.zoom || 1) * 100);

  return (
    <div
      role="status"
      aria-label="Studio canvas status"
      className="flex items-stretch text-[11px] font-medium bg-[#1f2937] dark:bg-[#0f172a] text-gray-100 border-t border-black/40 select-none"
      style={{ height: STUDIO_FOOTER_BAR_HEIGHT_PX }}
    >
      <Segment
        icon={<FolderGit2 size={11} />}
        label={selectedProjectName || '— no project'}
        title="Selected project"
        tone={selectedProjectName ? 'default' : 'muted'}
      />
      <Segment
        icon={<Tag size={11} />}
        label={selectedVersionLabel || '— no version'}
        title="Selected version (revision label)"
        tone={selectedVersionLabel ? 'default' : 'muted'}
      />
      {FEATURE_GITLIKE && (
        <Segment
          icon={<GitBranch size={11} />}
          label={branchLabel || '— no branch'}
          title="Active branch tracking the selected revision"
          tone={branchLabel ? 'default' : 'muted'}
        />
      )}

      {isReadOnly ? (
        <Segment
          icon={<Lock size={11} />}
          label="Read-only"
          title="This revision is published and cannot be modified"
          tone="warn"
        />
      ) : null}

      {syncLocalDirty ? (
        <Segment
          icon={<Circle size={9} fill="currentColor" />}
          label="Unsaved"
          title="Local canvas/layout edits not yet persisted"
          tone="warn"
        />
      ) : null}

      <div className="flex-1" />

      {!onCodeRoute && (
        <>
          <Segment
            icon={<ZoomIn size={11} />}
            label={`${zoomPct}%`}
            title="Canvas zoom level (updated when pan/zoom interaction ends)"
          />
          <Segment
            icon={<Grid3x3 size={11} />}
            label={
              showGrid
                ? `Grid: ${gridStyle} ${gridSize}`
                : 'Grid: off'
            }
            title="Grid visibility, style and size"
            tone={showGrid ? 'default' : 'muted'}
          />
          <Segment
            label={snapToGrid ? 'Snap: on' : 'Snap: off'}
            title="Snap-to-grid"
            tone={snapToGrid ? 'default' : 'muted'}
          />
        </>
      )}
    </div>
  );
}
