'use client';

/**
 * **A re-publish request** — `/ade/dashboard/pacts/republish-requests/{id}` (PFX-6.2, #6954).
 *
 * The stale pact (consumer version and pact version), the threshold it crossed and when it was last
 * verified, the request's state and its timeline (requested, acknowledged, closed), what notifying
 * the consumer's owners — and escalating on expiry — did, and the webhook deliveries it queued.
 * While the request is open the consumer can **Acknowledge** it with a note; the request still
 * expires at the end of its window unless the pact is re-published or verified.
 */

import * as React from 'react';
import Link from 'next/link';
import { CheckCircle2, RefreshCw } from 'lucide-react';
import { Button, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { formatWhen } from '@lib/pact-pacticipants';
import { pactRoute } from '@lib/pact-detail';
import { verificationRoute } from '@lib/pact-verification';
import {
  MAX_NOTE_LENGTH,
  REQUESTS_ROUTE,
  formatHours,
  isOpen,
  notificationText,
  stateText,
  type RepublishRequest,
} from '@lib/pact-remediation';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { Panel, SectionError } from '../pactVerification/PactVerificationClient';
import { RequestStateBadge } from './RepublishRequestsClient';
import { acknowledgeRequest, fetchRequest } from './remediationApi';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/**
 * The acknowledge form of an open request.
 *
 * @param props - The request and what acknowledging does.
 * @returns The form.
 */
function AcknowledgeForm({
  request,
  onAcknowledge,
}: {
  request: RepublishRequest;
  onAcknowledge: (note: string) => Promise<void>;
}) {
  const [note, setNote] = React.useState(request.note ?? '');
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onAcknowledge(note);
    } catch (caught) {
      setError(describeFailure(caught, 'Could not acknowledge the request'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="prx-form" onSubmit={(event) => void submit(event)} data-testid="prx-acknowledge-form">
      <label className="pmx-field" htmlFor="prx-note">
        <span className="ppx__field-label">Note (optional)</span>
        <textarea
          id="prx-note"
          className="pmx-input prx-note"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          maxLength={MAX_NOTE_LENGTH}
          rows={3}
          placeholder="Re-publishing from the main branch build on Friday."
          disabled={busy}
        />
      </label>
      <div className="prx-form__actions">
        <Button type="submit" disabled={busy} data-testid="prx-acknowledge">
          <CheckCircle2 aria-hidden />
          {busy ? 'Acknowledging…' : request.state === 'acknowledged' ? 'Update note' : 'Acknowledge'}
        </Button>
        {error ? (
          <span className="ppx__error" role="alert">
            {error}
          </span>
        ) : null}
      </div>
      <p className="ppx__muted">
        Acknowledging tells the provider&apos;s team you are on it. The request still expires{' '}
        {request.expires_at ? formatWhen(request.expires_at) : 'at the end of its window'} unless the pact is
        re-published or verified first.
      </p>
    </form>
  );
}

/**
 * One re-publish request's page.
 *
 * @param props - The request's id.
 * @returns The page.
 */
export default function RepublishRequestClient({ id }: { id: string }) {
  const [request, setRequest] = React.useState<RepublishRequest | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setError(null);
    setRequest(null);
    try {
      setRequest(await fetchRequest(id));
    } catch (caught) {
      setError(describeFailure(caught, 'Could not load the re-publish request'));
    }
  }, [id]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const title = request ? `${request.consumer_name} → ${request.provider_name}` : 'Re-publish request';
  const state = request ? stateText(request.state) : null;

  return (
    <Page>
      <PageHeader
        tabs={<ContractsTabs active="health" />}
        title={title}
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Contracts', href: CONTRACTS_ROUTE },
          { label: 'Re-publish requests', href: REQUESTS_ROUTE },
          { label: 'Request' },
        ]}
        description="A request to the consumer to re-publish a pact that went unverified past its stale threshold."
        actions={
          <Button variant="outline" onClick={() => void load()}>
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        }
      />
      <PageBody>
        <div className="ppx prx" data-testid="pact-republish-request">
          {error ? (
            <SectionError title="The re-publish request could not be read" error={error} onRetry={() => void load()} />
          ) : request === null ? (
            <LoadingState message="Reading the re-publish request…" minHeightClassName="min-h-[4rem]" />
          ) : (
            <>
              <Panel id="prx-overview" title="Overview" aside={<RequestStateBadge state={request.state} />}>
                <p className="ppx__statement" data-testid="prx-state-text">
                  {state?.description}
                </p>
                <dl className="prx-facts" data-testid="prx-facts">
                  <div>
                    <dt>Pact</dt>
                    <dd>
                      <Link className="ppx__link ppx__mono" href={pactRoute(request.consumer, request.provider)}>
                        {request.consumer_version}
                      </Link>{' '}
                      <span className="ppx__muted ppx__mono">{request.pact_version_sha.slice(0, 12)}</span>
                    </dd>
                  </div>
                  <div>
                    <dt>Stale threshold</dt>
                    <dd>{formatHours(request.threshold_hours)}</dd>
                  </div>
                  <div>
                    <dt>Last verified or published</dt>
                    <dd>{request.reference_at ? formatWhen(request.reference_at) : '—'}</dd>
                  </div>
                  <div>
                    <dt>Requested</dt>
                    <dd>{request.requested_at ? formatWhen(request.requested_at) : '—'}</dd>
                  </div>
                  <div>
                    <dt>{isOpen(request.state) ? 'Expires' : 'Window ended'}</dt>
                    <dd>{request.expires_at ? formatWhen(request.expires_at) : '—'}</dd>
                  </div>
                  {request.acknowledged_at ? (
                    <div>
                      <dt>Acknowledged</dt>
                      <dd>
                        {formatWhen(request.acknowledged_at)}
                        {request.acknowledged_by ? ` by ${request.acknowledged_by}` : ''}
                      </dd>
                    </div>
                  ) : null}
                  {request.resolved_at ? (
                    <div>
                      <dt>Closed</dt>
                      <dd>
                        {formatWhen(request.resolved_at)}
                        {request.resolved_consumer_version ? ` (version ${request.resolved_consumer_version})` : ''}
                      </dd>
                    </div>
                  ) : null}
                </dl>
                {request.note ? (
                  <blockquote className="prx-quote" data-testid="prx-note-text">
                    {request.note}
                  </blockquote>
                ) : null}
                <p className="ppx__muted">
                  <Link className="ppx__link" href={verificationRoute(request.provider, request.consumer)}>
                    {request.provider_name} verification
                  </Link>
                </p>
              </Panel>
              <Panel id="prx-notified" title="Who was told">
                <dl className="prx-facts" data-testid="prx-notified-facts">
                  <div>
                    <dt>Consumer&apos;s owners</dt>
                    <dd>{notificationText(request.notification_status)}</dd>
                  </div>
                  {request.state === 'expired' ? (
                    <div>
                      <dt>Escalation</dt>
                      <dd>{notificationText(request.escalation_status)}</dd>
                    </div>
                  ) : null}
                  <div>
                    <dt>Webhook deliveries</dt>
                    <dd>{request.webhook_deliveries}</dd>
                  </div>
                </dl>
              </Panel>
              {isOpen(request.state) ? (
                <Panel id="prx-acknowledge-panel" title="Acknowledge">
                  <AcknowledgeForm
                    request={request}
                    onAcknowledge={async (note) => {
                      setRequest(await acknowledgeRequest(request.id, note));
                    }}
                  />
                </Panel>
              ) : null}
            </>
          )}
        </div>
      </PageBody>
    </Page>
  );
}
