/**
 * A catalog item with no captured source, in the Export studio and the shared helpers (E1-6, #6221).
 *
 * The dialog's notice is pinned in `ExportDialog.test.tsx` and the Catalog's `?open=import-catalog`
 * landing in `catalog-hive-redesign.test.tsx`; this file covers the studio, the notice's copy and
 * the BFF's `restErrorCode` helper.
 */

import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

jest.mock('@monaco-editor/react', () => ({ __esModule: true, default: () => null }));

import { ExportStudio } from '../src/app/components/ade/dashboard/export/ExportStudio';
import {
  MissingSourceNotice,
  REIMPORT_HREF,
  isMissingSourceCode,
} from '../src/app/components/ade/dashboard/export/MissingSourceNotice';
import { __resetExportJobTrackerForTests } from '../src/app/components/ade/dashboard/export/exportJobTracker';
import { restErrorCode } from '../lib/rest-error-message';

beforeEach(() => {
  __resetExportJobTrackerForTests();
  window.sessionStorage.clear();
});

describe('helpers', () => {
  it('knows the two missing-source codes', () => {
    expect(isMissingSourceCode('source-not-captured')).toBe(true);
    expect(isMissingSourceCode('source-withheld')).toBe(true);
    expect(isMissingSourceCode('UNSUPPORTED_TARGET')).toBe(false);
    expect(isMissingSourceCode(null)).toBe(false);
  });

  it('reads the code of a typed REST refusal only', () => {
    expect(restErrorCode({ code: 'source-not-captured', message: 'x' })).toBe('source-not-captured');
    expect(restErrorCode('plain message')).toBeNull();
    expect(restErrorCode([{ msg: 'field required' }])).toBeNull();
    expect(restErrorCode({ message: 'no code' })).toBeNull();
    expect(restErrorCode(undefined)).toBeNull();
  });

  it('names a generic item when no label is known', () => {
    render(<MissingSourceNotice code="source-not-captured" />);
    expect(screen.getByTestId('export-missing-source')).toHaveTextContent("This item can't be exported");
    expect(screen.getByTestId('export-missing-source-reimport')).toHaveAttribute('href', REIMPORT_HREF);
  });
});

describe('Export studio', () => {
  it('shows the missing-source notice with Re-import, not the generic source error', async () => {
    global.fetch = jest.fn((input: unknown) =>
      String(input).includes('/api/export/targets')
        ? Promise.resolve({
            ok: false,
            status: 422,
            json: () => Promise.resolve({ success: false, error: 'No captured source.', code: 'source-not-captured' }),
          })
        : Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ success: false }) }),
    ) as unknown as typeof fetch;
    render(<ExportStudio artifact="item-1" artifactLabel="Orders RPC" version={null} />);
    const notice = await screen.findByTestId('export-missing-source');
    expect(notice).toHaveTextContent("Orders RPC can't be exported");
    expect(screen.queryByTestId('export-studio-error')).not.toBeInTheDocument();
  });
});
