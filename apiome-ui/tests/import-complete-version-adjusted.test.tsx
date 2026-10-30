/**
 * Import Done step: the sub-version an import was added as (#590).
 *
 * When the importer had to replace a taken version label with a sub-version, the Done panel names the
 * label used and the one that was taken. An import at a free label shows no such row.
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

describe('import Done: adjusted version (#590)', () => {
  it('names the sub-version used and the label that was taken', async () => {
    getImportStatus.mockResolvedValue(completed({ versionLabelAdjusted: { requested: '1.0.0', used: '1.0.0b' } }));
    render(<ImportCompletePanel jobId="job-1" />);
    await waitFor(() =>
      expect(screen.getByTestId('import-complete-version-adjusted')).toHaveTextContent('1.0.0b (1.0.0 was taken)'),
    );
  });

  it('shows nothing extra when the version was free', async () => {
    getImportStatus.mockResolvedValue(completed());
    render(<ImportCompletePanel jobId="job-2" />);
    await screen.findByText(/Shop/);
    expect(screen.queryByTestId('import-complete-version-adjusted')).not.toBeInTheDocument();
  });
});
