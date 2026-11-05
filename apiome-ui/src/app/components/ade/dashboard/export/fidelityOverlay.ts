/**
 * Fidelity overlay model — loss kinds painted onto the mapping graph (MFX-45.2, #4375).
 *
 * The lossiness report (`LossinessReport`) is a *list* of findings, one per construct and
 * outcome. The mapping graph (IXH-4.2, which absorbed MFX-45.1) is a *map* of the
 * canonical entities. This module joins the two, so the graph can show **where** an export
 * loses fidelity:
 *
 *  - every report item is placed on the entity whose canonical key equals its `construct`
 *    (the report and the manifest share the stable construct keys of MFX-2.1), and a node
 *    takes the **worst** kind among its items (DROP → APPROX → SYNTH → OK)
 *    ({@link buildFidelityOverlay});
 *  - the legend's counts are the report's own `kind_counts`, and the overlay states whether
 *    the items it placed plus the ones it could not place add back up to them exactly
 *    ({@link reconcileOverlayCounts});
 *  - a **kind filter** isolates one or more kinds ({@link overlayMatchesFilter});
 *  - a compact **treemap** groups the same items by construct path, one tile per construct,
 *    for APIs too large for the graph ({@link buildConstructTreemap},
 *    {@link layoutConstructTreemap}).
 *
 * The data comes straight from the report: no item is invented, merged away or re-counted.
 * Everything here is pure (no React, no fetch, no clock) so it unit-tests directly.
 */

import {
  kindLabel,
  type LossItem,
  type LossinessKind,
  type LossinessReport,
} from "./exportFidelityPreview";
import type { ExportManifestEntity } from "./exportPreviewManifest";
import type { ExportMappingRow } from "./exportMappingGraph";
import { entryAriaLabel, type ProjectionViewEntry } from "./projectionGraph";

// ---------------------------------------------------------------------------
// Kinds
// ---------------------------------------------------------------------------

/** The four loss kinds, worst first — the legend's and the filter's order. */
export const LOSS_KINDS: readonly LossinessKind[] = [
  "drop",
  "approx",
  "synth",
  "ok",
];

/** Worst-first rank of a kind (lower is worse). */
const KIND_RANK: Record<LossinessKind, number> = {
  drop: 0,
  approx: 1,
  synth: 2,
  ok: 3,
};

/**
 * The worst kind among a set of items: DROP beats APPROX beats SYNTH beats OK.
 *
 * @param items Report items (any order).
 * @returns The worst kind, or null when there are no items.
 */
export function worstKind(items: readonly LossItem[]): LossinessKind | null {
  let worst: LossinessKind | null = null;
  for (const item of items) {
    if (worst === null || KIND_RANK[item.kind] < KIND_RANK[worst])
      worst = item.kind;
  }
  return worst;
}

/** A zero-filled count per kind. */
export type KindCounts = Record<LossinessKind, number>;

/** A fresh zero-filled {@link KindCounts}. */
export function emptyKindCounts(): KindCounts {
  return { drop: 0, approx: 0, synth: 0, ok: 0 };
}

/**
 * Count items per kind.
 *
 * @param items Report items.
 * @returns The zero-filled count per kind.
 */
export function countKinds(items: readonly LossItem[]): KindCounts {
  const counts = emptyKindCounts();
  for (const item of items) counts[item.kind] += 1;
  return counts;
}

// ---------------------------------------------------------------------------
// The overlay
// ---------------------------------------------------------------------------

/** The overlay of one graph node: the report items that land on it. */
export interface NodeOverlay {
  /** The worst kind among the items — the node's paint. */
  kind: LossinessKind;
  /** The items, worst kind first, then worst severity, then report order. */
  items: LossItem[];
  /** The node's items counted per kind. */
  counts: KindCounts;
}

/** The report joined onto the loaded manifest entities. */
export interface FidelityOverlay {
  /** Overlay per entity key, for every entity at least one item lands on. */
  byEntityKey: Map<string, NodeOverlay>;
  /** Items whose construct is not one of the loaded entities, in report order. */
  unplaced: LossItem[];
  /** The report's own count per kind — what the legend prints. */
  reportCounts: KindCounts;
  /** Every item counted per kind (placed + unplaced). */
  itemCounts: KindCounts;
  /** The total number of report items. */
  total: number;
}

const SEVERITY_RANK: Record<LossItem["severity"], number> = {
  critical: 0,
  warn: 1,
  info: 2,
};

/** Order a node's items worst-first, stably (ties keep report order). */
function sortItems(items: LossItem[]): LossItem[] {
  return items
    .map((item, index) => ({ item, index }))
    .sort(
      (a, b) =>
        KIND_RANK[a.item.kind] - KIND_RANK[b.item.kind] ||
        SEVERITY_RANK[a.item.severity] - SEVERITY_RANK[b.item.severity] ||
        a.index - b.index,
    )
    .map(({ item }) => item);
}

/** Build a node overlay from a non-empty item list. */
function nodeOverlayFor(items: LossItem[]): NodeOverlay {
  const sorted = sortItems(items);
  return {
    kind: worstKind(sorted)!,
    items: sorted,
    counts: countKinds(sorted),
  };
}

/**
 * The report's `kind_counts`, zero-filled. A report from an older server may omit a kind;
 * a missing kind counts as zero.
 */
function reportKindCounts(report: LossinessReport): KindCounts {
  const counts = emptyKindCounts();
  for (const kind of LOSS_KINDS)
    counts[kind] = Number(report.kind_counts?.[kind] ?? 0);
  return counts;
}

/**
 * Join a lossiness report onto the manifest entities by construct key.
 *
 * An item lands on the entity whose `key` equals its `construct` — exactly, never by a
 * guessed prefix — so a node's paint is a claim the report itself makes about that entity.
 * An item with no matching entity (the manifest is still loading, or the construct is not
 * an entity) is kept in {@link FidelityOverlay.unplaced}, so the totals still add up.
 *
 * @param report The fidelity report of the export being reviewed.
 * @param entities The loaded manifest entities.
 * @returns The overlay.
 */
export function buildFidelityOverlay(
  report: LossinessReport,
  entities: readonly ExportManifestEntity[],
): FidelityOverlay {
  const keys = new Set(entities.map((entity) => entity.key));
  const grouped = new Map<string, LossItem[]>();
  const unplaced: LossItem[] = [];
  for (const item of report.items) {
    if (keys.has(item.construct)) {
      const list = grouped.get(item.construct);
      if (list) list.push(item);
      else grouped.set(item.construct, [item]);
    } else {
      unplaced.push(item);
    }
  }
  const byEntityKey = new Map<string, NodeOverlay>();
  for (const [key, items] of grouped)
    byEntityKey.set(key, nodeOverlayFor(items));
  return {
    byEntityKey,
    unplaced,
    reportCounts: reportKindCounts(report),
    itemCounts: countKinds(report.items),
    total: report.items.length,
  };
}

/**
 * The overlay of one graph entry: a row's own items, or every member's items for an
 * aggregate (the graph collapses clean rows; their OK findings still belong to them).
 *
 * @param entry A mapping-graph view entry.
 * @param overlay The overlay.
 * @returns The entry's overlay, or null when no report item lands on it.
 */
export function entryOverlay(
  entry: ProjectionViewEntry<string>,
  overlay: FidelityOverlay,
): NodeOverlay | null {
  const rows =
    entry.kind === "aggregate"
      ? ((entry.members ?? []) as ExportMappingRow[])
      : entry.row
        ? [entry.row as ExportMappingRow]
        : [];
  const items: LossItem[] = [];
  for (const row of rows) {
    const node = row.entity
      ? overlay.byEntityKey.get(row.entity.key)
      : undefined;
    if (node) items.push(...node.items);
  }
  return items.length > 0 ? nodeOverlayFor(items) : null;
}

/**
 * A short sentence of a node's item counts, worst kind first (`2 APPROX, 1 SYNTH`).
 *
 * @param counts The node's count per kind.
 * @returns The sentence; empty when every count is zero.
 */
export function overlayCountsSentence(counts: KindCounts): string {
  return LOSS_KINDS.filter((kind) => counts[kind] > 0)
    .map((kind) => `${counts[kind]} ${kindLabel(kind)}`)
    .join(", ");
}

/**
 * The accessible name of a graph entry with the overlay on: the graph's own name, plus what
 * the fidelity report says about the entry. The node and its table row share it, so the
 * graph and its text alternative keep identical names.
 *
 * @param entry The view entry.
 * @param node The entry's overlay (null when no item lands on it).
 * @returns The accessible name.
 */
export function overlayAriaLabel(
  entry: ProjectionViewEntry<string>,
  node: NodeOverlay | null,
): string {
  const base = entryAriaLabel(entry);
  return node
    ? `${base}; fidelity report: ${overlayCountsSentence(node.counts)}`
    : `${base}; fidelity report: no finding`;
}

// ---------------------------------------------------------------------------
// Reconciliation
// ---------------------------------------------------------------------------

/** One kind whose counted items disagree with the report's own count. */
export interface OverlayCountMismatch {
  kind: LossinessKind;
  /** The items the overlay counted. */
  counted: number;
  /** The report's `kind_counts` value. */
  reported: number;
}

/** Whether the overlay's counts reproduce the report's. */
export interface OverlayReconciliation {
  /** True when every kind's counted items equal the report's count. */
  matches: boolean;
  mismatches: OverlayCountMismatch[];
  /** Items placed on a graph node. */
  placed: number;
  /** Items with no node on the graph. */
  unplaced: number;
}

/**
 * State whether the overlay's items add back up to the report's `kind_counts` exactly.
 * They always do for a well-formed report; a disagreement is named kind by kind rather
 * than hidden, so a legend can never print a count the drawing does not carry.
 *
 * @param overlay The overlay.
 * @returns The reconciliation.
 */
export function reconcileOverlayCounts(
  overlay: FidelityOverlay,
): OverlayReconciliation {
  const mismatches: OverlayCountMismatch[] = [];
  for (const kind of LOSS_KINDS) {
    const counted = overlay.itemCounts[kind];
    const reported = overlay.reportCounts[kind];
    if (counted !== reported) mismatches.push({ kind, counted, reported });
  }
  return {
    matches: mismatches.length === 0,
    mismatches,
    placed: overlay.total - overlay.unplaced.length,
    unplaced: overlay.unplaced.length,
  };
}

// ---------------------------------------------------------------------------
// Filter
// ---------------------------------------------------------------------------

/**
 * Whether a node shows under the kind filter. With every kind active the filter is off and
 * every node shows; otherwise a node shows when at least one of its items is of an active
 * kind, and a node with no items never shows (it has nothing of the isolated kinds).
 *
 * @param node The node's overlay, or null when no item lands on it.
 * @param active The active kinds.
 * @returns True when the node matches.
 */
export function overlayMatchesFilter(
  node: NodeOverlay | null,
  active: ReadonlySet<LossinessKind>,
): boolean {
  if (isFilterOff(active)) return true;
  if (!node) return false;
  return node.items.some((item) => active.has(item.kind));
}

/** True when every kind is active — the filter is off. */
export function isFilterOff(active: ReadonlySet<LossinessKind>): boolean {
  return LOSS_KINDS.every((kind) => active.has(kind));
}

/**
 * Toggle one kind in the filter. The last active kind cannot be switched off: an empty
 * filter would hide everything and look like an empty report.
 *
 * @param active The active kinds.
 * @param kind The kind to toggle.
 * @returns The new active set.
 */
export function toggleKind(
  active: ReadonlySet<LossinessKind>,
  kind: LossinessKind,
): Set<LossinessKind> {
  const next = new Set(active);
  if (next.has(kind)) {
    if (next.size > 1) next.delete(kind);
  } else {
    next.add(kind);
  }
  return next;
}

/**
 * Isolate one kind — or, when it is already the only active kind, switch the filter off.
 *
 * @param active The active kinds.
 * @param kind The kind to isolate.
 * @returns The new active set.
 */
export function isolateKind(
  active: ReadonlySet<LossinessKind>,
  kind: LossinessKind,
): Set<LossinessKind> {
  if (active.size === 1 && active.has(kind)) return new Set(LOSS_KINDS);
  return new Set([kind]);
}

// ---------------------------------------------------------------------------
// Treemap — the compact view by construct path
// ---------------------------------------------------------------------------

/** One construct's tile: every item the report holds for that construct. */
export interface TreemapTile {
  /** The construct key. */
  construct: string;
  /** The tile's label: the construct's last path segment. */
  label: string;
  /** The items, worst first. */
  items: LossItem[];
  /** The worst kind — the tile's paint. */
  kind: LossinessKind;
  /** The tile's area weight: its item count. */
  size: number;
  /** The manifest entity the construct names, when it is loaded (selection target). */
  entity: ExportManifestEntity | null;
}

/** One top-level construct-path group (a type, a service, a channel…). */
export interface TreemapGroup {
  /** The group's path root. */
  key: string;
  tiles: TreemapTile[];
  /** The group's area weight: the sum of its tiles' sizes. */
  size: number;
  /** The worst kind among its tiles. */
  kind: LossinessKind;
}

/**
 * The top-level path root of a construct key.
 *
 * A loaded entity's root is its top ancestor through `parent_key` (an operation groups
 * under its service). Otherwise the root is the key up to its first `.` — `Pet.age` groups
 * under `Pet` — and a key with no `.` is its own root (`GET /pets`).
 *
 * @param construct The construct key.
 * @param entities The loaded entities, by key.
 * @returns The group key.
 */
export function constructRoot(
  construct: string,
  entities: ReadonlyMap<string, ExportManifestEntity>,
): string {
  let entity = entities.get(construct);
  if (entity) {
    const seen = new Set<string>();
    while (
      entity.parent_key &&
      entities.has(entity.parent_key) &&
      !seen.has(entity.key)
    ) {
      seen.add(entity.key);
      entity = entities.get(entity.parent_key)!;
    }
    return entity.key;
  }
  const dot = construct.indexOf(".");
  return dot > 0 ? construct.slice(0, dot) : construct;
}

/** The label of a tile: the construct relative to its group root, or the whole key. */
function tileLabel(construct: string, root: string): string {
  if (construct === root) return construct;
  return construct.startsWith(`${root}.`)
    ? construct.slice(root.length + 1)
    : construct;
}

/**
 * Group the report's items by construct path for the treemap: one group per path root,
 * one tile per construct. Only items of the active kinds are kept, so the filter isolates
 * kinds here exactly as it does on the graph — a tile shows only the items it was kept for.
 * Groups are ordered worst kind first, then largest; tiles likewise.
 *
 * @param report The fidelity report.
 * @param entities The loaded manifest entities.
 * @param active The active kinds.
 * @returns The groups.
 */
export function buildConstructTreemap(
  report: LossinessReport,
  entities: readonly ExportManifestEntity[],
  active: ReadonlySet<LossinessKind>,
): TreemapGroup[] {
  const byKey = new Map(
    entities.map((entity) => [entity.key, entity] as const),
  );
  const tiles = new Map<string, LossItem[]>();
  for (const item of report.items) {
    if (!active.has(item.kind)) continue;
    const list = tiles.get(item.construct);
    if (list) list.push(item);
    else tiles.set(item.construct, [item]);
  }
  const groups = new Map<string, TreemapTile[]>();
  for (const [construct, items] of tiles) {
    const root = constructRoot(construct, byKey);
    const sorted = sortItems(items);
    const tile: TreemapTile = {
      construct,
      label: tileLabel(construct, root),
      items: sorted,
      kind: worstKind(sorted)!,
      size: sorted.length,
      entity: byKey.get(construct) ?? null,
    };
    const list = groups.get(root);
    if (list) list.push(tile);
    else groups.set(root, [tile]);
  }
  const byWeight = <T extends { kind: LossinessKind; size: number }>(
    a: T,
    b: T,
    ka: string,
    kb: string,
  ) =>
    KIND_RANK[a.kind] - KIND_RANK[b.kind] ||
    b.size - a.size ||
    ka.localeCompare(kb);
  return [...groups.entries()]
    .map(([key, list]) => {
      const sortedTiles = [...list].sort((a, b) =>
        byWeight(a, b, a.construct, b.construct),
      );
      return {
        key,
        tiles: sortedTiles,
        size: sortedTiles.reduce((sum, tile) => sum + tile.size, 0),
        kind: sortedTiles.reduce<LossinessKind>(
          (worst, tile) =>
            KIND_RANK[tile.kind] < KIND_RANK[worst] ? tile.kind : worst,
          "ok",
        ),
      };
    })
    .sort((a, b) => byWeight(a, b, a.key, b.key));
}

/** An axis-aligned rectangle. */
export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Worst aspect ratio of a row of areas laid along a side of length `side`. */
function worstRatio(row: number[], side: number): number {
  const sum = row.reduce((a, b) => a + b, 0);
  if (sum <= 0 || side <= 0) return Infinity;
  const max = Math.max(...row);
  const min = Math.min(...row);
  const s2 = side * side;
  const sum2 = sum * sum;
  return Math.max((s2 * max) / sum2, sum2 / (s2 * min));
}

/**
 * Squarified treemap layout (Bruls, Huizing & van Wijk): split `rect` into one rectangle per
 * weight, in order, with areas proportional to the weights and aspect ratios kept near 1.
 * Deterministic — the same weights and rectangle always yield the same picture.
 *
 * @param weights Positive weights, in the order to place them (largest first reads best).
 * @param rect The rectangle to fill.
 * @returns One rectangle per weight, in input order.
 */
export function squarify(weights: readonly number[], rect: Rect): Rect[] {
  const total = weights.reduce((a, b) => a + Math.max(0, b), 0);
  if (weights.length === 0) return [];
  if (total <= 0 || rect.width <= 0 || rect.height <= 0) {
    return weights.map(() => ({ x: rect.x, y: rect.y, width: 0, height: 0 }));
  }
  const scale = (rect.width * rect.height) / total;
  const areas = weights.map((w) => Math.max(0, w) * scale);
  const out: Rect[] = [];
  let free = { ...rect };
  let start = 0;
  while (start < areas.length) {
    const side = Math.min(free.width, free.height);
    let end = start + 1;
    while (
      end < areas.length &&
      worstRatio(areas.slice(start, end + 1), side) <=
        worstRatio(areas.slice(start, end), side)
    ) {
      end += 1;
    }
    const row = areas.slice(start, end);
    const rowSum = row.reduce((a, b) => a + b, 0);
    const horizontal = free.width >= free.height; // lay the row along the short (left) side
    if (horizontal) {
      const thickness = free.height > 0 ? rowSum / free.height : 0;
      let y = free.y;
      for (const area of row) {
        const height = thickness > 0 ? area / thickness : 0;
        out.push({ x: free.x, y, width: thickness, height });
        y += height;
      }
      free = {
        x: free.x + thickness,
        y: free.y,
        width: free.width - thickness,
        height: free.height,
      };
    } else {
      const thickness = free.width > 0 ? rowSum / free.width : 0;
      let x = free.x;
      for (const area of row) {
        const width = thickness > 0 ? area / thickness : 0;
        out.push({ x, y: free.y, width, height: thickness });
        x += width;
      }
      free = {
        x: free.x,
        y: free.y + thickness,
        width: free.width,
        height: free.height - thickness,
      };
    }
    start = end;
  }
  return out;
}

/** One placed tile of the laid-out treemap. */
export interface PlacedTile {
  tile: TreemapTile;
  group: string;
  rect: Rect;
}

/** One placed group frame of the laid-out treemap. */
export interface PlacedGroup {
  group: TreemapGroup;
  rect: Rect;
}

/** The laid-out treemap the SVG draws verbatim. */
export interface TreemapLayout {
  width: number;
  height: number;
  groups: PlacedGroup[];
  tiles: PlacedTile[];
}

/** Geometry of the treemap drawing. */
export const TREEMAP_GEOMETRY = {
  /** Height reserved for each group's heading strip. */
  headerHeight: 18,
  /** Inset between a group's frame and its tiles. */
  inset: 2,
} as const;

/**
 * Lay out the treemap: groups squarified into the canvas, each group's tiles squarified
 * into the group's frame below its heading strip.
 *
 * @param groups The groups from {@link buildConstructTreemap}.
 * @param width Canvas width.
 * @param height Canvas height.
 * @returns The placed groups and tiles.
 */
export function layoutConstructTreemap(
  groups: readonly TreemapGroup[],
  width: number,
  height: number,
): TreemapLayout {
  const { headerHeight, inset } = TREEMAP_GEOMETRY;
  const groupRects = squarify(
    groups.map((group) => group.size),
    { x: 0, y: 0, width, height },
  );
  const placedGroups: PlacedGroup[] = [];
  const placedTiles: PlacedTile[] = [];
  groups.forEach((group, index) => {
    const rect = groupRects[index];
    placedGroups.push({ group, rect });
    const body: Rect = {
      x: rect.x + inset,
      y: rect.y + Math.min(headerHeight, rect.height / 2),
      width: Math.max(0, rect.width - 2 * inset),
      height: Math.max(
        0,
        rect.height - Math.min(headerHeight, rect.height / 2) - inset,
      ),
    };
    const tileRects = squarify(
      group.tiles.map((tile) => tile.size),
      body,
    );
    group.tiles.forEach((tile, tileIndex) =>
      placedTiles.push({ tile, group: group.key, rect: tileRects[tileIndex] }),
    );
  });
  return { width, height, groups: placedGroups, tiles: placedTiles };
}
