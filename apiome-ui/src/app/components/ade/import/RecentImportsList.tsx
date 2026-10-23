'use client';

/**
 * The last three imports, under the source tiles on the wizard's first step — HIVE-11.11 (#5607).
 *
 * Authority: `docs/mockups/PROPOSALS.md` (the Import wizard left ≈ 450 px empty under its
 * tiles) and DESIGN.md §8 (Wizard). When there are recent imports, step 1 lists the newest
 * three with their state; **All import jobs** opens the existing *Recent import jobs* drawer.
 * It reads one page of three from the same job store the drawer pages through
 * (`/api/catalog/import`), and draws nothing while loading, on a failed read or with no jobs —
 * the tiles are the step, and a placeholder here would only take their space back.
 */

import * as React from 'react';

import { Badge } from '@/app/components/ui/Badge';
import { Button } from '@/app/components/ui/Button';
import {
  recentAsyncJobsUrl,
  type RecentAsyncJobRow,
} from '../dashboard/asyncJobs/RecentAsyncJobsPanel';

/** How many imports step 1 shows. */
export const RECENT_IMPORTS_SHOWN = 3;

/** Props for {@link RecentImportsList}. */
export interface RecentImportsListProps {
  /** Opens the full *Recent import jobs* drawer. */
  onShowAll: () => void;
}

/**
 * The recent-imports list.
 *
 * @param props See {@link RecentImportsListProps}.
 * @returns The list, or `null` when there is nothing to show.
 */
export function RecentImportsList({ onShowAll }: RecentImportsListProps) {
  const [jobs, setJobs] = React.useState<RecentAsyncJobRow[]>([]);

  React.useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(recentAsyncJobsUrl('import', RECENT_IMPORTS_SHOWN, 0), {
          cache: 'no-store',
        });
        const body = (await response.json().catch(() => null)) as
          | { jobs?: RecentAsyncJobRow[]; success?: boolean }
          | null;
        if (cancelled || !response.ok || !body || body.success === false) return;
        setJobs(Array.isArray(body.jobs) ? body.jobs.slice(0, RECENT_IMPORTS_SHOWN) : []);
      } catch {
        // Best-effort context: a failed read leaves the step as the tiles alone.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (jobs.length === 0) return null;

  return (
    <section className="imp-recent" aria-labelledby="imp-recent-heading" data-testid="import-recent-list">
      <div className="imp-recent__head">
        <h3 id="imp-recent-heading" className="imp-recent__title">
          Recent imports
        </h3>
        <Button type="button" variant="link" size="sm" onClick={onShowAll} data-testid="import-recent-all">
          All import jobs
        </Button>
      </div>
      <ul className="imp-recent__list">
        {jobs.map((job) => (
          <li key={job.job_id} className="imp-recent__row">
            <span className="imp-recent__id mono">{job.job_id}</span>
            <Badge status={job.state}>{job.state}</Badge>
            <span className="imp-recent__pct">
              {typeof job.percent === 'number' ? `${job.percent}%` : '—'}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default RecentImportsList;
