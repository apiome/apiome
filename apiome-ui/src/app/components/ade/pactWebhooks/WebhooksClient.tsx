'use client';

/**
 * **Webhooks** — `/ade/dashboard/pacts/webhooks` (PFX-5.6, #6950).
 *
 * Every contract webhook of the workspace — what it is for, the events it fires on, where it
 * sends, whether it is enabled and signed, and its newest delivery — and the workspace's
 * **Recent deliveries**, newest first, narrowed by status. **New webhook** opens the editor, which
 * can **Test** the webhook before creating it. Each webhook opens its own page (edit, test,
 * enable or disable, delete, its delivery log); each delivery opens its execution log.
 *
 * A workspace with no webhook shows the CLI command that creates one.
 */

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { Plus, RefreshCw } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { ContractsTabs } from '../pactOverview/ContractsTabs';
import { CONTRACTS_ROUTE } from '@lib/pact-overview';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { CREATE_WEBHOOK_SNIPPET, webhookRoute, type WebhooksOverview } from '@lib/pact-webhooks';
import { CliSnippet } from '../pactPacticipants/PacticipantPanels';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { DeliveryLog, WebhookEditor, WebhooksTable } from './WebhookPanels';
import { createWebhook, fetchWebhooks, testUnsavedWebhook } from './webhooksApi';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The page's read. */
interface Loaded {
  data: WebhooksOverview | null;
  error: string | null;
}

/**
 * The Webhooks page.
 *
 * @returns The page.
 */
export default function WebhooksClient() {
  const router = useRouter();
  const [loaded, setLoaded] = React.useState<Loaded>({ data: null, error: null });
  const [editing, setEditing] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoaded({ data: null, error: null });
    try {
      setLoaded({ data: await fetchWebhooks(), error: null });
    } catch (caught) {
      setLoaded({ data: null, error: describeFailure(caught, 'Could not load the webhooks') });
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  const save = async (body: Record<string, unknown>) => {
    const created = await createWebhook(body);
    setEditing(false);
    router.push(webhookRoute(created.uuid));
  };

  const { data, error } = loaded;
  return (
    <Page>
      <PageHeader
        tabs={<ContractsTabs active="webhooks" />}
        title="Webhooks"
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Contracts', href: CONTRACTS_ROUTE },
          { label: 'Webhooks' },
        ]}
        description="Tell your CI when a pact needs verifying and when a verification finishes — and see every delivery."
        actions={
          <div className="ppx__actions">
            <Button variant="outline" onClick={() => void load()}>
              <RefreshCw aria-hidden />
              Refresh
            </Button>
            <Button onClick={() => setEditing(true)} data-testid="pwx-new">
              <Plus aria-hidden />
              New webhook
            </Button>
          </div>
        }
      />
      <PageBody>
        <div className="ppx pwx" data-testid="pact-webhooks">
          {error ? (
            <EmptyState
              variant="compact"
              tone="danger"
              titleAs="h2"
              title="The webhooks could not be read"
              description={error}
              action={
                <Button variant="soft" onClick={() => void load()}>
                  <RefreshCw aria-hidden />
                  Try again
                </Button>
              }
            />
          ) : data === null ? (
            <LoadingState message="Reading the webhooks…" minHeightClassName="min-h-[6rem]" />
          ) : data.webhooks.length === 0 ? (
            <EmptyState
              variant="compact"
              titleAs="h2"
              title="No webhooks yet"
              description="Choose New webhook, or create one from a pipeline:"
              action={<CliSnippet label="Create a webhook" command={CREATE_WEBHOOK_SNIPPET} />}
            />
          ) : (
            <>
              <p className="ppx__meta" data-testid="pwx-count">
                {data.webhooks.length} {data.webhooks.length === 1 ? 'webhook' : 'webhooks'} ·{' '}
                {data.webhooks.filter((webhook) => webhook.enabled).length} enabled
              </p>
              <WebhooksTable webhooks={data.webhooks} latest={data.latest} />
            </>
          )}
          {data && data.webhooks.length > 0 ? <DeliveryLog webhook={null} title="Recent deliveries" /> : null}
        </div>
        {editing ? (
          <WebhookEditor webhook={null} onSave={save} onTest={testUnsavedWebhook} onClose={() => setEditing(false)} />
        ) : null}
      </PageBody>
    </Page>
  );
}
