/**
 * exportJobTracker — the background export-job lifecycle: submit/poll, sessionStorage persistence,
 * resume, background-completion toast, retry, and cancel (MFX-46.2, #4380).
 */

import { jest } from '@jest/globals';

jest.mock('sonner', () => ({
  __esModule: true,
  toast: Object.assign(jest.fn(), { success: jest.fn(), error: jest.fn() }),
}));

import { toast } from 'sonner';
import {
  __resetExportJobTrackerForTests,
  cancelExportJob,
  exportJobScopeKey,
  getExportJob,
  retryExportJob,
  startExportJob,
  subscribeExportJob,
  type ExportJobSubmitParams,
} from '../src/app/components/ade/dashboard/export/exportJobTracker';

const PARAMS: ExportJobSubmitParams = {
  artifact: 'proj-1',
  version: 'rev-1',
  target: 'openapi',
  targetLabel: 'OpenAPI 3.1',
  options: null,
  confirm: false,
  acknowledgedSnapshot: 'abc123snapshot',
};

/** A completed-job GET status payload. */
const COMPLETED = {
  success: true,
  job_id: 'job-1',
  state: 'completed',
  percent: 100,
  events: [],
  result: { artifact: 'proj-1', version_record_id: 'rev-1', target: 'openapi', dry_run: false, files: [] },
};

/** Install a fetch mock: POST submit → 202, GET status → the given terminal payload. */
function installFetch(status: Record<string, unknown> = COMPLETED, jobStatusCode = 200): jest.Mock {
  const mock = jest.fn((input: unknown, init?: { method?: string }) => {
    const url = String(input);
    if (url.endsWith('/api/export/jobs') && init?.method === 'POST') {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, job_id: 'job-1', status_path: '/api/export/jobs/job-1' }),
      });
    }
    if (url.includes('/api/export/jobs/') && init?.method === 'DELETE') {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ success: true }) });
    }
    if (url.includes('/api/export/jobs/')) {
      return Promise.resolve({
        ok: jobStatusCode >= 200 && jobStatusCode < 300,
        status: jobStatusCode,
        json: () => Promise.resolve(status),
      });
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
  }) as unknown as jest.Mock;
  global.fetch = mock as unknown as typeof fetch;
  return mock;
}

/** Wait until the tracked job for a scope satisfies a predicate (the poll settles async). */
async function waitForJob(scopeKey: string, predicate: (state: string | null) => boolean) {
  for (let i = 0; i < 50; i += 1) {
    if (predicate(getExportJob(scopeKey)?.status.state ?? null)) return;
    await new Promise((r) => setTimeout(r, 5));
  }
  throw new Error(`job did not reach the expected state; last=${getExportJob(scopeKey)?.status.state}`);
}

beforeEach(() => {
  __resetExportJobTrackerForTests();
  window.sessionStorage.clear();
  (toast as unknown as jest.Mock).mockClear();
  (toast.success as jest.Mock).mockClear();
  (toast.error as jest.Mock).mockClear();
});

afterEach(() => {
  __resetExportJobTrackerForTests();
});

describe('exportJobTracker — submit + poll', () => {
  it('submits a job and polls it to completion, notifying subscribers', async () => {
    installFetch();
    const scopeKey = exportJobScopeKey('proj-1', 'rev-1');
    const changes: string[] = [];
    subscribeExportJob(scopeKey, () => changes.push(getExportJob(scopeKey)?.status.state ?? '—'));

    await startExportJob(PARAMS);
    await waitForJob(scopeKey, (s) => s === 'completed');

    expect(getExportJob(scopeKey)?.status.state).toBe('completed');
    expect(changes).toContain('completed');
    // A subscriber is attached (Studio on screen), so no background toast fires.
    expect(toast.success).not.toHaveBeenCalled();
  });

  it('includes acknowledged_snapshot in the submit payload (EFP-3.1)', async () => {
    const mock = installFetch();
    await startExportJob(PARAMS);
    const submit = mock.mock.calls.find(
      ([url, init]) => String(url).endsWith('/api/export/jobs') && init?.method === 'POST',
    );
    expect(submit).toBeTruthy();
    const body = JSON.parse((submit![1] as { body: string }).body);
    expect(body.acknowledged_snapshot).toBe('abc123snapshot');
  });

  it('toasts on background completion when no subscriber is attached', async () => {
    installFetch();
    const scopeKey = exportJobScopeKey('proj-1', 'rev-1');
    await startExportJob(PARAMS);
    await waitForJob(scopeKey, (s) => s === 'completed');
    expect(toast.success).toHaveBeenCalledTimes(1);
  });

  it('surfaces a lost job (404 after a process restart) as a failure', async () => {
    installFetch(COMPLETED, 404);
    const scopeKey = exportJobScopeKey('proj-1', 'rev-1');
    await startExportJob(PARAMS);
    await waitForJob(scopeKey, (s) => s === 'failed');
    expect(getExportJob(scopeKey)?.status.error?.code).toBe('JOB_LOST');
  });
});

describe('exportJobTracker — persistence + resume', () => {
  it('persists the job to sessionStorage and resumes it on the next rehydrate', async () => {
    installFetch();
    const scopeKey = exportJobScopeKey('proj-1', 'rev-1');
    await startExportJob(PARAMS);
    await waitForJob(scopeKey, (s) => s === 'completed');

    // A raw entry is persisted so a full reload can restore it.
    const raw = window.sessionStorage.getItem('apiome:export-jobs');
    expect(raw).toContain('job-1');

    // Simulate a reload: drop in-memory state (keeping storage) and re-subscribe → rehydrate.
    __resetExportJobTrackerForTests();
    subscribeExportJob(scopeKey, () => undefined);
    expect(getExportJob(scopeKey)?.jobId).toBe('job-1');
    expect(getExportJob(scopeKey)?.status.state).toBe('completed');
  });
});

describe('exportJobTracker — retry + cancel', () => {
  it('retry re-submits with the same config plus any overrides', async () => {
    const mock = installFetch();
    const scopeKey = exportJobScopeKey('proj-1', 'rev-1');
    await startExportJob(PARAMS);
    await waitForJob(scopeKey, (s) => s === 'completed');

    await retryExportJob(scopeKey, { confirm: true });
    const submits = mock.mock.calls.filter(
      ([url, init]) => String(url).endsWith('/api/export/jobs') && (init as { method?: string })?.method === 'POST',
    );
    expect(submits.length).toBe(2);
    expect(JSON.parse((submits[1][1] as { body: string }).body).confirm).toBe(true);
  });

  it('cancel issues a DELETE for the job', async () => {
    const mock = installFetch();
    const scopeKey = exportJobScopeKey('proj-1', 'rev-1');
    await startExportJob(PARAMS);
    await cancelExportJob(scopeKey);
    const deletes = mock.mock.calls.filter(
      ([, init]) => (init as { method?: string } | undefined)?.method === 'DELETE',
    );
    expect(deletes.length).toBe(1);
  });
});
