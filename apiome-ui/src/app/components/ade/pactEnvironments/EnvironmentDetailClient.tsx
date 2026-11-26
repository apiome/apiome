'use client';

/**
 * One environment — `/ade/dashboard/pacts/environments/{name}` (PFX-5.7, #6951).
 *
 * **Overview** (name, production, contract required), **Deployed now** (each version with its
 * instance and when), **Released and supported**, and the **Deployment history**: every deployment
 * recorded to it, current or replaced, newest first, narrowed by **Pacticipant**, with **Load
 * more** (25). **Simulate a deployment** opens the deploy simulator for this environment.
 *
 * The current state and the history load, fail and retry on their own.
 */

import * as React from 'react';
import Link from 'next/link';
import { FlaskConical, RefreshCw } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { PACTICIPANTS_ROUTE } from '@lib/pact-pacticipants';
import {
  ENVIRONMENTS_ROUTE,
  environmentPacticipants,
  recordDeploymentInto,
  simulatorRoute,
  type HistoryDeployment,
  type TopologyEnvironment,
} from '@lib/pact-environments';
import { CliSnippet } from '../pactPacticipants/PacticipantPanels';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { CurrentDeploymentsTable, CurrentReleasesTable, HistoryTable, ProductionBadge } from './EnvironmentPanels';
import { fetchHistory, fetchTopology } from './environmentsApi';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The environment as read: found, not found, or failed. */
interface Loaded {
  environment: TopologyEnvironment | null;
  missing: boolean;
  error: string | null;
  done: boolean;
}

/** The history as read so far. */
interface History {
  deployments: HistoryDeployment[];
  nextCursor: string | null;
  error: string | null;
  loading: boolean;
}

const NO_HISTORY: History = { deployments: [], nextCursor: null, error: null, loading: true };

/**
 * An environment's page.
 *
 * @param props - `name`: the environment's name from the route.
 * @returns The page.
 */
export default function EnvironmentDetailClient({ name }: { name: string }) {
  const [loaded, setLoaded] = React.useState<Loaded>({ environment: null, missing: false, error: null, done: false });
  const [pacticipant, setPacticipant] = React.useState('');
  const [history, setHistory] = React.useState<History>(NO_HISTORY);

  const load = React.useCallback(async () => {
    setLoaded({ environment: null, missing: false, error: null, done: false });
    try {
      const topology = await fetchTopology();
      const environment = topology.environments.find((candidate) => candidate.name === name) ?? null;
      setLoaded({ environment, missing: environment === null, error: null, done: true });
    } catch (caught) {
      setLoaded({ environment: null, missing: false, error: describeFailure(caught, 'Could not load the environment'), done: true });
    }
  }, [name]);

  const loadHistory = React.useCallback(
    async (filter: string, cursor: string | null) => {
      setHistory((previous) => ({ ...(cursor ? previous : NO_HISTORY), error: null, loading: true }));
      try {
        const page = await fetchHistory(name, { pacticipant: filter || null, cursor });
        setHistory((previous) => ({
          deployments: cursor ? [...previous.deployments, ...page.deployments] : page.deployments,
          nextCursor: page.nextCursor,
          error: null,
          loading: false,
        }));
      } catch (caught) {
        setHistory((previous) => ({
          ...previous,
          error: describeFailure(caught, 'Could not load the deployment history'),
          loading: false,
        }));
      }
    },
    [name],
  );

  React.useEffect(() => {
    void load();
  }, [load]);

  React.useEffect(() => {
    void loadHistory(pacticipant, null);
  }, [loadHistory, pacticipant]);

  const { environment } = loaded;
  const title = environment?.displayName ?? name;
  return (
    <Page>
      <PageHeader
        title={title}
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Pacticipants', href: PACTICIPANTS_ROUTE },
          { label: 'Environments', href: ENVIRONMENTS_ROUTE },
          { label: title },
        ]}
        description="What runs here now, every deployment recorded here, and what a deployment would change."
        actions={
          <div className="ppx__actions">
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCw aria-hidden />
              Refresh
            </Button>
            <Button asChild>
              <Link href={simulatorRoute(name)} data-testid="penv-simulate">
                <FlaskConical aria-hidden />
                Simulate a deployment
              </Link>
            </Button>
          </div>
        }
      />
      <PageBody>
        <div className="ppx" data-testid="pact-environment">
          {!loaded.done ? (
            <LoadingState message="Reading the environment…" minHeightClassName="min-h-[6rem]" />
          ) : loaded.error ? (
            <EmptyState
              variant="compact"
              tone="danger"
              titleAs="h2"
              title="The environment could not be read"
              description={loaded.error}
              action={
                <Button variant="soft" onClick={() => void load()}>
                  <RefreshCw aria-hidden />
                  Try again
                </Button>
              }
            />
          ) : loaded.missing || !environment ? (
            <EmptyState
              variant="compact"
              titleAs="h2"
              title="No such environment"
              description={`This workspace has no environment named ${name}.`}
              action={
                <Button variant="soft" asChild>
                  <Link href={ENVIRONMENTS_ROUTE}>All environments</Link>
                </Button>
              }
            />
          ) : (
            <>
              <section className="ppx__panel" aria-labelledby="penv-overview-title">
                <div className="ppx__panel-head">
                  <h2 id="penv-overview-title" className="ppx__title">
                    Overview
                  </h2>
                  <ProductionBadge production={environment.production} />
                </div>
                <dl className="ppx__facts" data-testid="penv-facts">
                  <div className="ppx__fact">
                    <dt>Name</dt>
                    <dd className="ppx__mono">{environment.name}</dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Production</dt>
                    <dd>{environment.production ? 'Yes' : 'No'}</dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Contract required</dt>
                    <dd>{environment.contractRequired ? 'Yes — a version without a pact cannot be deployed here' : 'No'}</dd>
                  </div>
                </dl>
              </section>
              <section className="ppx__panel" aria-labelledby="penv-deployed-title">
                <div className="ppx__panel-head">
                  <h2 id="penv-deployed-title" className="ppx__title">
                    Deployed now
                  </h2>
                  <span className="ppx__meta">{environment.deployed.length}</span>
                </div>
                {environment.deployed.length === 0 ? (
                  <div className="ppx__empty-note" data-testid="penv-deployed-empty">
                    <p className="ppx__statement">Nothing is deployed here yet. Record each deployment from your pipeline:</p>
                    <CliSnippet label="Record a deployment" command={recordDeploymentInto(environment.name)} />
                  </div>
                ) : (
                  <CurrentDeploymentsTable deployments={environment.deployed} />
                )}
              </section>
              {environment.released.length > 0 ? (
                <section className="ppx__panel" aria-labelledby="penv-released-title">
                  <div className="ppx__panel-head">
                    <h2 id="penv-released-title" className="ppx__title">
                      Released and supported
                    </h2>
                    <span className="ppx__meta">{environment.released.length}</span>
                  </div>
                  <CurrentReleasesTable releases={environment.released} />
                </section>
              ) : null}
            </>
          )}
          <section className="ppx__panel" aria-labelledby="penv-history-title" data-testid="penv-history">
            <div className="ppx__panel-head">
              <h2 id="penv-history-title" className="ppx__title">
                Deployment history
              </h2>
              <span className="ppx__actions">
                <label className="ppx__field">
                  <span className="ppx__field-label">Pacticipant</span>
                  <select
                    className="ppx__select"
                    value={pacticipant}
                    onChange={(event) => setPacticipant(event.target.value)}
                    data-testid="penv-history-filter"
                  >
                    <option value="">All pacticipants</option>
                    {(environment ? environmentPacticipants(environment) : []).map((option) => (
                      <option key={option.slug} value={option.slug}>
                        {option.name}
                      </option>
                    ))}
                  </select>
                </label>
              </span>
            </div>
            {history.error && history.deployments.length === 0 ? (
              <EmptyState
                variant="compact"
                tone="danger"
                titleAs="h3"
                title="The history could not be read"
                description={history.error}
                action={
                  <Button variant="soft" onClick={() => void loadHistory(pacticipant, null)}>
                    <RefreshCw aria-hidden />
                    Try again
                  </Button>
                }
              />
            ) : history.loading && history.deployments.length === 0 ? (
              <LoadingState message="Reading the history…" minHeightClassName="min-h-[4rem]" />
            ) : history.deployments.length === 0 ? (
              <p className="ppx__muted" data-testid="penv-history-empty">
                {pacticipant ? 'This pacticipant was never deployed here.' : 'No deployment has been recorded here yet.'}
              </p>
            ) : (
              <>
                <HistoryTable deployments={history.deployments} />
                {history.error ? (
                  <p className="ppx__error" role="alert">
                    {history.error}
                  </p>
                ) : null}
                {history.nextCursor ? (
                  <div className="ppx__more">
                    <Button
                      variant="outline"
                      disabled={history.loading}
                      onClick={() => void loadHistory(pacticipant, history.nextCursor)}
                      data-testid="penv-history-more"
                    >
                      {history.loading ? 'Loading…' : 'Load more'}
                    </Button>
                  </div>
                ) : null}
              </>
            )}
          </section>
        </div>
      </PageBody>
    </Page>
  );
}
