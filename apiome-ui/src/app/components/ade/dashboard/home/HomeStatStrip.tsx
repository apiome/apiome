'use client';

/**
 * Home's six-stat strip (HIVE-4.6, #5300).
 *
 * Authority: `docs/mockups/home/overview.html` §"Stats strip"; the figures and their subtitles
 * are `getDashboardStats`'s, unchanged, which is the ticket's first acceptance criterion.
 *
 * What changed is only how they are drawn. The pre-redesign strip was six hand-rolled panels,
 * each naming its own icon colour (`text-blue-600 dark:text-blue-400`, and five more like it) —
 * twelve literal hues that no theme could reach. This is {@link StatGrid} from the HIVE-2.6
 * metrics set, whose hairline-between-cells treatment makes the six read as one object, and
 * whose tone comes from the token layer.
 *
 * The skeleton is shaped like the loaded strip — six cells, each with a label, a figure and a
 * footnote line — because a skeleton that is not the shape of its content is a spinner
 * (`DESIGN.md` §8).
 */

import * as React from 'react';

import { CountUp, Ring, Sparkline, Stat, StatGrid } from '@/app/components/ui/metrics';
import type { PulseWeek } from '@lib/db/dashboard-home-model';
import { Skeleton } from '@/app/components/ui/Skeleton';
import { STAT_COUNT, resolveStats, type DashboardStats } from './homeModel';

/** Props for {@link HomeStatStrip}. */
export interface HomeStatStripProps {
  /** The statistics payload. Ignored while `loading`. */
  stats: DashboardStats;
  /** True until the first load resolves. */
  loading: boolean;  /**
   * The twelve-week publishing pulse, oldest first (facelift "viz", PROPOSALS_FACELIFT.md §2):
   * drawn as a sparkline under the Published figure. Omitted or empty, no sparkline.
   */
  pulse?: readonly PulseWeek[];
}

/** One cell of the loading strip: the three lines a loaded stat draws, at their real heights. */
function StatSkeleton() {
  return (
    <div className="hive-stat" aria-hidden>
      <Skeleton className="h-3 w-20" />
      <Skeleton className="h-7 w-14" />
      <Skeleton className="h-3 w-24" />
    </div>
  );
}

/**
 * Draw the strip.
 *
 * @param props See {@link HomeStatStripProps}.
 * @returns Six stats, or six skeleton cells of the same shape.
 */
export function HomeStatStrip({ stats, loading, pulse }: HomeStatStripProps) {
  if (loading) {
    return (
      <StatGrid columns={6} role="group" aria-label="Workspace statistics, loading">
        {Array.from({ length: STAT_COUNT }, (_, index) => (
          <StatSkeleton key={index} />
        ))}
      </StatGrid>
    );
  }

  return (
    <StatGrid columns={6} role="group" aria-label="Workspace statistics">
      {resolveStats(stats).map((stat) => {
        const Icon = stat.icon;
        const published = stat.id === 'published';
        const share =
          published && stats.total_versions > 0
            ? Math.round((stats.published_versions / stats.total_versions) * 100)
            : null;
        return (
          <Stat
            key={stat.id}
            data-stat={stat.id}
            label={stat.label}
            icon={<Icon aria-hidden />}
            // The figure counts up once as the page lands (facelift "motion").
            value={typeof stat.value === 'number' ? <CountUp value={stat.value} /> : stat.value}
            unit={stat.unit}
            footnote={stat.subtitle}
            // "5 of 14" is a share, so it is drawn as one: a ring beside the figure (facelift "viz").
            aside={
              share !== null ? (
                <Ring score={share} label={`${share}% of versions published`} size="sm" />
              ) : undefined
            }
            // The twelve-week pulse the panel below already draws, as a trend under the figure.
            trend={
              published && pulse && pulse.length > 1 ? (
                <Sparkline
                  data={pulse.map((week) => week.count)}
                  label="Versions published per week, last twelve weeks"
                  tone="ok"
                  area
                />
              ) : undefined
            }
          />
        );
      })}
    </StatGrid>
  );
}

export default HomeStatStrip;
