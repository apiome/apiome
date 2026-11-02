'use client';

/**
 * The revisions timeline (facelift "timeline", PROPOSALS_FACELIFT.md §2).
 *
 * The Versions tab is named "Timeline" and was a table. This draws it as one: a spine with a
 * node per revision — a draft hollow, a published revision green, a deprecated one orange with
 * its sunset flag, an archived one grey, a beta azure, and the HEAD node in honey — the
 * revision's message and changelog as the row's body, who and when beside it, and the same
 * hover actions and ⋯ menu the table has. The **Table** segment on the toolbar keeps the table
 * one click away; nothing is removed.
 *
 * Every cell here is the table's cell: {@link VersionCell} for the version line, the mock cell,
 * the review pill, the quick actions and the row menu are the same components, so the two views
 * cannot disagree about what a revision is or may do. Only the arrangement differs.
 *
 * Authority: `docs/mockups/proposals/facelift-versions.html` (`.vt`), `DESIGN.md` §8.
 */

import * as React from 'react';
import {
  Archive,
  CalendarX2,
  Check,
  CircleCheck,
  FlaskConical,
  Lock,
  LockOpen,
  Pencil,
  Sunset,
} from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import { Card } from '@/app/components/ui/Card';
import { ErrorState } from '@/app/components/ui/ErrorState';
import { Skeleton } from '@/app/components/ui/Skeleton';
import { VersionMockCell } from '@/app/components/ade/dashboard/VersionMockCell';
import { ReviewStatusPill } from '@/app/components/ade/reviews/ReviewStatusPill';
import { mockUsageSeriesKey } from '@/app/utils/mock-usage-series';
import { lookupReview } from '@lib/review-status';
import { cn } from '@lib/utils';
import { VersionRowMenu } from './VersionRowMenu';
import { VersionCell } from './VersionsTable';
import type { VersionsTableProps } from './VersionsTable';
import {
  VERSION_STATUS_LABEL,
  formatSunsetDay,
  formatVersionDate,
  formatVersionStamp,
  revisionDeprecationMeta,
  versionLabel,
  versionLifecycle,
  versionRowQuickActions,
  versionStatus,
  type Version,
  type VersionRowMenuContext,
} from './versionsModel';

/** Props for {@link VersionsTimeline} — the table's, minus the sort the timeline has no header for. */
export type VersionsTimelineProps = Omit<VersionsTableProps, 'sort' | 'onSortChange'>;

/** What a revision's node says at a glance. */
type NodeKind = 'head' | 'published' | 'deprecated' | 'archived' | 'beta' | 'draft';

const NODE_ICON: Record<NodeKind, React.ComponentType<{ 'aria-hidden'?: boolean }>> = {
  head: Pencil,
  published: Check,
  deprecated: Sunset,
  archived: Archive,
  beta: FlaskConical,
  draft: Pencil,
};

const NODE_TITLE: Record<NodeKind, string> = {
  head: 'HEAD · draft',
  published: 'Published',
  deprecated: 'Deprecated',
  archived: 'Archived',
  beta: 'Beta',
  draft: 'Draft',
};

/**
 * Which node a revision gets. Lifecycle wins over publish state — a deprecated revision is
 * still published, and the sunset is what the reader needs to see — and HEAD is only honey
 * while it is still a draft: a published HEAD is a published node like the others.
 */
function nodeKind(version: Version, isHead: boolean): NodeKind {
  const lifecycle = versionLifecycle(version);
  if (lifecycle === 'deprecated') return 'deprecated';
  if (lifecycle === 'archived') return 'archived';
  if (version.published) return 'published';
  if (lifecycle === 'beta') return 'beta';
  return isHead ? 'head' : 'draft';
}

/** The loading shape: four rows at their real heights, so the list does not jump when it fills. */
function TimelineSkeleton() {
  return (
    <ol className="vt" aria-hidden>
      {Array.from({ length: 4 }, (_, index) => (
        <li key={index} className="vt__row">
          <div className="vt__spine">
            <span className="vt__node vt__node--draft" />
          </div>
          <div className="vt__ver">
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-3 w-32" />
          </div>
          <div className="vt__body">
            <Skeleton className="h-4 w-56" />
            <Skeleton className="h-3 w-40" />
          </div>
          <div className="vt__meta">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-3 w-20" />
          </div>
        </li>
      ))}
    </ol>
  );
}

/**
 * Render the revisions timeline. See {@link VersionsTimelineProps}.
 *
 * @returns The timeline card, its toolbar and its foot.
 */
export default function VersionsTimeline({
  versions,
  loading = false,
  error = null,
  onRetry,
  projectId,
  projectSlug,
  headRevisionId,
  tagsByVersionId,
  hasClassSchemaMap,
  reviewsByVersionId = null,
  effectiveIsAdmin,
  can,
  currentUserId,
  hasBranches,
  freezingSchemaVersionId,
  isVersionPublishable,
  gitlike,
  mockUsageByVersion,
  onMockChanged,
  onRowAction,
  toolbar,
  footer,
  empty,
  caption = 'Revisions of this project',
}: VersionsTimelineProps) {
  const contextFor = React.useCallback(
    (version: Version): VersionRowMenuContext => ({
      headRevisionId,
      effectiveIsAdmin,
      currentUserId,
      hasBranches,
      schemaFrozen: Boolean(hasClassSchemaMap[version.id]),
      publishable: isVersionPublishable(version),
      freezing: freezingSchemaVersionId === version.id,
      gitlike,
      can,
    }),
    [
      can,
      currentUserId,
      effectiveIsAdmin,
      freezingSchemaVersionId,
      gitlike,
      hasBranches,
      hasClassSchemaMap,
      headRevisionId,
      isVersionPublishable,
    ]
  );

  let body: React.ReactNode;
  if (loading) {
    body = <TimelineSkeleton />;
  } else if (error) {
    body = (
      <ErrorState
        title="Couldn't load this project's versions"
        description={error}
        onRetry={onRetry}
        data-testid="versions-timeline-error"
      />
    );
  } else if (versions.length === 0) {
    body = empty ?? null;
  } else {
    body = (
      <ol className="vt" aria-label={caption} data-testid="versions-timeline-list">
        {versions.map((version) => {
          const isHead = headRevisionId !== null && version.id === headRevisionId;
          const kind = nodeKind(version, isHead);
          const NodeIcon = NODE_ICON[kind];
          const status = versionStatus(version);
          const context = contextFor(version);
          const quick = versionRowQuickActions(version, context);
          const label = versionLabel(version);
          const deprecation = revisionDeprecationMeta(version);
          return (
            <li
              key={version.id}
              className={cn('vt__row group', kind === 'head' && 'vt__row--head')}
              data-row-id={version.id}
              data-node={kind}
              data-testid={`versions-timeline-row-${version.id}`}
            >
              <div className="vt__spine" aria-hidden>
                <span className={cn('vt__node', `vt__node--${kind}`)} title={NODE_TITLE[kind]}>
                  <NodeIcon aria-hidden />
                </span>
              </div>

              <div className="vt__ver">
                <VersionCell
                  version={version}
                  projectId={projectId}
                  isHead={isHead}
                  tags={tagsByVersionId.get(version.id) ?? []}
                  onView={() => onRowAction('view', version)}
                />
                {deprecation.sunsetAt ? (
                  <span className="vt__sunset" data-testid={`versions-timeline-sunset-${version.id}`}>
                    <CalendarX2 aria-hidden />
                    Sunset {formatSunsetDay(deprecation.sunsetAt)}
                  </span>
                ) : null}
              </div>

              <div className="vt__body">
                {version.shortMessage ? (
                  <div className="vt__title" title={version.shortMessage}>
                    {version.shortMessage}
                  </div>
                ) : (
                  <div className="vt__title vt__title--none">No message</div>
                )}
                {version.changelog ? <pre className="vt__log">{version.changelog}</pre> : null}
                <div className="vt__chips">
                  <Badge status={status} dot data-testid={`versions-status-${version.id}`}>
                    {status === 'published' ? <CircleCheck aria-hidden /> : null}
                    {VERSION_STATUS_LABEL[status]}
                  </Badge>
                  {!version.enabled ? (
                    <Badge status="disabled" title="enabled = false">
                      Disabled
                    </Badge>
                  ) : null}
                  <ReviewStatusPill
                    review={lookupReview(reviewsByVersionId, version.id)}
                    data-testid={`versions-review-${version.id}`}
                  />
                  <VersionMockCell
                    versionRecordId={version.id}
                    projectId={version.project_id}
                    versionLabel={version.version_id}
                    published={version.published}
                    mockEnabled={Boolean(version.mockEnabled)}
                    mockPrivate={Boolean(version.mockPrivate)}
                    mockBaseUrl={version.mockBaseUrl ?? null}
                    usageSeries={
                      mockUsageByVersion === null || !projectSlug
                        ? undefined
                        : (mockUsageByVersion.get(mockUsageSeriesKey(projectSlug, version.version_id)) ?? [])
                    }
                    onMockChanged={(change) => onMockChanged(version.id, change)}
                  />
                </div>
              </div>

              <div className="vt__meta">
                <span className="vt__who" title={version.creator_email}>
                  {version.creator_name}
                </span>
                <span className="vt__when">{formatVersionStamp(version.created_at)}</span>
                {version.published_at ? (
                  <span className="vt__published" data-testid={`versions-published-at-${version.id}`}>
                    <CircleCheck aria-hidden />
                    Published {formatVersionDate(version.published_at)}
                  </span>
                ) : null}
              </div>

              <div
                className={cn(
                  'vt__actions',
                  // Revealed on hover and on keyboard focus, as the table's action cell is.
                  'opacity-0 transition-opacity duration-[var(--dur-fast)]',
                  'group-hover:opacity-100 group-focus-within:opacity-100'
                )}
                data-row-actions=""
              >
                {quick.map((action) => (
                  <Button
                    key={action.id}
                    variant="ghost"
                    size="sm"
                    className={cn('px-1.5', action.id === 'publish' && 'ver-row-action--publish')}
                    title={action.label}
                    aria-label={`${action.label} ${label}`}
                    data-testid={`versions-quick-${action.id}-${version.id}`}
                    onClick={() => onRowAction(action.id, version)}
                  >
                    {action.id === 'publish' ? (
                      <Lock aria-hidden />
                    ) : action.id === 'unpublish' ? (
                      <LockOpen aria-hidden />
                    ) : action.id === 'scheduleSunset' ? (
                      <Sunset aria-hidden />
                    ) : (
                      <Pencil aria-hidden />
                    )}
                  </Button>
                ))}
                <VersionRowMenu version={version} context={context} onAction={onRowAction} />
              </div>
            </li>
          );
        })}
      </ol>
    );
  }

  return (
    <Card className="ver-table ver-timeline" data-testid="versions-timeline">
      {toolbar}
      {body}
      {footer}
    </Card>
  );
}
