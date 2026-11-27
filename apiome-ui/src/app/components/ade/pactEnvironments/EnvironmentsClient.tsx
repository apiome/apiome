'use client';

/**
 * **Environments** — `/ade/dashboard/pacts/environments` (PFX-5.7, #6951).
 *
 * Which version of each pacticipant runs where: a grid of pacticipants × environments with the
 * versions deployed to each now (and the application instance) and the releases it supports, then
 * the environments themselves. Each environment opens its own page (what runs there, its
 * deployment history, the deploy simulator); each pacticipant its page.
 *
 * A workspace with no environment shows the CLI commands that create one and record a deployment.
 */

import * as React from 'react';
import { RefreshCw } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { CREATE_ENVIRONMENT_SNIPPET, type Topology } from '@lib/pact-environments';
import { CliSnippet } from '../pactPacticipants/PacticipantPanels';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { DeployedVersionsGrid, EnvironmentList } from './EnvironmentPanels';
import { fetchTopology } from './environmentsApi';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The page's read. */
interface Loaded {
  data: Topology | null;
  error: string | null;
}

/**
 * The Environments dashboard.
 *
 * @returns The page.
 */
export default function EnvironmentsClient() {
  const [loaded, setLoaded] = React.useState<Loaded>({ data: null, error: null });

  const load = React.useCallback(async () => {
    setLoaded({ data: null, error: null });
    try {
      setLoaded({ data: await fetchTopology(), error: null });
    } catch (caught) {
      setLoaded({ data: null, error: describeFailure(caught, 'Could not load the environments') });
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  const { data, error } = loaded;
  return (
    <Page>
      <PageHeader
        tabs={<ContractsTabs active="environments" />}
        title="Environments"
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Contracts', href: CONTRACTS_ROUTE },
          { label: 'Environments' },
        ]}
        description="Which version of each pacticipant runs where — and what a deployment would change."
        actions={
          <Button variant="outline" onClick={() => void load()}>
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        }
      />
      <PageBody>
        <div className="ppx" data-testid="pact-environments">
          {error ? (
            <EmptyState
              variant="compact"
              tone="danger"
              titleAs="h2"
              title="The environments could not be read"
              description={error}
              action={
                <Button variant="soft" onClick={() => void load()}>
                  <RefreshCw aria-hidden />
                  Try again
                </Button>
              }
            />
          ) : data === null ? (
            <LoadingState message="Reading the environments…" minHeightClassName="min-h-[6rem]" />
          ) : data.environments.length === 0 ? (
            <div className="ppx__empty-note" data-testid="penv-empty">
              <EmptyState
                variant="compact"
                titleAs="h2"
                title="No environments yet"
                description="Create an environment, then record each deployment to it from your pipeline:"
              />
              <CliSnippet label="Create an environment and record a deployment" command={CREATE_ENVIRONMENT_SNIPPET} />
            </div>
          ) : (
            <>
              {data.truncated ? (
                <p className="ppx__error" role="status" data-testid="penv-truncated">
                  This workspace has more than 2000 current deployments or releases; only the first 2000 are shown.
                  Each environment&apos;s deployment history lists every deployment.
                </p>
              ) : null}
              <section className="ppx__panel" aria-labelledby="penv-grid-title">
                <div className="ppx__panel-head">
                  <h2 id="penv-grid-title" className="ppx__title">
                    Deployed versions
                  </h2>
                  <span className="ppx__meta" data-testid="penv-count">
                    {data.environments.length} {data.environments.length === 1 ? 'environment' : 'environments'}
                  </span>
                </div>
                <DeployedVersionsGrid topology={data} />
              </section>
              <section className="ppx__panel" aria-labelledby="penv-list-title">
                <div className="ppx__panel-head">
                  <h2 id="penv-list-title" className="ppx__title">
                    Environments
                  </h2>
                </div>
                <EnvironmentList environments={data.environments} />
              </section>
            </>
          )}
        </div>
      </PageBody>
    </Page>
  );
}
