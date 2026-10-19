'use client';

/**
 * A connector's **Environments** tab — CDG-5.3 (#5981).
 *
 * One row per gateway config the connector's syncs keep: the environment, how many APIs it serves,
 * its auth schemes and rate limits at a glance, and a link to its page. Read when the tab opens.
 */

import * as React from 'react';
import Link from 'next/link';
import { RefreshCw } from 'lucide-react';
import { Button, EmptyState, LoadingState } from '@/app/components/ui';
import { gatewayConfigHref, type GatewayConfig } from '@lib/gateway-configs';
import { fetchConnectorGatewayConfigs } from './gatewayConfigsApi';

/** Props for {@link ConnectorEnvironments}. */
export interface ConnectorEnvironmentsProps {
  /** The connector. */
  connectorId: string;
  /** Read only once the tab is shown. */
  active: boolean;
}

/**
 * The environments table.
 *
 * @param props - See {@link ConnectorEnvironmentsProps}.
 * @returns The tab body.
 */
export function ConnectorEnvironments({ connectorId, active }: ConnectorEnvironmentsProps) {
  const [configs, setConfigs] = React.useState<GatewayConfig[] | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    setError(null);
    try {
      setConfigs(await fetchConnectorGatewayConfigs(connectorId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the environments');
    }
  }, [connectorId]);

  React.useEffect(() => {
    if (active && configs === null) void load();
  }, [active, configs, load]);

  if (error) {
    return (
      <EmptyState
        variant="compact"
        surface={false}
        tone="danger"
        title="The environments could not be read"
        description={error}
        action={
          <Button variant="soft" onClick={() => void load()}>
            <RefreshCw aria-hidden />
            Try again
          </Button>
        }
      />
    );
  }
  if (configs === null) return <LoadingState message="Reading the environments…" minHeightClassName="min-h-[6rem]" />;
  if (configs.length === 0) {
    return (
      <EmptyState
        variant="compact"
        surface={false}
        title="No environments yet"
        description="Each sync lists the gateway environments it finds here."
      />
    );
  }
  return (
    <div className="gwc-table-wrap" data-testid="connector-environments">
      <table className="gwc-table">
        <caption className="sr-only">Gateway environments of this connector</caption>
        <thead>
          <tr>
            <th scope="col">Environment</th>
            <th scope="col">APIs</th>
            <th scope="col">Auth</th>
            <th scope="col">Rate limits</th>
          </tr>
        </thead>
        <tbody>
          {configs.map((config) => (
            <tr key={config.id} data-testid={`connector-environment-${config.slug}`}>
              <td>
                <Link className="gwc-link" href={gatewayConfigHref(config.slug)}>
                  {config.environment || config.name}
                </Link>
              </td>
              <td className="gwc-num">{config.apiCount}</td>
              <td>{config.posture.auth.map((entry) => entry.scheme).join(', ') || '—'}</td>
              <td>{config.posture.rateLimits.map((entry) => entry.name).join(', ') || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
