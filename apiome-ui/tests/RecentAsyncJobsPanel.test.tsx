/**
 * RecentAsyncJobsPanel — paginated job list consumer (IXH-6.3, #5122).
 */

import React from 'react';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { RecentAsyncJobsPanel } from '../src/app/components/ade/dashboard/asyncJobs/RecentAsyncJobsPanel';

describe('RecentAsyncJobsPanel', () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    jest.restoreAllMocks();
  });

  it('fetches a bounded page from /api/export/jobs and renders rows', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        jobs: [
          { job_id: 'j1', state: 'completed', percent: 100, target: 'openapi', artifact: 'p1' },
        ],
        total: 1,
        limit: 10,
        offset: 0,
        has_more: false,
        next_cursor: null,
      }),
    }) as unknown as typeof fetch;

    render(<RecentAsyncJobsPanel kind="export" limit={10} />);

    await waitFor(() => {
      expect(screen.getByTestId('export-recent-jobs')).toBeInTheDocument();
      expect(screen.getByText('j1')).toBeInTheDocument();
      expect(screen.getByText('completed')).toBeInTheDocument();
    });

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/export/jobs?limit=10&include_total=true',
      expect.objectContaining({ cache: 'no-store' }),
    );
    expect(screen.getByTestId('export-recent-jobs-pagination-summary')).toHaveTextContent(
      '1–1 of 1',
    );
    // One page: nowhere to go.
    expect(screen.getByTestId('export-recent-jobs-next-page')).toBeDisabled();
    expect(screen.getByTestId('export-recent-jobs-prev-page')).toBeDisabled();
  });

  it('pages via Next and Previous by cursor, counting only on the first page (#7196)', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          jobs: [{ job_id: 'j1', state: 'completed', percent: 100 }],
          total: 12,
          limit: 10,
          offset: 0,
          has_more: true,
          next_cursor: 'after-j10',
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          jobs: [{ job_id: 'j11', state: 'failed', percent: 40 }],
          total: null,
          limit: 10,
          offset: 0,
          has_more: false,
          next_cursor: null,
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          jobs: [{ job_id: 'j1', state: 'completed', percent: 100 }],
          total: 12,
          limit: 10,
          offset: 0,
          has_more: true,
          next_cursor: 'after-j10',
        }),
      });
    global.fetch = fetchMock as unknown as typeof fetch;

    render(<RecentAsyncJobsPanel kind="import" limit={10} />);

    await waitFor(() => expect(screen.getByText('j1')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('import-recent-jobs-next-page'));
    await waitFor(() => expect(screen.getByText('j11')).toBeInTheDocument());
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/catalog/import?limit=10&cursor=after-j10',
      expect.anything(),
    );
    // The count came with the first page and is kept; the last page offers no Next.
    expect(screen.getByTestId('import-recent-jobs-pagination-summary')).toHaveTextContent(
      'Showing 11–11 of 12 jobs',
    );
    expect(screen.getByTestId('import-recent-jobs-next-page')).toBeDisabled();

    fireEvent.click(screen.getByTestId('import-recent-jobs-prev-page'));
    await waitFor(() => expect(screen.getByText('j1')).toBeInTheDocument());
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/catalog/import?limit=10&include_total=true',
      expect.anything(),
    );
  });

  it('pages on has_more alone and shows no count when the server gives none', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        jobs: [{ job_id: 'j1', state: 'completed', percent: 100 }],
        total: null,
        has_more: true,
        next_cursor: 'after-j1',
      }),
    }) as unknown as typeof fetch;
    render(<RecentAsyncJobsPanel kind="export" limit={10} />);
    await waitFor(() => expect(screen.getByText('j1')).toBeInTheDocument());
    expect(screen.getByTestId('export-recent-jobs-pagination-summary')).toHaveTextContent(/^Showing 1–1$/);
    expect(screen.getByTestId('export-recent-jobs-next-page')).not.toBeDisabled();
  });

  it('falls back to offset paging for an answer with a total and no has_more', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        jobs: [{ job_id: 'j1', state: 'completed', percent: 100 }],
        total: 12,
      }),
    });
    global.fetch = fetchMock as unknown as typeof fetch;
    render(<RecentAsyncJobsPanel kind="export" limit={10} />);
    await waitFor(() => expect(screen.getByText('j1')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('export-recent-jobs-next-page'));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith('/api/export/jobs?limit=10&offset=10', expect.anything()),
    );
  });

  it('skeletons the table while the first page is pending (RC6-H3, #6210)', async () => {
    global.fetch = jest.fn(() => new Promise(() => {})) as unknown as typeof fetch;
    render(<RecentAsyncJobsPanel kind="import" limit={10} />);
    expect(await screen.findByText('Loading import jobs…')).toBeInTheDocument();
  });

  it('says a failed read failed, with a retry that reads again (RC6-H3, #6210)', async () => {
    let fail = true;
    global.fetch = jest.fn(async () =>
      fail
        ? { ok: false, status: 503, json: async () => ({ success: false, error: 'Job store unavailable' }) }
        : { ok: true, json: async () => ({ success: true, jobs: [{ job_id: 'j9', state: 'completed', percent: 100 }], total: 1, limit: 10, offset: 0 }) }
    ) as unknown as typeof fetch;
    render(<RecentAsyncJobsPanel kind="import" limit={10} />);
    expect(await screen.findByTestId('import-recent-jobs-error')).toHaveTextContent('Job store unavailable');
    fail = false;
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByText('j9')).toBeInTheDocument();
  });
});
