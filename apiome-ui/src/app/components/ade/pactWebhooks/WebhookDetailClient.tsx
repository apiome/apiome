'use client';

/**
 * One webhook — `/ade/dashboard/pacts/webhooks/{uuid}` (PFX-5.6, #6950).
 *
 * What the webhook is for, the events it fires on and the request it sends (secrets read as
 * `**********`), with **Test** (send it once, now, and show what came back), **Edit**,
 * **Enable** / **Disable** and **Delete**, and its **Delivery log** — every firing newest first,
 * narrowed by status, each opening its execution log.
 */

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { Pencil, Power, RefreshCw, Send, Trash2 } from 'lucide-react';
import { Badge } from '@/app/components/ui/Badge';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { PACTICIPANTS_ROUTE, formatWhen } from '@lib/pact-pacticipants';
import {
  GITHUB_TARGET,
  WEBHOOKS_ROUTE,
  eventLabel,
  scopeLabel,
  toggleBody,
  type ExecutionResult,
  type WebhookDocument,
} from '@lib/pact-webhooks';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { DeleteWebhookDialog, DeliveryLog, TestOutcome, WebhookEditor } from './WebhookPanels';
import { deleteWebhook, fetchWebhook, replaceWebhook, testWebhook } from './webhooksApi';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The page's read. */
interface Loaded {
  data: WebhookDocument | null;
  error: string | null;
}

/** A request body as the page shows it. */
function bodyText(body: unknown): string {
  if (body === undefined || body === null) return '';
  return typeof body === 'string' ? body : JSON.stringify(body, null, 2);
}

/**
 * One webhook's page.
 *
 * @param props - The webhook's `uuid` from the route.
 * @returns The page.
 */
export default function WebhookDetailClient({ id }: { id: string }) {
  const router = useRouter();
  const [loaded, setLoaded] = React.useState<Loaded>({ data: null, error: null });
  const [editing, setEditing] = React.useState(false);
  const [deleting, setDeleting] = React.useState<WebhookDocument | null>(null);
  const [busy, setBusy] = React.useState<'test' | 'toggle' | 'delete' | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [tested, setTested] = React.useState<ExecutionResult | null>(null);

  const load = React.useCallback(async () => {
    setLoaded({ data: null, error: null });
    try {
      setLoaded({ data: await fetchWebhook(id), error: null });
    } catch (caught) {
      setLoaded({ data: null, error: describeFailure(caught, 'Could not load the webhook') });
    }
  }, [id]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const webhook = loaded.data;

  /** Run one action, showing its failure above the page. */
  const act = async (kind: 'test' | 'toggle' | 'delete', run: () => Promise<void>) => {
    setBusy(kind);
    setActionError(null);
    try {
      await run();
    } catch (caught) {
      setActionError(describeFailure(caught, 'The action could not be completed.'));
    } finally {
      setBusy(null);
    }
  };

  const test = () =>
    act('test', async () => {
      setTested(null);
      setTested(await testWebhook(id));
    });

  const toggle = () =>
    act('toggle', async () => {
      if (!webhook) return;
      setLoaded({ data: await replaceWebhook(id, toggleBody(webhook, !webhook.enabled)), error: null });
    });

  const remove = (target: WebhookDocument) => {
    setDeleting(null);
    void act('delete', async () => {
      await deleteWebhook(target.uuid);
      router.push(WEBHOOKS_ROUTE);
    });
  };

  const save = async (body: Record<string, unknown>) => {
    const saved = await replaceWebhook(id, body);
    setLoaded({ data: saved, error: null });
    setEditing(false);
  };

  const github = webhook?.target?.type === GITHUB_TARGET;
  return (
    <Page>
      <PageHeader
        title={webhook?.description ?? 'Webhook'}
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Pacticipants', href: PACTICIPANTS_ROUTE },
          { label: 'Webhooks', href: WEBHOOKS_ROUTE },
          { label: webhook?.description ?? 'Webhook' },
        ]}
        description="What this webhook sends and when, and every delivery it made."
        actions={
          webhook ? (
            <div className="ppx__actions">
              <Button variant="outline" onClick={() => void test()} disabled={busy !== null} data-testid="pwx-test">
                <Send aria-hidden />
                {busy === 'test' ? 'Testing…' : 'Test'}
              </Button>
              <Button variant="outline" onClick={() => setEditing(true)} disabled={busy !== null} data-testid="pwx-edit">
                <Pencil aria-hidden />
                Edit
              </Button>
              <Button variant="outline" onClick={() => void toggle()} disabled={busy !== null} data-testid="pwx-toggle">
                <Power aria-hidden />
                {webhook.enabled ? 'Disable' : 'Enable'}
              </Button>
              <Button
                variant="danger"
                onClick={() => setDeleting(webhook)}
                disabled={busy !== null}
                data-testid="pwx-delete"
              >
                <Trash2 aria-hidden />
                Delete
              </Button>
            </div>
          ) : null
        }
      />
      <PageBody>
        <div className="ppx pwx" data-testid="pact-webhook-detail">
          {loaded.error ? (
            <EmptyState
              variant="compact"
              tone="danger"
              titleAs="h2"
              title="This webhook could not be read"
              description={loaded.error}
              action={
                <Button variant="soft" onClick={() => void load()}>
                  <RefreshCw aria-hidden />
                  Try again
                </Button>
              }
            />
          ) : webhook === null ? (
            <LoadingState message="Reading the webhook…" minHeightClassName="min-h-[6rem]" />
          ) : (
            <>
              {actionError ? (
                <p className="ppx__error" role="alert" data-testid="pwx-action-error">
                  {actionError}
                </p>
              ) : null}
              <section className="ppx__panel" aria-labelledby="pwx-overview-title" data-testid="pwx-overview">
                <div className="ppx__panel-head">
                  <h2 id="pwx-overview-title" className="ppx__title">
                    Overview
                  </h2>
                  <Badge variant={webhook.enabled ? 'ok' : 'neutral'} data-testid="pwx-state">
                    {webhook.enabled ? 'Enabled' : 'Disabled'}
                  </Badge>
                  {webhook.signed ? <Badge variant="neutral">Signed</Badge> : null}
                </div>
                <dl className="ppx__facts">
                  <div className="ppx__fact">
                    <dt>For</dt>
                    <dd>{scopeLabel(webhook)}</dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Events</dt>
                    <dd>
                      <ul className="ppx__plain-list">
                        {webhook.events.map((event) => (
                          <li key={event.name}>{eventLabel(event.name)}</li>
                        ))}
                      </ul>
                    </dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Sends to</dt>
                    <dd className="ppx__mono">
                      {github ? `GitHub Actions · ${webhook.target?.repository}` : `${webhook.request.method} ${webhook.request.url}`}
                    </dd>
                  </div>
                  {github ? (
                    <div className="ppx__fact">
                      <dt>Event type</dt>
                      <dd className="ppx__mono">{webhook.target?.eventType ?? '${pactbroker.eventName}'}</dd>
                    </div>
                  ) : null}
                  <div className="ppx__fact">
                    <dt>Signing</dt>
                    <dd>{webhook.signed ? 'X-Apiome-Signature (HMAC-SHA256)' : 'Not signed'}</dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Created</dt>
                    <dd className="ppx__when">{formatWhen(webhook.createdAt)}</dd>
                  </div>
                  <div className="ppx__fact">
                    <dt>Changed</dt>
                    <dd className="ppx__when">{formatWhen(webhook.updatedAt ?? webhook.createdAt)}</dd>
                  </div>
                </dl>
              </section>

              {github ? null : (
                <section className="ppx__panel" aria-labelledby="pwx-request-title" data-testid="pwx-request">
                  <div className="ppx__panel-head">
                    <h2 id="pwx-request-title" className="ppx__title">
                      Request
                    </h2>
                  </div>
                  <pre className="ppx__snippet pwx-pre" tabIndex={0} aria-label="Request headers">
                    {Object.entries(webhook.request.headers ?? {})
                      .map(([name, value]) => `${name}: ${value}`)
                      .join('\n') || 'No headers'}
                    {webhook.request.username ? `\nBasic auth: ${webhook.request.username} / ${webhook.request.password ?? ''}` : ''}
                  </pre>
                  <pre className="ppx__snippet pwx-pre" tabIndex={0} aria-label="Request body">
                    {bodyText(webhook.request.body) || 'No body'}
                  </pre>
                </section>
              )}

              {tested ? (
                <section className="ppx__panel" aria-labelledby="pwx-test-title" data-testid="pwx-test-panel">
                  <div className="ppx__panel-head">
                    <h2 id="pwx-test-title" className="ppx__title">
                      Test run
                    </h2>
                    <span className="ppx__muted">Sent once, now; not queued or retried, and not in the delivery log.</span>
                  </div>
                  <TestOutcome result={tested} />
                </section>
              ) : null}

              <DeliveryLog webhook={id} title="Delivery log" />
            </>
          )}
        </div>
        {editing && webhook ? (
          <WebhookEditor webhook={webhook} onSave={save} onClose={() => setEditing(false)} />
        ) : null}
        <DeleteWebhookDialog webhook={deleting} onDelete={remove} onClose={() => setDeleting(null)} />
      </PageBody>
    </Page>
  );
}
