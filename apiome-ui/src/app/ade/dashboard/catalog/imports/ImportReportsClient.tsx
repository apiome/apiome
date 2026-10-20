'use client';

/**
 * Bring in → Catalog → **Import reports** — `/ade/dashboard/catalog/imports` (CDG-5.5, #5983).
 *
 * Every Backstage and Compass import report, newest first: a repository branch whose scan found
 * `catalog-info.yaml` files (one report, rewritten by each scan) and each uploaded Compass export.
 * **Waiting** counts the suggestions nobody has decided yet.
 */

import * as React from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Badge, Button, EmptyState, GatedState, LoadingState } from '@/app/components/ui';
import { fetchImportReports } from '@/app/components/ade/catalogMigrations/catalogMigrationsApi';
import { useAuthSession } from '@lib/auth/session-client';
import { MIGRATION_SOURCE_LABELS, importReportHref, migrationCountsLine, type MigrationRun } from '@lib/catalog-migrations';
import { formatRelativeWhen } from '@/app/components/ade/repositories/repositoryDetailModel';

const HOME_ROUTE = '/ade/dashboard';
const CATALOG_ROUTE = '/ade/dashboard/catalog';

/**
 * The import reports page.
 *
 * @returns The page.
 */
export default function ImportReportsClient() {
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const [runs, setRuns] = React.useState<MigrationRun[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setRuns(await fetchImportReports());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the import reports');
    }
  }, []);

  React.useEffect(() => {
    if (tenantId) void load();
  }, [tenantId, load]);

  return (
    <Page>
      <PageHeader
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Bring in' },
          { label: 'Catalog', href: CATALOG_ROUTE },
          { label: 'Import reports' },
        ]}
        title="Import reports"
        description="Backstage catalog-info files and Compass exports, and what is waiting for a decision."
      />
      <PageBody>
        {!tenantId ? (
          <GatedState description="Import reports belong to one workspace." />
        ) : error ? (
          <EmptyState
            variant="compact"
            surface={false}
            tone="danger"
            title="The import reports could not be read"
            description={error}
            action={
              <Button variant="soft" onClick={() => void load()}>
                <RefreshCw aria-hidden />
                Try again
              </Button>
            }
          />
        ) : runs === null ? (
          <LoadingState message="Reading the import reports…" minHeightClassName="min-h-[8rem]" />
        ) : runs.length === 0 ? (
          <EmptyState
            variant="compact"
            title="No imports yet"
            description="Scan a repository with a catalog-info.yaml, or upload a Compass export."
          />
        ) : (
          <div className="agt-table-wrap" data-testid="import-reports">
            <table className="agt-table">
              <thead>
                <tr>
                  <th scope="col">Report</th>
                  <th scope="col">Source</th>
                  <th scope="col">Found</th>
                  <th scope="col">Waiting</th>
                  <th scope="col">Updated</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <Link className="agt-link mono" href={importReportHref(run.id)}>
                        {run.label}
                      </Link>
                    </td>
                    <td>{MIGRATION_SOURCE_LABELS[run.source]}</td>
                    <td>{migrationCountsLine(run)}</td>
                    <td className="agt-num">
                      {run.pending > 0 ? <Badge variant="warn">{run.pending}</Badge> : <span className="agt-muted">0</span>}
                    </td>
                    <td className="agt-muted">{run.updatedAt ? formatRelativeWhen(run.updatedAt) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </PageBody>
    </Page>
  );
}
