/**
 * Canvas layout JSON interchange format (versioned for compatibility across app and project copies).
 */

import type { Edge } from '@xyflow/react';

export const CANVAS_LAYOUT_JSON_FORMAT_VERSION = 1 as const;

export type CanvasLayoutJsonDocument = {
  formatVersion: typeof CANVAS_LAYOUT_JSON_FORMAT_VERSION;
  /** ISO 8601 timestamp */
  exportedAt: string;
  layoutName?: string;
  viewport: { x: number; y: number; zoom: number };
  nodes: unknown[];
  edges: unknown[];
  groups?: unknown[];
  gridSettings?: unknown;
  minimapSettings?: unknown;
  /** Producer metadata (optional) */
  generator?: { name: string; version?: string };
};

export function buildCanvasLayoutJsonDocument(params: {
  layoutName?: string;
  viewport: { x: number; y: number; zoom: number };
  nodes: unknown[];
  edges: unknown[];
  groups?: unknown[];
  gridSettings?: unknown;
  minimapSettings?: unknown;
  generator?: { name: string; version?: string };
}): CanvasLayoutJsonDocument {
  return {
    formatVersion: CANVAS_LAYOUT_JSON_FORMAT_VERSION,
    exportedAt: new Date().toISOString(),
    ...(params.layoutName?.trim() ? { layoutName: params.layoutName.trim() } : {}),
    viewport: params.viewport,
    nodes: params.nodes,
    edges: params.edges,
    ...(params.groups !== undefined ? { groups: params.groups } : {}),
    ...(params.gridSettings !== undefined ? { gridSettings: params.gridSettings } : {}),
    ...(params.minimapSettings !== undefined ? { minimapSettings: params.minimapSettings } : {}),
    ...(params.generator ? { generator: params.generator } : {}),
  };
}

export function parseCanvasLayoutJson(
  raw: unknown
): { ok: true; doc: CanvasLayoutJsonDocument } | { ok: false; error: string } {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) {
    return { ok: false, error: 'File must contain a JSON object.' };
  }
  const o = raw as Record<string, unknown>;

  if (o.formatVersion !== CANVAS_LAYOUT_JSON_FORMAT_VERSION) {
    return {
      ok: false,
      error: `Unsupported formatVersion: ${String(o.formatVersion)} (expected ${CANVAS_LAYOUT_JSON_FORMAT_VERSION}).`,
    };
  }

  if (typeof o.exportedAt !== 'string' || !o.exportedAt.trim()) {
    return { ok: false, error: 'Missing or invalid exportedAt.' };
  }

  if (o.viewport === null || typeof o.viewport !== 'object' || Array.isArray(o.viewport)) {
    return { ok: false, error: 'Missing or invalid viewport.' };
  }
  const vp = o.viewport as Record<string, unknown>;
  const vpX = typeof vp.x === 'number' && Number.isFinite(vp.x) ? vp.x : 0;
  const vpY = typeof vp.y === 'number' && Number.isFinite(vp.y) ? vp.y : 0;
  const vpZoom = typeof vp.zoom === 'number' && Number.isFinite(vp.zoom) ? vp.zoom : 1;

  if (!Array.isArray(o.nodes)) {
    return { ok: false, error: 'Missing or invalid nodes array.' };
  }

  if (!Array.isArray(o.edges)) {
    return { ok: false, error: 'Missing or invalid edges array.' };
  }

  if (o.groups !== undefined && !Array.isArray(o.groups)) {
    return { ok: false, error: 'Invalid groups: expected an array when present.' };
  }

  const doc: CanvasLayoutJsonDocument = {
    formatVersion: CANVAS_LAYOUT_JSON_FORMAT_VERSION,
    exportedAt: o.exportedAt,
    viewport: { x: vpX, y: vpY, zoom: vpZoom },
    nodes: o.nodes,
    edges: o.edges,
    ...(Array.isArray(o.groups) ? { groups: o.groups } : {}),
    ...(o.gridSettings !== undefined ? { gridSettings: o.gridSettings } : {}),
    ...(o.minimapSettings !== undefined ? { minimapSettings: o.minimapSettings } : {}),
    ...(typeof o.layoutName === 'string' && o.layoutName.trim() ? { layoutName: o.layoutName.trim() } : {}),
    ...(o.generator !== undefined &&
    o.generator !== null &&
    typeof o.generator === 'object' &&
    !Array.isArray(o.generator) &&
    typeof (o.generator as { name?: unknown }).name === 'string'
      ? { generator: o.generator as { name: string; version?: string } }
      : {}),
  };

  return { ok: true, doc };
}

export type FilteredCanvasLayoutForImport = {
  viewport: { x: number; y: number; zoom: number };
  /** Class nodes only (group nodes stripped); sanitized to {id, position} */
  nodes: { id: string; position: { x: number; y: number } }[];
  edges: unknown[];
  /** Groups with nodeIds restricted to classes present in this version */
  groups: unknown[];
  nodePositions: Record<string, { x: number; y: number }>;
  droppedClassCount: number;
};

/**
 * Restricts an imported document to class IDs that exist in the target version.
 * Drops group nodes from `nodes` (groups are restored from DB after sync).
 */
export function filterCanvasLayoutForTargetClasses(
  doc: CanvasLayoutJsonDocument,
  validClassIds: Set<string>
): FilteredCanvasLayoutForImport {
  const rawNodes = Array.isArray(doc.nodes) ? doc.nodes : [];
  let droppedClassCount = 0;

  const filteredNodes = rawNodes.filter((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      return false;
    }
    const n = item as { id?: unknown; type?: unknown };
    if (n.type === 'groupNode') {
      return false;
    }
    if (typeof n.id !== 'string') {
      return false;
    }
    if (!validClassIds.has(n.id)) {
      droppedClassCount += 1;
      return false;
    }
    return true;
  });

  const nodePositions: Record<string, { x: number; y: number }> = {};
  filteredNodes.forEach((item) => {
    const n = item as { id: string; position?: { x?: unknown; y?: unknown } };
    const x = n.position?.x;
    const y = n.position?.y;
    if (typeof x === 'number' && Number.isFinite(x) && typeof y === 'number' && Number.isFinite(y)) {
      nodePositions[n.id] = { x, y };
    }
  });

  /** Sanitized class nodes: only id + validated position; nodes with invalid positions are dropped. */
  const sanitizedNodes = Object.entries(nodePositions).map(([id, position]) => ({ id, position }));

  const rawEdges = Array.isArray(doc.edges) ? doc.edges : [];
  const filteredEdges = rawEdges.filter((e) => {
    if (!e || typeof e !== 'object' || Array.isArray(e)) return false;
    const edge = e as { source?: unknown; target?: unknown };
    return (
      typeof edge.source === 'string' &&
      typeof edge.target === 'string' &&
      validClassIds.has(edge.source) &&
      validClassIds.has(edge.target)
    );
  });

  const rawGroups = Array.isArray(doc.groups) ? doc.groups : [];
  const filteredGroups = rawGroups
    .filter((g) => g && typeof g === 'object' && !Array.isArray(g))
    .map((g) => {
      const gr = g as { nodeIds?: unknown };
      const nodeIds = Array.isArray(gr.nodeIds)
        ? gr.nodeIds.filter((id): id is string => typeof id === 'string' && validClassIds.has(id))
        : [];
      return { ...gr, nodeIds };
    });

  return {
    viewport: doc.viewport,
    nodes: sanitizedNodes,
    edges: filteredEdges,
    groups: filteredGroups,
    nodePositions,
    droppedClassCount,
  };
}

/**
 * After the canvas rebuilds edges from schema, overlay handle IDs from an imported or saved layout
 * so routing matches the exported file when edge IDs still match.
 */
export function mergeSavedEdgeHandles(
  currentEdges: Edge[],
  savedEdges: unknown[] | undefined
): Edge[] {
  if (!savedEdges?.length) {
    return currentEdges;
  }
  const byId = new Map<string, { sourceHandle?: string; targetHandle?: string }>();
  for (const raw of savedEdges) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) continue;
    const e = raw as Record<string, unknown>;
    if (typeof e.id !== 'string') continue;
    const overlay: { sourceHandle?: string; targetHandle?: string } = {};
    if (typeof e.sourceHandle === 'string') overlay.sourceHandle = e.sourceHandle;
    if (typeof e.targetHandle === 'string') overlay.targetHandle = e.targetHandle;
    if (Object.keys(overlay).length === 0) continue;
    byId.set(e.id, overlay);
  }
  if (byId.size === 0) {
    return currentEdges;
  }
  return currentEdges.map((edge) => {
    const o = byId.get(edge.id);
    if (!o) return edge;
    return { ...edge, ...o };
  });
}
