import { describe, test, expect } from '@jest/globals';
import {
  expandVersionsForWindow,
  buildHistoryEdges,
  buildLayoutedHistoryGraph,
  filterVersionsBySelectedBranches,
  MAX_HISTORY_GRAPH_NODES,
  type VersionHistoryVertex,
} from '../../src/app/ade/dashboard/versions/version-history-dag';

describe('version-history-dag', () => {
  const linear: VersionHistoryVertex[] = [
    { id: 'a', version_id: '0.1.0', parent_version_id: null, merge_parent_version_id: null, created_at: '2024-01-01T00:00:00Z' },
    { id: 'b', version_id: '0.2.0', parent_version_id: 'a', merge_parent_version_id: null, created_at: '2024-02-01T00:00:00Z' },
    { id: 'c', version_id: '1.0.0', parent_version_id: 'b', merge_parent_version_id: null, created_at: '2024-03-01T00:00:00Z' },
  ];

  test('expandVersionsForWindow pulls in primary ancestors', () => {
    const sub = expandVersionsForWindow(linear, 1, MAX_HISTORY_GRAPH_NODES);
    expect(sub.map((x) => x.id).sort()).toEqual(['a', 'b', 'c']);
  });

  test('expandVersionsForWindow includes merge parent chain', () => {
    const merged: VersionHistoryVertex[] = [
      { id: 'a', version_id: '0.1.0', parent_version_id: null, merge_parent_version_id: null, created_at: '2024-01-01T00:00:00Z' },
      { id: 'b', version_id: '0.2.0', parent_version_id: 'a', merge_parent_version_id: null, created_at: '2024-02-01T00:00:00Z' },
      { id: 'm', version_id: '0.2.1', parent_version_id: 'a', merge_parent_version_id: null, created_at: '2024-02-05T00:00:00Z' },
      { id: 'c', version_id: '1.0.0', parent_version_id: 'b', merge_parent_version_id: 'm', created_at: '2024-03-01T00:00:00Z' },
    ];
    const sub = expandVersionsForWindow(merged, 1, MAX_HISTORY_GRAPH_NODES);
    expect(sub.map((x) => x.id).sort()).toEqual(['a', 'b', 'c', 'm']);
  });

  test('buildHistoryEdges has primary and merge edges for merge commit', () => {
    const merged: VersionHistoryVertex[] = [
      { id: 'a', version_id: '0.1.0', parent_version_id: null, merge_parent_version_id: null },
      { id: 'b', version_id: '0.2.0', parent_version_id: 'a', merge_parent_version_id: null },
      { id: 'm', version_id: '0.2.1', parent_version_id: 'a', merge_parent_version_id: null },
      { id: 'c', version_id: '1.0.0', parent_version_id: 'b', merge_parent_version_id: 'm' },
    ];
    const edges = buildHistoryEdges(merged);
    expect(edges.some((e) => e.source === 'b' && e.target === 'c')).toBe(true);
    expect(edges.some((e) => e.source === 'm' && e.target === 'c')).toBe(true);
    const mergeEdge = edges.find((e) => e.source === 'm' && e.target === 'c');
    expect(mergeEdge?.style?.strokeDasharray).toBeDefined();
  });

  test('expandVersionsForWindow respects maxTotal hard cap even when windowSize exceeds it', () => {
    // Create 10 linearly chained vertices
    const many: VersionHistoryVertex[] = Array.from({ length: 10 }, (_, i) => ({
      id: `v${i}`,
      version_id: `0.${i}.0`,
      parent_version_id: i > 0 ? `v${i - 1}` : null,
      merge_parent_version_id: null,
      created_at: `2024-01-${String(i + 1).padStart(2, '0')}T00:00:00Z`,
    }));
    // windowSize (20) > list length (10) > maxTotal (3) — hard cap must win
    const result = expandVersionsForWindow(many, 20, 3);
    expect(result.length).toBeLessThanOrEqual(3);
  });

  test('buildLayoutedHistoryGraph returns nodes and edges', () => {
    const { nodes, edges } = buildLayoutedHistoryGraph(linear);
    expect(nodes.length).toBe(3);
    expect(edges.length).toBeGreaterThanOrEqual(2);
    expect(nodes[0].position).toBeDefined();
    expect(nodes[0].data.layoutDirection).toBe('LR');
  });

  test('filterVersionsBySelectedBranches keeps ancestor union for selected branch tips', () => {
    const merged: VersionHistoryVertex[] = [
      { id: 'a', version_id: '0.1.0', parent_version_id: null, merge_parent_version_id: null },
      { id: 'b', version_id: '0.2.0', parent_version_id: 'a', merge_parent_version_id: null },
      { id: 'm', version_id: '0.2.1', parent_version_id: 'a', merge_parent_version_id: null },
      { id: 'c', version_id: '1.0.0', parent_version_id: 'b', merge_parent_version_id: 'm' },
    ];
    const branches = [
      { id: 'br-main', name: 'main', tip_version_id: 'c' },
      { id: 'br-side', name: 'side', tip_version_id: 'm' },
    ];
    const onlyMain = filterVersionsBySelectedBranches(merged, branches, ['br-main']);
    expect(onlyMain.map((x) => x.id).sort()).toEqual(['a', 'b', 'c', 'm']);
    const onlySide = filterVersionsBySelectedBranches(merged, branches, ['br-side']);
    expect(onlySide.map((x) => x.id).sort()).toEqual(['a', 'm']);
  });

  test('buildLayoutedHistoryGraph marks branch tips from branch metadata', () => {
    const linear: VersionHistoryVertex[] = [
      { id: 'a', version_id: '0.1.0', parent_version_id: null, merge_parent_version_id: null },
      { id: 'b', version_id: '0.2.0', parent_version_id: 'a', merge_parent_version_id: null },
    ];
    const { nodes } = buildLayoutedHistoryGraph(linear, {
      branches: [{ id: 'x', name: 'main', tip_version_id: 'b' }],
    });
    const tip = nodes.find((n) => n.id === 'b');
    expect(tip?.data.isBranchTip).toBe(true);
    expect(tip?.data.branchNamesForTip).toContain('main');
    const root = nodes.find((n) => n.id === 'a');
    expect(root?.data.isBranchTip).toBe(false);
  });
});
