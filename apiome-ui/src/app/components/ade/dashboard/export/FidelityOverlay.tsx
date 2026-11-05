"use client";

/**
 * FidelityOverlay — the fidelity heatmap overlay's controls and marks (MFX-45.2, #4375).
 *
 * The mapping graph (`ExportMappingGraphPanel`) draws these over its own nodes when it is
 * handed the export's lossiness report; the model lives in `./fidelityOverlay.ts`:
 *
 *  - {@link FidelityOverlayControls} — the loss-kind legend with the report's counts, each
 *    chip a toggle that filters the drawing by kind, a reconciliation line stating that the
 *    counts are the report's, and the Graph / Treemap view switch;
 *  - {@link FidelityKindMarker} — the SVG pill a graph node wears: the worst kind's glyph and
 *    the node's item count, in the chip palette (glyph + word + colour, never colour alone);
 *  - {@link FidelityOverlayDetail} — the LossItem detail of the hovered or focused node,
 *    rendered with the report's own row (`FidelityReportRow`);
 *  - {@link FidelityTreemap} — the compact view: one tile per construct, grouped by
 *    construct path, sized by item count, painted by worst kind.
 */

import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { cn } from "@lib/utils";
import { SVG_TEXT_SIZE } from "@/app/components/ui/svgTypography";
import {
  kindDescription,
  kindGlyph,
  kindLabel,
  kindTone,
  type LossItem,
  type LossinessKind,
} from "./exportFidelityPreview";
import { FidelityReportRow } from "./FidelityWarningPanel";
import type { ExportManifestEntity } from "./exportPreviewManifest";
import type { PlacedBox } from "./projectionGraph";
import {
  isFilterOff,
  layoutConstructTreemap,
  LOSS_KINDS,
  type KindCounts,
  type NodeOverlay,
  type OverlayReconciliation,
  type PlacedTile,
  type TreemapGroup,
} from "./fidelityOverlay";
import { fitProjectionLabel } from "./projectionGraphSvg";

/** The two overlay views. */
export type FidelityOverlayView = "graph" | "treemap";

// ---------------------------------------------------------------------------
// Controls
// ---------------------------------------------------------------------------

export interface FidelityOverlayControlsProps {
  /** The report's own count per kind — the legend prints these, never a recount. */
  counts: KindCounts;
  /** The active kinds. */
  active: ReadonlySet<LossinessKind>;
  /** Toggle one kind. */
  onToggleKind: (kind: LossinessKind) => void;
  /** Turn the filter off (every kind active). */
  onShowAll: () => void;
  /** Whether the overlay's counts reproduce the report's. */
  reconciliation: OverlayReconciliation;
  /** The current view. */
  view: FidelityOverlayView;
  onChangeView: (view: FidelityOverlayView) => void;
}

/** The kind legend + filter, the reconciliation line and the view switch. */
export function FidelityOverlayControls({
  counts,
  active,
  onToggleKind,
  onShowAll,
  reconciliation,
  view,
  onChangeView,
}: FidelityOverlayControlsProps) {
  const total = LOSS_KINDS.reduce((sum, kind) => sum + counts[kind], 0);
  return (
    <div className="xstd-fov" data-testid="fidelity-overlay-controls">
      <div className="xstd-fov__row">
        <span className="xstd-fov__title">Fidelity overlay</span>
        <div
          role="group"
          aria-label="Filter by loss kind"
          className="xstd-fov__chips"
        >
          {LOSS_KINDS.map((kind) => (
            <button
              key={kind}
              type="button"
              className="xstd-fov__filter"
              data-tone={kindTone(kind)}
              aria-pressed={active.has(kind)}
              data-testid={`fidelity-overlay-kind-${kind}`}
              title={`Show ${kindDescription(kind)} constructs`}
              onClick={() => onToggleKind(kind)}
            >
              <span aria-hidden>{kindGlyph(kind)}</span>
              {kindLabel(kind)}
              <span
                className="tabular-nums"
                data-testid={`fidelity-overlay-count-${kind}`}
              >
                {counts[kind]}
              </span>
            </button>
          ))}
          {!isFilterOff(active) && (
            <button
              type="button"
              className="xstd-chip"
              data-testid="fidelity-overlay-show-all"
              onClick={onShowAll}
            >
              Show all kinds
            </button>
          )}
        </div>
        <div
          role="group"
          aria-label="Overlay view"
          className="xstd-fov__chips xstd-fov__views"
        >
          {(["graph", "treemap"] as const).map((option) => (
            <button
              key={option}
              type="button"
              className="xstd-chip"
              aria-pressed={view === option}
              data-testid={`fidelity-overlay-view-${option}`}
              onClick={() => onChangeView(option)}
            >
              {option === "graph" ? "Graph" : "Treemap"}
            </button>
          ))}
        </div>
      </div>
      <p
        className="xstd-note"
        data-tone={reconciliation.matches ? undefined : "warn"}
        data-testid="fidelity-overlay-reconciliation"
        role={reconciliation.matches ? undefined : "status"}
      >
        {reconciliation.matches ? (
          <>
            {total.toLocaleString()} {total === 1 ? "finding" : "findings"}, the
            counts of the fidelity report.
            {reconciliation.unplaced > 0 &&
              ` ${reconciliation.unplaced.toLocaleString()} ${
                reconciliation.unplaced === 1 ? "is" : "are"
              } on constructs the graph does not draw (yet) — the treemap shows every one.`}
          </>
        ) : (
          <>
            The overlay does not add up to the fidelity report:{" "}
            {reconciliation.mismatches
              .map(
                (m) =>
                  `${kindLabel(m.kind)} counted ${m.counted}, reported ${m.reported}`,
              )
              .join("; ")}
            .
          </>
        )}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// The graph node's marker
// ---------------------------------------------------------------------------

/** Width of the marker pill drawn on a node box. */
export const KIND_MARKER_WIDTH = 30;

/**
 * The pill a graph node wears: the worst kind's glyph and the node's item count, at the
 * right end of the canonical box, in the chip palette. Decorative to assistive tech — the
 * node's accessible name carries the same facts in words.
 */
export function FidelityKindMarker({
  box,
  node,
}: {
  box: PlacedBox;
  node: NodeOverlay;
}) {
  const height = 16;
  const x = box.x + box.width - KIND_MARKER_WIDTH - 4;
  const y = box.y + (box.height - height) / 2;
  return (
    <g aria-hidden data-testid="fidelity-overlay-marker" data-kind={node.kind}>
      <rect
        x={x}
        y={y}
        width={KIND_MARKER_WIDTH}
        height={height}
        rx={height / 2}
        className="xstd-fov__mark"
        data-tone={kindTone(node.kind)}
      />
      <text
        x={x + KIND_MARKER_WIDTH / 2}
        y={y + height / 2 + 3.5}
        textAnchor="middle"
        fontSize={SVG_TEXT_SIZE.label}
        className="xstd-fov__mark-text"
      >
        {kindGlyph(node.kind)} {node.items.length}
      </text>
    </g>
  );
}

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------

/** The hovered/focused construct's report items. */
export interface OverlayDetailSubject {
  /** What the items are about (an entity key, `N constructs`, a construct path). */
  label: string;
  items: LossItem[];
}

/**
 * The LossItem detail of the hovered or focused node: each of its report items as the
 * report itself prints it. With nothing hovered it says how to get one.
 */
export function FidelityOverlayDetail({
  subject,
}: {
  subject: OverlayDetailSubject | null;
}) {
  return (
    <div
      className="xstd-fov__detail"
      aria-live="polite"
      data-testid="fidelity-overlay-detail"
    >
      {subject ? (
        <>
          <p className="xstd-fov__detail-title">
            <code className="xstd-mono">{subject.label}</code>
            {subject.items.length === 0
              ? " — the report records no outcome for it."
              : ` — ${subject.items.length} ${subject.items.length === 1 ? "finding" : "findings"}`}
          </p>
          {subject.items.length > 0 && (
            <ul className="xstd-fov__detail-list">
              {subject.items.map((item, index) => (
                <FidelityReportRow
                  key={`${item.construct}:${item.kind}:${index}`}
                  item={item}
                />
              ))}
            </ul>
          )}
        </>
      ) : (
        <p className="xstd-note">
          Hover or focus a construct to read what the fidelity report says about
          it.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Treemap
// ---------------------------------------------------------------------------

/** Default canvas of the treemap. */
const TREEMAP_WIDTH = 720;
const TREEMAP_HEIGHT = 320;

export interface FidelityTreemapProps {
  /** The groups to draw (already filtered by kind). */
  groups: TreemapGroup[];
  /** The selected entity key, highlighted on its tile. */
  selectedEntityKey: string | null;
  /** A tile was chosen; tiles whose construct is a loaded entity select it. */
  onSelectEntity: (entity: ExportManifestEntity) => void;
  /** A tile was hovered or focused (null when it left). */
  onHover: (subject: OverlayDetailSubject | null) => void;
  /** Accessible name of the drawing. */
  label: string;
  width?: number;
  height?: number;
}

/** The accessible name of one tile. */
export function tileAriaLabel(tile: PlacedTile["tile"]): string {
  const counts = LOSS_KINDS.map((kind) => ({
    kind,
    count: tile.items.filter((item) => item.kind === kind).length,
  }))
    .filter(({ count }) => count > 0)
    .map(({ kind, count }) => `${count} ${kindDescription(kind)}`)
    .join(", ");
  return `${tile.construct}: ${counts}`;
}

/**
 * The compact treemap: groups by construct path, one tile per construct sized by its item
 * count and painted by its worst kind (with the glyph printed in the tile when it fits).
 * Tiles are a roving-tabindex set of buttons in drawing order.
 */
export function FidelityTreemap({
  groups,
  selectedEntityKey,
  onSelectEntity,
  onHover,
  label,
  width = TREEMAP_WIDTH,
  height = TREEMAP_HEIGHT,
}: FidelityTreemapProps) {
  const layout = useMemo(
    () => layoutConstructTreemap(groups, width, height),
    [groups, width, height],
  );
  const [focusIndex, setFocusIndex] = useState(0);
  const tileRefs = useRef<(SVGGElement | null)[]>([]);
  const focus = Math.min(focusIndex, Math.max(0, layout.tiles.length - 1));

  const hover = useCallback(
    (placed: PlacedTile | null) =>
      onHover(
        placed
          ? { label: placed.tile.construct, items: placed.tile.items }
          : null,
      ),
    [onHover],
  );

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<SVGGElement>, index: number) => {
      const placed = layout.tiles[index];
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        if (placed.tile.entity) onSelectEntity(placed.tile.entity);
        return;
      }
      let next: number | null = null;
      if (event.key === "ArrowRight" || event.key === "ArrowDown")
        next = index + 1;
      else if (event.key === "ArrowLeft" || event.key === "ArrowUp")
        next = index - 1;
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = layout.tiles.length - 1;
      if (next === null) return;
      event.preventDefault();
      const clamped = Math.max(0, Math.min(next, layout.tiles.length - 1));
      setFocusIndex(clamped);
      tileRefs.current[clamped]?.focus();
    },
    [layout.tiles, onSelectEntity],
  );

  if (layout.tiles.length === 0) {
    return (
      <p className="xstd-empty" data-testid="fidelity-treemap-empty">
        No findings of the selected kinds.
      </p>
    );
  }

  return (
    <div className="xstd-map__frame">
      <svg
        data-testid="fidelity-treemap"
        role="group"
        aria-label={label}
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="block"
      >
        {layout.groups.map(({ group, rect }) => (
          <g
            key={group.key}
            aria-hidden
            data-testid={`fidelity-treemap-group-${group.key}`}
          >
            <rect
              x={rect.x}
              y={rect.y}
              width={rect.width}
              height={rect.height}
              className="xstd-fov__group"
            />
            {rect.width > 40 && (
              <text
                x={rect.x + 4}
                y={rect.y + 12}
                fontSize={SVG_TEXT_SIZE.label}
                className="xstd-fov__heading"
              >
                {fitProjectionLabel(
                  group.key,
                  Math.max(4, Math.floor(rect.width / 6.5)),
                )}
              </text>
            )}
          </g>
        ))}
        {layout.tiles.map((placed, index) => {
          const { tile, rect } = placed;
          const selected =
            tile.entity != null && tile.entity.key === selectedEntityKey;
          const chars = Math.floor((rect.width - 8) / 6.5);
          return (
            <g
              key={`${placed.group}:${tile.construct}`}
              ref={(el) => {
                tileRefs.current[index] = el;
              }}
              role="button"
              tabIndex={index === focus ? 0 : -1}
              aria-label={tileAriaLabel(tile)}
              aria-pressed={selected}
              aria-disabled={tile.entity ? undefined : true}
              data-testid={`fidelity-treemap-tile-${tile.construct}`}
              data-kind={tile.kind}
              className={cn(
                "outline-none",
                tile.entity ? "cursor-pointer" : "cursor-default",
              )}
              onClick={() => tile.entity && onSelectEntity(tile.entity)}
              onMouseEnter={() => hover(placed)}
              onMouseLeave={() => hover(null)}
              onFocus={() => {
                setFocusIndex(index);
                hover(placed);
              }}
              onBlur={() => hover(null)}
              onKeyDown={(event) => handleKeyDown(event, index)}
            >
              <rect
                x={rect.x + 1}
                y={rect.y + 1}
                width={Math.max(0, rect.width - 2)}
                height={Math.max(0, rect.height - 2)}
                rx={3}
                className="xstd-fov__mark xstd-fov__tile"
                data-tone={kindTone(tile.kind)}
                data-selected={selected}
              />
              {rect.width > 18 && rect.height > 14 && (
                <text
                  x={rect.x + 5}
                  y={rect.y + 13}
                  fontSize={SVG_TEXT_SIZE.tick}
                  className="xstd-fov__mark-text"
                >
                  {chars >= 3
                    ? fitProjectionLabel(
                        `${kindGlyph(tile.kind)} ${tile.label}`,
                        chars,
                      )
                    : kindGlyph(tile.kind)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
