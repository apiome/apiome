'use client';

/**
 * One webhook delivery — `/ade/dashboard/pacts/webhooks/deliveries/{uuid}` (PFX-5.6, #6950).
 *
 * The execution log of one firing: its status, the webhook, the event and the pact that caused
 * it, and every attempt — what was sent and what came back, secrets already removed by REST — with
 * **Copy**. **Redeliver** sends a finished firing again as a new delivery (the original and its log
 * stay); a firing still queued or retrying, or one whose webhook is disabled, is refused with the
 * reason REST gives.
 */

import * as React from 'react';
import Link from 'next/link';
import { Copy, RefreshCw, RotateCcw } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { PACTICIPANTS_ROUTE, formatWhen } from '@lib/pact-pacticipants';
import { pactRoute, shortSha } from '@lib/pact-detail';
import {
  WEBHOOKS_ROUTE,
  canRedeliver,
  deliveryRoute,
  eventLabel,
  renderDeliveryLog,
  triggerTypeLabel,
  webhookRoute,
  type DeliveryDetail,
  type WebhookDelivery,
} from '@lib/pact-webhooks';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { DeliveryStatusBadge } from './WebhookPanels';
import { fetchDelivery, redeliverDelivery } from './webhooksApi';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The page's read. */
interface Loaded {
  data: DeliveryDetail | null;
  error: string | null;
}

/**
 * One delivery's page.
 *
 * @param props - The firing's `uuid` from the route.
 * @returns The page.
 */
export default function DeliveryDetailClient({ id }: { id: string }) {
  const [loaded, setLoaded] = React.useState<Loaded>({ data: null, error: null });
  const [copied, setCopied] = React.useState<string | null>(null);
  const [redelivering, setRedelivering] = React.useState(false);
  const [redelivered, setRedelivered] = React.useState<WebhookDelivery | null>(null);
  const [redeliverError, setRedeliverError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setLoaded({ data: null, error: null });
    try {
      setLoaded({ data: await fetchDelivery(id), error: null });
    } catch (caught) {
      setLoaded({ data: null, error: describeFailure(caught, 'Could not load the delivery') });
    }
  }, [id]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const delivery = loaded.data;
  const log = React.useMemo(() => (delivery ? renderDeliveryLog(delivery) : ''), [delivery]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(log);
      setCopied('The log is copied.');
    } catch {
      setCopied('The log could not be copied; select it and copy it instead.');
    }
  };

  const redeliver = async () => {
    setRedelivering(true);
    setRedeliverError(null);
    setRedelivered(null);
    try {
      setRedelivered(await redeliverDelivery(id));
    } catch (caught) {
      setRedeliverError(describeFailure(caught, 'The delivery could not be sent again.'));
    } finally {
      setRedelivering(false);
    }
  };

  const title = delivery ? `${eventLabel(delivery.eventName)} — ${formatWhen(delivery.triggeredAt)}` : 'Delivery';
  return (
    <Page>
      <PageHeader
        title={title}
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Pacticipants', href: PACTICIPANTS_ROUTE },
          { label: 'Webhooks', href: WEBHOOKS_ROUTE },
          ...(delivery ? [{ label: delivery.name, href: webhookRoute(delivery.webhookId) }] : []),
          { label: 'Delivery' },
        ]}
        description="One firing of a webhook: what each attempt sent and what came back."
        actions={
          <div className="ppx__actions">
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCw aria-hidden />
              Refresh
            </Button>
            {delivery ? (
              <Button
                onClick={() => void redeliver()}
                disabled={redelivering || !canRedeliver(delivery.status)}
                title={canRedeliver(delivery.status) ? undefined : 'Only a delivered or failed delivery can be sent again.'}
                data-testid="pwx-redeliver"
              >
                <RotateCcw aria-hidden />
                {redelivering ? 'Redelivering…' : 'Redeliver'}
              </Button>
            ) : null}
          </div>
        }
      />
      <PageBody>
        <div className="ppx pwx" data-testid="pact-webhook-delivery">
          {loaded.error ? (
            <EmptyState
              variant="compact"
              tone="danger"
              titleAs="h2"
              title="This delivery could not be read"
              description={loaded.error}
              action={
                <div className="ppx__actions">
                  <Button variant="soft" onClick={() => void load()}>
                    <RefreshCw aria-hidden />
                    Try again
                  </Button>
                  <Link className="ppx__link" href={WEBHOOKS_ROUTE}>
                    All webhooks
                  </Link>
                </div>
              }
            />
          ) : delivery === null ? (
            <LoadingState message="Reading the delivery…" minHeightClassName="min-h-[6rem]" />
          ) : (
            <>
              {redeliverError ? (
                <p className="ppx__error" role="alert" data-testid="pwx-redeliver-error">
                  {redeliverError}
                </p>
              ) : null}
              {redelivered ? (
                <p className="ppx__meta" role="status" data-testid="pwx-redelivered">
                  Queued again as a new delivery.{' '}
                  <Link className="ppx__link" href={deliveryRoute(redelivered.id)}>
                    Open the new delivery
                  </Link>
                </p>
              ) : null}
              <section className="ppx__panel" aria-labelledby="pwx-delivery-title" data-testid="pwx-delivery-overview">
                <div className="ppx__panel-head">
                  <h2 id="pwx-delivery-title" className="ppx__title">
                    Overview
                  </h2>
                  <DeliveryStatusBadge status={delivery.status} />
                </div>
                <dl className="ppx__facts">
                  <div className="ppx__fact">
                    <dt>Webhook</dt>
                    <dd>
                      <Link className="ppx__link" href={webhookRoute(delivery.webhookId)}>
                        {delivery.name}
                      </Link>
                    </dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Event</dt>
                    <dd>{eventLabel(delivery.eventName)}</dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Pact</dt>
                    <dd>
                      <Link
                        className="ppx__link"
                        href={pactRoute(delivery.consumer.slug, delivery.provider.slug, delivery.consumerVersionNumber)}
                      >
                        {delivery.consumer.name} → {delivery.provider.name}
                      </Link>
                      {delivery.pactVersionSha ? (
                        <span className="ppx__muted ppx__mono" title={delivery.pactVersionSha}>
                          {' '}
                          {shortSha(delivery.pactVersionSha)}
                        </span>
                      ) : null}
                    </dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Consumer version</dt>
                    <dd className="ppx__mono">{delivery.consumerVersionNumber ?? '—'}</dd>
                  </div>
                  {delivery.verificationNumber !== null ? (
                    <div className="ppx__fact">
                      <dt>Verification result</dt>
                      <dd>#{delivery.verificationNumber}</dd>
                    </div>
                  ) : null}
                  <div className="ppx__fact">
                    <dt>Attempts</dt>
                    <dd>
                      {delivery.attemptsMade}
                      {delivery.attemptsRemaining > 0 ? ` (${delivery.attemptsRemaining} left)` : ''}
                    </dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Trigger</dt>
                    <dd>{triggerTypeLabel(delivery.triggerType)}</dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Triggered</dt>
                    <dd className="ppx__when">{formatWhen(delivery.triggeredAt)}</dd>
                  </div>
                </dl>
              </section>

              <section className="ppx__panel" aria-labelledby="pwx-attempts-title" data-testid="pwx-attempts">
                <div className="ppx__panel-head">
                  <h2 id="pwx-attempts-title" className="ppx__title">
                    Execution log
                  </h2>
                  <Button variant="outline" size="sm" onClick={() => void copy()} data-testid="pwx-log-copy">
                    <Copy aria-hidden />
                    Copy
                  </Button>
                </div>
                {copied ? (
                  <p className="ppx__muted" role="status">
                    {copied}
                  </p>
                ) : null}
                {delivery.executions.length === 0 ? (
                  <p className="ppx__muted" data-testid="pwx-not-sent">
                    Not sent yet — the delivery is queued. Refresh in a few seconds.
                  </p>
                ) : (
                  <ol className="pvx-interactions">
                    {delivery.executions.map((execution) => (
                      <li key={execution.attempt}>
                        <details className="pvx-interaction" open={!execution.success}>
                          <summary className="pvx-interaction__summary">
                            <span className="pvx-interaction__name">Attempt {execution.attempt}</span>
                            <Badge variant={execution.success ? 'ok' : 'danger'}>
                              {execution.status ? `HTTP ${execution.status}` : execution.success ? 'Sent' : 'Not sent'}
                            </Badge>
                            <span className="ppx__muted ppx__when">{formatWhen(execution.createdAt)}</span>
                          </summary>
                          <div className="pvx-interaction__body">
                            <pre
                              className="ppx__snippet pwx-pre"
                              tabIndex={0}
                              aria-label={`Log of attempt ${execution.attempt}`}
                            >
                              {execution.logs || 'No log was recorded.'}
                            </pre>
                          </div>
                        </details>
                      </li>
                    ))}
                  </ol>
                )}
              </section>
            </>
          )}
        </div>
      </PageBody>
    </Page>
  );
}
