'use client';

/**
 * Home's "Recently viewed" panel (#510).
 *
 * The projects the reader most recently opened in the current workspace, from their own view
 * history (`apiome.project_views`) — not from what anyone last changed, which is "Pick up where
 * you left off". Each row opens the project's versions, the same destination as a Continue card,
 * so the two panels lead to one place.
 *
 * Built from the row and panel classes Home's other lists use (`.home-panel`, `.home-rows`,
 * `.home-row--link`), so it needs no styles of its own.
 */

import * as React from 'react';
import Link from 'next/link';
import { ChevronRight, FolderKanban } from 'lucide-react';

import { Card, CardHeader } from '@/app/components/ui/Card';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { Skeleton } from '@/app/components/ui/Skeleton';
import { RECENTLY_VIEWED_LIMIT, type RecentlyViewedProject } from '@lib/db/dashboard-home-model';
import { continueCardHref } from './ContinueWorking';
import { PANEL, recentlyViewedLine } from './homeModel';

/** Props for {@link RecentlyViewed}. */
export interface RecentlyViewedProps {
  /** Up to {@link RECENTLY_VIEWED_LIMIT} projects, last opened first. */
  projects: readonly RecentlyViewedProject[];
  /** True until the first load resolves. */
  loading: boolean;
}

/**
 * Draw the panel.
 *
 * Always drawn: a reader who has not opened a project yet gets an empty state saying how the list
 * fills, rather than a panel that appears only later and moves the page under them.
 *
 * @param props See {@link RecentlyViewedProps}.
 * @returns The card, with rows, skeleton rows, or the empty state.
 */
export function RecentlyViewed({ projects, loading }: RecentlyViewedProps) {
  const Icon = PANEL.recentlyViewed.icon;

  return (
    <Card className="home-panel" role="group" aria-labelledby="home-recently-viewed-title">
      <CardHeader className="home-panel__header">
        <span className="home-panel__title">
          <Icon aria-hidden />
          <h2 id="home-recently-viewed-title">{PANEL.recentlyViewed.title}</h2>
          <span className="home-panel__note">{PANEL.recentlyViewed.subtitle}</span>
        </span>
      </CardHeader>

      {loading ? (
        <div className="home-rows" aria-hidden>
          {Array.from({ length: RECENTLY_VIEWED_LIMIT }, (_, index) => (
            <div className="home-row" key={index}>
              <Skeleton className="size-7 rounded-sm" />
              <div className="home-row__body">
                <Skeleton className="h-3.5 w-3/5" />
                <Skeleton className="h-2.5 w-2/5" />
              </div>
            </div>
          ))}
        </div>
      ) : projects.length > 0 ? (
        <ol className="home-rows">
          {projects.map((project) => (
            <li key={project.projectId}>
              <Link
                href={continueCardHref(project.projectId)}
                className="home-row home-row--link"
                data-recently-viewed={project.projectId}
              >
                <span className="home-tile home-tone" data-tone="accent" aria-hidden>
                  <FolderKanban />
                </span>
                <span className="home-row__body">
                  <span className="home-row__title">{project.projectName}</span>
                  {/* Relative time with the absolute instant as its tooltip (DESIGN.md §10). */}
                  <span className="home-row__sub" title={project.lastViewedAt}>
                    {recentlyViewedLine(project.versionLabel, project.lastViewedAt, project.viewCount)}
                  </span>
                </span>
                <ChevronRight className="home-row__go" aria-hidden />
              </Link>
            </li>
          ))}
        </ol>
      ) : (
        <EmptyState
          brand
          variant="compact"
          title="Nothing viewed yet"
          description="Projects you open appear here, most recent first."
        />
      )}
    </Card>
  );
}

export default RecentlyViewed;
