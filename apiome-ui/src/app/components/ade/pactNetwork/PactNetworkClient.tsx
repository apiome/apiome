'use client';

/**
 * **Network** — `/ade/dashboard/pacts/pacticipants/{handle}/network` (PFX-5.3, #6947).
 *
 * The pacticipants connected to one through pacts, drawn consumer → provider with each
 * integration's verdict:
 *
 * * **Diagram** — the network as a picture (`NetworkGraphSvg`): each edge is coloured and marked by
 *   the verdict of the integration's newest pact and opens that pact; each pacticipant opens its
 *   own network. A key names the verdicts with their counts. What the roll-up could not read is
 *   said above the picture.
 * * **Integrations** — every integration in the network as a table (the source of truth, and the
 *   keyboard-friendly way through it): the pact, its newest consumer version, when it was
 *   published and its verdict.
 *
 * ### What this page owns
 *
 * One read (the network, collected by the `/api/pact/*` proxy) with **Try again** and **Refresh**.
 * The layout is `networkLayoutModel`; the roll-up and wording are `@lib/pact-network`.
 */

import * as React from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import {
  PACTICIPANTS_ROUTE,
  PUBLISH_SNIPPET,
  formatWhen,
  pacticipantRoute,
  shortVersion,
} from '@lib/pact-pacticipants';
import { VERDICT_LABELS, pactRoute } from '@lib/pact-detail';
import {
  networkNotices,
  verdictCounts,
  type NetworkIntegration,
  type PactNetwork,
} from '@lib/pact-network';
import { CliSnippet } from '../pactPacticipants/PacticipantPanels';
import { describeFailure } from '../pactPacticipants/describeFailure';
import { VerdictBadge } from '../pactDetail/PactPanels';
import { NetworkGraphSvg, NetworkLegend } from './NetworkGraphSvg';
import { networkLayout } from './networkLayoutModel';
import { fetchPactNetwork } from './pactNetworkApi';

/** Where the breadcrumb's first step goes. */
const HOME_ROUTE = '/ade/dashboard';

/** The read: loading (`data` null, no error), failed (`error`), or loaded. */
type Loaded = { data: PactNetwork | null; error: string | null };

/**
 * Every integration of the network, as a table.
 *
 * @param props - The integrations.
 * @returns The table.
 */
export function NetworkIntegrationsTable({ integrations }: { integrations: NetworkIntegration[] }) {
  return (
    <div className="ppx__table-wrap">
      <table className="ppx__table" data-testid="pact-network-table">
        <caption className="sr-only">Integrations in this network</caption>
        <thead>
          <tr>
            <th scope="col">Pact</th>
            <th scope="col">Latest consumer version</th>
            <th scope="col">Published</th>
            <th scope="col">Verification</th>
          </tr>
        </thead>
        <tbody>
          {integrations.map((integration) => (
            <tr key={`${integration.consumer.slug}-${integration.provider.slug}`}>
              <th scope="row">
                <Link
                  className="ppx__link ppx__name"
                  href={pactRoute(integration.consumer.slug, integration.provider.slug)}
                  data-testid={`pnx-pact-${integration.consumer.slug}-${integration.provider.slug}`}
                >
                  {integration.consumer.name} → {integration.provider.name}
                </Link>
              </th>
              <td className="ppx__mono" title={integration.latestVersion}>
                {shortVersion(integration.latestVersion)}
              </td>
              <td className="ppx__when">{formatWhen(integration.publishedAt)}</td>
              <td>
                <VerdictBadge latest={integration.latestVerification} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The network page.
 *
 * @param props - The pacticipant's handle from the route.
 * @returns The page.
 */
export default function PactNetworkClient({ slug }: { slug: string }) {
  const [network, setNetwork] = React.useState<Loaded>({ data: null, error: null });

  const load = React.useCallback(async () => {
    setNetwork({ data: null, error: null });
    try {
      setNetwork({ data: await fetchPactNetwork(slug), error: null });
    } catch (caught) {
      setNetwork({ data: null, error: describeFailure(caught, 'Could not load the network') });
    }
  }, [slug]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const data = network.data;
  const name = data?.pacticipants.find((p) => p.slug === slug)?.name ?? slug;
  const layout = React.useMemo(() => (data ? networkLayout(data) : null), [data]);
  const notices = React.useMemo(() => (data ? networkNotices(data) : []), [data]);
  const counts = React.useMemo(() => verdictCounts(data?.integrations ?? []), [data]);

  return (
    <Page>
      <PageHeader
        title={`${name} network`}
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Pacticipants', href: PACTICIPANTS_ROUTE },
          { label: name, href: pacticipantRoute(slug) },
          { label: 'Network' },
        ]}
        description="The pacticipants connected through pacts, with the verdict of each integration."
        actions={
          <Button variant="outline" onClick={() => void load()}>
            <RefreshCw aria-hidden />
            Refresh
          </Button>
        }
      />
      <PageBody>
        <div className="ppx" data-testid="pact-network">
          {network.error ? (
            <EmptyState
              variant="compact"
              titleAs="h2"
              tone="danger"
              title="The network could not be read"
              description={network.error}
              action={
                <div className="ppx__actions">
                  <Button variant="soft" onClick={() => void load()}>
                    <RefreshCw aria-hidden />
                    Try again
                  </Button>
                  <Link className="ppx__link" href={PACTICIPANTS_ROUTE}>
                    All pacticipants
                  </Link>
                </div>
              }
            />
          ) : data === null || layout === null ? (
            <LoadingState message="Reading the network…" minHeightClassName="min-h-[6rem]" />
          ) : data.integrations.length === 0 ? (
            <div className="ppx__empty-note" data-testid="pnx-empty">
              <EmptyState
                variant="compact"
                titleAs="h2"
                title="No integrations yet"
                description={`No pact names ${name} yet, so it is not connected to any other pacticipant. A consumer's build publishes its pacts:`}
                action={
                  <Link className="ppx__link" href={pacticipantRoute(slug)}>
                    Back to {name}
                  </Link>
                }
              />
              <CliSnippet label="Publish a pact" command={PUBLISH_SNIPPET} />
            </div>
          ) : (
            <>
              <section
                className="ppx__panel"
                aria-labelledby="pnx-diagram-title"
                data-testid="pnx-diagram"
              >
                <div className="ppx__panel-head">
                  <h2 id="pnx-diagram-title" className="ppx__title">
                    Diagram
                  </h2>
                  <span className="ppx__meta" data-testid="pnx-summary">
                    {data.pacticipants.length} pacticipants · {data.integrations.length}{' '}
                    {data.integrations.length === 1 ? 'integration' : 'integrations'}
                  </span>
                </div>
                <p className="ppx__statement">
                  Each arrow points from a consumer to its provider and shows the verdict of the
                  newest pact. Select an arrow to open that pact, or a pacticipant to see its own
                  network.
                </p>
                <NetworkLegend counts={counts} labels={VERDICT_LABELS} />
                {notices.length > 0 ? (
                  <ul className="pnx-notices" data-testid="pnx-notices">
                    {notices.map((notice) => (
                      <li key={notice}>{notice}</li>
                    ))}
                  </ul>
                ) : null}
                <NetworkGraphSvg network={data} layout={layout} />
                {layout.hiddenNodes > 0 ? (
                  <p className="ppx__muted" data-testid="pnx-hidden">
                    {layout.hiddenNodes}{' '}
                    {layout.hiddenNodes === 1 ? 'pacticipant is' : 'pacticipants are'} not drawn in
                    a crowded column; their integrations are in the table.
                  </p>
                ) : null}
              </section>

              <section
                className="ppx__panel"
                aria-labelledby="pnx-integrations-title"
                data-testid="pnx-integrations"
              >
                <div className="ppx__panel-head">
                  <h2 id="pnx-integrations-title" className="ppx__title">
                    Integrations
                  </h2>
                  <span className="ppx__meta">{data.integrations.length}</span>
                </div>
                <NetworkIntegrationsTable integrations={data.integrations} />
              </section>
            </>
          )}
        </div>
      </PageBody>
    </Page>
  );
}
