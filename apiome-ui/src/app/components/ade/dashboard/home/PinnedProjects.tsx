'use client';

/**
 * Home's "Pinned projects" panel (#513).
 *
 * The projects the reader chose to keep one click away, newest pin first, from their own pins
 * (`apiome.project_pins`). A project is pinned from its ⋯ menu on **Projects** and unpinned there
 * or from the pin button on its row here. Each row opens the project's versions, the same
 * destination as "Pick up where you left off" and "Recently viewed".
 *
 * The row is two controls side by side — the link and the unpin button — never one inside the
 * other, which is why it needs `.home-pin` on top of Home's shared row classes.
 */

import * as React from 'react';
import Link from 'next/link';
import { ArrowRight, ChevronRight, FolderKanban, PinOff } from 'lucide-react';

import { Button } from '@/app/components/ui/Button';
import { Card, CardFooter, CardHeader } from '@/app/components/ui/Card';
import { EmptyState } from '@/app/components/ui/EmptyState';
import { Skeleton } from '@/app/components/ui/Skeleton';
import { PROJECT_PIN_LIMIT, type PinnedProject } from '@lib/db/dashboard-home-model';
import { continueCardHref } from './ContinueWorking';
import { PANEL, pinnedLine } from './homeModel';

/** Where the empty state sends the reader to pin something. */
const PROJECTS_HREF = '/ade/dashboard/projects';

/** How many skeleton rows the loading panel draws. */
const SKELETON_ROWS = 2;

/** Props for {@link PinnedProjects}. */
export interface PinnedProjectsProps {
  /** Up to {@link PROJECT_PIN_LIMIT} projects, newest pin first. */
  projects: readonly PinnedProject[];
  /** True until the first load resolves. */
  loading: boolean;
  /** Unpin one project. The page removes the row and puts it back if the write fails. */
  onUnpin: (project: PinnedProject) => void;
  /** Ids of projects whose unpin is in flight; their buttons go inert. */
  unpinning?: ReadonlySet<string>;
  /**
   * The panel's heading and quiet note. Defaults to Home's "Pinned projects"; the Profile page
   * draws the same list as "Favorite projects" (#542).
   */
  heading?: { title: string; subtitle: string };
  /** `data-testid` for the card. */
  testId?: string;
}

/**
 * Draw the panel.
 *
 * Always drawn, so a reader who has not pinned anything learns where pinning lives.
 *
 * @param props See {@link PinnedProjectsProps}.
 * @returns The card, with rows, skeleton rows, or the empty state.
 */
export function PinnedProjects({
  projects,
  loading,
  onUnpin,
  unpinning,
  heading = PANEL.pinned,
  testId,
}: PinnedProjectsProps) {
  const Icon = PANEL.pinned.icon;
  const titleId = React.useId();

  return (
    <Card className="home-panel" role="group" aria-labelledby={titleId} data-testid={testId}>
      <CardHeader className="home-panel__header">
        <span className="home-panel__title">
          <Icon aria-hidden />
          <h2 id={titleId}>{heading.title}</h2>
          <span className="home-panel__note">{heading.subtitle}</span>
        </span>
      </CardHeader>

      {loading ? (
        <div className="home-rows" aria-hidden>
          {Array.from({ length: SKELETON_ROWS }, (_, index) => (
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
        <>
          <ul className="home-rows">
            {projects.map((project) => (
              <li className="home-pin" key={project.projectId} data-pinned={project.projectId}>
                <Link href={continueCardHref(project.projectId)} className="home-row home-row--link">
                  <span className="home-tile home-tone" data-tone="honey" aria-hidden>
                    <FolderKanban />
                  </span>
                  <span className="home-row__body">
                    <span className="home-row__title">{project.projectName}</span>
                    {/* Relative time with the absolute instant as its tooltip (DESIGN.md §10). */}
                    <span className="home-row__sub" title={project.pinnedAt}>
                      {pinnedLine(project.versionLabel, project.pinnedAt)}
                    </span>
                  </span>
                  <ChevronRight className="home-row__go" aria-hidden />
                </Link>
                <Button
                  variant="ghost"
                  size="icon"
                  className="home-pin__unpin"
                  aria-label={`Unpin ${project.projectName}`}
                  title="Unpin from Home"
                  disabled={unpinning?.has(project.projectId) ?? false}
                  onClick={() => onUnpin(project)}
                >
                  <PinOff aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
          <CardFooter className="home-panel__footer">
            <span>
              {projects.length} of {PROJECT_PIN_LIMIT} pinned
            </span>
          </CardFooter>
        </>
      ) : (
        <EmptyState
          brand
          variant="compact"
          title="No pinned projects"
          description={`Pin up to ${PROJECT_PIN_LIMIT} projects from their ⋯ menu on Projects to keep them here.`}
          action={
            <Button variant="outline" size="sm" asChild>
              <Link href={PROJECTS_HREF}>
                Go to Projects
                <ArrowRight aria-hidden />
              </Link>
            </Button>
          }
        />
      )}
    </Card>
  );
}

export default PinnedProjects;
