'use client';

/**
 * Bring in → Catalog → one **import report** — `/ade/dashboard/catalog/imports/[id]` (CDG-5.5, #5983).
 *
 * What one Backstage scan or Compass upload found: the teams and components waiting for a click,
 * and every field that has no Apiome equivalent. See {@link MigrationReport}.
 */

import * as React from 'react';
import { RefreshCw } from 'lucide-react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Button, EmptyState, GatedState, LoadingState } from '@/app/components/ui';
import { MigrationReport } from '@/app/components/ade/catalogMigrations/MigrationReport';
import { fetchImportReport, useCanImport } from '@/app/components/ade/catalogMigrations/catalogMigrationsApi';
import { useAuthSession } from '@lib/auth/session-client';
import { IMPORT_REPORTS_ROUTE, type MigrationRun } from '@lib/catalog-migrations';

const HOME_ROUTE = '/ade/dashboard';
const CATALOG_ROUTE = '/ade/dashboard/catalog';

/** Props for {@link ImportReportClient}. */
export interface ImportReportClientProps {
  /** The report id, from the route. */
  id: string;
}

/**
 * The import report page.
 *
 * @param props - See {@link ImportReportClientProps}.
 * @returns The page.
 */
export default function ImportReportClient({ id }: ImportReportClientProps) {
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const canDecide = useCanImport();
  const [run, setRun] = React.useState<MigrationRun | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setRun(await fetchImportReport(id));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the import report');
    }
  }, [id]);

  React.useEffect(() => {
    if (tenantId) void load();
  }, [tenantId, load]);

  const title = run?.label ?? 'Import report';
  return (
    <Page>
      <PageHeader
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Bring in' },
          { label: 'Catalog', href: CATALOG_ROUTE },
          { label: 'Import reports', href: IMPORT_REPORTS_ROUTE },
          { label: title },
        ]}
        title={title}
        description="Nothing is created, and nobody becomes an owner, until you accept it."
      />
      <PageBody>
        {!tenantId ? (
          <GatedState description="Import reports belong to one workspace." />
        ) : error && !run ? (
          <EmptyState
            variant="compact"
            surface={false}
            tone="danger"
            title="The import report could not be read"
            description={error}
            action={
              <Button variant="soft" onClick={() => void load()}>
                <RefreshCw aria-hidden />
                Try again
              </Button>
            }
          />
        ) : !run ? (
          <LoadingState message="Reading the import report…" minHeightClassName="min-h-[8rem]" />
        ) : (
          <MigrationReport run={run} canDecide={canDecide} onChanged={() => void load()} />
        )}
      </PageBody>
    </Page>
  );
}
