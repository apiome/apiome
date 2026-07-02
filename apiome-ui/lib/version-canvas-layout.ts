/**
 * Resolve persisted Studio canvas rows into {@link LayoutState} for version-level compare (#742).
 */

import type { LayoutState } from './layout-diff';
import {
  getDefaultCanvasLayout,
  getEffectiveDefaultLayoutName,
  getNamedCanvasLayout,
} from './db/helper';

function parseMaybeJson<T>(v: unknown): T | null {
  if (v == null) return null;
  if (typeof v === 'string') {
    try {
      return JSON.parse(v) as T;
    } catch {
      return null;
    }
  }
  return v as T;
}

/** Normalize a DB `canvas_layouts` row into {@link LayoutState}. */
export function rowToLayoutState(row: Record<string, unknown>): LayoutState {
  const nodes = parseMaybeJson<LayoutState['nodes']>(row.nodes);
  const edges = parseMaybeJson<LayoutState['edges']>(row.edges);
  return {
    viewport: parseMaybeJson(row.viewport) ?? undefined,
    nodes: Array.isArray(nodes) ? nodes : [],
    edges: Array.isArray(edges) ? edges : [],
    grid_settings: parseMaybeJson(row.grid_settings) ?? undefined,
    minimap_settings: parseMaybeJson(row.minimap_settings) ?? undefined,
  };
}

/**
 * Load the best-effort layout snapshot for a version: default row, else the effective named layout
 * (same resolution as Studio open).
 *
 * Caller-supplied actor identifiers are intentionally ignored here. User/tenant context must be
 * derived and enforced in the server action layer rather than forwarded from potentially
 * client-controlled inputs.
 */
export async function loadLayoutStateForVersionCompare(
  versionId: string,
  _userId: string | undefined,
  _tenantId: string | undefined
): Promise<LayoutState | null> {
  const defRaw = await getDefaultCanvasLayout(versionId, undefined);
  const def = JSON.parse(defRaw) as { success?: boolean; layout?: Record<string, unknown> };
  if (def.success && def.layout) {
    return rowToLayoutState(def.layout);
  }

  const effRaw = await getEffectiveDefaultLayoutName(versionId, undefined, undefined);
  const eff = JSON.parse(effRaw) as { success?: boolean; layoutName?: string };
  if (eff.success && eff.layoutName) {
    const namedRaw = await getNamedCanvasLayout(versionId, null, eff.layoutName);
    const named = JSON.parse(namedRaw) as { success?: boolean; layout?: Record<string, unknown> };
    if (named.success && named.layout) {
      return rowToLayoutState(named.layout);
    }
  }

  return null;
}
