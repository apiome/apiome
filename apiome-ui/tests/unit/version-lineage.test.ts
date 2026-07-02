import { describe, test, expect } from '@jest/globals';
import {
  buildLineageSnippet,
  buildPrimaryAncestors,
  branchNamesForTip,
  type VersionLineageInput,
} from '../../src/app/ade/dashboard/versions/version-lineage';

describe('version-lineage', () => {
  const linear: VersionLineageInput[] = [
    { id: 'a', version_id: '0.1.0', parent_version_id: null, merge_parent_version_id: null },
    { id: 'b', version_id: '0.2.0', parent_version_id: 'a', merge_parent_version_id: null },
    { id: 'c', version_id: '1.0.0', parent_version_id: 'b', merge_parent_version_id: null },
  ];

  test('buildPrimaryAncestors walks primary parent from tip', () => {
    const chain = buildPrimaryAncestors('c', linear);
    expect(chain.map((x) => x.version_id)).toEqual(['1.0.0', '0.2.0', '0.1.0']);
  });

  test('buildLineageSnippet breadcrumb is root to tip', () => {
    const sn = buildLineageSnippet('c', linear);
    expect(sn?.breadcrumbLabels).toEqual(['v0.1.0', 'v0.2.0', 'v1.0.0']);
    expect(sn?.asciiLines.length).toBeGreaterThan(0);
  });

  test('buildLineageSnippet surfaces merge parent on tip', () => {
    const merged: VersionLineageInput[] = [
      { id: 'a', version_id: '0.1.0', parent_version_id: null, merge_parent_version_id: null },
      { id: 'b', version_id: '0.2.0', parent_version_id: 'a', merge_parent_version_id: null },
      { id: 'm', version_id: '0.2.1', parent_version_id: 'a', merge_parent_version_id: null },
      { id: 'c', version_id: '1.0.0', parent_version_id: 'b', merge_parent_version_id: 'm' },
    ];
    const sn = buildLineageSnippet('c', merged);
    expect(sn?.mergeParentLabel).toBe('v0.2.1');
    expect(sn?.screenSummary).toContain('Merge parent');
  });

  test('branchNamesForTip collects branch names', () => {
    const names = branchNamesForTip('tip-1', [
      { name: 'main', tip_version_id: 'tip-1' },
      { name: 'release', tip_version_id: 'tip-2' },
    ]);
    expect(names).toEqual(['main']);
  });
});
