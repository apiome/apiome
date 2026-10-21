'use client';

/**
 * The class heatmap for one revision (#560).
 *
 * Opened from a revision's row menu (**Heatmap**). Every class of the revision is a tile, and
 * a switch above the grid picks what its warmth means — complexity, recent change, how many
 * classes reference it, or how complete its documentation is. The measurements and the 0–4
 * levels are `class-heatmap.ts`; this only draws them. The warmth itself is the
 * `.vdlg-heatmap__tile[data-heat]` ramp in globals.css, mixed from the warn/danger tokens so
 * it follows the theme.
 */

import React, { useMemo, useState } from 'react';
import { Flame } from 'lucide-react';
import { Dialog, DialogContent } from '../../../components/ui/Dialog';
import { Segmented, SegmentedItem } from '../../../components/ui/Segmented';
import { VersionDialogHead } from '../../../components/ade/versions';
import {
  HEATMAP_METRICS,
  HEATMAP_METRIC_COPY,
  buildClassHeatmap,
  heatLevels,
  heatmapCellSummary,
  heatmapValueLabel,
  sortCellsByHeat,
  type HeatLevel,
  type HeatmapClass,
  type HeatmapMetric,
} from '@/app/utils/class-heatmap';

/** The levels the legend draws, coldest first. */
const LEGEND_LEVELS: readonly HeatLevel[] = [0, 1, 2, 3, 4];

export interface ClassHeatmapDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** Called when the dialog asks to open or close. */
  onOpenChange: (open: boolean) => void;
  /** The revision being mapped, or `null` before one is chosen. */
  version: { id: string; version_id: string } | null;
  /** The owning project's name, for the description line. */
  projectName: string;
  /** The revision's classes with their properties; `null` when nothing has loaded. */
  classes: HeatmapClass[] | null;
  /** True while the classes load. */
  isLoading?: boolean;
  /** The time "recently" is measured from — injectable for tests. Defaults to now. */
  now?: Date;
}

/**
 * Render the heatmap dialog. See {@link ClassHeatmapDialogProps}.
 *
 * @returns The dialog.
 */
export default function ClassHeatmapDialog({
  open,
  onOpenChange,
  version,
  projectName,
  classes,
  isLoading = false,
  now,
}: ClassHeatmapDialogProps) {
  const [metric, setMetric] = useState<HeatmapMetric>('complexity');
  const cells = useMemo(() => buildClassHeatmap(classes ?? [], now ?? new Date()), [classes, now]);
  const levels = useMemo(() => heatLevels(cells, metric), [cells, metric]);
  const sorted = useMemo(() => sortCellsByHeat(cells, levels, metric), [cells, levels, metric]);
  const copy = HEATMAP_METRIC_COPY[metric];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="vdlg-dialog vdlg-dialog--lg vdlg-heatmap"
        aria-describedby={undefined}
        data-testid="class-heatmap-dialog"
      >
        <VersionDialogHead
          icon={<Flame aria-hidden />}
          tone="warn"
          title="Heatmap"
          description={
            version ? `${projectName} — v${version.version_id} · classes colored by one metric` : undefined
          }
        />
        <div className="vdlg-heatmap__bar">
          <Segmented
            value={metric}
            onValueChange={(value) => setMetric(value as HeatmapMetric)}
            aria-label="Color classes by"
            size="sm"
            data-testid="heatmap-metric"
          >
            {HEATMAP_METRICS.map((m) => (
              <SegmentedItem key={m} value={m} data-testid={`heatmap-metric-${m}`}>
                {HEATMAP_METRIC_COPY[m].label}
              </SegmentedItem>
            ))}
          </Segmented>
          <div className="vdlg-heatmap__legend" data-testid="heatmap-legend">
            <span>{copy.cold}</span>
            <span className="vdlg-heatmap__ramp" aria-hidden>
              {LEGEND_LEVELS.map((level) => (
                <span key={level} className="vdlg-heatmap__swatch" data-heat={level} />
              ))}
            </span>
            <span>{copy.warm}</span>
          </div>
        </div>
        <div className="vdlg-heatmap__frame">
          {isLoading ? (
            <p className="vdlg-relgraph__state">Loading schema…</p>
          ) : cells.length === 0 ? (
            <div className="vdlg-relgraph__state" data-testid="heatmap-empty">
              <p className="vdlg-relgraph__state-title">
                {classes === null ? 'No schema data loaded.' : 'This version has no classes yet.'}
              </p>
              <p className="vdlg-quiet">Add classes in the Studio to see them on the heatmap.</p>
            </div>
          ) : (
            <ul className="vdlg-heatmap__grid" aria-label={`Classes by ${copy.label.toLowerCase()}`} data-testid="heatmap-grid">
              {sorted.map((cell) => {
                const level = levels.get(cell.id) ?? 0;
                return (
                  <li
                    key={cell.id}
                    className="vdlg-heatmap__tile"
                    data-heat={level}
                    title={heatmapCellSummary(cell)}
                    data-testid={`heatmap-tile-${cell.id}`}
                  >
                    <span className="vdlg-heatmap__name">{cell.name}</span>
                    <span className="vdlg-heatmap__value">{heatmapValueLabel(cell, metric)}</span>
                    <span className="sr-only">{`, heat ${level} of 4. ${heatmapCellSummary(cell)}`}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
