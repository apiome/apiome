/**
 * Import Done step: the additive merge an import made (#591).
 *
 * When the import was merged additively into the project's latest version, the Done panel adds a
 * **Merge** row saying what was merged, added and kept. An import without the merge shows no such row.
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

describe('import Done: additive merge (#591)', () => {
  it('says what was merged, added and kept', async () => {
    getImportStatus.mockResolvedValue(
      completed({
        additiveMerge: { schemasMerged: 2, propertiesAdded: 3, schemasCarried: 4, pathsCarried: 5, operationsAdded: 1 },
      }),
    );
    render(<ImportCompletePanel jobId="job-1" />);
    await waitFor(() =>
      expect(screen.getByTestId('import-complete-additive-merge')).toHaveTextContent(
        'Additive — 2 schemas merged (3 properties added), 1 operation added; 4 schemas and 5 paths kept from the latest version',
      ),
    );
    expect(screen.getByText('Merge')).toBeInTheDocument();
  });

  it('shows no merge row for an import that replaced the version', async () => {
    getImportStatus.mockResolvedValue(completed());
    render(<ImportCompletePanel jobId="job-2" />);
    await screen.findByText(/Shop/);
    expect(screen.queryByTestId('import-complete-additive-merge')).not.toBeInTheDocument();
  });
});
