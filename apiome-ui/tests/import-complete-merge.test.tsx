/**
 * Import Done step: the merge an import made (#591 additive, #592 override).
 *
 * When the import was merged into the project's latest version, the Done panel adds a **Merge** row
 * saying what was merged, added, updated and kept. An import without a merge shows no such row.
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { describe, expect, it, jest } from '@jest/globals';

const getImportStatus = jest.fn<(jobId: string) => Promise<unknown>>();

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }) }));
jest.mock('@lib/db/import-actions', () => ({
  getImportStatus: (jobId: string) => getImportStatus(jobId),
  rollbackCompletedImport: jest.fn(),
}));
jest.mock('@/app/components/ade/dashboard/SchemaVersionScoringPanel', () => ({
  SchemaVersionScoringPanel: () => null,
}));

import ImportCompletePanel from '@/app/components/ade/dashboard/ImportCompletePanel';

/**
 * A completed import's status.
 *
 * @param summary Extra summary fields.
 * @returns The status `getImportStatus` resolves to.
 */
function completed(summary: Record<string, unknown> = {}) {
  return {
    state: 'completed',
    result: { projectId: 'p-1', versionId: 'ver-1' },
    events: [],
    summary: { classesCreated: 1, propertiesCreated: 1, pathsImported: 0, warnings: 0, failed: 0, classes: [], projectName: 'Shop', ...summary },
  };
}

describe('import Done: merge (#591, #592)', () => {
  it('says what was merged, added and kept', async () => {
    getImportStatus.mockResolvedValue(
      completed({
        importMerge: {
          strategy: 'additive',
          schemasMerged: 2,
          propertiesAdded: 3,
          propertiesUpdated: 0,
          schemasCarried: 4,
          pathsCarried: 5,
          operationsAdded: 1,
          operationsUpdated: 0,
        },
      }),
    );
    render(<ImportCompletePanel jobId="job-1" />);
    await waitFor(() =>
      expect(screen.getByTestId('import-complete-merge')).toHaveTextContent(
        'Additive — 2 schemas merged (3 properties added), 1 operation added; 4 schemas and 5 paths kept from the latest version',
      ),
    );
    expect(screen.getByText('Merge')).toBeInTheDocument();
  });

  it('says what an override merge updated (#592)', async () => {
    getImportStatus.mockResolvedValue(
      completed({
        importMerge: {
          strategy: 'override',
          schemasMerged: 1,
          propertiesAdded: 0,
          propertiesUpdated: 2,
          schemasCarried: 1,
          pathsCarried: 0,
          operationsAdded: 0,
          operationsUpdated: 1,
        },
      }),
    );
    render(<ImportCompletePanel jobId="job-3" />);
    await waitFor(() =>
      expect(screen.getByTestId('import-complete-merge')).toHaveTextContent(
        'Override — 1 schema merged (0 properties added, 2 updated), 1 operation updated; 1 schema and 0 paths kept from the latest version',
      ),
    );
  });

  it('shows no merge row for an import that replaced the version', async () => {
    getImportStatus.mockResolvedValue(completed());
    render(<ImportCompletePanel jobId="job-2" />);
    await screen.findByText(/Shop/);
    expect(screen.queryByTestId('import-complete-merge')).not.toBeInTheDocument();
  });
});
