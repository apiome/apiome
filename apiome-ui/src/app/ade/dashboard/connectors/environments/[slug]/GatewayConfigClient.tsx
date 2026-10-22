'use client';

/**
 * Bring in → Connectors → one environment — `/ade/dashboard/connectors/environments/[slug]`
 * (CDG-5.3, #5981).
 *
 * A **gateway config** is one (connector, environment), refreshed by every sync of its connector.
 * **Overview**: the APIs the environment serves (each linking to its catalog item or Project), the
 * auth and rate-limit posture read from their imported gateway configuration (names and schemes
 * only — credentials are redacted at import), what a gateway configuration cannot carry, and the
 * owner team. **Push back** exports a governed catalog item back to the gateway's own format, with
 * the fidelity report shown before anything is exported — Kong, AWS API Gateway, Azure APIM and
 * Apigee, each to its own format (FMT-7.7). **Graph**: the APIs `deployed_on` this environment.
 */

import * as React from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { RefreshCw, Upload } from 'lucide-react';

import PageHeader from '@/app/components/shell/PageHeader';
import { Page, PageBody } from '@/app/components/shell/pageChrome';
import { Alert, Badge, Button, EmptyState, GatedState, LoadingState } from '@/app/components/ui';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/app/components/ui/Tabs';
import { DependenciesPanel } from '@/app/components/ade/graph/DependenciesPanel';
import { EntityOwnerSection } from '@/app/components/ade/catalogAgents/EntityOwnerSection';
import { CatalogFactsPanel } from '@/app/components/ade/catalogFacts/CatalogFactsPanel';
import ExportDialog from '@/app/components/ade/dashboard/export/ExportDialog';
import { exportStudioHref } from '@/app/components/ade/dashboard/export/exportStudioLink';
import { fetchGatewayConfig } from '@/app/components/ade/gatewayConfigs/gatewayConfigsApi';
import { useAuthSession } from '@lib/auth/session-client';
import { isFeatureReleased } from '@lib/feature-release';
import {
  pushBackUnavailable,
  servedApiHref,
  type GatewayConfig,
  type GatewayServedApi,
} from '@lib/gateway-configs';

const HOME_ROUTE = '/ade/dashboard';
const CONNECTORS_ROUTE = '/ade/dashboard/connectors';

/** Props for {@link GatewayConfigClient}. */
export interface GatewayConfigClientProps {
  /** The gateway config's slug (or id), from the route. */
  slug: string;
}

/**
 * The gateway config page.
 *
 * @param props - See {@link GatewayConfigClientProps}.
 * @returns The page.
 */
export default function GatewayConfigClient({ slug }: GatewayConfigClientProps) {
  const router = useRouter();
  const { data: session } = useAuthSession();
  const tenantId = (session?.user as { current_tenant_id?: string } | undefined)?.current_tenant_id;
  const [config, setConfig] = React.useState<GatewayConfig | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [tab, setTab] = React.useState('overview');
  const [pushing, setPushing] = React.useState<GatewayServedApi | null>(null);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setConfig(await fetchGatewayConfig(slug));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the gateway config');
    }
  }, [slug]);

  React.useEffect(() => {
    if (tenantId) void load();
  }, [tenantId, load]);

  /** Push one served API back to the gateway's format: the Studio's Verify step, or the dialog. */
  const pushBack = (api: GatewayServedApi) => {
    if (!config?.pushBack.target || !api.projectId) return;
    if (isFeatureReleased('export-studio')) {
      router.push(
        exportStudioHref({
          artifact: api.projectId,
          label: api.projectName ?? api.name,
          target: config.pushBack.target,
          origin: 'gateway-config',
          step: 'verify',
        }),
      );
      return;
    }
    setPushing(api);
  };

  const title = config?.name ?? slug;
  const unavailable = config ? pushBackUnavailable(config.pushBack) : null;

  return (
    <Page>
      <PageHeader
        breadcrumb={[
          { label: 'Home', href: HOME_ROUTE },
          { label: 'Bring in' },
          { label: 'Connectors', href: CONNECTORS_ROUTE },
          ...(config ? [{ label: config.connector.name, href: `${CONNECTORS_ROUTE}/${encodeURIComponent(config.connector.id)}` }] : []),
          { label: config?.environment || 'Environment' },
        ]}
        title={title}
        description="A gateway environment: the APIs it serves, and its auth and rate-limit posture."
      />
      <PageBody>
        {!tenantId ? (
          <GatedState description="Gateway configs belong to one workspace." />
        ) : error && !config ? (
          <EmptyState
            variant="compact"
            surface={false}
            tone="danger"
            title="The gateway config could not be read"
            description={error}
            action={
              <Button variant="soft" onClick={() => void load()}>
                <RefreshCw aria-hidden />
                Try again
              </Button>
            }
          />
        ) : !config ? (
          <LoadingState message="Reading the gateway config…" minHeightClassName="min-h-[8rem]" />
        ) : (
          <div className="gwc-page" data-testid="gateway-config-detail">
            <dl className="gwc-facts">
              <div>
                <dt>Connector</dt>
                <dd>
                  <Link className="gwc-link" href={`${CONNECTORS_ROUTE}/${encodeURIComponent(config.connector.id)}`}>
                    {config.connector.name}
                  </Link>
                </dd>
              </div>
              <div>
                <dt>Environment</dt>
                <dd className="mono">{config.environment || '—'}</dd>
              </div>
              <div>
                <dt>Gateway</dt>
                <dd>{config.flavor}</dd>
              </div>
              <div>
                <dt>APIs served</dt>
                <dd className="gwc-num">{config.apiCount}</dd>
              </div>
              <div>
                <dt>Last synced</dt>
                <dd>{config.lastSyncedAt ? new Date(config.lastSyncedAt).toLocaleString() : '—'}</dd>
              </div>
            </dl>

            <Tabs value={tab} onValueChange={setTab}>
              <TabsList aria-label="Gateway config">
                <TabsTrigger value="overview" data-testid="gateway-config-tab-overview">
                  Overview
                </TabsTrigger>
                <TabsTrigger value="graph" data-testid="gateway-config-tab-graph">
                  Graph
                </TabsTrigger>
              </TabsList>
              <TabsContent value="overview" className="gwc-page">
                <ServedApis config={config} unavailable={unavailable} onPushBack={pushBack} />
                <PostureSection config={config} />
                <EntityOwnerSection kind="gateway_config" entityId={config.id} owner={config.owner} onChanged={() => void load()} />
                <CatalogFactsPanel kind="gateway_config" id={config.id} active={tab === 'overview'} />
              </TabsContent>
              <TabsContent value="graph">
                <DependenciesPanel
                  kind="gateway_config"
                  id={config.id}
                  active={tab === 'graph'}
                  label={{ name: config.name, slug: config.slug, owner: null }}
                />
              </TabsContent>
            </Tabs>
          </div>
        )}
      </PageBody>
      {config && pushing?.projectId ? (
        <ExportDialog
          open
          onClose={() => setPushing(null)}
          artifact={pushing.projectId}
          artifactLabel={pushing.projectName ?? pushing.name}
          studioOrigin="gateway-config"
          initialTarget={config.pushBack.target}
        />
      ) : null}
    </Page>
  );
}

/** The APIs the environment serves, with Push back. */
function ServedApis({
  config,
  unavailable,
  onPushBack,
}: {
  config: GatewayConfig;
  unavailable: string | null;
  onPushBack: (api: GatewayServedApi) => void;
}) {
  return (
    <section className="gwc-section" aria-labelledby="gwc-apis" data-testid="gateway-config-apis">
      <h2 id="gwc-apis" className="gwc-section__title">
        APIs served
      </h2>
      {unavailable ? (
        <p className="gwc-muted" data-testid="gateway-config-push-back-unavailable">
          {unavailable}
        </p>
      ) : null}
      {config.apis.length === 0 ? (
        <p className="gwc-muted">The last sync saw no APIs in this environment.</p>
      ) : (
        <div className="gwc-table-wrap">
          <table className="gwc-table">
            <caption className="sr-only">APIs {config.name} serves</caption>
            <thead>
              <tr>
                <th scope="col">API</th>
                <th scope="col">Route</th>
                <th scope="col">In the catalog</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {config.apis.map((api) => {
                const href = servedApiHref(api);
                return (
                  <tr key={api.itemId} data-testid={`gateway-config-api-${api.itemId}`}>
                    <td>
                      <span className="gwc-strong">{api.name}</span>
                      {api.status !== 'imported' ? <Badge variant="neutral">{api.status}</Badge> : null}
                    </td>
                    <td className="mono gwc-muted">
                      {api.hosts[0] ?? ''}
                      {api.basePath ?? ''}
                    </td>
                    <td>
                      {href ? (
                        <Link className="gwc-link" href={href}>
                          {api.projectName ?? api.name}
                        </Link>
                      ) : (
                        <span className="gwc-muted">Not imported</span>
                      )}
                    </td>
                    <td>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={Boolean(unavailable) || !api.projectId}
                        title={unavailable ?? undefined}
                        onClick={() => onPushBack(api)}
                        data-testid={`gateway-config-push-back-${api.itemId}`}
                      >
                        <Upload aria-hidden />
                        Push back
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** Auth, rate limits, other policies and the declared loss. */
function PostureSection({ config }: { config: GatewayConfig }) {
  const { posture } = config;
  return (
    <section className="gwc-section" aria-labelledby="gwc-posture" data-testid="gateway-config-posture">
      <h2 id="gwc-posture" className="gwc-section__title">
        Posture
      </h2>
      <dl className="gwc-posture">
        <div>
          <dt>Auth</dt>
          <dd>
            {posture.auth.length === 0
              ? 'None declared'
              : posture.auth.map((entry) => (
                  <Badge key={`${entry.scheme}:${entry.via}`} variant="neutral" square>
                    {entry.scheme}
                    {entry.via ? ` · ${entry.via}` : ''}
                  </Badge>
                ))}
          </dd>
        </div>
        <div>
          <dt>Rate limits</dt>
          <dd>
            {posture.rateLimits.length === 0
              ? 'None declared'
              : posture.rateLimits.map((entry) => (
                  <Badge key={`${entry.name}:${entry.kind}`} variant="neutral" square>
                    {entry.name}
                  </Badge>
                ))}
          </dd>
        </div>
        <div>
          <dt>Other policies</dt>
          <dd>{posture.policies.length === 0 ? '—' : posture.policies.join(', ')}</dd>
        </div>
      </dl>
      {posture.credentialRedactions > 0 ? (
        <p className="gwc-muted">
          {posture.credentialRedactions} credential{posture.credentialRedactions === 1 ? ' was' : 's were'} redacted from
          the configuration.
        </p>
      ) : null}
      {config.declaredLosses.map((loss) => (
        <Alert key={loss.construct} variant="info" data-testid="gateway-config-loss">
          {loss.reason}
        </Alert>
      ))}
    </section>
  );
}
