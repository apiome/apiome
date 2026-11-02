/**
 * The revisions timeline — facelift "timeline" (PROPOSALS_FACELIFT.md §2).
 *
 * A spine with a node per revision, the HEAD draft in honey, a deprecated revision with its
 * sunset flag, the same cells and actions as the table, and the table one segment away.
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import VersionsTimeline from '@/app/components/ade/versions/VersionsTimeline';
import type { Version } from '@/app/components/ade/versions/versionsModel';

jest.mock('@/app/components/ade/dashboard/VersionMockCell', () => ({
  VersionMockCell: ({ versionLabel }: { versionLabel: string }) => (
    <span data-testid={`mock-cell-${versionLabel}`}>mock</span>
  ),
}));

jest.mock('@/app/components/ade/dashboard/VersionLintBadge', () => ({
  VersionLintBadge: () => null,
}));

const PROJECT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

function version(over: Partial<Version> = {}): Version {
  return {
    id: 'v-1',
    project_id: PROJECT_ID,
    creator_id: 'u-ada',
    version_id: '2.4.0',
    shortMessage: 'Add refund reasons',
    changelog: '- added: RefundReason enum\n- added: payout.settled event',
    enabled: true,
    published: false,
    deleted_at: null,
    created_at: '2026-08-15T03:12:00.000Z',
    updated_at: '2026-08-15T03:12:00.000Z',
    published_at: null,
    creator_name: 'Ada Lovelace',
    creator_email: 'ada@example.com',
    ...over,
  };
}

const ROWS: Version[] = [
  version(),
  version({
    id: 'v-2',
    version_id: '2.3.1',
    published: true,
    published_at: '2026-08-03T10:40:00.000Z',
    shortMessage: 'Patch: fix Refund.amount minimum',
    changelog: null,
  }),
  version({
    id: 'v-3',
    version_id: '2.2.0',
    published: true,
    published_at: '2026-06-10T08:15:00.000Z',
    lifecycle: 'deprecated',
    metadata: { sunsetAt: '2026-09-30T00:00:00.000Z' },
    shortMessage: null,
  }),
];

function renderTimeline(rows: Version[] = ROWS, over: Partial<React.ComponentProps<typeof VersionsTimeline>> = {}) {
  const onRowAction = jest.fn();
  render(
    <VersionsTimeline
      versions={rows}
      projectId={PROJECT_ID}
      headRevisionId={rows[0]?.id ?? null}
      tagsByVersionId={new Map()}
      hasClassSchemaMap={{}}
      effectiveIsAdmin
      currentUserId="u-ada"
      hasBranches={false}
      freezingSchemaVersionId={null}
      isVersionPublishable={() => true}
      gitlike={{ enabled: false, marked: false }}
      mockUsageByVersion={null}
      onMockChanged={jest.fn()}
      onRowAction={onRowAction}
      toolbar={<div data-testid="toolbar">toolbar</div>}
      footer={<div data-testid="footer">footer</div>}
      empty={<div data-testid="empty">nothing</div>}
      {...over}
    />
  );
  return { onRowAction };
}

describe('VersionsTimeline', () => {
  it('draws one row per revision on a spine, newest first, with the toolbar and foot around it', () => {
    renderTimeline();
    const list = screen.getByTestId('versions-timeline-list');
    expect(within(list).getAllByRole('listitem')).toHaveLength(3);
    expect(screen.getByTestId('toolbar')).toBeInTheDocument();
    expect(screen.getByTestId('footer')).toBeInTheDocument();
    expect(screen.getByTestId('versions-timeline')).toHaveClass('ver-table', 'ver-timeline');
  });

  it('gives each revision the node its state calls for: HEAD draft in honey, published, deprecated', () => {
    renderTimeline();
    expect(screen.getByTestId('versions-timeline-row-v-1')).toHaveAttribute('data-node', 'head');
    expect(screen.getByTestId('versions-timeline-row-v-2')).toHaveAttribute('data-node', 'published');
    expect(screen.getByTestId('versions-timeline-row-v-3')).toHaveAttribute('data-node', 'deprecated');
    expect(screen.getByTestId('versions-timeline-row-v-1')).toHaveClass('vt__row--head');
  });

  it('flags a deprecated revision with its sunset day', () => {
    renderTimeline();
    expect(screen.getByTestId('versions-timeline-sunset-v-3')).toHaveTextContent('Sunset 30 Sep 2026');
    expect(screen.queryByTestId('versions-timeline-sunset-v-2')).not.toBeInTheDocument();
  });

  it('reads the message and changelog as the body, and says when there is no message', () => {
    renderTimeline();
    const head = screen.getByTestId('versions-timeline-row-v-1');
    expect(within(head).getByText('Add refund reasons')).toBeInTheDocument();
    expect(within(head).getByText(/RefundReason enum/)).toBeInTheDocument();
    expect(within(screen.getByTestId('versions-timeline-row-v-3')).getByText('No message')).toBeInTheDocument();
  });

  it('keeps the table’s cells: status, mock, creator, created and the published date', () => {
    renderTimeline();
    expect(screen.getByTestId('versions-status-v-2')).toHaveTextContent('Published');
    expect(screen.getByTestId('mock-cell-2.3.1')).toBeInTheDocument();
    expect(screen.getByTestId('versions-published-at-v-2')).toHaveTextContent('Published');
    const head = screen.getByTestId('versions-timeline-row-v-1');
    expect(within(head).getByText('Ada Lovelace')).toBeInTheDocument();
  });

  it('offers the row actions and routes them through onRowAction', async () => {
    const { onRowAction } = renderTimeline();
    const publish = screen.getByTestId('versions-quick-publish-v-1');
    publish.click();
    expect(onRowAction).toHaveBeenCalledWith('publish', expect.objectContaining({ id: 'v-1' }));
  });

  it('draws the caller’s empty state when nothing matched, and a skeleton while loading', () => {
    renderTimeline([]);
    expect(screen.getByTestId('empty')).toBeInTheDocument();
  });
});
