/**
 * Change-report review, PDF export and the audit log in the browser (#2705): the review bar,
 * the Reject dialog, the audit dialog, and both wired into the Change report panel.
 */

import * as fs from 'fs';
import * as path from 'path';
import React from 'react';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockDownloadBlob = jest.fn();
jest.mock('../src/app/components/ade/dashboard/export/exportDownload', () => ({
  ...jest.requireActual('../src/app/components/ade/dashboard/export/exportDownload'),
  downloadBlob: (...args: unknown[]) => mockDownloadBlob(...args),
}));

// Radix Dialog / Select need a few browser APIs jsdom doesn't implement.
beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  if (!Element.prototype.hasPointerCapture) Element.prototype.hasPointerCapture = () => false;
  if (!Element.prototype.setPointerCapture) Element.prototype.setPointerCapture = () => {};
  if (!Element.prototype.releasePointerCapture) Element.prototype.releasePointerCapture = () => {};
  Element.prototype.scrollIntoView = () => {};
});

import {
  ChangeReportApprovalBar,
  ChangeReportAuditDialog,
  type ChangeReportApproval,
} from '../src/app/components/ade/versions/changeReport';
import { VersionChangeReportPanel } from '../src/app/ade/dashboard/versions/VersionChangeReportPanel';
import { Page, PageBody } from '../src/app/components/shell/pageChrome';

const PENDING: ChangeReportApproval = {
  approvalState: 'pending_review',
  submittedBy: 'user-a',
  submittedAt: '2026-11-13T12:05:00Z',
};
const APPROVED: ChangeReportApproval = {
  ...PENDING,
  approvalState: 'approved',
  approvedBy: 'admin-b',
  approvedAt: '2026-11-13T13:00:00Z',
};

interface Reply {
  ok?: boolean;
  body?: unknown;
  headers?: Record<string, string>;
  blob?: Blob;
}

/** `fetch` answering one reply for every call; calls are recorded for inspection. */
function mockFetch(reply: Reply) {
  const fetchMock = jest.fn(async () => ({
    ok: reply.ok ?? true,
    json: async () => reply.body ?? {},
    blob: async () => reply.blob ?? new Blob(['%PDF-1.3']),
    headers: { get: (name: string) => reply.headers?.[name.toLowerCase()] ?? null },
  }));
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

function renderBar(
  approval: ChangeReportApproval,
  viewer: { currentUserId?: string; canEdit?: boolean; isAdmin?: boolean } = {}
) {
  const onReportChange = jest.fn();
  const onExported = jest.fn();
  render(
    <ChangeReportApprovalBar
      projectId="p1"
      revisionId="v1"
      approval={approval}
      currentUserId={viewer.currentUserId ?? 'user-a'}
      canEdit={viewer.canEdit ?? true}
      isAdmin={viewer.isAdmin ?? false}
      onReportChange={onReportChange}
      onExported={onExported}
    />
  );
  return { onReportChange, onExported };
}

afterEach(() => {
  jest.restoreAllMocks();
  mockDownloadBlob.mockReset();
});

describe('the review bar', () => {
  it('shows a draft with Submit for review and Download PDF disabled with its reason', () => {
    renderBar({});

    expect(screen.getByTestId('change-report-approval-badge')).toHaveTextContent('Draft');
    expect(screen.getByTestId('change-report-approval-summary')).toHaveTextContent(
      'Not reviewed yet'
    );
    expect(screen.getByTestId('change-report-submit')).toBeEnabled();
    const download = screen.getByTestId('change-report-download-pdf');
    expect(download).toBeDisabled();
    expect(download).toHaveAttribute(
      'title',
      'Only an approved change report can be exported as PDF'
    );
    expect(screen.queryByTestId('change-report-approve')).not.toBeInTheDocument();
  });

  it('submits a draft and hands the answered report to the caller', async () => {
    const fetchMock = mockFetch({ body: { success: true, report: PENDING } });
    const { onReportChange } = renderBar({});

    fireEvent.click(screen.getByTestId('change-report-submit'));

    await waitFor(() => expect(onReportChange).toHaveBeenCalledWith(PENDING));
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/versions/v1/change-report/submit?projectId=p1');
    expect(init.method).toBe('POST');
    expect(init.body).toBeUndefined();
  });

  it('offers Approve and Reject on a pending report to an administrator', async () => {
    const fetchMock = mockFetch({ body: { success: true, report: APPROVED } });
    const { onReportChange } = renderBar(PENDING, { currentUserId: 'admin-b', isAdmin: true });

    expect(screen.getByTestId('change-report-approval-badge')).toHaveTextContent('Pending review');
    expect(screen.getByTestId('change-report-reject')).toBeEnabled();
    fireEvent.click(screen.getByTestId('change-report-approve'));

    await waitFor(() => expect(onReportChange).toHaveBeenCalledWith(APPROVED));
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toBe(
      '/api/versions/v1/change-report/approve?projectId=p1'
    );
  });

  it('keeps Approve disabled for the administrator who submitted the report', () => {
    renderBar({ ...PENDING, submittedBy: 'admin-b' }, { currentUserId: 'admin-b', isAdmin: true });

    const approve = screen.getByTestId('change-report-approve');
    expect(approve).toBeDisabled();
    expect(approve).toHaveAttribute('title', expect.stringContaining('other than its submitter'));
  });

  it('rejects with a note from the dialog', async () => {
    const draftAgain = { approvalState: 'draft', reviewNote: 'Name the removed field.' };
    const fetchMock = mockFetch({ body: { success: true, report: draftAgain } });
    const { onReportChange } = renderBar(PENDING, { currentUserId: 'admin-b', isAdmin: true });

    fireEvent.click(screen.getByTestId('change-report-reject'));
    const dialog = await screen.findByRole('dialog', { name: 'Reject change report' });
    fireEvent.change(within(dialog).getByLabelText('Note'), {
      target: { value: '  Name the removed field.  ' },
    });
    fireEvent.click(within(dialog).getByTestId('change-report-reject-confirm'));

    await waitFor(() => expect(onReportChange).toHaveBeenCalledWith(draftAgain));
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/versions/v1/change-report/reject?projectId=p1');
    expect(JSON.parse(init.body as string)).toEqual({ note: 'Name the removed field.' });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('blocks a note that is too long before anything is sent', async () => {
    const fetchMock = mockFetch({ body: {} });
    renderBar(PENDING, { currentUserId: 'admin-b', isAdmin: true });

    fireEvent.click(screen.getByTestId('change-report-reject'));
    fireEvent.change(await screen.findByTestId('change-report-reject-note'), {
      target: { value: 'x'.repeat(1001) },
    });

    expect(screen.getByText('Keep the note to 1000 characters or fewer.')).toBeInTheDocument();
    expect(screen.getByTestId('change-report-reject-confirm')).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('shows the reviewer’s note and the last export’s hash', () => {
    renderBar({
      approvalState: 'draft',
      reviewNote: 'Name the removed field.',
      lastPdfSha256: 'ab'.repeat(32),
      lastPdfExportedAt: '2026-11-13T14:00:00Z',
    });

    expect(screen.getByTestId('change-report-review-note')).toHaveTextContent(
      'Name the removed field.'
    );
    const exported = screen.getByTestId('change-report-last-export');
    expect(exported).toHaveTextContent('exported 2026-11-13 14:00 UTC');
    expect(within(exported).getByTitle('ab'.repeat(32))).toHaveTextContent('abababababab…');
  });

  it('downloads the PDF of an approved report under the server’s filename', async () => {
    const blob = new Blob(['%PDF-1.3']);
    const fetchMock = mockFetch({
      blob,
      headers: { 'content-disposition': 'attachment; filename="payments-1.1.0-change-report.pdf"' },
    });
    const { onExported } = renderBar(APPROVED, { canEdit: false });

    const download = screen.getByTestId('change-report-download-pdf');
    expect(download).toBeEnabled();
    fireEvent.click(download);

    await waitFor(() => expect(mockDownloadBlob).toHaveBeenCalled());
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toBe(
      '/api/versions/v1/change-report/pdf?projectId=p1'
    );
    expect(mockDownloadBlob).toHaveBeenCalledWith(blob, 'payments-1.1.0-change-report.pdf');
    expect(onExported).toHaveBeenCalled();
  });

  it('says why in place when the server refuses', async () => {
    mockFetch({
      ok: false,
      body: {
        success: false,
        error: "This tenant is not entitled to the 'change-report-enterprise' feature.",
      },
    });
    const { onReportChange } = renderBar({});

    fireEvent.click(screen.getByTestId('change-report-submit'));

    expect(await screen.findByTestId('change-report-approval-error')).toHaveTextContent(
      'not entitled'
    );
    expect(onReportChange).not.toHaveBeenCalled();
  });

  it('says why when the PDF cannot be exported, and downloads nothing', async () => {
    mockFetch({ ok: false, body: { success: false, error: 'The report is not approved' } });
    const { onExported } = renderBar(APPROVED);

    fireEvent.click(screen.getByTestId('change-report-download-pdf'));

    expect(await screen.findByTestId('change-report-approval-error')).toHaveTextContent(
      'not approved'
    );
    expect(mockDownloadBlob).not.toHaveBeenCalled();
    expect(onExported).not.toHaveBeenCalled();
  });
});

describe('the audit dialog', () => {
  const ENTRIES = [
    {
      id: 'e2',
      action: 'report.approve',
      actorId: 'admin-b-0000-0000',
      detail: { note: 'Checked.' },
      createdAt: '2026-11-13T13:00:00Z',
    },
    { id: 'e1', action: 'report.submit', actorId: null, detail: {}, createdAt: '2026-11-13T12:05:00Z' },
  ];

  it('lists this report’s entries, newest first, with their words', async () => {
    const fetchMock = mockFetch({
      body: { success: true, audit: { items: ENTRIES, limit: 25, nextCursor: null } },
    });
    render(<ChangeReportAuditDialog revisionId="v1" revisionLabel="v1.1.0" onClose={jest.fn()} />);

    const list = await screen.findByTestId('change-report-audit-list');
    const rows = within(list).getAllByRole('listitem');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('2026-11-13 13:00 UTC');
    expect(rows[0]).toHaveTextContent('Approved');
    expect(rows[0]).toHaveTextContent('Note: Checked.');
    expect(rows[0]).toHaveTextContent('admin-b-…');
    expect(rows[1]).toHaveTextContent('Submitted for review');
    expect(rows[1]).toHaveTextContent('system');
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toBe(
      '/api/change-report-audit?versionId=v1&limit=25'
    );
    expect(screen.queryByTestId('change-report-audit-more')).not.toBeInTheDocument();
  });

  it('reloads from the top when a filter changes', async () => {
    const fetchMock = mockFetch({
      body: { success: true, audit: { items: [], limit: 25, nextCursor: null } },
    });
    render(<ChangeReportAuditDialog revisionId="v1" revisionLabel="v1.1.0" onClose={jest.fn()} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    fireEvent.change(screen.getByTestId('change-report-audit-action'), {
      target: { value: 'report.export_pdf' },
    });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    fireEvent.change(screen.getByTestId('change-report-audit-scope'), { target: { value: 'tenant' } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));

    const urls = fetchMock.mock.calls.map((call) => (call as unknown as [string])[0]);
    expect(urls[1]).toBe('/api/change-report-audit?action=report.export_pdf&versionId=v1&limit=25');
    expect(urls[2]).toBe('/api/change-report-audit?action=report.export_pdf&limit=25');
    expect(screen.getByText('No Audit Entries')).toBeInTheDocument();
  });

  it('appends the older page when Load older is pressed', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          audit: { items: [ENTRIES[0]], limit: 25, nextCursor: 'CUR' },
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          success: true,
          audit: { items: [ENTRIES[1]], limit: 25, nextCursor: null },
        }),
      });
    global.fetch = fetchMock as unknown as typeof fetch;
    render(<ChangeReportAuditDialog revisionId="v1" revisionLabel="v1.1.0" onClose={jest.fn()} />);

    fireEvent.click(await screen.findByTestId('change-report-audit-more'));

    await waitFor(() =>
      expect(within(screen.getByTestId('change-report-audit-list')).getAllByRole('listitem')).toHaveLength(2)
    );
    expect(fetchMock.mock.calls[1][0]).toBe('/api/change-report-audit?versionId=v1&limit=25&cursor=CUR');
    expect(screen.queryByTestId('change-report-audit-more')).not.toBeInTheDocument();
  });

  it('says why when the log cannot be read', async () => {
    mockFetch({
      ok: false,
      body: { success: false, error: 'Only a tenant administrator can read the change-report audit trail' },
    });
    render(<ChangeReportAuditDialog revisionId="v1" revisionLabel="v1.1.0" onClose={jest.fn()} />);

    expect(await screen.findByTestId('change-report-audit-error')).toHaveTextContent(
      'Only a tenant administrator'
    );
  });

  it('closes from the Close button', async () => {
    mockFetch({ body: { success: true, audit: { items: [], limit: 25, nextCursor: null } } });
    const onClose = jest.fn();
    render(<ChangeReportAuditDialog revisionId="v1" revisionLabel="v1.1.0" onClose={onClose} />);

    fireEvent.click(await screen.findByTestId('change-report-audit-close'));

    expect(onClose).toHaveBeenCalled();
  });
});

describe('the Change report panel', () => {
  const VERSIONS = [
    {
      id: 'v1',
      project_id: 'p1',
      creator_id: 'user-a',
      version_id: '1.1.0',
      published: true,
      shortMessage: 'Refunds',
    },
  ];
  const REPORT = {
    effectiveHeaderSnapshot: '# Payments API',
    effectiveRenderedBody: '## Summary',
    effectiveFootnoteSnapshot: '',
    ...PENDING,
  };

  /** Route `fetch` by URL: the report read, the template list, and a transition. */
  function mockPanelFetch(transitionReport?: unknown) {
    const fetchMock = jest.fn(async (url: string) => {
      if (url.includes('/change-report/approve')) {
        return { ok: true, json: async () => ({ success: true, report: transitionReport }) };
      }
      if (url.startsWith('/api/change-report-template-versions')) {
        return { ok: true, json: async () => ({ success: true, templates: [] }) };
      }
      if (url.startsWith('/api/change-report-audit')) {
        return {
          ok: true,
          json: async () => ({ success: true, audit: { items: [], limit: 25, nextCursor: null } }),
        };
      }
      return { ok: true, json: async () => ({ success: true, report: REPORT }) };
    });
    global.fetch = fetchMock as unknown as typeof fetch;
    return fetchMock;
  }

  it('draws the review bar above the report and updates it after an approval', async () => {
    mockPanelFetch({ ...REPORT, ...APPROVED });
    render(
      <VersionChangeReportPanel
        projectId="p1"
        versions={VERSIONS}
        currentUserId="admin-b"
        effectiveIsAdmin
      />
    );

    expect(await screen.findByTestId('change-report-approval-badge')).toHaveTextContent(
      'Pending review'
    );
    fireEvent.click(screen.getByTestId('change-report-approve'));

    await waitFor(() =>
      expect(screen.getByTestId('change-report-approval-badge')).toHaveTextContent('Approved')
    );
    expect(screen.getByTestId('change-report-download-pdf')).toBeEnabled();
    // The report itself is still on screen: the transition's answer did not blank it.
    expect(screen.getByTestId('change-report-view')).toBeInTheDocument();
  });

  it('offers the Audit log to an administrator only', async () => {
    mockPanelFetch();
    const { unmount } = render(
      <VersionChangeReportPanel
        projectId="p1"
        versions={VERSIONS}
        currentUserId="admin-b"
        effectiveIsAdmin
      />
    );
    fireEvent.click(await screen.findByTestId('change-report-audit-open'));
    expect(
      await screen.findByRole('dialog', { name: 'Change report audit log' })
    ).toBeInTheDocument();
    unmount();

    render(
      <VersionChangeReportPanel
        projectId="p1"
        versions={VERSIONS}
        currentUserId="user-a"
        effectiveIsAdmin={false}
      />
    );
    await screen.findByTestId('change-report-approval-badge');
    expect(screen.queryByTestId('change-report-audit-open')).not.toBeInTheDocument();
  });
});

/**
 * The docs screenshots of this feature (`change-report-approval`, `change-report-audit` in
 * `apiome-docs/screens.json`) are captured from markup the components actually render. It is
 * written here, into `e2e/fixtures/hive-change-report/`, when `CHANGE_REPORT_FIXTURE_DUMP=1`:
 *
 *     CHANGE_REPORT_FIXTURE_DUMP=1 npx jest -c jest.config.ts tests/change-report-approval.test.tsx
 *
 * Without the variable the test still renders both surfaces, so a change that would leave the
 * fixtures stale fails here first.
 */
describe('the browser fixtures', () => {
  const OUT = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-change-report');
  const dump = process.env.CHANGE_REPORT_FIXTURE_DUMP === '1';

  const write = (name: string, html: string) => {
    expect(html.length).toBeGreaterThan(0);
    if (!dump) return;
    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, `${name}.html`), html);
  };

  const VERSIONS = [
    {
      id: 'v1',
      project_id: 'p1',
      creator_id: 'user-a',
      version_id: '1.1.0',
      published: true,
      shortMessage: 'Refunds and disputes',
    },
  ];
  const REPORT = {
    // Plain sentences: Jest renders Markdown through a stub, so Markdown syntax would show raw
    // in the captured screenshot.
    effectiveHeaderSnapshot: 'Payments API — 1.0.0 → 1.1.0',
    effectiveRenderedBody:
      'Two schemas were added (Refund, Dispute) and one was removed (LegacyCharge). Payment gained amount.currency.',
    effectiveFootnoteSnapshot: 'Generated by Apiome',
    approvalState: 'approved',
    submittedBy: 'user-a',
    submittedAt: '2026-11-13T12:05:00Z',
    approvedBy: 'admin-b',
    approvedAt: '2026-11-13T13:00:00Z',
    reviewNote: 'Checked against the release notes.',
    lastPdfSha256: '9f2c41d07ab35e61c8d4f0a97b12e3c5d6a7b8c9d0e1f2a3b4c5d6e7f8091a2b',
    lastPdfExportedAt: '2026-11-13T13:10:00Z',
  };
  const AUDIT = [
    { id: 'a5', action: 'report.export_pdf', actorId: '7c1d2e3f-0000-4000-8000-000000000002', detail: { sha256: REPORT.lastPdfSha256 }, createdAt: '2026-11-13T13:10:00Z' },
    { id: 'a4', action: 'report.approve', actorId: '7c1d2e3f-0000-4000-8000-000000000002', detail: { note: 'Checked against the release notes.' }, createdAt: '2026-11-13T13:00:00Z' },
    { id: 'a3', action: 'report.submit', actorId: '4a5b6c7d-0000-4000-8000-000000000001', detail: {}, createdAt: '2026-11-13T12:05:00Z' },
    { id: 'a2', action: 'report.edit', actorId: '4a5b6c7d-0000-4000-8000-000000000001', detail: { approval_reset: false }, createdAt: '2026-11-13T11:40:00Z' },
    { id: 'a1', action: 'report.regenerate', actorId: '4a5b6c7d-0000-4000-8000-000000000001', detail: { approval_reset: false }, createdAt: '2026-11-13T11:30:00Z' },
  ];

  it('renders the approved report and its audit log (and writes the fixtures on request)', async () => {
    global.fetch = jest.fn(async (url: string) => {
      if (url.startsWith('/api/change-report-template-versions')) {
        return { ok: true, json: async () => ({ success: true, templates: [] }) };
      }
      if (url.startsWith('/api/change-report-audit')) {
        return {
          ok: true,
          json: async () => ({ success: true, audit: { items: AUDIT, limit: 25, nextCursor: null } }),
        };
      }
      return { ok: true, json: async () => ({ success: true, report: REPORT }) };
    }) as unknown as typeof fetch;

    render(
      <Page>
        <PageBody>
          <VersionChangeReportPanel
            projectId="p1"
            versions={VERSIONS}
            currentUserId="admin-b"
            effectiveIsAdmin
          />
        </PageBody>
      </Page>
    );
    await screen.findByTestId('change-report-last-export');
    const page = document.querySelector('.page') as HTMLElement;
    write('approval', page.outerHTML);

    fireEvent.click(screen.getByTestId('change-report-audit-open'));
    const dialog = await screen.findByRole('dialog', { name: 'Change report audit log' });
    await within(dialog).findByTestId('change-report-audit-list');
    // The dialog is portalled to <body>: take the page, then whatever else sits on the body
    // (the overlay and the dialog) — not the body itself, which would repeat the page.
    const portalled = Array.from(document.body.children)
      .filter((element) => !element.contains(page))
      .map((element) => element.outerHTML)
      .join('');
    expect(portalled).toContain('change-report-audit-dialog');
    write('audit', page.outerHTML + portalled);
  });
});
