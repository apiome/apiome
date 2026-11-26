'use client';

/**
 * **Pair health** — `/ade/dashboard/pacts/health/{provider}/{consumer}` (PFX-6.3, #6955).
 *
 * One consumer ↔ provider pair: its state, every fused signal with why (and its reason code), the
 * window's analytics, and its **Trends** — pass rate, flakiness and mean duration per day (per week
 * over 90 days) — drawn as charts and listed in the **Trend** table. **Window** is kept in the
 * address. Links lead to the pact, the provider's Verification page and an open re-publish request.
 */

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { RefreshCw } from 'lucide-react';
import { Button, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { PACTICIPANTS_ROUTE } from '@lib/pact-pacticipants';
import { pactRoute } from '@lib/pact-detail';
import { verificationRoute } from '@lib/pact-verification';
import { requestRoute } from '@lib/pact-remediation';
import {
  HEALTH_WINDOWS,
  WINDOW_TEXT,
  healthRoute,
  pairHealthRoute,
  type HealthWindow,
  type PairHealthDetail,
} from '@lib/pact-health';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { Panel, SectionError } from '../pactVerification/PactVerificationClient';
import {
  HealthStateBadge,
  MetricsKpis,
  PairFacts,
  SignalList,
  TrendChart,
  TrendTable,
  trendSeries,
} from './HealthPanels';
import { fetchPairHealth } from './healthApi';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The detail read. */
type DetailRead = { data: PairHealthDetail | null; loading: boolean; error: string | null };

/**
 * The Pair health page.
 *
 * @param props - The provider's and consumer's handles and the `?window=` it was opened with.
 * @returns The page.
 */
export default function PairHealthClient({
  provider,
  consumer,
  window,
}: {
  provider: string;
  consumer: string;
  window: HealthWindow;
}) {
  const router = useRouter();
  const [read, setRead] = React.useState<DetailRead>({ data: null, loading: true, error: null });

  const load = React.useCallback(async () => {
    setRead((current) => ({ ...current, loading: true, error: null }));
    try {
      setRead({
        data: await fetchPairHealth(provider, consumer, window),
        loading: false,
        error: null,
      });
    } catch (caught) {
      setRead({
        data: null,
        loading: false,
        error: describeFailure(caught, "Could not load the pair's health"),
      });
    }
  }, [provider, consumer, window]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const data = read.data;
  const pair = data?.pair;
  const title = pair
    ? `${pair.consumer_name} → ${pair.provider_name}`
    : `${consumer} → ${provider}`;
  return (
    <Page>
      <PageHeader
        title={title}
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Pacticipants', href: PACTICIPANTS_ROUTE },
          { label: 'Contract health', href: healthRoute({ window }) },
          { label: title },
        ]}
        description="This pair's contract health: each signal fused into it, and how its verification has trended."
        actions={
          <div className="ppx__actions">
            <Button variant="outline" asChild>
              <Link href={pactRoute(consumer, provider)}>Pact</Link>
            </Button>
            <Button variant="outline" asChild>
              <Link href={verificationRoute(provider, consumer)}>Verification</Link>
            </Button>
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCw aria-hidden />
              Refresh
            </Button>
          </div>
        }
      />
      <PageBody>
        <div className="ppx phx" data-testid="pact-pair-health">
          {read.error ? (
            <SectionError
              title="This pair's health could not be read"
              error={read.error}
              onRetry={() => void load()}
            />
          ) : !data || !pair ? (
            <LoadingState
              message="Rolling up the pair's health…"
              minHeightClassName="min-h-[4rem]"
            />
          ) : (
            <>
              <Panel
                id="phx-overview"
                title="Health"
                aside={
                  <label className="pmx-field pvx-filter" htmlFor="phx-pair-window">
                    <span className="sr-only">Window</span>
                    <select
                      id="phx-pair-window"
                      className="pmx-input pmx-select--narrow"
                      value={window}
                      onChange={(event) =>
                        router.replace(pairHealthRoute(provider, consumer, event.target.value))
                      }
                      data-testid="phx-window"
                    >
                      {HEALTH_WINDOWS.map((option) => (
                        <option key={option} value={option}>
                          {WINDOW_TEXT[option]}
                        </option>
                      ))}
                    </select>
                  </label>
                }
              >
                <div className="phx-verdict" data-testid="phx-verdict">
                  <HealthStateBadge state={pair.state} />
                  {pair.republish_request_id ? (
                    <Link className="ppx__link" href={requestRoute(pair.republish_request_id)}>
                      Open re-publish request
                    </Link>
                  ) : null}
                </div>
                <PairFacts pair={pair} />
                <MetricsKpis metrics={pair.metrics} />
              </Panel>
              <Panel id="phx-signals-panel" title="Signals">
                <SignalList components={pair.components} />
              </Panel>
              <Panel id="phx-trends" title="Trends">
                <div className="phx-charts">
                  {trendSeries(data.trend).map((series) => (
                    <TrendChart key={series.key} series={series} trend={data.trend} />
                  ))}
                </div>
                <p className="ppx__muted" data-testid="phx-untimed">
                  {pair.metrics.timed_runs < pair.metrics.runs
                    ? `${pair.metrics.runs - pair.metrics.timed_runs} of ${pair.metrics.runs} results carry no duration (published by a verifier outside Apiome) and are left out of the mean duration.`
                    : 'Every result in the window carries its duration.'}
                </p>
              </Panel>
              <Panel id="phx-trend" title="Trend">
                <TrendTable trend={data.trend} bucketDays={data.bucket_days} />
              </Panel>
            </>
          )}
        </div>
      </PageBody>
    </Page>
  );
}
