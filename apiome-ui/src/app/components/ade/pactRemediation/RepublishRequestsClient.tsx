'use client';

/**
 * **Re-publish requests** — `/ade/dashboard/pacts/republish-requests` (PFX-6.2, #6954).
 *
 * Every request the remediation sweep opened when a pact went stale, newest first: the pair, the
 * stale pact, its state (requested, acknowledged, re-published, cleared, expired), when it expires
 * and whether the consumer's owners were notified. **State** narrows the list (kept in the address
 * as `?state=`, default `open`); **Load more** pages. Each request opens its own page, where the
 * consumer acknowledges it.
 */

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { RefreshCw } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { formatWhen, shortVersion } from '@lib/pact-pacticipants';
import { pactRoute, shortSha } from '@lib/pact-detail';
import {
  REQUEST_STATES,
  requestRoute,
  requestsRoute,
  stateText,
  type RepublishRequest,
} from '@lib/pact-remediation';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { Panel, SectionError } from '../pactVerification/PactVerificationClient';
import { fetchRequests } from './remediationApi';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The list read. */
type ListRead = {
  requests: RepublishRequest[];
  next: string | null;
  loaded: boolean;
  loading: boolean;
  error: string | null;
};

/**
 * A request's state as a badge.
 *
 * @param props - The state.
 * @returns The badge.
 */
export function RequestStateBadge({ state }: { state: string }) {
  const text = stateText(state);
  return (
    <Badge variant={text.variant} data-testid="prx-state" title={text.description}>
      {text.label}
    </Badge>
  );
}

/**
 * The requests table.
 *
 * @param props - The requests.
 * @returns The table.
 */
export function RequestsTable({ requests }: { requests: RepublishRequest[] }) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="prx-requests-table">
        <caption className="sr-only">Re-publish requests, newest first</caption>
        <thead>
          <tr>
            <th scope="col">Request</th>
            <th scope="col">Pact</th>
            <th scope="col">State</th>
            <th scope="col">Requested</th>
            <th scope="col">Expires</th>
          </tr>
        </thead>
        <tbody>
          {requests.map((request) => (
            <tr key={request.id} data-testid={`prx-request-${request.id}`}>
              <th scope="row">
                <Link className="ppx__link ppx__name" href={requestRoute(request.id)}>
                  {request.consumer_name} → {request.provider_name}
                </Link>
              </th>
              <td>
                <Link className="ppx__link ppx__mono" href={pactRoute(request.consumer, request.provider)}>
                  {shortVersion(request.consumer_version)}
                </Link>{' '}
                <span className="ppx__muted ppx__mono" title={request.pact_version_sha}>
                  {shortSha(request.pact_version_sha)}
                </span>
              </td>
              <td>
                <RequestStateBadge state={request.state} />
              </td>
              <td className="ppx__when">{request.requested_at ? formatWhen(request.requested_at) : '—'}</td>
              <td className="ppx__when">
                {request.resolved_at ? (
                  <span className="ppx__muted">Closed {formatWhen(request.resolved_at)}</span>
                ) : request.expires_at ? (
                  formatWhen(request.expires_at)
                ) : (
                  '—'
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The Re-publish requests page.
 *
 * @param props - The `?state=` filter (`open` by default; `all` for every state).
 * @returns The page.
 */
export default function RepublishRequestsClient({ state }: { state: string }) {
  const router = useRouter();
  const [list, setList] = React.useState<ListRead>({
    requests: [],
    next: null,
    loaded: false,
    loading: true,
    error: null,
  });
  const filter = state === 'all' ? null : state;

  const load = React.useCallback(
    async (cursor?: string | null) => {
      setList((current) => ({
        ...current,
        loading: true,
        error: null,
        ...(cursor ? {} : { loaded: false, requests: [] }),
      }));
      try {
        const page = await fetchRequests({ state: filter, cursor });
        setList((current) => ({
          requests: cursor ? [...current.requests, ...page.requests] : page.requests,
          next: page.next_cursor,
          loaded: true,
          loading: false,
          error: null,
        }));
      } catch (caught) {
        setList((current) => ({
          ...current,
          loading: false,
          error: describeFailure(caught, 'Could not load the re-publish requests'),
        }));
      }
    },
    [filter],
  );

  React.useEffect(() => {
    void load();
  }, [load]);

  return (
    <Page>
      <PageHeader
        tabs={<ContractsTabs active="health" />}
        title="Re-publish requests"
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Contracts', href: CONTRACTS_ROUTE },
          { label: 'Re-publish requests' },
        ]}
        description="When a pact goes unverified past its stale threshold, its consumer is asked to re-publish it. Each request is tracked until it is answered or expires."
        actions={
          <Button variant="outline" onClick={() => void load()}>
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        }
      />
      <PageBody>
        <div className="ppx prx" data-testid="pact-republish-requests">
          <Panel
            id="prx-requests"
            title="Requests"
            aside={
              <label className="pmx-field pvx-filter" htmlFor="prx-state-filter">
                <span className="sr-only">State</span>
                <select
                  id="prx-state-filter"
                  className="pmx-input pmx-select--narrow"
                  value={state}
                  onChange={(event) => router.replace(requestsRoute({ state: event.target.value }))}
                  data-testid="prx-state-filter"
                >
                  <option value="open">Open</option>
                  <option value="all">Every state</option>
                  {REQUEST_STATES.map((option) => (
                    <option key={option} value={option}>
                      {stateText(option).label}
                    </option>
                  ))}
                </select>
              </label>
            }
          >
            {list.error && !list.loaded ? (
              <SectionError
                title="The re-publish requests could not be read"
                error={list.error}
                onRetry={() => void load()}
              />
            ) : !list.loaded ? (
              <LoadingState message="Reading the re-publish requests…" minHeightClassName="min-h-[4rem]" />
            ) : list.requests.length === 0 ? (
              <EmptyState
                variant="compact"
                titleAs="h3"
                title={filter === 'open' ? 'No open re-publish requests' : 'No re-publish requests'}
                description="A request opens when a pact has not been verified for longer than its stale threshold. Change the threshold, or turn requests off, on Verification settings."
                data-testid="prx-requests-empty"
              />
            ) : (
              <>
                <RequestsTable requests={list.requests} />
                {list.error ? <p className="ppx__error">{list.error}</p> : null}
                {list.next ? (
                  <div className="ppx__more">
                    <Button
                      variant="outline"
                      onClick={() => void load(list.next)}
                      disabled={list.loading}
                      data-testid="prx-requests-more"
                    >
                      {list.loading ? 'Loading…' : 'Load more'}
                    </Button>
                  </div>
                ) : null}
              </>
            )}
          </Panel>
        </div>
      </PageBody>
    </Page>
  );
}
