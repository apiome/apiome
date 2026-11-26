'use client';

/**
 * **Contract health** — `/ade/dashboard/pacts/health` (PFX-6.3, #6955).
 *
 * Every consumer ↔ provider pair with a pact, rolled up into one state (healthy, degraded, failing,
 * unknown) from the broker's signals — the newest pact's latest verdict, the window's pass rate and
 * flakiness, overdue, an open re-publish request and failed webhook deliveries — worst first, with
 * the window's analytics. **Window** (7, 30 or 90 days) and **State** are kept in the address. Each
 * pair opens its own page with the signals and the trends.
 */

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { RefreshCw } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { PACTICIPANTS_ROUTE, formatWhen } from '@lib/pact-pacticipants';
import { SETTINGS_ROUTE } from '@lib/pact-remediation';
import {
  HEALTH_STATES,
  HEALTH_WINDOWS,
  WINDOW_TEXT,
  healthRoute,
  healthStateText,
  type HealthOverview,
  type HealthWindow,
} from '@lib/pact-health';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { Panel, SectionError } from '../pactVerification/PactVerificationClient';
import { HealthKpis, PairsTable } from './HealthPanels';
import { fetchHealth } from './healthApi';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The overview read. */
type OverviewRead = { data: HealthOverview | null; loading: boolean; error: string | null };

/**
 * The window and state pickers.
 *
 * @param props - The current window and state, and where a change goes.
 * @returns The pickers.
 */
export function HealthFilters({
  window,
  state,
  onChange,
}: {
  window: HealthWindow;
  state: string | null;
  onChange: (next: { window: HealthWindow; state: string | null }) => void;
}) {
  return (
    <div className="phx-filters">
      <label className="pmx-field pvx-filter" htmlFor="phx-window">
        <span className="sr-only">Window</span>
        <select
          id="phx-window"
          className="pmx-input pmx-select--narrow"
          value={window}
          onChange={(event) => onChange({ window: event.target.value as HealthWindow, state })}
          data-testid="phx-window"
        >
          {HEALTH_WINDOWS.map((option) => (
            <option key={option} value={option}>
              {WINDOW_TEXT[option]}
            </option>
          ))}
        </select>
      </label>
      <label className="pmx-field pvx-filter" htmlFor="phx-state-filter">
        <span className="sr-only">State</span>
        <select
          id="phx-state-filter"
          className="pmx-input pmx-select--narrow"
          value={state ?? ''}
          onChange={(event) => onChange({ window, state: event.target.value || null })}
          data-testid="phx-state-filter"
        >
          <option value="">Every state</option>
          {HEALTH_STATES.map((option) => (
            <option key={option} value={option}>
              {healthStateText(option).label}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}

/**
 * The Contract health page.
 *
 * @param props - The `?window=` and `?state=` it was opened with.
 * @returns The page.
 */
export default function HealthClient({
  window,
  state,
}: {
  window: HealthWindow;
  state: string | null;
}) {
  const router = useRouter();
  const [read, setRead] = React.useState<OverviewRead>({ data: null, loading: true, error: null });

  const load = React.useCallback(async () => {
    setRead((current) => ({ ...current, loading: true, error: null }));
    try {
      setRead({ data: await fetchHealth({ window, state }), loading: false, error: null });
    } catch (caught) {
      setRead({
        data: null,
        loading: false,
        error: describeFailure(caught, 'Could not load the contract health'),
      });
    }
  }, [window, state]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const data = read.data;
  return (
    <Page>
      <PageHeader
        title="Contract health"
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Pacticipants', href: PACTICIPANTS_ROUTE },
          { label: 'Contract health' },
        ]}
        description="Each consumer and provider pair, rolled up into one state from its verification results, staleness, re-publish requests and webhook deliveries."
        actions={
          <div className="ppx__actions">
            <Button variant="outline" asChild>
              <Link href={SETTINGS_ROUTE}>Verification settings</Link>
            </Button>
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCw aria-hidden />
              Refresh
            </Button>
          </div>
        }
      />
      <PageBody>
        <div className="ppx phx" data-testid="pact-health">
          {data ? <HealthKpis counts={data.counts} totals={data.totals} /> : null}
          <Panel
            id="phx-pairs"
            title="Pairs"
            aside={
              <HealthFilters
                window={window}
                state={state}
                onChange={(next) => router.replace(healthRoute(next))}
              />
            }
          >
            {read.error ? (
              <SectionError
                title="The contract health could not be read"
                error={read.error}
                onRetry={() => void load()}
              />
            ) : !data ? (
              <LoadingState
                message="Rolling up the contract health…"
                minHeightClassName="min-h-[4rem]"
              />
            ) : data.pairs.length === 0 ? (
              <EmptyState
                variant="compact"
                titleAs="h3"
                title={
                  state ? `No ${healthStateText(state).label.toLowerCase()} pairs` : 'No pacts yet'
                }
                description={
                  state
                    ? 'No pair is in this state over the window. Choose another state, or every state.'
                    : 'A pair appears here once a consumer publishes a pact for a provider.'
                }
                data-testid="phx-pairs-empty"
              />
            ) : (
              <>
                <PairsTable pairs={data.pairs} window={window} />
                {data.truncated ? (
                  <p className="ppx__muted" data-testid="phx-truncated">
                    {data.omitted_pairs} more pairs are not listed. Narrow the list by state.
                  </p>
                ) : null}
              </>
            )}
            {data ? (
              <p className="ppx__muted phx-generated" data-testid="phx-generated">
                Computed {formatWhen(data.generated_at)} from {formatWhen(data.since)} to{' '}
                {formatWhen(data.until)}.
              </p>
            ) : null}
          </Panel>
        </div>
      </PageBody>
    </Page>
  );
}
