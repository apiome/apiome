/**
 * fidelityOverlay — the fidelity heatmap overlay model (MFX-45.2, #4375).
 *
 * Pins the model-level contract:
 *
 *  1. Report items land on the entity whose key equals their construct — exactly — and a
 *     node takes the worst kind of its items (DROP → APPROX → SYNTH → OK).
 *  2. The counts are the report's: placed + unplaced items add back up to `kind_counts`,
 *     and a disagreement is named kind by kind.
 *  3. The kind filter isolates kinds; it can never be emptied.
 *  4. The treemap groups by construct path, keeps only the active kinds, and its squarified
 *     layout fills the canvas with areas proportional to the weights.
 */

import {
  buildConstructTreemap,
  buildFidelityOverlay,
  constructRoot,
  countKinds,
  entryOverlay,
  isFilterOff,
  isolateKind,
  layoutConstructTreemap,
  LOSS_KINDS,
  overlayAriaLabel,
  overlayCountsSentence,
  overlayMatchesFilter,
  reconcileOverlayCounts,
  squarify,
  toggleKind,
  worstKind,
} from '../src/app/components/ade/dashboard/export/fidelityOverlay';
import {
  buildExportMappingRows,
  buildExportMappingView,
} from '../src/app/components/ade/dashboard/export/exportMappingGraph';
import { entryAriaLabel } from '../src/app/components/ade/dashboard/export/projectionGraph';
import type {
  LossItem,
  LossinessKind,
  LossinessReport,
} from '../src/app/components/ade/dashboard/export/exportFidelityPreview';
import type { ExportManifestEntity } from '../src/app/components/ade/dashboard/export/exportPreviewManifest';

// ---------------------------------------------------------------------------
// Fixtures — a lossy OpenAPI → proto3 export (the shape the Petstore one has)
// ---------------------------------------------------------------------------

function entity(overrides: Partial<ExportManifestEntity>): ExportManifestEntity {
  return {
    key: 'Entity',
    name: 'Entity',
    entity_kind: 'type',
    parent_key: null,
    order: 0,
    description: null,
    deprecated: false,
    status: 'retained',
    reason: null,
    severity: 'info',
    detail: 'carried faithfully',
    target_mapping: null,
    emitted: true,
    location: null,
    aggregated: false,
    reported: true,
    native_name: null,
    native_id: null,
    source_location: null,
    ...overrides,
  };
}

const ENTITIES: ExportManifestEntity[] = [
  entity({ key: 'default', name: 'default', entity_kind: 'service', order: 0 }),
  entity({ key: 'GET /pets', name: 'GET /pets', entity_kind: 'operation', parent_key: 'default', order: 1 }),
  entity({ key: 'Pet', name: 'Pet', order: 2 }),
  entity({ key: 'Pet.id', name: 'id', entity_kind: 'field', parent_key: 'Pet', order: 3, status: 'approximated', severity: 'warn' }),
  entity({ key: 'Pet.name', name: 'name', entity_kind: 'field', parent_key: 'Pet', order: 4, status: 'approximated', severity: 'warn' }),
  entity({ key: 'Pet.links', name: 'links', entity_kind: 'field', parent_key: 'Pet', order: 5, status: 'dropped', severity: 'critical', emitted: false }),
];

function item(construct: string, kind: LossinessKind, severity: LossItem['severity'] = 'warn', message = `${kind} ${construct}`): LossItem {
  return { construct, kind, severity, message, target_mapping: kind === 'drop' ? null : 'optional' };
}

const ITEMS: LossItem[] = [
  item('GET /pets', 'ok', 'info'),
  item('Pet', 'ok', 'info'),
  item('Pet.id', 'approx'),
  item('Pet.id', 'synth'),
  item('Pet.id', 'approx', 'critical'),
  item('Pet.name', 'synth'),
  item('Pet.links', 'drop', 'critical'),
  item('Owner.email', 'approx'), // not an entity — stays unplaced
];

function report(items: LossItem[] = ITEMS, kind_counts?: Record<string, number>): LossinessReport {
  const counts = countKinds(items);
  return {
    items,
    kind_counts: kind_counts ?? { ...counts },
    severity_counts: { info: 0, warn: 0, critical: 0 },
  };
}

// ---------------------------------------------------------------------------
// 1. Placement and paint
// ---------------------------------------------------------------------------

describe('worstKind', () => {
  it('ranks DROP over APPROX over SYNTH over OK', () => {
    expect(worstKind([item('a', 'ok'), item('a', 'synth')])).toBe('synth');
    expect(worstKind([item('a', 'synth'), item('a', 'approx')])).toBe('approx');
    expect(worstKind([item('a', 'approx'), item('a', 'drop'), item('a', 'ok')])).toBe('drop');
    expect(worstKind([])).toBeNull();
  });
});

describe('buildFidelityOverlay', () => {
  const overlay = buildFidelityOverlay(report(), ENTITIES);

  it('places every item on the entity its construct names, exactly', () => {
    expect([...overlay.byEntityKey.keys()].sort()).toEqual(['GET /pets', 'Pet', 'Pet.id', 'Pet.links', 'Pet.name']);
    expect(overlay.byEntityKey.get('Pet.id')!.items).toHaveLength(3);
    // No prefix guessing: `Pet` does not collect its fields' items.
    expect(overlay.byEntityKey.get('Pet')!.items).toHaveLength(1);
  });

  it('paints a node with the worst kind of its items, and counts them per kind', () => {
    const id = overlay.byEntityKey.get('Pet.id')!;
    expect(id.kind).toBe('approx');
    expect(id.counts).toEqual({ drop: 0, approx: 2, synth: 1, ok: 0 });
    expect(overlay.byEntityKey.get('Pet.links')!.kind).toBe('drop');
    expect(overlay.byEntityKey.get('Pet.name')!.kind).toBe('synth');
    expect(overlay.byEntityKey.get('Pet')!.kind).toBe('ok');
  });

  it('orders a node’s items worst kind first, then worst severity, then report order', () => {
    expect(overlay.byEntityKey.get('Pet.id')!.items.map((i) => `${i.kind}:${i.severity}`)).toEqual([
      'approx:critical',
      'approx:warn',
      'synth:warn',
    ]);
  });

  it('keeps an item whose construct is not a loaded entity as unplaced', () => {
    expect(overlay.unplaced.map((i) => i.construct)).toEqual(['Owner.email']);
  });

  it('carries the report’s own counts, zero-filling a kind the report omits', () => {
    const partial = buildFidelityOverlay(report(ITEMS, { approx: 4, synth: 2, drop: 1 }), ENTITIES);
    expect(partial.reportCounts).toEqual({ drop: 1, approx: 4, synth: 2, ok: 0 });
  });
});

describe('entryOverlay', () => {
  const overlay = buildFidelityOverlay(report(), ENTITIES);

  it('returns a row’s own items', () => {
    const view = buildExportMappingView(buildExportMappingRows(ENTITIES));
    const id = view.entries.find((entry) => entry.row && (entry.row as { entity: ExportManifestEntity }).entity.key === 'Pet.id')!;
    expect(entryOverlay(id, overlay)!.items).toHaveLength(3);
    const service = view.entries.find((entry) => (entry.row as { entity?: ExportManifestEntity })?.entity?.key === 'default')!;
    expect(entryOverlay(service, overlay)).toBeNull();
  });

  it('merges an aggregate’s members’ items', () => {
    const clean = Array.from({ length: 6 }, (_, i) => entity({ key: `T${i}`, name: `T${i}`, order: 10 + i }));
    const view = buildExportMappingView(buildExportMappingRows(clean), 2);
    const aggregate = view.entries.find((entry) => entry.kind === 'aggregate')!;
    const merged = entryOverlay(aggregate, buildFidelityOverlay(report([item('T1', 'ok'), item('T4', 'synth')]), clean))!;
    expect(merged.items).toHaveLength(2);
    expect(merged.kind).toBe('synth');
  });
});

describe('overlayAriaLabel', () => {
  it('appends the report’s counts to the graph’s own name', () => {
    const view = buildExportMappingView(buildExportMappingRows(ENTITIES));
    const overlay = buildFidelityOverlay(report(), ENTITIES);
    const id = view.entries.find((entry) => (entry.row as { entity?: ExportManifestEntity })?.entity?.key === 'Pet.id')!;
    expect(overlayAriaLabel(id, entryOverlay(id, overlay))).toBe(
      `${entryAriaLabel(id)}; fidelity report: 2 APPROX, 1 SYNTH`,
    );
    const service = view.entries.find((entry) => (entry.row as { entity?: ExportManifestEntity })?.entity?.key === 'default')!;
    expect(overlayAriaLabel(service, null)).toBe(`${entryAriaLabel(service)}; fidelity report: no finding`);
  });

  it('prints counts worst kind first and skips zeroes', () => {
    expect(overlayCountsSentence({ drop: 1, approx: 0, synth: 3, ok: 2 })).toBe('1 DROP, 3 SYNTH, 2 OK');
    expect(overlayCountsSentence({ drop: 0, approx: 0, synth: 0, ok: 0 })).toBe('');
  });
});

// ---------------------------------------------------------------------------
// 2. Counts match the report
// ---------------------------------------------------------------------------

describe('reconcileOverlayCounts', () => {
  it('matches the report exactly, splitting placed and unplaced', () => {
    const r = reconcileOverlayCounts(buildFidelityOverlay(report(), ENTITIES));
    expect(r).toEqual({ matches: true, mismatches: [], placed: 7, unplaced: 1 });
  });

  it('every item is accounted for, whatever is loaded', () => {
    const r = reconcileOverlayCounts(buildFidelityOverlay(report(), []));
    expect(r.placed).toBe(0);
    expect(r.unplaced).toBe(ITEMS.length);
    expect(r.matches).toBe(true);
  });

  it('names a kind whose items disagree with the report', () => {
    const r = reconcileOverlayCounts(buildFidelityOverlay(report(ITEMS, { drop: 1, approx: 9, synth: 2, ok: 2 }), ENTITIES));
    expect(r.matches).toBe(false);
    expect(r.mismatches).toEqual([{ kind: 'approx', counted: 3, reported: 9 }]);
  });
});

// ---------------------------------------------------------------------------
// 3. Filter
// ---------------------------------------------------------------------------

describe('kind filter', () => {
  const all = new Set(LOSS_KINDS);
  const overlay = buildFidelityOverlay(report(), ENTITIES);

  it('is off with every kind active, and shows every node', () => {
    expect(isFilterOff(all)).toBe(true);
    expect(overlayMatchesFilter(null, all)).toBe(true);
  });

  it('isolates a kind: only nodes with an item of that kind match', () => {
    const drop = new Set<LossinessKind>(['drop']);
    const matching = [...overlay.byEntityKey.entries()]
      .filter(([, node]) => overlayMatchesFilter(node, drop))
      .map(([key]) => key);
    expect(matching).toEqual(['Pet.links']);
    expect(overlayMatchesFilter(null, drop)).toBe(false);
  });

  it('matches on any of a node’s items, not only its worst', () => {
    const synth = new Set<LossinessKind>(['synth']);
    expect(overlayMatchesFilter(overlay.byEntityKey.get('Pet.id')!, synth)).toBe(true);
  });

  it('toggles kinds, never emptying the filter', () => {
    let active = toggleKind(all, 'ok');
    expect([...active].sort()).toEqual(['approx', 'drop', 'synth']);
    active = toggleKind(active, 'ok');
    expect(isFilterOff(active)).toBe(true);
    expect([...toggleKind(new Set<LossinessKind>(['drop']), 'drop')]).toEqual(['drop']);
  });

  it('isolates a kind, and isolating it again shows all', () => {
    expect([...isolateKind(all, 'approx')]).toEqual(['approx']);
    expect(isFilterOff(isolateKind(new Set<LossinessKind>(['approx']), 'approx'))).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 4. Treemap
// ---------------------------------------------------------------------------

describe('constructRoot', () => {
  const byKey = new Map(ENTITIES.map((e) => [e.key, e] as const));

  it('walks a loaded entity up to its top ancestor', () => {
    expect(constructRoot('Pet.id', byKey)).toBe('Pet');
    expect(constructRoot('GET /pets', byKey)).toBe('default');
  });

  it('falls back to the key up to its first dot, or the whole key', () => {
    expect(constructRoot('Owner.email', byKey)).toBe('Owner');
    expect(constructRoot('POST /orders', byKey)).toBe('POST /orders');
  });

  it('survives a parent cycle', () => {
    const cyclic = new Map([
      ['A', entity({ key: 'A', parent_key: 'B' })],
      ['B', entity({ key: 'B', parent_key: 'A' })],
    ]);
    expect(['A', 'B']).toContain(constructRoot('A', cyclic));
  });
});

describe('buildConstructTreemap', () => {
  const all = new Set(LOSS_KINDS);

  it('groups by construct path, one tile per construct, every item kept', () => {
    const groups = buildConstructTreemap(report(), ENTITIES, all);
    const tiles = groups.flatMap((group) => group.tiles);
    expect(tiles.reduce((sum, tile) => sum + tile.size, 0)).toBe(ITEMS.length);
    const pet = groups.find((group) => group.key === 'Pet')!;
    expect(pet.tiles.map((tile) => tile.label)).toEqual(['links', 'id', 'name', 'Pet']);
    expect(pet.kind).toBe('drop');
    expect(pet.size).toBe(6);
    expect(pet.tiles.find((tile) => tile.label === 'id')!.entity?.key).toBe('Pet.id');
    expect(groups.find((group) => group.key === 'Owner')!.tiles[0].entity).toBeNull();
  });

  it('orders groups worst kind first', () => {
    const groups = buildConstructTreemap(report(), ENTITIES, all);
    expect(groups.map((group) => group.key)).toEqual(['Pet', 'Owner', 'default']);
  });

  it('keeps only the items of the active kinds', () => {
    const groups = buildConstructTreemap(report(), ENTITIES, new Set<LossinessKind>(['synth']));
    const tiles = groups.flatMap((group) => group.tiles);
    expect(tiles.map((tile) => tile.construct).sort()).toEqual(['Pet.id', 'Pet.name']);
    expect(tiles.every((tile) => tile.items.every((i) => i.kind === 'synth'))).toBe(true);
    expect(tiles.find((tile) => tile.construct === 'Pet.id')!.kind).toBe('synth');
  });
});

describe('squarify', () => {
  const area = (r: { width: number; height: number }) => r.width * r.height;

  it('fills the rectangle with areas proportional to the weights', () => {
    const rects = squarify([6, 6, 4, 3, 2, 2, 1], { x: 0, y: 0, width: 600, height: 400 });
    const total = rects.reduce((sum, r) => sum + area(r), 0);
    expect(total).toBeCloseTo(240000, 3);
    rects.forEach((r, i) => expect(area(r)).toBeCloseTo(([6, 6, 4, 3, 2, 2, 1][i] / 24) * 240000, 3));
    for (const r of rects) {
      expect(r.x).toBeGreaterThanOrEqual(-1e-9);
      expect(r.y).toBeGreaterThanOrEqual(-1e-9);
      expect(r.x + r.width).toBeLessThanOrEqual(600 + 1e-6);
      expect(r.y + r.height).toBeLessThanOrEqual(400 + 1e-6);
    }
  });

  it('keeps tiles near-square', () => {
    const rects = squarify([1, 1, 1, 1], { x: 0, y: 0, width: 200, height: 200 });
    for (const r of rects) expect(Math.max(r.width / r.height, r.height / r.width)).toBeLessThanOrEqual(1.0001);
  });

  it('is deterministic and handles empty and degenerate input', () => {
    const rect = { x: 0, y: 0, width: 300, height: 100 };
    expect(squarify([3, 2, 1], rect)).toEqual(squarify([3, 2, 1], rect));
    expect(squarify([], rect)).toEqual([]);
    expect(squarify([0, 0], rect).every((r) => r.width === 0 && r.height === 0)).toBe(true);
    expect(squarify([1], { x: 0, y: 0, width: 0, height: 10 })[0].width).toBe(0);
  });
});

describe('layoutConstructTreemap', () => {
  it('places every tile inside its group frame', () => {
    const groups = buildConstructTreemap(report(), ENTITIES, new Set(LOSS_KINDS));
    const layout = layoutConstructTreemap(groups, 720, 320);
    expect(layout.tiles).toHaveLength(groups.reduce((sum, g) => sum + g.tiles.length, 0));
    for (const placed of layout.tiles) {
      const frame = layout.groups.find((g) => g.group.key === placed.group)!.rect;
      expect(placed.rect.x).toBeGreaterThanOrEqual(frame.x - 1e-6);
      expect(placed.rect.y).toBeGreaterThanOrEqual(frame.y - 1e-6);
      expect(placed.rect.x + placed.rect.width).toBeLessThanOrEqual(frame.x + frame.width + 1e-6);
      expect(placed.rect.y + placed.rect.height).toBeLessThanOrEqual(frame.y + frame.height + 1e-6);
    }
  });
});
