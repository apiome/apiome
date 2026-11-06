/**
 * The Versions screen sorts by version number by default, and marks the highest version
 * "(latest)" — across the whole project, in the table and the timeline alike.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { projectLatestRevisionId, compareVersionsDashboardRows } from '../src/app/utils/versions-dashboard-sort';
import { DEFAULT_VERSIONS_SORT } from '../src/app/components/ade/versions/versionsModel';
import { VersionCell } from '../src/app/components/ade/versions/VersionsTable';
import type { Version } from '../src/app/components/ade/versions/versionsModel';

/** A revision row with just what these tests read. */
function row(id: string, version_id: string, created_at: string) {
  return {
    id,
    version_id,
    created_at,
    project_id: 'p1',
    published: false,
    enabled: true,
    lifecycle: 'stable',
  } as unknown as Version;
}

describe('projectLatestRevisionId', () => {
  it('picks the highest version number, compared numerically', () => {
    const versions = [
      row('a', '1.9.0', '2026-11-03T00:00:00Z'),
      row('b', '1.10.0', '2026-10-01T00:00:00Z'),
      row('c', '1.2.0', '2026-11-05T00:00:00Z'),
    ];
    expect(projectLatestRevisionId(versions)).toBe('b');
  });

  it('ignores creation order: an older but higher version is still the latest', () => {
    const versions = [row('new', '1.0.1', '2026-11-05T00:00:00Z'), row('old', '2.0.0', '2026-01-01T00:00:00Z')];
    expect(projectLatestRevisionId(versions)).toBe('old');
  });

  it('breaks a tie on the same version number with the newer revision', () => {
    const versions = [row('first', '3.0.0', '2026-01-01T00:00:00Z'), row('second', '3.0.0', '2026-02-01T00:00:00Z')];
    expect(projectLatestRevisionId(versions)).toBe('second');
  });

  it('returns null for a project with no revisions', () => {
    expect(projectLatestRevisionId([])).toBeNull();
  });

  it('puts the latest revision first under the default sort', () => {
    const versions = [
      row('a', '1.9.0', '2026-11-03T00:00:00Z'),
      row('b', '1.10.0', '2026-10-01T00:00:00Z'),
      row('c', '0.5.0', '2026-11-05T00:00:00Z'),
    ];
    const sorted = [...versions].sort((x, y) =>
      compareVersionsDashboardRows(x, y, 'version', DEFAULT_VERSIONS_SORT.direction as 'asc' | 'desc')
    );
    expect(sorted.map((v) => v.id)).toEqual(['b', 'a', 'c']);
    expect(sorted[0].id).toBe(projectLatestRevisionId(versions));
  });
});

describe('VersionCell', () => {
  it('says "(latest)" beside the highest version, and nowhere else', () => {
    const { rerender } = render(
      <VersionCell version={row('b', '1.10.0', '2026-10-01T00:00:00Z')} projectId="p1" isHead={false} isLatest tags={[]} onView={jest.fn()} />
    );
    expect(screen.getByTestId('versions-latest-b')).toHaveTextContent('(latest)');
    rerender(
      <VersionCell version={row('a', '1.9.0', '2026-11-03T00:00:00Z')} projectId="p1" isHead={false} tags={[]} onView={jest.fn()} />
    );
    expect(screen.queryByText('(latest)')).not.toBeInTheDocument();
  });
});
